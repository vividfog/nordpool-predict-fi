"""
Electricity Price Prediction Model Comparison

This script trains and compares various tree-based machine learning models
for predicting electricity prices. 

Features:
    - Model training and evaluation (Random Forest, XGBoost, Gradient Boosting, LightGBM)
    - Cross-validation
    - Hyperparameter tuning (in full mode)
    - Performance metrics calculation (MAE, MSE, RMSE, R²)
    - full analysis including Durbin-Watson test and autocorrelation (in 'full' mode)
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
    """
    Determine the number of jobs to run in parallel.
    Use half of the available CPU cores.
    """
    total_cores = multiprocessing.cpu_count()
    return max(1, total_cores // 2)  # Ensure at least 1 core is used

def preprocess_data(df: pd.DataFrame, fmisid_ws: List[str], fmisid_t: List[str]) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Preprocess the input data for model training.
    """
    logger.info("Starting data preprocessing...")
    
    logger.info(f"Initial data shape: {df.shape}")
    df = shuffle(df, random_state=42)
    logger.info("Data shuffled")
    
    df = df.drop(columns=['PricePredict_cpkWh'])
    logger.info("Dropped 'PricePredict_cpkWh' column")

    logger.info("Creating time-related features from timestamp...")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['day_of_week'] = df['timestamp'].dt.dayofweek + 1
    df['hour'] = df['timestamp'].dt.hour
    logger.info("Time-related features created")

    logger.info("Removing outliers using the IQR method...")
    Q1, Q3 = df['Price_cpkWh'].quantile([0.25, 0.75])
    IQR = Q3 - Q1
    df_filtered = df[(df['Price_cpkWh'] >= Q1 - 2.5 * IQR) & (df['Price_cpkWh'] <= Q3 + 2.5 * IQR)]
    logger.info(f"Outliers removed. New shape: {df_filtered.shape}")

    logger.info("Defining features for the model...")
    feature_columns = ['day_of_week', 'hour', 'NuclearPowerMW', 'ImportCapacityMW'] + fmisid_ws + fmisid_t
    X_filtered = df_filtered[feature_columns]
    y_filtered = df_filtered['Price_cpkWh']

    logger.info(f"Preprocessed data shape: X={X_filtered.shape}, y={y_filtered.shape}")
    return X_filtered, y_filtered

def perform_cross_validation(model, X: pd.DataFrame, y: pd.Series, model_name: str, n_splits: int = 5) -> Dict[str, float]:
    """
    Perform k-fold cross-validation and return the results.
    """
    logger.info(f"Starting {n_splits}-fold cross-validation for {model_name}...")
    
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    
    n_jobs = get_n_jobs()
    
    mae_scores = cross_val_score(model, X, y, scoring='neg_mean_absolute_error', cv=kf, n_jobs=n_jobs)
    mse_scores = cross_val_score(model, X, y, scoring='neg_mean_squared_error', cv=kf, n_jobs=n_jobs)
    r2_scores = cross_val_score(model, X, y, scoring='r2', cv=kf, n_jobs=n_jobs)
    
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
    """
    Train the model and evaluate its performance.
    """
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
        logger.info("full analysis completed")

    feature_importance = pd.DataFrame({'Feature': X_train.columns, 'Importance': model.feature_importances_})
    results["Feature Importance"] = feature_importance.sort_values('Importance', ascending=False)

    logger.info(f"{model_name} evaluation completed")
    logger.info(f"MAE: {mae:.4f}, MSE: {mse:.4f}, RMSE: {rmse:.4f}, R²: {r2:.4f}")
    
    return results

def display_results(results: Dict[str, Dict[str, Any]], mode: str):
    """
    Display the results of model comparison.
    """
    logger.info("Preparing to display model comparison results...")

    # Main metrics table
    main_metrics_table = Table(title="Model Performance Comparison - Test Set Metrics")
    main_metrics_table.add_column("Model", justify="left", style="cyan")
    main_metrics_table.add_column("MAE", justify="right")
    main_metrics_table.add_column("MSE", justify="right")
    main_metrics_table.add_column("RMSE", justify="right")
    main_metrics_table.add_column("R²", justify="right")

    for model_name, metrics in results.items():
        main_metrics_table.add_row(
            model_name,
            f"{metrics['MAE']:.4f}",
            f"{metrics['MSE']:.4f}",
            f"{metrics['RMSE']:.4f}",
            f"{metrics['R²']:.4f}"
        )

    console.print(main_metrics_table)
    logger.info("Main metrics table displayed")

    if mode in ['default', 'full']:
        # Cross-validation results table
        cv_table = Table(title="3-Fold Cross-Validation Results")
        cv_table.add_column("Model", justify="left", style="cyan")
        cv_table.add_column("CV MAE", justify="right")
        cv_table.add_column("CV MSE", justify="right")
        cv_table.add_column("CV RMSE", justify="right")
        cv_table.add_column("CV R²", justify="right")

        for model_name, metrics in results.items():
            cv_table.add_row(
                model_name,
                f"{metrics['CV_MAE']:.4f}",
                f"{metrics['CV_MSE']:.4f}",
                f"{metrics['CV_RMSE']:.4f}",
                f"{metrics['CV_R²']:.4f}"
            )

        console.print(cv_table)
        logger.info("Cross-validation results table displayed")

    if mode == 'full':
        # Autocorrelation table
        autocorr_table = Table(title="Autocorrelation Analysis")
        autocorr_table.add_column("Model", justify="left", style="cyan")
        autocorr_table.add_column("Durbin-Watson", justify="right")
        autocorr_table.add_column("ACF (Lag 1)", justify="right")
        autocorr_table.add_column("ACF (Lag 2)", justify="right")
        autocorr_table.add_column("ACF (Lag 3)", justify="right")

        for model_name, metrics in results.items():
            autocorr_table.add_row(
                model_name,
                f"{metrics['Durbin-Watson']:.4f}",
                f"{metrics['ACF'][1]:.4f}",
                f"{metrics['ACF'][2]:.4f}",
                f"{metrics['ACF'][3]:.4f}"
            )

        console.print(autocorr_table)
        logger.info("Autocorrelation analysis table displayed")

    # Feature importance
    for model_name, metrics in results.items():
        console.print(f"\nTop 10 Feature Importance for {model_name}:")
        console.print(metrics['Feature Importance'].head(10).to_string(index=False))
        logger.info(f"Feature importance displayed for {model_name}")

def tune_model(model, X, y):
    logger.info(f"Starting model tuning for {type(model).__name__}")
    
    if isinstance(model, RandomForestRegressor):
        param_distributions = {
            'n_estimators': randint(500, 1000),
            'max_depth': randint(20, 50),
            'min_samples_split': randint(2, 5),
            'min_samples_leaf': randint(1, 4)
        }
    elif isinstance(model, XGBRegressor):
        param_distributions = {
            'n_estimators': randint(500, 1000),
            'max_depth': randint(6, 12),
            'learning_rate': uniform(0.01, 0.1),
            'subsample': uniform(0.7, 0.3),
            'colsample_bytree': uniform(0.7, 0.3)
        }
    elif isinstance(model, GradientBoostingRegressor):
        param_distributions = {
            'n_estimators': randint(500, 1000),
            'max_depth': randint(5, 15),
            'learning_rate': uniform(0.01, 0.1),
            'subsample': uniform(0.7, 0.3),
            'max_features': uniform(0.7, 0.3)
        }
    elif isinstance(model, LGBMRegressor):
        param_distributions = {
            'n_estimators': randint(500, 1000),
            'max_depth': randint(6, 12),
            'learning_rate': uniform(0.01, 0.1),
            'subsample': uniform(0.7, 0.3),
            'colsample_bytree': uniform(0.7, 0.3)
        }
    else:
        logger.warning(f"No specific tuning parameters for {type(model).__name__}. Using default.")
        return model

    n_iter = 20  # Number of parameter settings that are sampled
    cv = 3  # Number of cross-validation folds
    n_jobs = get_n_jobs()

    random_search = RandomizedSearchCV(
        model, param_distributions=param_distributions, 
        n_iter=n_iter, cv=cv, scoring='neg_mean_squared_error',
        n_jobs=n_jobs, random_state=42, verbose=1
    )

    random_search.fit(X, y)
    
    logger.info(f"Best parameters found: {random_search.best_params_}")
    logger.info(f"Best score: {-random_search.best_score_:.4f}")
    
    return random_search.best_estimator_

def main():
    """
    Main function to run the model comparison experiment.
    """
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(description="Train and compare tree-based models for electricity price prediction.")
    parser.add_argument('--data', type=str, default='data/dump.csv', help='Path to the data file (default: data/dump.csv)')
    parser.add_argument('--mode', type=str, choices=['quick', 'default', 'full'], default='default', help='Operation mode (default: default)')
    args = parser.parse_args()

    logger.info(f"Starting model comparison in {args.mode} mode")

    # Load the dataset
    logger.info(f"Loading dataset from {args.data}...")
    df = pd.read_csv(args.data)
    logger.info(f"Dataset loaded. Shape: {df.shape}")

    # Define feature names for weather stations and temperature
    fmisid_ws = [f"ws_{id}" for id in FMISID_WS]
    fmisid_t = [f"t_{id}" for id in FMISID_T]
    
    # Preprocess data
    X, y = preprocess_data(df, fmisid_ws, fmisid_t)

    # Split into train and test sets
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    logger.info(f"Data split. Train shape: {X_train.shape}, Test shape: {X_test.shape}")

    # Define models based on the selected mode
    if args.mode == 'quick':
        models = {"Random Forest": RandomForestRegressor(random_state=42, n_jobs=-1)}
    else:
        models = {
            "Random Forest": RandomForestRegressor(random_state=42, n_jobs=-1),
            "XGBoost": XGBRegressor(random_state=42, n_jobs=-1),
            "Gradient Boosting": GradientBoostingRegressor(random_state=42),
            "Light GBM": LGBMRegressor(random_state=42, n_jobs=-1)
        }

    results = {}
    for model_name, model in models.items():
        logger.info(f"Processing {model_name}...")
        if args.mode == 'full':
            logger.info(f"Tuning {model_name}...")
            model = tune_model(model, X_train, y_train)
        
        if args.mode in ['default', 'full']:
            # Perform cross-validation on the training set
            cv_results = perform_cross_validation(model, X_train, y_train, model_name)
        else:
            cv_results = {}
        
        # Train and evaluate the model
        eval_results = train_and_evaluate_model(model, X_train, y_train, X_test, y_test, model_name, args.mode)
        
        # Combine all results for the current model
        results[model_name] = {**cv_results, **eval_results}
        logger.info(f"Completed processing for {model_name}")

    # Display the results for all models
    display_results(results, args.mode)
    logger.info("Model comparison completed")

if __name__ == "__main__":
    main()
