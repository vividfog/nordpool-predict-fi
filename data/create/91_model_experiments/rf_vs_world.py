# pip install numpy pandas python-dotenv rich scikit-learn xgboost statsmodels scipy argparse matplotlib optuna shap

"""
Electricity Price Prediction Model Comparison

This script trains and compares tree-based models (Random Forest, XGBoost, Gradient Boosting)
for predicting electricity prices.

Features:
---------
1. Data Preprocessing:
   - Cyclical transformations for time features
   - Handling missing values and outliers

2. Model Training and Evaluation:
   - Nested cross-validation with Optuna for hyperparameter tuning
   - Metrics: MAE, MSE, RMSE, R², SMAPE
   - Residual analysis: Durbin-Watson and autocorrelation

3. Feature Importance:
   - SHAP values for interpretability

4. Output:
   - Logs, metrics, comparison tables, SHAP plots, and model artifacts

Usage:
------
    python rf_vs_world.py --data 'data/dump.csv' --optimize 'rf,xgb'

Arguments:
----------
    --data:     Path to input CSV (default: 'data/dump.csv')
    --optimize: Models to optimize (e.g., 'rf,xgb,gb')
    --timeout:  Optimization timeout (default: 1800 seconds)
    --iters:    Number of optimization trials (default: 200)

Pre-requisites:
---------------
- Define FMISID features in a .env.local file per the .env.template
"""

import shap
import time
import joblib
import optuna
import logging
import argparse
import numpy as np
import pandas as pd
import multiprocessing
from rich.table import Table
import matplotlib.pyplot as plt
from rich.console import Console
from rich.logging import RichHandler
from typing import List, Tuple, Dict
from dotenv import load_dotenv, dotenv_values
from sklearn.model_selection import train_test_split, KFold
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.stattools import acf
from optuna.pruners import MedianPruner
from xgboost import XGBRegressor
from optuna import Trial
from tqdm import tqdm

# Load environment variables
load_dotenv()
env_vars = dotenv_values(".env.local")

# Get the FMISID features from environment variables
FMISID_T = env_vars["FMISID_T"].split(',')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="[%Y-%m-%d %H:%M:%S]",
    handlers=[RichHandler(rich_tracebacks=True)]
)

# Suppress Optuna logging
# optuna.logging.set_verbosity(optuna.logging.WARNING)

# Initialize logger and console
logger = logging.getLogger("rich")
console = Console()

def get_n_jobs() -> int:
    """Determine the number of jobs to run in parallel."""
    total_cores = multiprocessing.cpu_count()
    return int(max(1, total_cores * 0.8))

def symmetric_mean_absolute_percentage_error(y_true, y_pred):
    """Compute SMAPE between true and predicted values."""
    denominator = (np.abs(y_true) + np.abs(y_pred)) / 2
    denominator = np.where(denominator == 0, 1e-10, denominator)  # Avoid division by zero
    return np.mean(np.abs(y_true - y_pred) / denominator) * 100

def preprocess_data(df: pd.DataFrame, fmisid_t: List[str]) -> Tuple[pd.DataFrame, pd.Series]:
    """Preprocess the data for model training."""
    logger.info("Starting data preprocessing...\n")

    # Log initial data shape and NaN values in target column
    logger.info(f"Initial data shape: {df.shape}")
    initial_nan_count = df['Price_cpkWh'].isna().sum()
    logger.info(f"Initial number of NaN values in target column 'Price_cpkWh': {initial_nan_count}")

    # Drop the 'PricePredict_cpkWh' column if it exists
    df = df.drop(columns=['PricePredict_cpkWh'], errors='ignore')
    logger.info("'PricePredict_cpkWh' column dropped if existed.")

    # Extract day of week and hour from timestamp
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    df['day_of_week'] = df['timestamp'].dt.dayofweek
    df['hour'] = df['timestamp'].dt.hour
        
    # Drop any remaining rows with NaN values in the target column
    df.dropna(subset=['Price_cpkWh'], inplace=True)
    logger.debug(f"Number of NaN values in 'Price_cpkWh' after forward-fill imputation: {df['Price_cpkWh'].isna().sum()}")

    # Cyclical transformation
    df['day_of_week_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
    df['day_of_week_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
    df['year'] = df['timestamp'].dt.year

    # Calculate temp_mean and temp_variance from temperature features
    df['temp_mean'] = df[fmisid_t].mean(axis=1)
    df['temp_variance'] = df[fmisid_t].var(axis=1)
    
    # Take the int value of the 'holiday' column
    # df['holiday'] = df['holiday'].astype(int)

    # Drop the original time features from training data
    feature_columns = [
        'year', 'day_of_week_sin', 'day_of_week_cos', 'hour_sin', 'hour_cos',
        'NuclearPowerMW', 'ImportCapacityMW', 'WindPowerMW',
        'temp_mean', 'temp_variance', 'holiday', 'sum_irradiance', 'mean_irradiance', 
        'std_irradiance', 'min_irradiance', 'max_irradiance',
        # Individual border capacities
        'SE1_FI', 'SE3_FI', 'EE_FI',
        # Baltic Sea wind speeds
        'eu_ws_EE01', 'eu_ws_EE02', 'eu_ws_DK01', 'eu_ws_DK02', 'eu_ws_DE01', 'eu_ws_DE02', 'eu_ws_SE01', 'eu_ws_SE02', 'eu_ws_SE03'
    ] + fmisid_t

    # Log the number of NaN values in the final feature columns
    nan_count = df[feature_columns].isna().sum().sum()
    logger.info(f"Number of NaN values in final feature columns: {nan_count}")
    
    # Drop the rows with NaN values in the feature columns
    # df = df.dropna(subset=feature_columns)

    # Use forward-fill imputation to handle missing values
    df[feature_columns] = df[feature_columns].ffill()

    # Log the final feature columns
    logger.info(f"Initial feature columns extracted: {feature_columns}")

    # Cap the outliers at percentile thresholds
    upper_limit = df['Price_cpkWh'].quantile(0.9997)
    lower_limit = df['Price_cpkWh'].quantile(0.0009)
    df['Price_cpkWh'] = np.clip(df['Price_cpkWh'], lower_limit, upper_limit)
    logger.info(f"Capped 'Price_cpkWh' at lower_limit: {lower_limit} and upper_limit: {upper_limit}")

    # Log the final data shape to be used for optimization
    X_filtered = df[feature_columns]
    y_filtered = df['Price_cpkWh']
    logger.info(f"Data shape for optimization: X={X_filtered.shape}, y={y_filtered.shape}")

    return X_filtered, y_filtered

def cross_validate(model, X, y, model_name, n_splits=5) -> Dict[str, float]:
    """Perform cross-validation on the model using KFold."""
    logger.debug(f"Starting cross-validation for {model_name}...")

    # Use KFold with shuffle for cross-validation
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42) 
    mae_scores, mse_scores, r2_scores, smape_scores = [], [], [], []

    # Iterate over each fold and calculate metrics
    for fold, (train_index, test_index) in enumerate(tqdm(kf.split(X), total=n_splits, desc=f"CV for {model_name}")):
        X_train, X_val = X.iloc[train_index], X.iloc[test_index]
        y_train, y_val = y.iloc[train_index], y.iloc[test_index]
        model.fit(X_train, y_train)
        y_pred = model.predict(X_val)
        mae_scores.append(mean_absolute_error(y_val, y_pred))
        mse_scores.append(mean_squared_error(y_val, y_pred))
        r2_scores.append(r2_score(y_val, y_pred))
        smape_scores.append(symmetric_mean_absolute_percentage_error(y_val, y_pred))
        logger.debug(f"Completed fold {fold+1}/{n_splits}")

    # Calculate mean metrics across all folds
    mae = np.mean(mae_scores)
    mse = np.mean(mse_scores)
    rmse = np.sqrt(mse)
    r2 = np.mean(r2_scores)
    smape = np.mean(smape_scores)

    # Log the cross-validation results
    logger.info(f"Cross-validation completed for {model_name}")
    logger.info(f"Mean MAE: {mae:.4f}, Mean MSE: {mse:.4f}, Mean RMSE: {rmse:.4f}, Mean R²: {r2:.4f}, Mean SMAPE: {smape:.4f}")

    return {
        "CV_MAE": mae,
        "CV_MSE": mse,
        "CV_RMSE": rmse,
        "CV_R²": r2,
        "CV_SMAPE": smape
    }

def train_and_evaluate(model, X_train, y_train, X_test, y_test, model_name):
    """Train the model and evaluate its performance."""
    logger.info(f"Starting training and evaluation for {model_name}...")
    
    start_time = time.time()
    
    # Check if the model supports eval_set
    if hasattr(model, 'fit') and 'eval_set' in model.fit.__code__.co_varnames:
        # Fit the model with training data and use eval_set for early stopping
        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            eval_metric='rmse',
            early_stopping_rounds=50,
            verbose=True
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
    smape = symmetric_mean_absolute_percentage_error(y_test, y_pred)

    # Calculate residuals
    residuals = y_test - y_pred

    # Durbin-Watson statistic for autocorrelation in residuals
    dw_stat = durbin_watson(residuals)
    
    # Autocorrelation function to further analyze residuals
    acf_values = acf(residuals, nlags=3, fft=False)

    # Feature importance
    feature_importance = None

    # Extract feature importance for tree-based models
    if hasattr(model, 'feature_importances_'):
        feature_importance = pd.DataFrame({
            'Feature': X_train.columns,
            'Importance': model.feature_importances_
        }).sort_values(by='Importance', ascending=False)
        logger.debug(f"Feature importance extracted for {model_name}.")

    # For linear models, use coefficients as feature importance
    elif hasattr(model, 'coef_'):
        feature_importance = pd.DataFrame({
            'Feature': X_train.columns,
            'Importance': model.coef_
        }).sort_values(by='Importance', ascending=False)
        logger.debug(f"Coef based feature importance extracted for {model_name}.")

    # SHAP values for feature impact analysis
    shap_values = None
    try:
        explainer = shap.TreeExplainer(model, X_train)
        shap_values = explainer(X_test, check_additivity=False)
        shap.summary_plot(shap_values, X_test, plot_type="bar", show=False)
        plt.savefig(f"{model_name}_shap_summary.png")
        logger.info(f"SHAP summary plot saved to {model_name}_shap_summary.png")
    except Exception as e:
        logger.warning(f"SHAP analysis failed for {model_name}: {str(e)}")

    # Compile results including all computed metrics and feature importance
    results = {
        "MAE": mae,
        "MSE": mse,
        "RMSE": rmse,
        "R²": r2,
        "SMAPE": smape,
        "Durbin-Watson": dw_stat,
        "ACF": acf_values,
        "Feature Importance": feature_importance,
        "SHAP Values": shap_values,
    }
    
    # Log the evaluation results
    logger.info(f"{model_name} evaluation completed with metrics:")
    logger.info(f"MAE: {mae:.4f}, MSE: {mse:.4f}, RMSE: {rmse:.4f}, R²: {r2:.4f}, SMAPE: {smape:.4f}")

    return results

def display_results(results):
    """Display the results of model comparison."""
    logger.info("Preparing to display model comparison results...")

    # Create tables for displaying results
    tables = {
        "main": Table(title="Model Performance Comparison - Test Set Metrics"),
        "cv": Table(title="5-Fold Cross-Validation Results"),
        "autocorr": Table(title="Autocorrelation Analysis")
    }

    # Main table setup
    tables["main"].add_column("Model", justify="left", style="cyan")
    for metric in ["MAE", "MSE", "RMSE", "R²", "SMAPE"]:
        tables["main"].add_column(metric, justify="right")

    # Cross-validation table setup
    tables["cv"].add_column("Model", justify="left", style="cyan")
    for metric in ["CV MAE", "CV MSE", "CV RMSE", "CV R²", "CV SMAPE"]:
        tables["cv"].add_column(metric, justify="right")

    # Autocorrelation table setup
    tables["autocorr"].add_column("Model", justify="left", style="cyan")
    tables["autocorr"].add_column("Durbin-Watson", justify="right")
    for i in range(1, 4):
        tables["autocorr"].add_column(f"ACF (Lag {i})", justify="right")

    # Filling in tables with available data
    for model_name, metrics in results.items():
        tables["main"].add_row(
            model_name,
            *[f"{metrics.get(m, np.nan):.4f}" for m in ["MAE", "MSE", "RMSE", "R²", "SMAPE"]]
        )

        tables["cv"].add_row(
            model_name,
            *[f"{metrics.get(f'CV_{m}', np.nan):.4f}" for m in ["MAE", "MSE", "RMSE", "R²", "SMAPE"]]
        )

        acf_vals = metrics.get("ACF", [np.nan]*4)
        tables["autocorr"].add_row(
            model_name,
            f"{metrics.get('Durbin-Watson', np.nan):.4f}",
            *[f"{acf_vals[i]:.4f}" for i in range(1, 4)]
        )

    # Display tables
    for table in tables.values():
        console.print(table)

    # Display feature importance and best parameters
    for model_name, metrics in results.items():
        console.print(f"\nTop 10 Feature Importance for {model_name}:")
        feature_importance = metrics.get('Feature Importance')
        if feature_importance is not None:
            console.print(feature_importance.head(10).to_string(index=True))
        else:
            console.print("Feature importance data not available.")

        if 'Best Params' in metrics:
            console.print(f"Best Parameters found for {model_name}: {metrics['Best Params']}")

def tune_model_with_optuna(model_class, X, y, model_name, timeout, iterations):
    """Use Optuna to find the best model parameters with nested cross-validation."""
    logger.info(f"Starting nested cross-validation with Optuna tuning for {model_name}")
    
    # Outer cross-validation setup
    outer_kf = KFold(n_splits=5, shuffle=True, random_state=42)
    outer_cv_results = []

    # Nested cross-validation with Optuna
    for outer_fold, (outer_train_index, outer_test_index) in enumerate(outer_kf.split(X)):
        logger.info(f"Processing outer fold {outer_fold + 1}/5...")
        X_outer_train, X_outer_test = X.iloc[outer_train_index], X.iloc[outer_test_index]
        y_outer_train, y_outer_test = y.iloc[outer_train_index], y.iloc[outer_test_index]

        # Objective setup for Optuna for each model
        def objective(trial: Trial):
            params = {}
            
            if model_name == 'Random Forest':
                params = {
                    'n_estimators': trial.suggest_int('n_estimators', 100, 1000),
                    'max_depth': trial.suggest_int('max_depth', 5, 30),
                    'min_samples_split': trial.suggest_int('min_samples_split', 2, 20),
                    'min_samples_leaf': trial.suggest_int('min_samples_leaf', 1, 10),
                    'random_state': 42,
                    'n_jobs': get_n_jobs(),
                }
                
            # For this model we know a range from previous experiments
            elif model_name == 'XGBoost':
                params = {
                    'n_estimators': trial.suggest_int('n_estimators', 7000, 12000),
                    'max_depth': trial.suggest_int('max_depth', 5, 12),            
                    'learning_rate': trial.suggest_float('learning_rate', 0.005, 0.05, log=True),
                    'subsample': trial.suggest_float('subsample', 0.1, 0.8),
                    'colsample_bytree': trial.suggest_float('colsample_bytree', 0.4, 0.8),
                    'gamma': trial.suggest_float('gamma', 0, 0.1),
                    'reg_alpha': trial.suggest_float('reg_alpha', 0.6, 5.0),
                    'reg_lambda': trial.suggest_float('reg_lambda', 0.0001, 0.8),
                    'random_state': 42,
                    'n_jobs': get_n_jobs(),
                }

            elif model_name == 'Gradient Boosting':
                params = {
                    'n_estimators': trial.suggest_int('n_estimators', 100, 1000),
                    'max_depth': trial.suggest_int('max_depth', 3, 15),
                    'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
                    'min_samples_split': trial.suggest_int('min_samples_split', 2, 20),
                    'min_samples_leaf': trial.suggest_int('min_samples_leaf', 1, 10),
                    'random_state': 42,
                }

            # Inner cross-validation setup
            model = model_class(**params)
            inner_kf = KFold(n_splits=3, shuffle=True, random_state=42)  # Inner cross-validation
            inner_scores = []

            # Inner fold training and evaluation with early stopping
            for inner_fold, (inner_train_index, inner_test_index) in enumerate(inner_kf.split(X_outer_train)):
                X_inner_train, X_inner_val = X_outer_train.iloc[inner_train_index], X_outer_train.iloc[inner_test_index]
                y_inner_train, y_inner_val = y_outer_train.iloc[inner_train_index], y_outer_train.iloc[inner_test_index]

                # Check if the model supports eval_set for early stopping
                if hasattr(model, 'fit') and 'eval_set' in model.fit.__code__.co_varnames:
                    model.fit(
                        X_inner_train, y_inner_train,
                        eval_set=[(X_inner_val, y_inner_val)],
                        eval_metric='rmse',
                        early_stopping_rounds=50,
                        verbose=False
                    )
                else:
                    model.fit(X_inner_train, y_inner_train)

                y_pred = model.predict(X_inner_val)
                score = mean_squared_error(y_inner_val, y_pred)
                inner_scores.append(score)
                trial.report(score, inner_fold)
                if trial.should_prune():
                    raise optuna.exceptions.TrialPruned()
            return np.mean(inner_scores)

        # Run Optuna optimization for the model
        study = optuna.create_study(
            direction='minimize',
            sampler=optuna.samplers.TPESampler(),
            pruner=MedianPruner(n_startup_trials=5, n_warmup_steps=5)
        )
        study.optimize(objective, n_trials=iterations, timeout=timeout, n_jobs=get_n_jobs())

        # Train the best model on the outer fold
        best_params = study.best_trial.params
        best_model = model_class(**best_params)
        best_model.fit(X_outer_train, y_outer_train)
        y_outer_pred = best_model.predict(X_outer_test)
        outer_mse = mean_squared_error(y_outer_test, y_outer_pred)
        outer_cv_results.append(outer_mse)
        logger.info(f"Outer fold {outer_fold + 1} completed with test MSE: {outer_mse}")

    # Calculate average test MSE across all outer folds
    nested_cv_mse = np.mean(outer_cv_results)
    logger.info(f"Nested cross-validation completed with average test MSE: {nested_cv_mse}")

    return best_model, best_params

def main():
    """Main function to run the model comparison experiment."""
    parser = argparse.ArgumentParser(description="Train and compare tree-based models for electricity price prediction.")
    parser.add_argument('--data', type=str, default='data/dump.csv', help='Path to the data file (default: data/dump.csv)')
    parser.add_argument('--optimize', type=str, help="Comma-separated list of model abbreviations to optimize (e.g., 'rf,xgb')", default='rf,xgb,gb')
    parser.add_argument('--timeout', type=int, default=1800, help='Timeout in seconds for each model optimization (default: 1800)')
    parser.add_argument('--iters', type=int, default=200, help='Number of trials for hyperparameter optimization with Optuna (default: 200)')
    args = parser.parse_args()

    logger.info("Starting model comparison")

    # Store timeout and iterations from arguments
    timeout = args.timeout
    iterations = args.iters

    # Load data from SQLite3 CSV dump
    try:
        df = pd.read_csv(args.data)
        logger.info(f"Dataset loaded successfully. Shape: {df.shape}")
    except Exception as e:
        logger.error(f"Error loading the dataset: {str(e)}")
        return

    # Environment variable feature names
    fmisid_t = [f"t_{id}" for id in FMISID_T]

    # Preprocess data
    try:
        X, y = preprocess_data(df, fmisid_t)
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    except Exception as e:
        logger.error(f"Error during data preprocessing or splitting: {str(e)}")
        return

    # Determine the number of jobs to run in parallel
    n_jobs = get_n_jobs()

    # Define models to optimize
    all_models = {
        "rf": ("Random Forest", RandomForestRegressor(random_state=42, n_jobs=n_jobs)),
        "xgb": ("XGBoost", XGBRegressor(random_state=42, n_jobs=n_jobs, early_stopping_rounds=50)),
        "gb": ("Gradient Boosting", GradientBoostingRegressor(random_state=42))
    }

    # Convert the optimize parameter to a list of abbreviations
    optimize_abbr = [abbr.strip() for abbr in args.optimize.split(",")]

    # Filter models based on the user-provided abbreviations
    models = {name: model for abbr, (name, model) in all_models.items() if abbr in optimize_abbr}

    # Check if any valid models are selected for optimization
    if not models:
        logger.error("No valid models selected for optimization. Please check the --optimize parameter.")
        return

    results = {}

    # Iterate over each model and train it
    for model_name, model in tqdm(models.items(), desc="Model Processing"):
        logger.info(f"Processing {model_name}...")
        try:
            model_class = type(model)
            model, best_params = tune_model_with_optuna(
                model_class, X_train, y_train, model_name, timeout, iterations)

            cv_results = cross_validate(model, X_train, y_train, model_name, n_splits=5)
            eval_results = train_and_evaluate(model, X_train, y_train, X_test, y_test, model_name)
            results[model_name] = {**cv_results, **eval_results, "Best Params": best_params}

            joblib.dump(model, f'{model_name}_model.pkl')
            logger.info(f"{model_name} model saved to '{model_name}_model.pkl'")

        except Exception as e:
            logger.error(f"Error processing {model_name}: {str(e)}")

    # Display the results
    try:
        display_results(results)
        logger.info("Model comparison completed")
    except Exception as e:
        logger.error(f"Error displaying results: {str(e)}")

if __name__ == "__main__":
    main()