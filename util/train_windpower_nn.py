"""
2025-01-12: DEPRECATED, not currently maintained; using XGB for now

This module provides components and processes to train a neural network for predicting wind power output using
meteorological and temporal data features.

- Prepares input features and targets through data preprocessing.
- Defines a PyTorch dataset and model for wind power prediction.
- Retrieves hyperparameters from a JSON file specified via an environment variable.
- Incorporates a training loop with early stopping based on validation loss.
- Outputs a trained model and scalers for feature and target transformations.

Context:
Designed to dynamically train a wind power prediction model during execution, this module is part of a system 
for integrating and inferring wind power data, offering adaptability to new datasets and conditions without 
relying on pre-trained models.

Requirements:
- CSV dataset with weather features and wind power data ("data/dump.csv").
- WIND_POWER_NN_HYPERPARAMS environment variable pointing to a JSON file with model hyperparameters.

Usage:
- Ensure availability of the dataset and correct environment variable configuration.
- Use the `train_windpower_nn` function with the target column and feature IDs.
- Apply the trained model and scalers to predict wind power.
"""

import os
import sys
import json
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import numpy as np
import pandas as pd
from typing import Tuple
from rich import print
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import pytz

pd.options.mode.copy_on_write = True

class WindPowerDataset(Dataset):
    def __init__(self, features: np.ndarray, target: np.ndarray):
        self.features = features
        self.target = target

    def __len__(self):
        return len(self.features)

    def __getitem__(self, idx):
        X = torch.tensor(self.features[idx], dtype=torch.float32)
        y = torch.tensor(self.target[idx], dtype=torch.float32)
        return X, y

class WindPowerNN(nn.Module):
    def __init__(self, input_size: int, hidden_size_1: int, hidden_size_2: int, dropout_rate: float):
        super(WindPowerNN, self).__init__()
        self.fc1 = nn.Linear(input_size, hidden_size_1)
        self.leaky_relu = nn.LeakyReLU()
        self.dropout = nn.Dropout(dropout_rate)
        self.fc2 = nn.Linear(hidden_size_1, hidden_size_2)
        self.fc3 = nn.Linear(hidden_size_2, 1)

    def forward(self, x):
        x = self.leaky_relu(self.fc1(x))
        x = self.dropout(x)
        x = self.leaky_relu(self.fc2(x))
        x = self.fc3(x)
        return x

def preprocess_data(df, target_col: str, wp_fmisid: list) -> Tuple[np.ndarray, np.ndarray, StandardScaler, StandardScaler]:
    print("→ Preprocess: Starting data preprocessing")

    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # Drop time stamps that are part yesterday and beyond
    # print(f"→ Dropping rows with timestamps beyond yesterday: {pd.Timestamp.now(tz=pytz.timezone('Europe/Helsinki')).replace(hour=0, minute=0, second=0, microsecond=0)}")
    # df = df[df['timestamp'] < pd.Timestamp.now(tz=pytz.timezone('Europe/Helsinki')).replace(hour=0, minute=0, second=0, microsecond=0)]
    
    print(f"→ Last time stamp in the dataset: {df['timestamp'].max()}")

    df['hour'] = df['timestamp'].dt.hour
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)

    if 'WindPowerCapacityMW' in df.columns:
        df['WindPowerCapacityMW'] = df['WindPowerCapacityMW'].ffill()
    else:
        print("[ERROR] 'WindPowerCapacityMW' column not found, this would cause missing features.")
        sys.exit(1)

    ws_cols = [f"ws_{id}" for id in wp_fmisid]
    t_cols = [f"t_{id}" for id in wp_fmisid if f"t_{id}" in df.columns]

    print("→ Preprocess: Checking for wind speed columns")
    if all(col in df.columns for col in ws_cols):
        df['Avg_WindSpeed'] = df[ws_cols].mean(axis=1)
        df['WindSpeed_Variance'] = df[ws_cols].var(axis=1)
    else:
        missing_ws_cols = [col for col in ws_cols if col not in df.columns]
        print(f"→ Missing wind speed columns: {missing_ws_cols}")
        raise KeyError(f"[ERROR] Missing columns: {missing_ws_cols}")

    feature_columns = ws_cols + t_cols + ['hour_sin', 'hour_cos', 'WindPowerCapacityMW', 'Avg_WindSpeed', 'WindSpeed_Variance']
    print("→ Preprocess: Required feature columns:")
    print(feature_columns)

    missing_cols = [col for col in feature_columns if col not in df.columns]
    if missing_cols:
        print(f"→ Missing feature columns: {missing_cols}")
        raise KeyError(f"[ERROR] Missing feature columns: {missing_cols}")

    if target_col not in df.columns:
        print(f"→ Target column '{target_col}' not found. This will cause an error.")
        raise KeyError(f"[ERROR] Target column '{target_col}' not found in dataframe.")

    # Drop rows with missing feature or target values
    initial_row_count = df.shape[0]
    df.dropna(subset=feature_columns + [target_col], inplace=True)
    dropped_row_count = initial_row_count - df.shape[0]
    if dropped_row_count > 0:
        print(f"→ Nr of dropped rows with NaN values: {dropped_row_count}")

    # Describe the dataset after dropping NaN values
    print("→ Preprocess: Dataset description after dropping NaN values")
    print(df.describe())
    
    # Print the head and tail of the dataset
    print("→ Preprocess: Dataset head")
    print(df.head())
    print("→ Preprocess: Dataset tail")
    print(df.tail())

    X = df[feature_columns]
    y = df[target_col]

    # Print the head and tail of X and Y
    print("→ Preprocess: Features (X) head")
    print(X.head())
    print("→ Preprocess: Features (X) tail")
    print(X.tail())
    print("→ Preprocess: Target (y) head")
    print(y.head())
    print("→ Preprocess: Target (y) tail")
    print(y.tail())

    # Print X column and Y column names
    print("→ Preprocess: Features (X) columns")
    print(X.columns)
    print("→ Preprocess: Target (y) column")
    print(y.name)

    # Sanity check: ensure that X and y have the same number of rows and there are no NaN values
    if X.shape[0] != y.shape[0]:
        raise ValueError(f"Mismatch in number of rows between features (X) and target (y): {X.shape[0]} vs {y.shape[0]}")
    if X.isnull().any().any() or y.isnull().any():
        raise ValueError("NaN values found in features (X) or target (y)")

    print("→ Preprocess: Scaling features and target")
    scaler_X = StandardScaler()
    scaler_y = StandardScaler()
    X_scaled = scaler_X.fit_transform(X)
    y_scaled = scaler_y.fit_transform(y.values.reshape(-1, 1)).flatten()

    # print("* Fingrid: Windpower: Preprocess: Finished preprocessing")
    print(f"→ Training feature matrix shape: {X_scaled.shape}, Target vector shape: {y_scaled.shape}")

    return X_scaled, y_scaled, scaler_X, scaler_y

def train_windpower_nn(df: pd.DataFrame, target_col: str, wp_fmisid: list):
    print("→ Train model: Starting training process: Reading hyperparameters")

    try:
        WIND_POWER_NN_HYPERPARAMS = os.getenv("WIND_POWER_NN_HYPERPARAMS")
        if WIND_POWER_NN_HYPERPARAMS is None:
            raise ValueError("[ERROR] Environment variable WIND_POWER_NN_HYPERPARAMS is not set.")
    except ValueError as e:
        print("[ERROR] Wind power .env.local variables are not set correctly. See .env.local.template for reference.")
        sys.exit(1)

    try:
        with open(WIND_POWER_NN_HYPERPARAMS, 'r') as f:
            hyperparams = json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] Hyperparameters file not found at {WIND_POWER_NN_HYPERPARAMS}.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Decoding JSON from {WIND_POWER_NN_HYPERPARAMS}: {e}")
        sys.exit(1)

    hidden_size_1 = hyperparams.get("hidden_size_1", 256)
    hidden_size_2 = hyperparams.get("hidden_size_2", 112)
    dropout_rate = hyperparams.get("dropout_rate", 0.01)
    learning_rate = hyperparams.get("learning_rate", 1e-3)
    batch_size = hyperparams.get("batch_size", 64)
    epochs = hyperparams.get("epochs", 200)

    print("→ Train model: Reading data")
    print(f"→ Training: Input data shape: {df.shape}")
    print(df.describe())

    X_scaled, y_scaled, scaler_X, scaler_y = preprocess_data(df, target_col, wp_fmisid)

    # Training data description:
    print(f"→ Training data: X_scaled shape: {X_scaled.shape}, y_scaled shape: {y_scaled.shape}")

    # Sanity check: ensure that X and y have the same number of rows and there are no NaN values
    if X_scaled.shape[0] != y_scaled.shape[0]:
        raise ValueError(f"Mismatch in number of rows between features (X) and target (y): {X_scaled.shape[0]} vs {y_scaled.shape[0]}")
    if np.isnan(X_scaled).any() or np.isnan(y_scaled).any():
        raise ValueError("NaN values found in features (X) or target (y)")

    print("* Fingrid: Windpower: Train model: Splitting data into train and test sets")
    train_X, test_X, train_y, test_y = train_test_split(X_scaled, y_scaled, test_size=0.2, random_state=42)
    # Additional split for validation
    train_X, val_X, train_y, val_y = train_test_split(train_X, train_y, test_size=0.25, random_state=42)
    input_size = train_X.shape[1]
    print(f"→ Input size: {input_size}")

    print("* Fingrid: Windpower: Train model: Initializing model")
    model = WindPowerNN(input_size, hidden_size_1, hidden_size_2, dropout_rate)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model.to(device)
    print(f"→ Using device: {device}")

    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)

    train_dataset = WindPowerDataset(train_X, train_y)
    val_dataset = WindPowerDataset(val_X, val_y)
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    # Early stopping parameters
    patience = 10
    best_val_loss = float('inf')
    no_improvement = 0

    print(f"→ Fingrid: Wind power model: Training with {device}...")
    for epoch in range(epochs):
        model.train()
        epoch_loss = 0.0
        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device).unsqueeze(1)
            optimizer.zero_grad()
            outputs = model(X_batch)
            loss = criterion(outputs, y_batch)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
        epoch_loss /= len(train_loader)

        # Validation loss
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for X_val, y_val in val_loader:
                X_val, y_val = X_val.to(device), y_val.to(device).unsqueeze(1)
                val_outputs = model(X_val)
                val_loss += criterion(val_outputs, y_val).item()
        val_loss /= len(val_loader)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            no_improvement = 0
        else:
            no_improvement += 1
            if no_improvement >= patience:
                print(f"→ Early stopping after round {epoch+1}, validation loss: {val_loss:.4f}")
                break

        if (epoch+1) % 10 == 0:
            print(f"Epoch {epoch+1}/{epochs}, Train Loss: {epoch_loss:.4f}, Val Loss: {val_loss:.4f}")

    print("* Fingrid: Windpower: Train model: Training completed")

    model.eval()
    print("* Fingrid: Windpower: Train model: Returning trained model and scalers")

    return model, scaler_X, scaler_y
