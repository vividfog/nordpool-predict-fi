"""
Trains an XGBoost model for wind power prediction using meteorological features.

Functions:
- preprocess_data: Preprocesses the input DataFrame for training.
- train_windpower_xgb: Trains an XGBoost model with the preprocessed data.

"""

import os
import sys
import json
import numpy as np
import pandas as pd
from typing import Tuple, List
from rich import print
from sklearn.model_selection import train_test_split
import xgboost as xgb
from .logger import logger
from .xgb_utils import configure_cuda

pd.options.mode.copy_on_write = True

def preprocess_data(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
    # logger.info(f"Preprocess: Starting data preprocessing")

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)

    if 'WindPowerCapacityMW' in df.columns:
        df['WindPowerCapacityMW'] = df['WindPowerCapacityMW'].ffill()
    else:
        logger.error(f"'WindPowerCapacityMW' column not found.", exc_info=True)
        sys.exit(1)

    if 'WindPowerMW' in df.columns and 'WindPowerCapacityMW' in df.columns:
        df['WindProductionPercent'] = df['WindPowerMW'] / df['WindPowerCapacityMW']
    else:
        logger.error(f"'WindPowerMW' or 'WindPowerCapacityMW' column not found.", exc_info=True)
        sys.exit(1)

    ws_cols = [col for col in df.columns if col.startswith("ws_") or col.startswith("eu_ws_")]
    t_cols = [col for col in df.columns if col.startswith("t_")]

    if not all(col in df.columns for col in ws_cols):
        missing_ws_cols = [col for col in ws_cols if col not in df.columns]
        raise KeyError(f"[ERROR] Missing wind speed columns: {missing_ws_cols}")
    df['Avg_WindSpeed'] = df[ws_cols].mean(axis=1)
    df['WindSpeed_Variance'] = df[ws_cols].var(axis=1)

    feature_columns = ws_cols + t_cols + [
        # 'hour_sin', 'hour_cos', # 2025-01-01: Consider adding these later
        'WindPowerCapacityMW',
        'Avg_WindSpeed',
        'WindSpeed_Variance'
    ]

    target_col = 'WindProductionPercent'

    missing_cols = [col for col in feature_columns if col not in df.columns]
    if missing_cols:
        raise KeyError(f"[ERROR] Missing feature columns: {missing_cols}")

    if target_col not in df.columns:
        raise KeyError(f"[ERROR] Target column '{target_col}' not found in dataframe.")

    initial_count = df.shape[0]
    df.dropna(subset=feature_columns + [target_col], inplace=True)
    dropped_count = initial_count - df.shape[0]
    if dropped_count > 0:
        logger.info(f"Dropped {dropped_count} rows with NaN values.")

    X = df[feature_columns]
    y = df[target_col]

    return X, y

def train_windpower_xgb(df: pd.DataFrame):
    # logger.info(f"Train model: Reading hyperparameters")

    try:
        WIND_POWER_XGB_HYPERPARAMS = os.getenv("WIND_POWER_XGB_HYPERPARAMS", "models/windpower_xgb_hyperparams.json")
        if WIND_POWER_XGB_HYPERPARAMS is None:
            raise ValueError("WIND_POWER_XGB_HYPERPARAMS is not set.")
    except ValueError as e:
        logger.error(f"Missing environment variable for XGB hyperparams.", exc_info=True)
        sys.exit(1)

    try:
        with open(WIND_POWER_XGB_HYPERPARAMS, 'r') as f:
            hyperparams = json.load(f)
    except FileNotFoundError:
        logger.error(f"Hyperparameters file not found at {WIND_POWER_XGB_HYPERPARAMS}.", exc_info=True)
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Decoding JSON: {e}", exc_info=True)
        sys.exit(1)

    # logger.info(f"Train model: Preprocessing wind power data")
    X_features, y_target = preprocess_data(df)

    # Sort the feature columns to ensure predictable order
    X_features = X_features[sorted(X_features.columns)]

    # logger.info(f"Input data shape: {X_features.shape}, Target shape: {y_target.shape}")

    train_X, test_X, train_y, test_y = train_test_split(
        X_features, 
        y_target, 
        test_size=0.1, 
        shuffle=False, 
        random_state=42
    )

    logger.info(f"Train set: {train_X.shape}, Test set: {test_X.shape}")
    
    # Print final training columns, sanity check
    logger.info(f"WS model features: {', '.join(X_features.columns)}")
    
    # Print tail of the training data
    logger.info(f"Training with Fingrid wind power data up to {df['timestamp'].max()}, with tail:")
    print(X_features.tail())
    
    # Train the model
    hyperparams = configure_cuda(hyperparams, logger)
    logger.info(f"XGBoost for wind power: ")
    logger.info(f", ".join(f"{k}={v}" for k, v in hyperparams.items()))

    # First, create a model with early stopping to find the optimal number of trees
    logger.info(f"Fitting model with early stopping...")
    early_stopping_model = xgb.XGBRegressor(**hyperparams)
    early_stopping_model.fit(train_X, train_y, eval_set=[(test_X, test_y)], verbose=500)

    # Get the best iteration from early stopping
    best_iteration = early_stopping_model.best_iteration
    logger.info(f"Best iteration from early stopping: {best_iteration}")

    # Create a copy of hyperparams without early_stopping_rounds for the final fit
    training_params = {k: v for k, v in hyperparams.items() if k not in ["test_size", "early_stopping_rounds"]}

    # Set the optimal number of trees and refit on all data without early stopping
    final_model = xgb.XGBRegressor(**training_params)
    final_model.set_params(n_estimators=best_iteration)
    logger.info(f"Refitting model on all data with optimal n_estimators={best_iteration}...")
    final_model.fit(X_features, y_target, verbose=500)

    # Use the final model (trained on all data) for further evaluation
    xgb_model = final_model

    logger.info(f"Wind power model training complete.")
    return xgb_model
