# pip install numpy pandas python-dotenv lightgbm rich scikit-learn xgboost statsmodels scipy argparse

"""
Electricity Price Prediction Model Comparison

This script trains and compares various tree-based machine learning models
for predicting electricity prices. 

Features:
    - Model training and evaluation (Random Forest, XGBoost, Gradient Boosting, LightGBM)
    - Cross-validation
    - Hyperparameter tuning (in full mode)
    - Performance metrics calculation (MAE, MSE, RMSE, R²)
    - Durbin-Watson test and autocorrelation (in 'full' mode)
    - Feature importance ranking
    - Results visualization

Usage:
    python data/create/91_model_experiments/rf_vs_world.py --data 'data/dump.csv' --mode 'quick'
    python data/create/91_model_experiments/rf_vs_world.py --data 'data/dump.csv' --mode 'default'
    python data/create/91_model_experiments/rf_vs_world.py --data 'data/dump.csv' --mode 'full'

Arguments:
    --data: Path to the input CSV data file (default: 'data/dump.csv')
    --mode: Operation mode (default: 'default')
        'quick': Only trains and evaluates Random Forest
        'default': Trains and evaluates all models without grid search
        'full': Includes hyperparameter grid search and additional analyses
    --optimize: Specify which model to optimize hyperparameters for (only in 'full' mode), if not all.
        Options are 'RF' for Random Forest, 'XGB' for XGBoost, 'GB' for Gradient Boosting, and 'LGBM' for LightGBM.

The application uses environment variables for FMISID features, which should be
defined in a .env.local file. See .env.template for an example.

Output:
    - Detailed logging of the process
    - Tables displaying model performance comparisons
    - Feature importance rankings
"""

import argparse
import logging
import time
from typing import List, Tuple, Dict, Any
import numpy as np
import pandas as pd
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
    df = df.drop(columns=['PricePredict_cpkWh'], errors='ignore')
    
    # Convert the timestamp to datetime and extract features
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    df['day_of_week'] = df['timestamp'].dt.dayofweek + 1
    df['hour'] = df['timestamp'].dt.hour

    # Define feature columns including dynamic columns based on fmisid_ws and fmisid_t
    # feature_columns = ['day_of_week', 'hour', 'NuclearPowerMW', 'ImportCapacityMW'] + fmisid_ws + fmisid_t

    # TEST - Include WindPowerMW
    feature_columns = ['day_of_week', 'hour', 'NuclearPowerMW', 'ImportCapacityMW', 'WindPowerMW'] + fmisid_ws + fmisid_t

    # Drop rows with NaN values in the feature columns
    initial_row_count = df.shape[0]
    df = df.dropna(subset=feature_columns + ['Price_cpkWh'])
    dropped_rows = initial_row_count - df.shape[0]
    logger.info(f"Dropped {dropped_rows} rows due to NaN values in feature or target columns.")

    # Filter outliers based on the IQR for Price_cpkWh column
    Q1, Q3 = df['Price_cpkWh'].quantile([0.25, 0.75])
    IQR = Q3 - Q1
    df_filtered = df[(df['Price_cpkWh'] >= Q1 - 2.5 * IQR) & (df['Price_cpkWh'] <= Q3 + 2.5 * IQR)]

    # Extract features and target variable
    X_filtered = df_filtered[feature_columns]
    y_filtered = df_filtered['Price_cpkWh']

    logger.info(f"Preprocessed data shape: X={X_filtered.shape}, y={y_filtered.shape}")
    return X_filtered, y_filtered

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
            'n_estimators': randint(500, 1000),
            'max_depth': randint(20, 50),
            'min_samples_split': randint(2, 5),
            'min_samples_leaf': randint(1, 4)
        },
        'GradientBoostingRegressor': {
            'n_estimators': randint(500, 1000),
            'max_depth': randint(5, 15),
            'learning_rate': uniform(0.01, 0.1),
            'subsample': uniform(0.7, 0.3),
            'max_features': uniform(0.7, 0.3)
        },
        'LGBMRegressor': {
            'n_estimators': randint(500, 1000),
            'max_depth': randint(6, 12),
            'learning_rate': uniform(0.01, 0.1),
            'subsample': uniform(0.7, 0.3),
            'colsample_bytree': uniform(0.7, 0.3)
        },
        'XGBRegressor': {
            'n_estimators': randint(500, 1000),
            'max_depth': randint(3, 12),
            'learning_rate': uniform(0.01, 0.1),
            'subsample': uniform(0.7, 0.3),
            'colsample_bytree': uniform(0.7, 0.3),
            'gamma': uniform(0, 0.5),
            'reg_alpha': uniform(0, 0.5),
            'reg_lambda': uniform(0, 0.5),
            'max_delta_step': randint(0, 5)
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
    parser = argparse.ArgumentParser(description="Train and compare tree-based models for electricity price prediction.")
    parser.add_argument('--data', type=str, default='data/dump.csv', help='Path to the data file (default: data/dump.csv)')
    parser.add_argument('--mode', type=str, choices=['quick', 'default', 'full'], default='default', help='Operation mode (default: default)')
    parser.add_argument('--optimize', type=str, choices=['RF', 'XGB', 'GB', 'LGBM'], help='Specify which model to optimize (RF: Random Forest, XGB: XGBoost, GB: Gradient Boosting, LGBM: Light GBM)')
    args = parser.parse_args()

    logger.info(f"Starting model comparison in {args.mode} mode")

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
            
            if model_name == "XGBoost":
                model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
            else:
                model.fit(X_train, y_train)
            
            eval_results = train_and_evaluate_model(model, X_train, y_train, X_test, y_test, model_name, args.mode)
            results[model_name] = {**cv_results, **eval_results}
        except Exception as e:
            logger.error(f"Error processing {model_name}: {str(e)}")

    try:
        display_results(results, args.mode)
        logger.info("Model comparison completed")
    except Exception as e:
        logger.error(f"Error displaying results: {str(e)}")

if __name__ == "__main__":
    main()

# Sample run, 2024-09-02, with WindPowerMW included:

# [2024-09-01 23:18:30] INFO     [2024-09-01 23:18:30] - Starting model comparison in full mode                                                                                                     rf_vs_world.py:327
#                       INFO     [2024-09-01 23:18:30] - Dataset loaded successfully. Shape: (14750, 15)                                                                                            rf_vs_world.py:331
#                       INFO     [2024-09-01 23:18:30] - Starting data preprocessing...                                                                                                              rf_vs_world.py:88
#                       INFO     [2024-09-01 23:18:30] - Dropped 88 rows due to NaN values in feature or target columns.                                                                            rf_vs_world.py:111
#                       INFO     [2024-09-01 23:18:30] - Preprocessed data shape: X=(14517, 13), y=(14517,)                                                                                         rf_vs_world.py:122
#                       INFO     [2024-09-01 23:18:30] - Data splits: Training set: (9290, 13), Validation set: (2323, 13), Testing set: (2904, 13)                                                 rf_vs_world.py:344
#                       INFO     [2024-09-01 23:18:30] - Processing Random Forest...                                                                                                                rf_vs_world.py:384
#                       INFO     [2024-09-01 23:18:30] - Starting model tuning for RandomForestRegressor                                                                                            rf_vs_world.py:252
# Fitting 3 folds for each of 100 candidates, totalling 300 fits
# [2024-09-01 23:36:57] INFO     [2024-09-01 23:36:57] - Best parameters found: {'max_depth': 47, 'min_samples_leaf': 1, 'min_samples_split': 2, 'n_estimators': 779}                               rf_vs_world.py:314
#                       INFO     [2024-09-01 23:36:57] - Best score: 6.3706                                                                                                                         rf_vs_world.py:315
#                       INFO     [2024-09-01 23:36:57] - Starting 5-fold cross-validation for Random Forest...                                                                                      rf_vs_world.py:126
# Cross-validating Random Forest... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:00
# [2024-09-01 23:38:53] INFO     [2024-09-01 23:38:53] - Cross-validation completed for Random Forest                                                                                               rf_vs_world.py:147
#                       INFO     [2024-09-01 23:38:53] - Mean MAE: 1.4178, Mean MSE: 4.9802, Mean RMSE: 2.2316, Mean R²: 0.8284                                                                     rf_vs_world.py:148
# [2024-09-01 23:39:08] INFO     [2024-09-01 23:39:08] - Starting training and evaluation for Random Forest...                                                                                      rf_vs_world.py:160
# [2024-09-01 23:39:22] INFO     [2024-09-01 23:39:22] - Random Forest training completed in 14.18 seconds                                                                                          rf_vs_world.py:165
#                       INFO     [2024-09-01 23:39:22] - Random Forest prediction completed in 0.13 seconds                                                                                         rf_vs_world.py:170
#                       INFO     [2024-09-01 23:39:22] - Performing full analysis for Random Forest...                                                                                              rf_vs_world.py:185
#                       INFO     [2024-09-01 23:39:22] - Full analysis completed                                                                                                                    rf_vs_world.py:189
#                       INFO     [2024-09-01 23:39:22] - Random Forest evaluation completed                                                                                                         rf_vs_world.py:194
#                       INFO     [2024-09-01 23:39:22] - MAE: 1.3871, MSE: 4.8166, RMSE: 2.1947, R²: 0.8462                                                                                         rf_vs_world.py:195
# [2024-09-01 23:39:23] INFO     [2024-09-01 23:39:23] - Processing XGBoost...                                                                                                                      rf_vs_world.py:384
#                       INFO     [2024-09-01 23:39:23] - Starting model tuning for XGBRegressor                                                                                                     rf_vs_world.py:252
# Fitting 3 folds for each of 100 candidates, totalling 300 fits
# [2024-09-01 23:43:09] INFO     [2024-09-01 23:43:09] - Best parameters found: {'colsample_bytree': 0.9724797657899961, 'gamma': 0.11978094533348621, 'learning_rate': 0.02448948720912231,        rf_vs_world.py:314
#                                'max_delta_step': 3, 'max_depth': 8, 'n_estimators': 915, 'reg_alpha': 0.29634836193969677, 'reg_lambda': 0.040426663166357624, 'subsample': 0.8108963368184213}
#                       INFO     [2024-09-01 23:43:09] - Best score: 4.9067                                                                                                                         rf_vs_world.py:315
#                       INFO     [2024-09-01 23:43:09] - Starting 5-fold cross-validation for XGBoost...                                                                                            rf_vs_world.py:126
# Cross-validating XGBoost... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:00
# [2024-09-01 23:43:41] INFO     [2024-09-01 23:43:41] - Cross-validation completed for XGBoost                                                                                                     rf_vs_world.py:147
#                       INFO     [2024-09-01 23:43:41] - Mean MAE: 1.2581, Mean MSE: 3.8796, Mean RMSE: 1.9697, Mean R²: 0.8663                                                                     rf_vs_world.py:148
# [2024-09-01 23:43:43] INFO     [2024-09-01 23:43:43] - Starting training and evaluation for XGBoost...                                                                                            rf_vs_world.py:160
# [2024-09-01 23:43:46] INFO     [2024-09-01 23:43:46] - XGBoost training completed in 2.34 seconds                                                                                                 rf_vs_world.py:165
#                       INFO     [2024-09-01 23:43:46] - XGBoost prediction completed in 0.02 seconds                                                                                               rf_vs_world.py:170
#                       INFO     [2024-09-01 23:43:46] - Performing full analysis for XGBoost...                                                                                                    rf_vs_world.py:185
#                       INFO     [2024-09-01 23:43:46] - Full analysis completed                                                                                                                    rf_vs_world.py:189
#                       INFO     [2024-09-01 23:43:46] - XGBoost evaluation completed                                                                                                               rf_vs_world.py:194
#                       INFO     [2024-09-01 23:43:46] - MAE: 1.2165, MSE: 3.6411, RMSE: 1.9082, R²: 0.8837                                                                                         rf_vs_world.py:195
#                       INFO     [2024-09-01 23:43:46] - Processing Gradient Boosting...                                                                                                            rf_vs_world.py:384
#                       INFO     [2024-09-01 23:43:46] - Starting model tuning for GradientBoostingRegressor                                                                                        rf_vs_world.py:252
# Fitting 3 folds for each of 100 candidates, totalling 300 fits
# [2024-09-02 00:06:19] INFO     [2024-09-02 00:06:19] - Best parameters found: {'learning_rate': 0.027711067940704895, 'max_depth': 9, 'max_features': 0.9650482066798776, 'n_estimators': 879,    rf_vs_world.py:314
#                                'subsample': 0.7046369849586602}
#                       INFO     [2024-09-02 00:06:19] - Best score: 4.9145                                                                                                                         rf_vs_world.py:315
#                       INFO     [2024-09-02 00:06:19] - Starting 5-fold cross-validation for Gradient Boosting...                                                                                  rf_vs_world.py:126
# Cross-validating Gradient Boosting... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:00
# [2024-09-02 00:08:37] INFO     [2024-09-02 00:08:37] - Cross-validation completed for Gradient Boosting                                                                                           rf_vs_world.py:147
#                       INFO     [2024-09-02 00:08:37] - Mean MAE: 1.2027, Mean MSE: 3.7273, Mean RMSE: 1.9306, Mean R²: 0.8716                                                                     rf_vs_world.py:148
# [2024-09-02 00:09:03] INFO     [2024-09-02 00:09:03] - Starting training and evaluation for Gradient Boosting...                                                                                  rf_vs_world.py:160
# [2024-09-02 00:09:29] INFO     [2024-09-02 00:09:29] - Gradient Boosting training completed in 26.30 seconds                                                                                      rf_vs_world.py:165
#                       INFO     [2024-09-02 00:09:29] - Gradient Boosting prediction completed in 0.08 seconds                                                                                     rf_vs_world.py:170
#                       INFO     [2024-09-02 00:09:29] - Performing full analysis for Gradient Boosting...                                                                                          rf_vs_world.py:185
#                       INFO     [2024-09-02 00:09:29] - Full analysis completed                                                                                                                    rf_vs_world.py:189
#                       INFO     [2024-09-02 00:09:29] - Gradient Boosting evaluation completed                                                                                                     rf_vs_world.py:194
#                       INFO     [2024-09-02 00:09:29] - MAE: 1.1514, MSE: 3.5129, RMSE: 1.8743, R²: 0.8878                                                                                         rf_vs_world.py:195
#                       INFO     [2024-09-02 00:09:29] - Processing Light GBM...                                                                                                                    rf_vs_world.py:384
#                       INFO     [2024-09-02 00:09:29] - Starting model tuning for LGBMRegressor                                                                                                    rf_vs_world.py:252
# Fitting 3 folds for each of 100 candidates, totalling 300 fits
# [2024-09-02 00:13:17] INFO     [2024-09-02 00:13:17] - Best parameters found: {'colsample_bytree': 0.954674147279825, 'learning_rate': 0.08217295211648731, 'max_depth': 11, 'n_estimators': 858, rf_vs_world.py:314
#                                'subsample': 0.7121300768615294}
#                       INFO     [2024-09-02 00:13:17] - Best score: 4.8420                                                                                                                         rf_vs_world.py:315
#                       INFO     [2024-09-02 00:13:17] - Starting 5-fold cross-validation for Light GBM...                                                                                          rf_vs_world.py:126
# Cross-validating Light GBM... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:00
# [2024-09-02 00:13:34] INFO     [2024-09-02 00:13:34] - Cross-validation completed for Light GBM                                                                                                   rf_vs_world.py:147
#                       INFO     [2024-09-02 00:13:34] - Mean MAE: 1.2837, Mean MSE: 3.7761, Mean RMSE: 1.9432, Mean R²: 0.8698                                                                     rf_vs_world.py:148
# [2024-09-02 00:13:35] INFO     [2024-09-02 00:13:35] - Starting training and evaluation for Light GBM...                                                                                          rf_vs_world.py:160
# [2024-09-02 00:13:36] INFO     [2024-09-02 00:13:36] - Light GBM training completed in 1.11 seconds                                                                                               rf_vs_world.py:165
#                       INFO     [2024-09-02 00:13:36] - Light GBM prediction completed in 0.04 seconds                                                                                             rf_vs_world.py:170
#                       INFO     [2024-09-02 00:13:36] - Performing full analysis for Light GBM...                                                                                                  rf_vs_world.py:185
#                       INFO     [2024-09-02 00:13:36] - Full analysis completed                                                                                                                    rf_vs_world.py:189
#                       INFO     [2024-09-02 00:13:36] - Light GBM evaluation completed                                                                                                             rf_vs_world.py:194
#                       INFO     [2024-09-02 00:13:36] - MAE: 1.2358, MSE: 3.5830, RMSE: 1.8929, R²: 0.8856                                                                                         rf_vs_world.py:195
#                       INFO     [2024-09-02 00:13:36] - Preparing to display model comparison results...                                                                                           rf_vs_world.py:201
#      Model Performance Comparison - Test Set Metrics
# ┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┓
# ┃ Model             ┃    MAE ┃    MSE ┃   RMSE ┃     R² ┃
# ┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━┩
# │ Random Forest     │ 1.3871 │ 4.8166 │ 2.1947 │ 0.8462 │
# │ XGBoost           │ 1.2165 │ 3.6411 │ 1.9082 │ 0.8837 │
# │ Gradient Boosting │ 1.1514 │ 3.5129 │ 1.8743 │ 0.8878 │
# │ Light GBM         │ 1.2358 │ 3.5830 │ 1.8929 │ 0.8856 │
# └───────────────────┴────────┴────────┴────────┴────────┘
#              5-Fold Cross-Validation Results
# ┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┓
# ┃ Model             ┃ CV MAE ┃ CV MSE ┃ CV RMSE ┃  CV R² ┃
# ┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━╇━━━━━━━━┩
# │ Random Forest     │ 1.4178 │ 4.9802 │  2.2316 │ 0.8284 │
# │ XGBoost           │ 1.2581 │ 3.8796 │  1.9697 │ 0.8663 │
# │ Gradient Boosting │ 1.2027 │ 3.7273 │  1.9306 │ 0.8716 │
# │ Light GBM         │ 1.2837 │ 3.7761 │  1.9432 │ 0.8698 │
# └───────────────────┴────────┴────────┴─────────┴────────┘
#                            Autocorrelation Analysis
# ┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
# ┃ Model             ┃ Durbin-Watson ┃ ACF (Lag 1) ┃ ACF (Lag 2) ┃ ACF (Lag 3) ┃
# ┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
# │ Random Forest     │        1.9569 │      0.0193 │     -0.0184 │     -0.0233 │
# │ XGBoost           │        1.9560 │      0.0170 │     -0.0226 │     -0.0244 │
# │ Gradient Boosting │        1.9608 │      0.0176 │     -0.0215 │     -0.0189 │
# │ Light GBM         │        1.9513 │      0.0183 │     -0.0274 │     -0.0177 │
# └───────────────────┴───────────────┴─────────────┴─────────────┴─────────────┘

# Top 10 Feature Importance for Random Forest:
#          Feature  Importance
#      WindPowerMW    0.187503
#         t_101118    0.160503
#   NuclearPowerMW    0.134186
#         t_100968    0.125291
#             hour    0.079554
#      day_of_week    0.065748
#         t_101786    0.060388
# ImportCapacityMW    0.059412
#         t_101339    0.035450
#        ws_101673    0.025667

# Top 10 Feature Importance for XGBoost:
#          Feature  Importance
#         t_100968    0.232281
#         t_101118    0.193524
#      WindPowerMW    0.126449
#   NuclearPowerMW    0.082230
# ImportCapacityMW    0.064701
#      day_of_week    0.056527
#             hour    0.056055
#         t_101339    0.050888
#         t_101786    0.045616
#        ws_101256    0.026455

# Top 10 Feature Importance for Gradient Boosting:
#          Feature  Importance
#      WindPowerMW    0.176867
#         t_100968    0.153029
#   NuclearPowerMW    0.136690
#         t_101118    0.125474
#             hour    0.090595
# ImportCapacityMW    0.073169
#      day_of_week    0.065681
#         t_101786    0.050461
#         t_101339    0.036762
#        ws_101256    0.024679

# Top 10 Feature Importance for Light GBM:
#          Feature  Importance
#   NuclearPowerMW        3036
#      WindPowerMW        2764
# ImportCapacityMW        2465
#         t_101786        2165
#        ws_101673        1889
#        ws_101267        1845
#        ws_101256        1815
#        ws_101846        1777
#         t_100968        1756
#         t_101339        1687
#                       INFO     [2024-09-02 00:13:36] - Model comparison completed