# pip install numpy pandas python-dotenv lightgbm rich scikit-learn xgboost statsmodels scipy argparse joblib optuna shap

"""
Wind Power Prediction Model Comparison

This script trains and compares various tree-based machine learning models
for predicting wind power amounts based on weather data.

Features:
    - Model training and evaluation (Random Forest, XGBoost, Gradient Boosting, LightGBM)
    - Cross-validation with nested approach
    - Hyperparameter tuning with Optuna
    - Performance metrics calculation (MAE, MSE, RMSE, R²)
    - Durbin-Watson test and autocorrelation
    - SHAP values for feature importance
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
        'full': Includes hyperparameter tuning with Optuna
    --optimize: Specify which model to optimize hyperparameters for (only in 'full' mode), if not all.
        Options are 'RF' for Random Forest, 'XGB' for XGBoost, 'GB' for Gradient Boosting, and 'LGBM' for LightGBM.
    --output-dir: Directory to save trained models (default: 'data/')

The application uses environment variables for FMISID features, which should be
defined in a .env.local file. See .env.template for an example.

Output:
    - Detailed logging of the process
    - Tables displaying model performance comparisons
    - SHAP values
    - Saved model files
"""

import argparse
import logging
import time
import os
from typing import List, Tuple, Dict, Any
import numpy as np
import pandas as pd
import multiprocessing
from scipy.stats import randint, uniform
import joblib
import shap
import optuna
from dotenv import load_dotenv, dotenv_values
from lightgbm import LGBMRegressor
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from sklearn.impute import SimpleImputer
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split, KFold
from xgboost import XGBRegressor
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.stattools import acf

# Load environment variables
load_dotenv()
env_vars = dotenv_values(".env.local")

# Get the FMISID features from environment variables
FMISID_WS = env_vars["FMISID_WS"].split(',')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="[%Y-%m-%d %H:%M:%S]",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("rich")
console = Console()

logger.info(f"FMISID_WS: {FMISID_WS}")

def get_n_jobs() -> int:
    """Determine the number of jobs to run in parallel."""
    total_cores = multiprocessing.cpu_count()
    return int(max(1, total_cores * 0.5))

def preprocess_data(df: pd.DataFrame, FMISID_WS: List[str]) -> Tuple[pd.DataFrame, pd.Series]:
    """Preprocess the input data for model training."""
    logger.info("Starting data preprocessing with dropping missing values...")
    
    # Convert the timestamp column to datetime format
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # Extract hour from the timestamp
    df['hour'] = df['timestamp'].dt.hour

    # Add sine and cosine transformation of the hour
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)

    # Forward fill missing values for WindPowerCapacityMW
    df['WindPowerCapacityMW'] = df['WindPowerCapacityMW'].ffill()

    # Compute statistical features: Avg_WindSpeed and WindSpeed_Variance
    ws_cols = [f"ws_{id}" for id in FMISID_WS]
    df['Avg_WindSpeed'] = df[ws_cols].mean(axis=1)
    df['WindSpeed_Variance'] = df[ws_cols].var(axis=1)
    
    # Drop the predictions column if it exists
    df = df.drop(columns=['WindPowerMW_predict'], errors='ignore')
    
    # Define feature columns including WS and T columns based on FMISID_WS
    feature_columns = (
        [f"ws_{id}" for id in FMISID_WS] + 
        [f"t_{id}" for id in FMISID_WS] + 
        ['hour_sin', 'hour_cos', 'WindPowerCapacityMW', 'Avg_WindSpeed', 'WindSpeed_Variance']
    )

    # Log the initial number of rows
    initial_row_count = df.shape[0]

    # Drop rows with missing values in features or target variable
    df = df.dropna(subset=feature_columns + ['WindPowerMW'])
    
    # Log the number of rows dropped
    dropped_rows = initial_row_count - df.shape[0]
    logger.info(f"Dropped {dropped_rows} rows due to missing data")

    # Separate features and target variable
    X = df[feature_columns]
    y = df['WindPowerMW']
    
    # Log final shapes
    logger.info(f"Preprocessed data shape: X={X.shape}, y={y.shape}")
    return X, y

def cross_validate(model, X, y, model_name, n_splits=5) -> Dict[str, float]:
    """Perform cross-validation on the model using KFold."""
    logger.info(f"Starting cross-validation for {model_name}...")

    # Use KFold with shuffle for cross-validation
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42) 
    mae_scores, mse_scores, r2_scores = [], [], []

    # Iterate over each fold and calculate metrics
    for fold, (train_index, test_index) in enumerate(kf.split(X)):
        X_train, X_val = X.iloc[train_index], X.iloc[test_index]
        y_train, y_val = y.iloc[train_index], y.iloc[test_index]
        model.fit(X_train, y_train)
        y_pred = model.predict(X_val)
        mae_scores.append(mean_absolute_error(y_val, y_pred))
        mse_scores.append(mean_squared_error(y_val, y_pred))
        r2_scores.append(r2_score(y_val, y_pred))

    # Calculate mean metrics across all folds
    mae = np.mean(mae_scores)
    mse = np.mean(mse_scores)
    rmse = np.sqrt(mse)
    r2 = np.mean(r2_scores)

    # Log the cross-validation results
    logger.info(f"Cross-validation completed for {model_name}")
    logger.info(f"Mean MAE: {mae:.4f}, Mean MSE: {mse:.4f}, Mean RMSE: {rmse:.4f}, Mean R²: {r2:.4f}")

    return {
        "CV_MAE": mae,
        "CV_MSE": mse,
        "CV_RMSE": rmse,
        "CV_R²": r2
    }

def train_and_evaluate_model(model, X_train, y_train, X_test, y_test, model_name):
    """Train the model and evaluate its performance."""
    logger.info(f"Starting training and evaluation for {model_name}...")
    
    start_time = time.time()
    
    # Check if the model supports eval_set
    if hasattr(model, 'fit') and 'eval_set' in model.fit.__code__.co_varnames:
        # Fit the model with training data and use eval_set for early stopping
        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            eval_metric='rmse',  # You can choose other metrics like 'mae' or 'logloss'
            early_stopping_rounds=50,  # Adjust the number of rounds for early stopping
            verbose=True  # Set to True if you want to see the evaluation results during training
        )
        logger.info(f"Training time for {model_name}: {time.time() - start_time:.2f} seconds")
        if hasattr(model, 'best_iteration'):
            logger.info(f"{model_name} stopped on iteration: {model.best_iteration}")
    else:
        # Fit the model without eval_set
        model.fit(X_train, y_train)
        logger.info(f"Training time for {model_name}: {time.time() - start_time:.2f} seconds")
    
    # Predict using the model on the test set
    y_pred = model.predict(X_test)

    # Calculate performance metrics
    mae = mean_absolute_error(y_test, y_pred)
    mse = mean_squared_error(y_test, y_pred)
    rmse = np.sqrt(mse)
    r2 = r2_score(y_test, y_pred)

    # Calculate residuals and perform additional analyses
    residuals = y_test - y_pred
    dw_stat = durbin_watson(residuals)
    acf_values = acf(residuals, nlags=3, fft=False)

    # Feature importance
    feature_importance = pd.DataFrame({'Feature': X_train.columns, 'Importance': model.feature_importances_}).sort_values(by='Importance', ascending=False)

    # SHAP values
    shap_values = None
    shap_summary = None
    try:
        explainer = shap.TreeExplainer(model, X_train)
        shap_values = explainer.shap_values(X_test)
        
        # Calculate mean absolute SHAP values
        mean_shap_values = np.abs(shap_values).mean(axis=0)
        shap_summary = pd.DataFrame({'Feature': X_test.columns, 'Mean SHAP Value': mean_shap_values}).sort_values(by='Mean SHAP Value', ascending=False)
    except Exception as e:
        logger.warning(f"SHAP analysis failed for {model_name}: {str(e)}")

    # Compile results
    results = {
        "MAE": mae,
        "MSE": mse,
        "RMSE": rmse,
        "R²": r2,
        "Durbin-Watson": dw_stat,
        "ACF": acf_values,
        "Feature Importance": feature_importance,
        "SHAP Summary": shap_summary,
    }
    
    # Log the evaluation results
    logger.info(f"{model_name} evaluation completed")
    logger.info(f"MAE: {mae:.4f}, MSE: {mse:.4f}, RMSE: {rmse:.4f}, R²: {r2:.4f}")
    
    return results

def display_results(results, mode):
    """Display the results of model comparison."""
    logger.info("Preparing to display model comparison results...")

    tables = {
        "main": Table(title="Model Performance Comparison - Test Set Metrics"),
        "cv": Table(title="5-Fold Cross-Validation Results"),
        "autocorr": Table(title="Autocorrelation Analysis")
    }

    # Main table setup
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
        
        if 'SHAP Summary' in metrics and metrics['SHAP Summary'] is not None:
            console.print(f"\nTop 10 SHAP Mean Absolute Values for {model_name}:")
            console.print(metrics['SHAP Summary'].head(10).to_string(index=False))

def tune_model_with_optuna(model_class, X, y, model_name, timeout, n_trials):
    """Use Optuna to find the best model parameters with nested cross-validation."""
    logger.info(f"Starting nested cross-validation with Optuna for {model_name}")

    def objective(trial):
        if model_name == "XGBoost":
            params = {
                'n_estimators': trial.suggest_int('n_estimators', 1000, 12000),
                'max_depth': trial.suggest_int('max_depth', 2, 12),
                'learning_rate': trial.suggest_float('learning_rate', 0.001, 0.06),
                'subsample': trial.suggest_float('subsample', 0.2, 0.6),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.25, 0.85),
                'gamma': trial.suggest_float('gamma', 0, 0.1),
                'reg_alpha': trial.suggest_float('reg_alpha', 0, 1.0),
                'reg_lambda': trial.suggest_float('reg_lambda', 0, 1.0),
                'random_state': 42,
                'tree_method': 'auto'
            }

        elif model_name == "Light GBM":
            params = {
                'n_estimators': trial.suggest_int('n_estimators', 200, 2000),
                'max_depth': trial.suggest_int('max_depth', -1, 20),
                'learning_rate': trial.suggest_float('learning_rate', 0.001, 0.3, log=True),
                'num_leaves': trial.suggest_int('num_leaves', 2, 256),
                'feature_fraction': trial.suggest_float('feature_fraction', 0.5, 1.0),
                'bagging_fraction': trial.suggest_float('bagging_fraction', 0.5, 1.0),
                'bagging_freq': trial.suggest_int('bagging_freq', 1, 7),
            }
        elif model_name == "Gradient Boosting":
            params = {
                'n_estimators': trial.suggest_int('n_estimators', 100, 1000),
                'max_depth': trial.suggest_int('max_depth', 3, 20),
                'learning_rate': trial.suggest_loguniform('learning_rate', 0.001, 0.3),
                'subsample': trial.suggest_float('subsample', 0.5, 1.0),
            }
        elif model_name == "Random Forest":
            params = {
                'n_estimators': trial.suggest_int('n_estimators', 100, 1000),
                'max_depth': trial.suggest_int('max_depth', 3, 30),
                'max_features': trial.suggest_categorical('max_features', ['auto', 'sqrt', 'log2']),
                'min_samples_split': trial.suggest_int('min_samples_split', 2, 10),
            }
        else:
            logger.error(f"Unknown model name: {model_name}")
            return float('inf')

        model = model_class(**params)
        inner_kf = KFold(n_splits=3, shuffle=True, random_state=42)
        cv_scores = []

        for train_idx, val_idx in inner_kf.split(X):
            X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
            y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

            # Check if the model supports eval_set
            if hasattr(model, 'fit') and 'eval_set' in model.fit.__code__.co_varnames:
                model.fit(
                    X_train, y_train,
                    eval_set=[(X_val, y_val)],
                    eval_metric='rmse',  # Adjust metric as needed
                    early_stopping_rounds=50,
                    verbose=True
                )
                if hasattr(model, 'best_iteration'):
                    logger.info(f"Model stopped on iteration: {model.best_iteration}")
            else:
                model.fit(X_train, y_train)

            y_pred = model.predict(X_val)
            rmse = np.sqrt(mean_squared_error(y_val, y_pred))
            cv_scores.append(rmse)
            
        return np.mean(cv_scores)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, timeout=timeout, n_jobs=get_n_jobs())
    
    best_params = study.best_params
    logger.info(f"Best parameters found for {model_name}: {best_params}")

    best_model = model_class(**best_params)
    return best_model

def main():
    """Main function to run the model comparison experiment."""
    parser = argparse.ArgumentParser(description="Train and compare tree-based models for wind power prediction based on weather.")
    parser.add_argument('--data', type=str, default='data/dump.csv', help='Path to the data file (default: data/dump.csv)')
    parser.add_argument('--mode', type=str, choices=['quick', 'default', 'full'], default='default', help='Operation mode (default: default)')
    parser.add_argument('--optimize', type=str, choices=['RF', 'XGB', 'GB', 'LGBM'], help='Specify which model to optimize (RF: Random Forest, XGB: XGBoost, GB: Gradient Boosting, LGBM: Light GBM)')
    parser.add_argument('--output-dir', type=str, default='data/', help='Directory to save trained models (default: data/)')
    parser.add_argument('--iters', type=int, default=200, help='Number of Optuna trials (default: 200)')
    parser.add_argument('--timeout', type=int, default=3600, help='Timeout for Optuna optimization in seconds (default: 3600)')

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

    # Preprocess data using the single list FMISID_WS
    try:
        X, y = preprocess_data(df, FMISID_WS)
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        logger.info(
            f"Data splits: "
            f"Training set: {X_train.shape}, "
            f"Testing set: {X_test.shape}"
        )

    except Exception as e:
        logger.error(f"Error during data preprocessing or splitting: {str(e)}")
        return

    n_jobs = get_n_jobs()
    models = {
        "Random Forest": RandomForestRegressor(random_state=42, n_jobs=n_jobs),
        "XGBoost": XGBRegressor(random_state=42, n_jobs=n_jobs, early_stopping_rounds=50),
        "Gradient Boosting": GradientBoostingRegressor(random_state=42),
        "Light GBM": LGBMRegressor(random_state=42, n_jobs=n_jobs, verbose=-1)
    }

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
                model_class = type(model)
                model = tune_model_with_optuna(model_class, X_train, y_train, model_name, timeout=args.timeout, n_trials=args.iters)
            
            if args.mode in ['default', 'full']:
                cv_results = cross_validate(model, X_train, y_train, model_name)
            else:
                cv_results = {}
            
            eval_results = train_and_evaluate_model(model, X_train, y_train, X_test, y_test, model_name)
            results[model_name] = {**cv_results, **eval_results}

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