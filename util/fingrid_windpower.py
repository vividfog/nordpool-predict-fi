"""
Retrieves wind power data from the Fingrid API, integrates it into an existing DataFrame, infers missing values up to 5 days in the future.

- Fetches wind power data from 7 days in the past to 5 days in the future.
- Merges the retrieved data into an input DataFrame and infers absent values using a pre-trained Gradient Boosting model, which forecasts wind power based on defined weather inputs in .env.local.
- There's a main function with dummy data generation for testing purposes.

To pretrain a model:
    python data/create/91_model_experiments/rf_vs_world_windpower.py --help

Currently using a pretrained Grandient Boosting model, as it scored the best in benchmarking experiment. We may switch to runtime training in the future.

Known issues:

- We should use more weather stations for training this model, but 4+4 is what the price prediction model uses for now, and we inherit the same environment.

- Currently, the WindPowerMW column is just an experiment for visualization purposes. The wind speed and temperature columns used to train the wind power model are already used for price prediction. A future experiment would be to create a more complete wind power model, and then include it in the price prediction pipeline.
"""

import os
import time
import pandas as pd
import requests
import pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv
from rich import print
import joblib
import numpy as np

# Constants: experimental for now so not in .env.local
WIND_POWER_DATASET_ID = 245
GB_MODEL_PATH = 'data/create/91_model_experiments/windpower_gradient_boosting.joblib'

def fetch_wind_power_data(fingrid_api_key, dataset_id, start_date, end_date):
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
                    
                    df.rename(columns={'value': 'WindPowerMW'}, inplace=True)
                    return df[['startTime', 'WindPowerMW']]
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
    Fills in missing WindPowerMW values using a Gradient Boosting model.
    """

    # Define the current date and adjust the start and end dates
    current_date = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
    history_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (datetime.now(pytz.UTC) + timedelta(hours=120)).strftime("%Y-%m-%d")

    print(f"* Fingrid: Fetching wind power data between {history_date} and {end_date}")

    # Fetch wind power data
    wind_power_df = fetch_wind_power_data(fingrid_api_key, WIND_POWER_DATASET_ID, history_date, end_date)

    # Ensure the Timestamp column is in datetime format
    df['Timestamp'] = pd.to_datetime(df['Timestamp'], utc=True)

    # Merge to include wind power data while preserving other columns
    merged_df = pd.merge(df, wind_power_df, left_on='Timestamp', right_on='startTime', how='left', suffixes=('', '_api'))

    # Drop the API-specific timestamp column
    merged_df.drop(columns=['startTime'], inplace=True)

    # Priority: Overwrite input DF from API truthful data
    merged_df['WindPowerMW'] = merged_df['WindPowerMW_api']

    # Drop intermediate columns with API suffix
    merged_df.drop(columns=['WindPowerMW_api'], inplace=True)

    # Load the Gradient Boosting model
    gb_model = joblib.load(GB_MODEL_PATH)

    # Identify rows with missing WindPowerMW values
    missing_wind_power = merged_df['WindPowerMW'].isnull()

    # Prepare input features for the model
    load_dotenv('.env.local')
    ws_ids = os.getenv('FMISID_WS').split(',')
    t_ids = os.getenv('FMISID_T').split(',')

    # Aggregate the ws_ and t_ columns and create a DataFrame
    features = {f'ws_{ws_id}': merged_df.loc[missing_wind_power, f'ws_{ws_id}'] for ws_id in ws_ids}
    features.update({f't_{t_id}': merged_df.loc[missing_wind_power, f't_{t_id}'] for t_id in t_ids})

    # Create a DataFrame with the feature columns
    X_missing_df = pd.DataFrame(features)

    if not X_missing_df.empty:
        predicted_wind_power = gb_model.predict(X_missing_df)
        predicted_wind_power = np.round(predicted_wind_power, 1)
        merged_df.loc[missing_wind_power, 'WindPowerMW'] = predicted_wind_power
    else:
        print("→ No missing wind power values found, no predictions needed.")

    # Calculate statistics for the inferred values
    if len(predicted_wind_power) > 0:
        min_pred = np.min(predicted_wind_power)
        max_pred = np.max(predicted_wind_power)
        avg_pred = np.mean(predicted_wind_power)
        median_pred = np.median(predicted_wind_power)

        print(f"→ Inferred wind power values for {missing_wind_power.sum()} missing entries "
              f"(Min: {round(min_pred, 1)}, Max: {round(max_pred, 1)}, "
              f"Avg: {round(avg_pred, 1)}, Median: {round(median_pred, 1)}).")
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
    end_date = (datetime.now(pytz.UTC) + timedelta(days=5)).strftime("%Y-%m-%d")

    # Prepare a dummy DataFrame covering the entire period
    print(f"Prepare dummy data from {start_date} to {end_date}")
    timestamps = pd.date_range(start=start_date, end=end_date, freq='h', tz=pytz.UTC)
    
    # Add dummy columns including the ws_ and t_ columns based on FMISID
    df_data = {
        'Timestamp': timestamps, 
    }

    # Populate dummy data for ws_ columns with rounding to 1 decimal place
    for ws_id in ws_ids:
        df_data[f'ws_{ws_id}'] = np.round(np.random.uniform(0.0, 15.0, len(timestamps)), 1)

    # Populate dummy data for t_ columns with rounding to 1 decimal place
    for t_id in t_ids:
        df_data[f't_{t_id}'] = np.round(np.random.uniform(-10.0, 20.0, len(timestamps)), 1)

    # Add dummy data for the WindPowerMW column, setting last 50 entries to NaN
    df_data['WindPowerMW'] = np.round(np.random.uniform(50.0, 150.0, len(timestamps)), 1)
    df_data['WindPowerMW'][-50:] = np.nan  # Set the last 50 values to NaN

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
