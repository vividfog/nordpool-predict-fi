"""
This script retrieves wind power data from the Fingrid API, integrates it into an existing DataFrame,
and infers missing values up to 5 days in the future using a neural network model that is trained on-the-fly.

- Fetches wind power data from 7 days in the past to 5 days in the future.
- Merges the retrieved data into an input DataFrame and infers absent values using a dynamically trained neural network model.
- The model predicts wind power based on weather inputs defined in the .env.local configuration.
- Utilizes PyTorch for defining and training the neural network model.

Requirements:
- API keys and FMISID values set in the .env.local file for accessing the Fingrid API and configuring the weather input features.

Usage:
- Ensure the environment variables are properly set in .env.local.
- Run the script to test that it can infer missing wind power values from a synthetic test dataset.
"""

import os
import sys
import time
import pandas as pd
import requests
import pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv
from rich import print
import torch
import numpy as np
from sklearn.preprocessing import StandardScaler
import torch.nn as nn
import joblib
import json

from util.train_windpower_nn import train_windpower_nn
from util.sql import db_query_all

pd.options.mode.copy_on_write = True

# Load environment variables
load_dotenv('.env.local')

# Constants
WIND_POWER_DATASET_ID = 245  # Fingrid dataset ID for wind power
WIND_POWER_CAPACITY_DATASET_ID = 268  # Fingrid dataset ID for wind power capacity

def fetch_fingrid_data(fingrid_api_key, dataset_id, start_date, end_date):
    api_url = "https://data.fingrid.fi/api/data"
    headers = {'x-api-key': fingrid_api_key}
    params = {
        'datasets': str(dataset_id),
        'startTime': f"{start_date}T00:00:00.000Z",
        'endTime': f"{end_date}T23:59:59.000Z",
        'format': 'json',
        'oneRowPerTimePeriod': False,
        'page': 1,
        'pageSize': 20000,
        'locale': 'en'
    }
    
    # Rate limit handling
    time.sleep(3)
    
    for attempt in range(3):
        try:
            response = requests.get(api_url, headers=headers, params=params)
            response.raise_for_status()
            
            if response.status_code == 200:
                try:
                    data = response.json().get('data', [])
                except ValueError:
                    raise ValueError("Failed to decode JSON from response from Fingrid")

                if 'data' not in response.json():
                    raise ValueError("Unexpected response structure: " + str(response.json()))

                df = pd.DataFrame(data)
                if not df.empty:
                    if df['startTime'].dtype == 'int64':
                        df['startTime'] = pd.to_datetime(df['startTime'], unit='ms', utc=True)
                    else:
                        df['startTime'] = pd.to_datetime(df['startTime'], utc=True)
                    
                    return df
            elif response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                print(f"Rate limited! Waiting for {retry_after} seconds.")
                time.sleep(retry_after)
            else:
                raise requests.exceptions.RequestException(f"Failed to fetch data: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"Error occurred while requesting Fingrid data: {e}")
            time.sleep(5)
    
    raise RuntimeError("Failed to fetch data after 3 attempts")

def update_windpower(df, fingrid_api_key):
    """
    Updates the input DataFrame with wind power data.
    Fills in missing WindPowerMW values using a given model.
    """
    
    # Define the current date and adjust the start and end dates
    current_date = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
    history_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (datetime.now(pytz.UTC) + timedelta(days=8)).strftime("%Y-%m-%d")

    print(f"* Fingrid: Fetching wind power data between {history_date} and {end_date}")

    # Fetch wind power data
    wind_power_df = fetch_fingrid_data(fingrid_api_key, WIND_POWER_DATASET_ID, history_date, end_date)
    wind_power_df.rename(columns={'value': 'WindPowerMW'}, inplace=True)

    # Fetch wind power capacity data
    wind_power_capacity_df = fetch_fingrid_data(fingrid_api_key, WIND_POWER_CAPACITY_DATASET_ID, history_date, end_date)
    wind_power_capacity_df.rename(columns={'value': 'WindPowerCapacityMW'}, inplace=True)

    # Ensure the Timestamp column is in datetime format
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)

    # Merge both wind power data and wind power capacity into input dataframe
    merged_df = pd.merge(df, wind_power_df, left_on='timestamp', right_on='startTime', how='left', suffixes=('', '_api'))
    merged_df = pd.merge(merged_df, wind_power_capacity_df, left_on='timestamp', right_on='startTime', how='left', suffixes=('', '_capacity_api'))

    # Drop the API-specific timestamp columns
    merged_df.drop(columns=['startTime', 'startTime_capacity_api'], inplace=True)

    # Prioritize overwriting input DF with API truthful data
    merged_df['WindPowerMW'] = merged_df['WindPowerMW_api']
    merged_df.drop(columns=['WindPowerMW_api'], inplace=True)

    # Prioritize filling WindPowerCapacityMW from API data
    merged_df['WindPowerCapacityMW'] = merged_df['WindPowerCapacityMW_capacity_api'].ffill()
    merged_df.drop(columns=['WindPowerCapacityMW_capacity_api'], inplace=True)

    # Drop redundant columns that originated from the API data
    merged_df.drop(columns=['datasetId', 'endTime', 'datasetId_capacity_api', 'endTime_capacity_api'], inplace=True)

    # Fetch full historical data from SQL helper function
    db_path = os.getenv('DB_PATH', 'data/prediction.db')
    historical_df = db_query_all(db_path)

    # Merge historical data with the latest Fingrid data, prioritizing Fingrid data for latest values
    df_training = pd.concat([historical_df, merged_df]).drop_duplicates(subset=['timestamp'], keep='last').reset_index(drop=True)

    # Ensure df_training contains timestamps only up to the last known value from the Fingrid API
    last_known_timestamp = pd.to_datetime(wind_power_df['startTime'].max())
    
    # Print the last known timestamp for debugging
    print(f"Last known timestamp from Fingrid wind power API: {last_known_timestamp}")
    
    # Ensure the timestamp column in df_training is of type Timestamp
    df_training['timestamp'] = pd.to_datetime(df_training['timestamp'], utc=True)

    df_training = df_training[df_training['timestamp'] <= last_known_timestamp]
    
    # Print the tail of the training DataFrame for debugging
    print("Training DataFrame tail:")
    print(df_training.tail())

    # Identify rows with missing WindPowerMW values
    missing_wind_power = merged_df['WindPowerMW'].isnull()

    # Prepare input features dynamically
    ws_ids = os.getenv('FMISID_WS').split(',')
    t_ids = os.getenv('FMISID_T').split(',')

    # Train model on-demand using the df_training
    model, scaler_X, scaler_y = train_windpower_nn(df_training, target_col='WindPowerMW', wp_fmisid=ws_ids)

    # Construct the feature dictionary dynamically without adding columns to merged_df
    features = {f'ws_{ws_id}': merged_df.loc[missing_wind_power, f'ws_{ws_id}'] for ws_id in ws_ids}
    features.update({f't_{t_id}': merged_df.loc[missing_wind_power, f't_{t_id}'] for t_id in t_ids})
    
    # Extract the hour from the Timestamp and create cyclic features dynamically
    hour = merged_df.loc[missing_wind_power, 'timestamp'].dt.hour
    features['hour_sin'] = np.sin(2 * np.pi * hour / 24)
    features['hour_cos'] = np.cos(2 * np.pi * hour / 24)

    # Use the WindPowerCapacityMW from the merged df
    features['WindPowerCapacityMW'] = merged_df.loc[missing_wind_power, 'WindPowerCapacityMW'].ffill()

    # Dynamically compute average wind speed and variance
    ws_cols = [f'ws_{ws_id}' for ws_id in ws_ids]
    features['Avg_WindSpeed'] = merged_df.loc[missing_wind_power, ws_cols].mean(axis=1)
    features['WindSpeed_Variance'] = merged_df.loc[missing_wind_power, ws_cols].var(axis=1)

    # Create a DataFrame with the feature columns
    X_missing_df = pd.DataFrame(features)

    if not X_missing_df.empty:
        # Print the features before scaling for debugging
        print("Features before scaling:")
        print(X_missing_df)

        # Scale the features
        X_scaled = scaler_X.transform(X_missing_df)

        # Print the features after scaling for debugging
        print("Features after scaling:")
        print(X_scaled)

        # Convert to torch tensor
        X_tensor = torch.tensor(X_scaled, dtype=torch.float32)

        # Predict using the trained model
        with torch.no_grad():
            predicted_wind_power = model(X_tensor).numpy().flatten()

        # Print the raw predictions for debugging
        print("Raw predictions:")
        print(predicted_wind_power)

        # Inverse transform the predictions
        predicted_wind_power = scaler_y.inverse_transform(predicted_wind_power.reshape(-1, 1)).flatten()
        predicted_wind_power = np.round(predicted_wind_power, 1)

        # Print the inverse-transformed and rounded predictions for debugging
        print("Inverse-transformed and rounded predictions:")
        print(predicted_wind_power)

        # Ensure no negative predictions
        predicted_wind_power[predicted_wind_power < 0] = 0

        # Print the final predictions before updating the DataFrame
        print("Final predictions (non-negative):")
        print(predicted_wind_power)

        merged_df.loc[missing_wind_power, 'WindPowerMW'] = predicted_wind_power
    else:
        print("→ No missing wind power values found, no predictions needed.")

    # Calculate statistics for the inferred values
    if 'predicted_wind_power' in locals() and len(predicted_wind_power) > 0:
        min_pred = np.min(predicted_wind_power)
        max_pred = np.max(predicted_wind_power)
        avg_pred = np.mean(predicted_wind_power)
        median_pred = np.median(predicted_wind_power)

        # Check if any of the statistics are NaN, and exit if so
        if np.isnan(min_pred) or np.isnan(max_pred) or np.isnan(avg_pred) or np.isnan(median_pred):
            print("→ Error: One or more statistics contain NaN values. Exiting.")
            sys.exit(1)

        print(f"→ Inferred wind power values for {missing_wind_power.sum()} missing entries "
            f"(Min: {min_pred:.1f}, Max: {max_pred:.1f}, "
            f"Avg: {avg_pred:.1f}, Median: {median_pred:.1f}).")
    else:
        print("→ No wind power values needed to be inferred.")

    return merged_df

# Main function for testing only, with dummy data
def main():
    # Configure pandas to display all rows
    pd.set_option('display.max_rows', None)
    
    # Load the Fingrid API key and FMISID values from the environment
    load_dotenv('.env.local')

    fingrid_api_key = os.getenv('FINGRID_API_KEY')
    if fingrid_api_key is None:
        raise ValueError("Fingrid API key not found in environment variables")

    fmisid_ws = os.getenv('FMISID_WS')
    fmisid_t = os.getenv('FMISID_T')
    
    if fmisid_ws is None or fmisid_t is None:
        raise ValueError("FMISID values for ws and/or t not found in environment variables")
    
    ws_ids = fmisid_ws.split(',')
    t_ids = fmisid_t.split(',')

    # Define the date range: 7 days in the past to 5 days in the future
    start_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (datetime.now(pytz.UTC) + timedelta(days=8)).strftime("%Y-%m-%d")

    # Prepare a dummy DataFrame covering the entire period
    print(f"Prepare dummy data from {start_date} to {end_date}")
    timestamps = pd.date_range(start=start_date, end=end_date, freq='h', tz=pytz.UTC)
    
    # Add dummy columns including the ws_ and t_ columns based on FMISID
    df_data = {
        'timestamp': timestamps, 
    }

    # Populate dummy data for ws_ columns with rounding to 1 decimal place
    for ws_id in ws_ids:
        df_data[f'ws_{ws_id}'] = np.round(np.random.uniform(0.0, 15.0, len(timestamps)), 1)

    # Populate dummy data for t_ columns with rounding to 1 decimal place
    for t_id in t_ids:
        df_data[f't_{t_id}'] = np.round(np.random.uniform(-10.0, 20.0, len(timestamps)), 1)

    # Add dummy data for the WindPowerMW column
    df_data['WindPowerMW'] = np.round(np.random.uniform(50.0, 5000.0, len(timestamps)), 1)
    df_data['WindPowerMW'][-120:] = np.nan  # Set the last values to NaN

    # Add dummy data for the WindPowerCapacityMW column
    df_data['WindPowerCapacityMW'] = np.round(np.random.uniform(7000.0, 7000.0, len(timestamps)), 1)
    df_data['WindPowerCapacityMW'][-120:] = np.nan  # Set the last values to NaN

    df = pd.DataFrame(df_data)
    
    # Output the initial DataFrame
    print("Initial DataFrame:")
    print(df)
    
    # Update the DataFrame with wind power data
    updated_df = update_windpower(df, fingrid_api_key)

    # Output the DataFrame after updating with wind power data
    print("DataFrame After Wind Power Update:")
    print(updated_df)

if __name__ == "__main__":
    main()
