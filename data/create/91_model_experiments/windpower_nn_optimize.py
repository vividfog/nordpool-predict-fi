import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from dotenv import load_dotenv, dotenv_values
import pandas as pd
import numpy as np
import argparse
import logging
import os
import optuna
import json
from typing import Tuple
import joblib
from tqdm import tqdm

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

# Configure logging with Rich
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="[%Y-%m-%d %H:%M:%S]",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("rich")
console = Console()

# Dataset class
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

# Neural network model
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

def preprocess_data(df: pd.DataFrame, target_col: str) -> Tuple[np.ndarray, np.ndarray, StandardScaler, StandardScaler]:
    load_dotenv()
    env_vars = dotenv_values(".env.local")
    wp_fmisid = env_vars["WP_FMISID"].split(',')
    logger.info(f"WP_FMISID loaded: {wp_fmisid}")

    logger.info("Starting data preprocessing...")
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
        df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
    df['WindPowerCapacityMW'] = df['WindPowerCapacityMW'].ffill()

    ws_cols = [f"ws_{id}" for id in wp_fmisid]
    if all(col in df.columns for col in ws_cols):
        df['Avg_WindSpeed'] = df[ws_cols].mean(axis=1)
        df['WindSpeed_Variance'] = df[ws_cols].var(axis=1)
    else:
        missing_ws_cols = [col for col in ws_cols if col not in df.columns]
        logger.error(f"Missing wind speed columns: {missing_ws_cols}")
        raise KeyError(f"Expected wind speed columns {missing_ws_cols} are not in the dataset.")

    df = df.drop(columns=['timestamp', 'WindPowerMW_predict'], errors='ignore')

    feature_columns = (
        ws_cols +
        [f"t_{id}" for id in wp_fmisid if f"t_{id}" in df.columns] +
        ['hour_sin', 'hour_cos', 'WindPowerCapacityMW', 'Avg_WindSpeed', 'WindSpeed_Variance']
    )

    missing_cols = [col for col in feature_columns if col not in df.columns]
    if missing_cols:
        logger.error(f"Missing feature columns: {missing_cols}")
        raise KeyError(f"The following expected feature columns are missing: {missing_cols}")

    imp = SimpleImputer(strategy='mean')
    X = pd.DataFrame(imp.fit_transform(df[feature_columns]), columns=feature_columns)
    y = df[target_col].fillna(df[target_col].mean())

    scaler_X = StandardScaler()
    scaler_y = StandardScaler()
    X_scaled = scaler_X.fit_transform(X)
    y_scaled = scaler_y.fit_transform(y.values.reshape(-1, 1)).flatten()

    logger.info(f"Preprocessed data shape: X={X_scaled.shape}, y={y_scaled.shape}")
    return X_scaled, y_scaled, scaler_X, scaler_y

def objective(trial, train_X, train_y, test_X, test_y, input_size, scaler_y):

    # Define hyperparameters to optimize
    hidden_size_1 = trial.suggest_int("hidden_size_1", 64, 256, step=16)  # Narrow around 128
    hidden_size_2 = trial.suggest_int("hidden_size_2", 32, 128, step=8)    # Narrow around 64
    dropout_rate = trial.suggest_float("dropout_rate", 0.01, 0.5, step=0.01)
    learning_rate = trial.suggest_float("learning_rate", 1e-6, 1e-2, log=True)
    batch_size = trial.suggest_categorical("batch_size", [32, 64, 128])  # Focus on smaller batch sizes

    # Model, optimizer, and loss function
    model = WindPowerNN(input_size, hidden_size_1, hidden_size_2, dropout_rate)

    # Check for available devices and prioritize them in the order: CUDA, MPS, CPU
    if torch.cuda.is_available():
        device = torch.device('cuda')
    elif torch.backends.mps.is_available():
        device = torch.device('mps')
    else:
        device = torch.device('cpu')
    
    model.to(device)

    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)

    # Prepare data loaders
    train_dataset = WindPowerDataset(train_X, train_y)
    test_dataset = WindPowerDataset(test_X, test_y)
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False)

    # Train the model
    for epoch in range(30):  # Use a smaller number of epochs for Optuna trials
        model.train()
        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device).unsqueeze(1)
            optimizer.zero_grad()
            outputs = model(X_batch)
            loss = criterion(outputs, y_batch)
            loss.backward()
            optimizer.step()

    # Evaluate the model
    model.eval()
    predictions, actuals = [], []
    with torch.no_grad():
        for X_batch, y_batch in test_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device)
            outputs = model(X_batch).cpu().numpy()
            predictions.extend(outputs)
            actuals.extend(y_batch.cpu().numpy())

    predictions = scaler_y.inverse_transform(np.array(predictions).reshape(-1, 1)).flatten()
    actuals = scaler_y.inverse_transform(np.array(actuals).reshape(-1, 1)).flatten()

    # Calculate evaluation metrics
    mae = mean_absolute_error(actuals, predictions)
    rmse = np.sqrt(mean_squared_error(actuals, predictions))
    r2 = r2_score(actuals, predictions)

    trial.set_user_attr("mae", mae)
    trial.set_user_attr("rmse", rmse)
    trial.set_user_attr("r2", r2)

    model.to('cpu')

    return rmse  # Optuna minimizes this objective

def retrain_final_model(best_hyperparams, train_X, train_y, scaler_y, input_size):
    logger.info("Retraining the best model with extended epochs...")

    # Define the model
    best_model = WindPowerNN(
        input_size=input_size,
        hidden_size_1=best_hyperparams["hidden_size_1"],
        hidden_size_2=best_hyperparams["hidden_size_2"],
        dropout_rate=best_hyperparams["dropout_rate"],
    )
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    best_model.to(device)

    # Log model architecture
    logger.info(f"Retraining with architecture:\n{best_model}")

    # Optimizer and loss
    optimizer = optim.Adam(best_model.parameters(), lr=best_hyperparams["learning_rate"])
    criterion = nn.MSELoss()

    # Prepare dataloader
    train_dataset = WindPowerDataset(train_X, train_y)
    train_loader = DataLoader(train_dataset, batch_size=best_hyperparams["batch_size"], shuffle=True)

    # Retrain for extended epochs
    num_epochs = 100
    for epoch in tqdm(range(num_epochs), desc="Training Epochs"):
        best_model.train()
        epoch_loss = 0.0
        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device).unsqueeze(1)
            optimizer.zero_grad()
            outputs = best_model(X_batch)
            loss = criterion(outputs, y_batch)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()

        epoch_loss /= len(train_loader)
        logger.info(f"Epoch {epoch + 1}/{num_epochs}, Loss: {epoch_loss:.4f}")

    # Move model to CPU for saving
    best_model.to('cpu')

    # Ensure the 'models/' directory exists
    os.makedirs("models", exist_ok=True)

    # Save the retrained model's state dictionary
    torch.save(best_model.state_dict(), "models/windpower_nn_state_dict.pth")

    # Save the full model
    torch.save(best_model, "models/windpower_nn_full.pth")

    logger.info("Retrained model saved as 'models/windpower_nn_state_dict.pth' and 'models/windpower_nn_full.pth'.")

    # Save the best hyperparameters to a JSON file
    with open("models/windpower_nn_hyperparams.json", "w") as f:
        json.dump(best_hyperparams, f)
    logger.info("Best hyperparameters saved to 'models/windpower_nn_hyperparams.json'.")

def main():
    parser = argparse.ArgumentParser(description="Hyperparameter optimization with Optuna for wind power prediction.")
    parser.add_argument('--data', type=str, default='data/dump.csv', help='Path to the input data file (CSV)')
    parser.add_argument('--target', type=str, default='WindPowerMW', help='Target column for prediction')
    parser.add_argument('--test-size', type=float, default=0.2, help='Proportion of data to use for testing')
    parser.add_argument('--trials', type=int, default=100, help='Number of Optuna trials')
    args = parser.parse_args()

    if not os.path.exists(args.data):
        logger.error(f"Data file not found: {args.data}")
        return

    df = pd.read_csv(args.data)
    X_scaled, y_scaled, scaler_X, scaler_y = preprocess_data(df, args.target)

    # Save the scalers
    os.makedirs("models", exist_ok=True)
    joblib.dump(scaler_X, "models/windpower_nn_scaler_X.joblib")
    joblib.dump(scaler_y, "models/windpower_nn_scaler_y.joblib")
    logger.info("Scalers saved to 'models/windpower_nn_scaler_X.joblib' and 'models/windpower_nn_scaler_y.joblib'.")

    train_X, test_X, train_y, test_y = train_test_split(X_scaled, y_scaled, test_size=args.test_size, random_state=42)

    input_size = train_X.shape[1]

    # Run Optuna study
    study = optuna.create_study(direction="minimize", study_name="wind_power_opt")

    # Use tqdm to wrap the optimization process
    for _ in tqdm(range(args.trials), desc="Optuna Trials"):
        study.optimize(lambda trial: objective(trial, train_X, train_y, test_X, test_y, input_size, scaler_y), n_trials=1, n_jobs=1)

    best_hyperparams = study.best_trial.params
    retrain_final_model(best_hyperparams, train_X, train_y, scaler_y, input_size)

    # Save results
    results = []
    for trial in study.trials:
        results.append({
            "Trial": trial.number,
            "MAE": trial.user_attrs.get("mae"),
            "RMSE": trial.user_attrs.get("rmse"),
            "R²": trial.user_attrs.get("r2"),
            **trial.params
        })

    results_df = pd.DataFrame(results)
    results_df.to_csv("optuna_results.csv", index=False)
    console.print("[bold green]Results saved to optuna_results.csv[/bold green]")

    # Display top trials in a table
    table = Table(title="Top Trials")
    for col in results_df.columns:
        table.add_column(col, justify="center")
    for _, row in results_df.nsmallest(10, "MAE").iterrows():
        table.add_row(*[str(row[col]) for col in results_df.columns])
    console.print(table)

if __name__ == "__main__":
    main()