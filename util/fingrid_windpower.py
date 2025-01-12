"""
Retrieves wind power data from the Fingrid API, integrates it into an existing DataFrame, and infers missing values up to 5 days in the future. There's a main function with dummy data generation for testing purposes.

To pretrain a model for explore optimal hyperparameters:
    data/create/91_model_experiments/rf_vs_world_windpower.py

"""

import os
import time
import pandas as pd
import requests
import pytz
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
from rich import print
from util.sql import db_query_all
from util.train_windpower_xgb import train_windpower_xgb

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
    Fills in missing WindPowerMW values using a newly trained XGBoost model.
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
    merged_df = pd.merge(
        df,
        wind_power_df,
        left_on='timestamp',
        right_on='startTime',
        how='left',
        suffixes=('', '_api')
    )
    merged_df = pd.merge(
        merged_df,
        wind_power_capacity_df,
        left_on='timestamp',
        right_on='startTime',
        how='left',
        suffixes=('', '_capacity_api')
    )

    # Drop the API-specific timestamp columns
    merged_df.drop(columns=['startTime', 'startTime_capacity_api'], inplace=True)

    # Explicitly set WindPowerMW to null if it didn't come from the API
    merged_df['WindPowerMW'] = merged_df['WindPowerMW_api']
    merged_df.drop(columns=['WindPowerMW_api'], inplace=True)

    # Prioritize filling WindPowerCapacityMW from API data
    merged_df['WindPowerCapacityMW'] = merged_df['WindPowerCapacityMW_capacity_api'].ffill()
    merged_df.drop(columns=['WindPowerCapacityMW_capacity_api'], inplace=True)

    # Backfill the WindPowerCapacityMW column with the first known value, and print out how many values were backfilled
    if merged_df['WindPowerCapacityMW'].isnull().any():
        print(f"[WARNING] Backfilling {merged_df['WindPowerCapacityMW'].isnull().sum()} missing WindPowerCapacityMW values")
        merged_df['WindPowerCapacityMW'] = merged_df['WindPowerCapacityMW'].bfill()

    # Drop redundant columns that originated from the API data
    merged_df.drop(columns=['datasetId', 'endTime', 'datasetId_capacity_api', 'endTime_capacity_api'], inplace=True)

    # Load local historical data and merge with the newly fetched data
    db_path = os.getenv('DB_PATH', 'data/prediction.db')
    historical_df = db_query_all(db_path)
    df_training = pd.concat([historical_df, merged_df]).drop_duplicates(
        subset=['timestamp'],
        keep='last'
    ).reset_index(drop=True)

    # Only train on data up to the last known timestamp from the Fingrid API
    last_known_timestamp = pd.to_datetime(wind_power_df['startTime'].max())
    df_training['timestamp'] = pd.to_datetime(df_training['timestamp'], utc=True)
    df_training = df_training[df_training['timestamp'] <= last_known_timestamp]
    
    ws_ids = os.getenv('FMISID_WS').split(',')
    try:
        model = train_windpower_xgb(df_training, target_col='WindPowerMW', wp_fmisid=ws_ids)
    except Exception as e:
        print(f"[ERROR] XGBoost training failed: {e}")
        exit(1)

    # Identify rows with missing WindPowerMW values
    missing_wind_power = merged_df['WindPowerMW'].isnull()

    # Prepare input features for the rows that need prediction
    if missing_wind_power.any():
        t_ids = os.getenv('FMISID_T').split(',')
        features = {}
        for ws_id in ws_ids:
            features[f'ws_{ws_id}'] = merged_df.loc[missing_wind_power, f'ws_{ws_id}']
        for t_id in t_ids:
            features[f't_{t_id}'] = merged_df.loc[missing_wind_power, f't_{t_id}']

        # 2025-01-02: The utility of these features needs more study
        # hour = merged_df.loc[missing_wind_power, 'timestamp'].dt.hour
        # features['hour_sin'] = np.sin(2 * np.pi * hour / 24)
        # features['hour_cos'] = np.cos(2 * np.pi * hour / 24)

        # Fill in the WindPowerCapacityMW, Avg_WindSpeed, and WindSpeed_Variance
        features['WindPowerCapacityMW'] = merged_df.loc[missing_wind_power, 'WindPowerCapacityMW'].ffill()

        ws_cols = [f'ws_{ws_id}' for ws_id in ws_ids]
        features['Avg_WindSpeed'] = merged_df.loc[missing_wind_power, ws_cols].mean(axis=1)
        features['WindSpeed_Variance'] = merged_df.loc[missing_wind_power, ws_cols].var(axis=1)
        
        print(f"→ Predicting wind power values for missing entries")
        X_missing_df = pd.DataFrame(features)
        # print(X_missing_df)
        # print(X_missing_df.describe())

        if not X_missing_df.empty:

            predictions = model.predict(X_missing_df)

            # Round and clip negatives
            predictions = np.round(predictions, 1)
            predictions[predictions < 0] = 0

            merged_df.loc[missing_wind_power, 'WindPowerMW'] = predictions

            # Stats
            min_pred = np.min(predictions)
            max_pred = np.max(predictions)
            avg_pred = np.mean(predictions)
            median_pred = np.median(predictions)
            print(f"→ Inferred wind power values for {missing_wind_power.sum()} missing entries "
                  f"(Min: {min_pred:.0f}, Max: {max_pred:.0f}, "
                  f"Avg: {avg_pred:.0f}, Median: {median_pred:.0f}).")
        else:
            print("→ No rows need inference after filtering, no predictions made.")
    else:
        print("→ No missing wind power values found, no predictions needed.")

    # Garbage collection to save memory
    del model

    print(f"→ Returning wind power predictions with shape ({merged_df.shape}): ")
    # print(merged_df.columns)
    # print(merged_df.describe())
    # print(merged_df.head())
    # print(merged_df.tail())

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

# [2024-12-30 04:20:02] INFO     [2024-12-30 04:20:02] - Best parameters found for XGBoost: {'n_estimators': 9504, 'max_depth': 6, 'learning_rate': 0.01947750028840404, 'subsample': 0.501928078337343,                rf_vs_world_windpower.py:384
#                                'colsample_bytree': 0.7049959928625888, 'gamma': 0.037206239719660555, 'reg_alpha': 0.2875908668333263, 'reg_lambda': 0.9459970106572207}
#                       INFO     [2024-12-30 04:20:02] - Starting cross-validation for XGBoost...                                                                                                                       rf_vs_world_windpower.py:144
# [2024-12-30 04:21:44] INFO     [2024-12-30 04:21:44] - Cross-validation completed for XGBoost                                                                                                                         rf_vs_world_windpower.py:167
#                       INFO     [2024-12-30 04:21:44] - Mean MAE: 215.0528, Mean MSE: 97769.2919, Mean RMSE: 312.6808, Mean R²: 0.9558                                                                                 rf_vs_world_windpower.py:168
#                       INFO     [2024-12-30 04:21:44] - Starting training and evaluation for XGBoost...                                                                                                                rf_vs_world_windpower.py:179
# [2024-12-30 04:22:05] INFO     [2024-12-30 04:22:05] - Training time for XGBoost: 20.94 seconds                                                                                                                       rf_vs_world_windpower.py:199
# 100%|===================| 3479/3481 [17:27<00:00]       [2024-12-30 04:39:36] INFO     [2024-12-30 04:39:36] - XGBoost evaluation completed                                                                                                                                   rf_vs_world_windpower.py:244
#                       INFO     [2024-12-30 04:39:36] - MAE: 192.6108, MSE: 76552.4818, RMSE: 276.6812, R²: 0.9648                                                                                                     rf_vs_world_windpower.py:245
#                       INFO     [2024-12-30 04:39:36] - XGBoost saved as data/windpower_xgboost.joblib                                                                                                                 rf_vs_world_windpower.py:474
#                       INFO     [2024-12-30 04:39:36] - Preparing to display model comparison results...                                                                                                               rf_vs_world_windpower.py:251
#     Model Performance Comparison - Test Set Metrics
# ┏━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┓
# ┃ Model   ┃      MAE ┃        MSE ┃     RMSE ┃     R² ┃
# ┡━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━┩
# │ XGBoost │ 192.6108 │ 76552.4818 │ 276.6812 │ 0.9648 │
# └─────────┴──────────┴────────────┴──────────┴────────┘
#             5-Fold Cross-Validation Results
# ┏━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┓
# ┃ Model   ┃   CV MAE ┃     CV MSE ┃  CV RMSE ┃  CV R² ┃
# ┡━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━┩
# │ XGBoost │ 215.0528 │ 97769.2919 │ 312.6808 │ 0.9558 │
# └─────────┴──────────┴────────────┴──────────┴────────┘
#                       Autocorrelation Analysis
# ┏━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
# ┃ Model   ┃ Durbin-Watson ┃ ACF (Lag 1) ┃ ACF (Lag 2) ┃ ACF (Lag 3) ┃
# ┡━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
# │ XGBoost │        1.9826 │      0.0075 │     -0.0161 │      0.0124 │
# └─────────┴───────────────┴─────────────┴─────────────┴─────────────┘

# Top 10 Feature Importance for XGBoost:
#             Feature  Importance
#       Avg_WindSpeed    0.384222
# WindPowerCapacityMW    0.077101
#           ws_101673    0.059475
#           ws_101783    0.052062
#           ws_101268    0.031325
#           ws_101785    0.025192
#            hour_cos    0.021147
#           ws_101851    0.018250
#            t_101794    0.017348
#           ws_101267    0.014904

# Top 10 SHAP Mean Absolute Values for XGBoost:
#             Feature  Mean SHAP Value
#       Avg_WindSpeed       418.223272
# WindPowerCapacityMW       293.311113
#            t_101268       156.009600
#            t_101783       112.871670
#            hour_cos       112.176201
#           ws_101673       106.893331
#            t_100932       100.865706
#           ws_101785       100.368998
#            t_101840        96.292516
#           ws_101851        94.688842
#                       INFO     [2024-12-30 04:39:36] - Model comparison completed