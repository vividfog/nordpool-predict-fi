# pip install numpy pandas python-dotenv lightgbm rich scikit-learn xgboost statsmodels scipy argparse joblib

"""
Wind Power Prediction Model Comparison

This script trains and compares various tree-based machine learning models
for predicting wind power amounts based on weather data.

Features:
    - Model training and evaluation (Random Forest, XGBoost, Gradient Boosting, LightGBM)
    - Cross-validation
    - Hyperparameter tuning (in full mode)
    - Performance metrics calculation (MAE, MSE, RMSE, R²)
    - Durbin-Watson test and autocorrelation (in 'full' mode)
    - Feature importance ranking
    - Results visualization

Usage:
    python data/create/91_model_experiments/rf_vs_world_windpower.py --data 'data/dump.csv' --mode 'quick'
    python data/create/91_model_experiments/rf_vs_world_windpower.py --data 'data/dump.csv' --mode 'default'
    python data/create/91_model_experiments/rf_vs_world_windpower.py --data 'data/dump.csv' --mode 'full' --output-dir 'data/'

Arguments:
    --data: Path to the input CSV data file (default: 'data/dump.csv')
    --mode: Operation mode (default: 'default')
        'quick': Only trains and evaluates Random Forest
        'default': Trains and evaluates all models without grid search
        'full': Includes hyperparameter grid search and additional analyses
    --optimize: Specify which model to optimize hyperparameters for (only in 'full' mode), if not all.
        Options are 'RF' for Random Forest, 'XGB' for XGBoost, 'GB' for Gradient Boosting, and 'LGBM' for LightGBM.
    --output-dir: Directory to save trained models (default: 'data/')

The application uses environment variables for FMISID features, which should be
defined in a .env.local file. See .env.template for an example.

Output:
    - Detailed logging of the process
    - Tables displaying model performance comparisons
    - Feature importance rankings
    - Saved model files
    
Todo:
    - Add more weather stations for training
    - Create a more robust wind power model for use in the price prediction pipeline
    - Multi-pass hyperparameter search, narrowing down the search space depending on the results of the previous passes
"""

import argparse
import logging
import time
from typing import List, Tuple, Dict, Any
import numpy as np
import pandas as pd
import os
from dotenv import load_dotenv, dotenv_values
from lightgbm import LGBMRegressor
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.progress import Progress
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split, cross_val_score, KFold, RandomizedSearchCV
from sklearn.utils import shuffle
from xgboost import XGBRegressor
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.stattools import acf
import multiprocessing
from scipy.stats import randint, uniform
import joblib

# Load environment variables
load_dotenv()
env_vars = dotenv_values(".env.local")

# Get the FMISID features from environment variables
FMISID_WS = env_vars["FMISID_WS"].split(',')
FMISID_T = env_vars["FMISID_T"].split(',')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="[%Y-%m-%d %H:%M:%S]",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("rich")
console = Console()

logger.info(f"FMISID_WS: {FMISID_WS}, FMISID_T: {FMISID_T}")

def get_n_jobs():
    """Determine the number of jobs to run in parallel."""
    total_cores = multiprocessing.cpu_count()
    return max(1, total_cores // 2)

def preprocess_data(df: pd.DataFrame, fmisid_ws: List[str], fmisid_t: List[str]) -> Tuple[pd.DataFrame, pd.Series]:
    """Preprocess the input data for model training."""
    logger.info("Starting data preprocessing...")

    # Shuffle the data
    df = shuffle(df, random_state=42)
    
    # Drop the predictions column if it exists
    df = df.drop(columns=['WindPowerMW_predict'], errors='ignore')
    
    # Define feature columns including dynamic columns based on fmisid_ws and fmisid_t
    feature_columns = fmisid_ws + fmisid_t

    # Drop rows with NaN values in the feature columns or target variable
    initial_row_count = df.shape[0]
    df = df.dropna(subset=feature_columns + ['WindPowerMW'])
    dropped_rows = initial_row_count - df.shape[0]
    logger.info(f"Dropped {dropped_rows} rows due to NaN values.")

    # Extract features and target variable
    X = df[feature_columns]
    y = df['WindPowerMW']

    logger.info(f"Preprocessed data shape: X={X.shape}, y={y.shape}")
    return X, y

def perform_cross_validation(model, X: pd.DataFrame, y: pd.Series, model_name: str, n_splits: int = 5) -> Dict[str, float]:
    logger.info(f"Starting {n_splits}-fold cross-validation for {model_name}...")
    
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    n_jobs = get_n_jobs()

    with Progress() as progress:
        task = progress.add_task(f"[cyan]Cross-validating {model_name}...", total=n_splits)

        mae_scores = cross_val_score(model, X, y, scoring='neg_mean_absolute_error', cv=kf, n_jobs=n_jobs)
        mse_scores = cross_val_score(model, X, y, scoring='neg_mean_squared_error', cv=kf, n_jobs=n_jobs)
        r2_scores = cross_val_score(model, X, y, scoring='r2', cv=kf, n_jobs=n_jobs)

        # Simulating progress update for the cross-validation
        for _ in range(n_splits):
            progress.update(task, advance=1)

    mae = -mae_scores.mean()
    mse = -mse_scores.mean()
    rmse = np.sqrt(mse)
    r2 = r2_scores.mean()
    
    logger.info(f"Cross-validation completed for {model_name}")
    logger.info(f"Mean MAE: {mae:.4f}, Mean MSE: {mse:.4f}, Mean RMSE: {rmse:.4f}, Mean R²: {r2:.4f}")
    
    return {
        "CV_MAE": mae,
        "CV_MSE": mse,
        "CV_RMSE": rmse,
        "CV_R²": r2
    }

def train_and_evaluate_model(model, X_train: pd.DataFrame, y_train: pd.Series, X_test: pd.DataFrame, y_test: pd.Series, model_name: str, mode: str) -> Dict[str, Any]:
    """Train the model and evaluate its performance."""
    logger.info(f"Starting training and evaluation for {model_name}...")
    
    start_time = time.time()
    model.fit(X_train, y_train)
    training_time = time.time() - start_time
    logger.info(f"{model_name} training completed in {training_time:.2f} seconds")

    start_time = time.time()
    y_pred = model.predict(X_test)
    prediction_time = time.time() - start_time
    logger.info(f"{model_name} prediction completed in {prediction_time:.2f} seconds")

    mae = mean_absolute_error(y_test, y_pred)
    mse = mean_squared_error(y_test, y_pred)
    rmse = np.sqrt(mse)
    r2 = r2_score(y_test, y_pred)

    results = {
        "MAE": mae,
        "MSE": mse,
        "RMSE": rmse,
        "R²": r2,
    }

    if mode == 'full':
        logger.info(f"Performing full analysis for {model_name}...")
        residuals = y_test - y_pred
        results["Durbin-Watson"] = durbin_watson(residuals)
        results["ACF"] = acf(residuals, nlags=5, fft=False)
        logger.info("Full analysis completed")

    feature_importance = pd.DataFrame({'Feature': X_train.columns, 'Importance': model.feature_importances_})
    results["Feature Importance"] = feature_importance.sort_values('Importance', ascending=False)

    logger.info(f"{model_name} evaluation completed")
    logger.info(f"MAE: {mae:.4f}, MSE: {mse:.4f}, RMSE: {rmse:.4f}, R²: {r2:.4f}")
    
    return results

def display_results(results: Dict[str, Dict[str, Any]], mode: str):
    """Display the results of model comparison."""
    logger.info("Preparing to display model comparison results...")

    tables = {
        "main": Table(title="Model Performance Comparison - Test Set Metrics"),
        "cv": Table(title="5-Fold Cross-Validation Results"),
        "autocorr": Table(title="Autocorrelation Analysis")
    }

    tables["main"].add_column("Model", justify="left", style="cyan")
    for metric in ["MAE", "MSE", "RMSE", "R²"]:
        tables["main"].add_column(metric, justify="right")

    if mode in ['default', 'full']:
        tables["cv"].add_column("Model", justify="left", style="cyan")
        for metric in ["CV MAE", "CV MSE", "CV RMSE", "CV R²"]:
            tables["cv"].add_column(metric, justify="right")

    if mode == 'full':
        tables["autocorr"].add_column("Model", justify="left", style="cyan")
        tables["autocorr"].add_column("Durbin-Watson", justify="right")
        for i in range(1, 4):
            tables["autocorr"].add_column(f"ACF (Lag {i})", justify="right")

    for model_name, metrics in results.items():
        tables["main"].add_row(
            model_name,
            *[f"{metrics[m]:.4f}" for m in ["MAE", "MSE", "RMSE", "R²"]]
        )

        if mode in ['default', 'full']:
            tables["cv"].add_row(
                model_name,
                *[f"{metrics[f'CV_{m}']:.4f}" for m in ["MAE", "MSE", "RMSE", "R²"]]
            )

        if mode == 'full':
            tables["autocorr"].add_row(
                model_name,
                f"{metrics['Durbin-Watson']:.4f}",
                *[f"{metrics['ACF'][i]:.4f}" for i in range(1, 4)]
            )

    for table in tables.values():
        console.print(table)

    for model_name, metrics in results.items():
        console.print(f"\nTop 10 Feature Importance for {model_name}:")
        console.print(metrics['Feature Importance'].head(10).to_string(index=False))

def tune_model(model, X, y):
    """Tune model hyperparameters."""
    logger.info(f"Starting model tuning for {type(model).__name__}")
        
    param_distributions = {
        'RandomForestRegressor': {
            'n_estimators': randint(200, 2000),
            'max_depth': randint(10, 100),
            'min_samples_split': randint(2, 10),
            'min_samples_leaf': randint(1, 10)
        },
        'GradientBoostingRegressor': {
            'n_estimators': randint(200, 2000),
            'max_depth': randint(3, 20),
            'learning_rate': uniform(0.001, 0.499),  # Upper bound is 0.001 + 0.499 = 0.5
            'subsample': uniform(0.5, 0.5),  # Range is 0.5 to 1.0
            'max_features': uniform(0.5, 0.5)  # Range is 0.5 to 1.0
        },
        'LGBMRegressor': {
            'n_estimators': randint(200, 2000),
            'max_depth': randint(3, 20),
            'learning_rate': uniform(0.001, 0.499),
            'subsample': uniform(0.5, 0.5),
            'colsample_bytree': uniform(0.5, 0.5)
        },
        'XGBRegressor': {
            'n_estimators': randint(200, 2000),
            'max_depth': randint(3, 20),
            'learning_rate': uniform(0.001, 0.499),
            'subsample': uniform(0.5, 0.5),
            'colsample_bytree': uniform(0.5, 0.5),
            'gamma': uniform(0, 5),
            'reg_alpha': uniform(1e-5, 1.0),
            'reg_lambda': uniform(1e-5, 1.0),
            'min_child_weight': randint(1, 10)
        }
    }

    model_type = type(model).__name__
    if model_type not in param_distributions:
        logger.warning(f"No specific tuning parameters for {model_type}. Using default.")
        return model

    n_iter = 100
    cv = 3
    n_jobs = get_n_jobs()

    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)

    random_search = RandomizedSearchCV(
        model, param_distributions=param_distributions[model_type], 
        n_iter=n_iter, cv=cv, scoring='neg_mean_squared_error',
        n_jobs=n_jobs, random_state=42, verbose=1
    )

    if model_type == 'XGBoost':
        random_search.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False
        )
    else:
        random_search.fit(X_train, y_train)
    
    logger.info(f"Best parameters found: {random_search.best_params_}")
    logger.info(f"Best score: {-random_search.best_score_:.4f}")
    
    return random_search.best_estimator_

def main():
    """Main function to run the model comparison experiment."""
    parser = argparse.ArgumentParser(description="Train and compare tree-based models for wind power prediction based on weather.")
    parser.add_argument('--data', type=str, default='data/dump.csv', help='Path to the data file (default: data/dump.csv)')
    parser.add_argument('--mode', type=str, choices=['quick', 'default', 'full'], default='default', help='Operation mode (default: default)')
    parser.add_argument('--optimize', type=str, choices=['RF', 'XGB', 'GB', 'LGBM'], help='Specify which model to optimize (RF: Random Forest, XGB: XGBoost, GB: Gradient Boosting, LGBM: Light GBM)')
    parser.add_argument('--output-dir', type=str, default='data/', help='Directory to save trained models (default: data/)')
    args = parser.parse_args()

    logger.info(f"Starting model comparison in {args.mode} mode")

    # Ensure the output directory exists
    output_dir = args.output_dir
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        df = pd.read_csv(args.data)
        logger.info(f"Dataset loaded successfully. Shape: {df.shape}")
    except Exception as e:
        logger.error(f"Error loading the dataset: {str(e)}")
        return

    fmisid_ws = [f"ws_{id}" for id in FMISID_WS]
    fmisid_t = [f"t_{id}" for id in FMISID_T]
    
    try:
        X, y = preprocess_data(df, fmisid_ws, fmisid_t)
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        X_train, X_val, y_train, y_val = train_test_split(X_train, y_train, test_size=0.2, random_state=42)

        logger.info(
            f"Data splits: "
            f"Training set: {X_train.shape}, "
            f"Validation set: {X_val.shape}, "
            f"Testing set: {X_test.shape}"
        )

    except Exception as e:
        logger.error(f"Error during data preprocessing or splitting: {str(e)}")
        return

    n_jobs = get_n_jobs()
    models = {
        "Random Forest": RandomForestRegressor(random_state=42, n_jobs=n_jobs),
        "XGBoost": XGBRegressor(random_state=42, n_jobs=n_jobs),
        "Gradient Boosting": GradientBoostingRegressor(random_state=42),
        "Light GBM": LGBMRegressor(random_state=42, n_jobs=n_jobs, verbose=-1)
    }

    # Mapping between short names and full names
    model_map = {
        "RF": "Random Forest",
        "XGB": "XGBoost",
        "GB": "Gradient Boosting",
        "LGBM": "Light GBM"
    }

    if args.mode == 'quick':
        models = {"Random Forest": models["Random Forest"]}
    elif args.mode == 'full' and args.optimize:
        full_name = model_map.get(args.optimize)
        if full_name:
            models = {full_name: models[full_name]}
        else:
            logger.error(f"Invalid optimization choice: {args.optimize}")
            return

    results = {}
    for model_name, model in models.items():
        logger.info(f"Processing {model_name}...")
        try:
            if args.mode == 'full':
                model = tune_model(model, X_train, y_train)
            
            if args.mode in ['default', 'full']:
                cv_results = perform_cross_validation(model, X_train, y_train, model_name)
            else:
                cv_results = {}
            
            eval_results = train_and_evaluate_model(model, X_train, y_train, X_test, y_test, model_name, args.mode)
            results[model_name] = {**cv_results, **eval_results}

            # Save the trained model
            filename = f"windpower_{model_name.replace(' ', '_').lower()}.joblib"
            filepath = os.path.join(output_dir, filename)
            joblib.dump(model, filepath)
            logger.info(f"{model_name} saved as {filepath}")

        except Exception as e:
            logger.error(f"Error processing {model_name}: {str(e)}")

    try:
        display_results(results, args.mode)
        logger.info("Model comparison completed")
    except Exception as e:
        logger.error(f"Error displaying results: {str(e)}")

if __name__ == '__main__':
    main()
      
# 2024-09-01: Winner: Gradient Boosting

# learning_rate: 0.012508150095666463
# max_depth: 12
# max_features: 0.5233328316068078
# n_estimators: 899
# subsample: 0.6831809216468459

# Results:

#          Model Performance Comparison - Test Set Metrics
# ┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┓
# ┃ Model             ┃      MAE ┃         MSE ┃     RMSE ┃     R² ┃
# ┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━┩
# │ Random Forest     │ 459.6638 │ 392049.6739 │ 626.1387 │ 0.7594 │
# │ XGBoost           │ 432.8361 │ 362743.4374 │ 602.2819 │ 0.7774 │
# │ Gradient Boosting │ 424.6831 │ 350969.3553 │ 592.4267 │ 0.7846 │
# │ Light GBM         │ 461.0011 │ 399318.5351 │ 631.9166 │ 0.7549 │
# └───────────────────┴──────────┴─────────────┴──────────┴────────┘
#                  5-Fold Cross-Validation Results
# ┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┓
# ┃ Model             ┃   CV MAE ┃      CV MSE ┃  CV RMSE ┃  CV R² ┃
# ┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━┩
# │ Random Forest     │ 479.2966 │ 426813.8320 │ 653.3099 │ 0.7474 │
# │ XGBoost           │ 446.6376 │ 382851.2972 │ 618.7498 │ 0.7735 │
# │ Gradient Boosting │ 441.6042 │ 379494.6784 │ 616.0314 │ 0.7755 │
# │ Light GBM         │ 471.8722 │ 415177.6202 │ 644.3428 │ 0.7543 │
# └───────────────────┴──────────┴─────────────┴──────────┴────────┘
#                            Autocorrelation Analysis
# ┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
# ┃ Model             ┃ Durbin-Watson ┃ ACF (Lag 1) ┃ ACF (Lag 2) ┃ ACF (Lag 3) ┃
# ┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
# │ Random Forest     │        2.0024 │     -0.0049 │      0.0216 │     -0.0314 │
# │ XGBoost           │        2.0091 │     -0.0059 │      0.0182 │     -0.0256 │
# │ Gradient Boosting │        1.9968 │      0.0000 │      0.0219 │     -0.0347 │
# │ Light GBM         │        1.9795 │      0.0097 │      0.0114 │     -0.0178 │
# └───────────────────┴───────────────┴─────────────┴─────────────┴─────────────┘

# Top 10 Feature Importance for Random Forest:
#   Feature  Importance
# ws_101673    0.430571
# ws_101256    0.176456
# ws_101846    0.080221
#  t_101339    0.067645
#  t_101786    0.067280
# ws_101267    0.066799
#  t_100968    0.062345
#  t_101118    0.048683

# Top 10 Feature Importance for XGBoost:
#   Feature  Importance
# ws_101673    0.375390
# ws_101256    0.177948
# ws_101846    0.090846
#  t_100968    0.075800
#  t_101339    0.074666
# ws_101267    0.073706
#  t_101786    0.069250
#  t_101118    0.062394

# Top 10 Feature Importance for Gradient Boosting:
#   Feature  Importance
# ws_101673    0.281634
# ws_101256    0.188972
# ws_101846    0.133093
# ws_101267    0.098818
#  t_101786    0.080414
#  t_100968    0.074849
#  t_101339    0.074281
#  t_101118    0.067938

# Top 10 Feature Importance for Light GBM:
#   Feature  Importance
#  t_101786        8121
# ws_101256        7420
# ws_101673        7162
# ws_101846        7149
# ws_101267        7086
#  t_100968        6999
#  t_101339        6769
#  t_101118        6631