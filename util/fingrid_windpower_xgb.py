"""
Retrieves wind power data from the Fingrid API, integrates it into an existing DataFrame, and infers missing values up to X days in the future.

Functions:
- fetch_fingrid_data: Fetches data from the Fingrid API.
- update_windpower: Updates the DataFrame with real, forecast, and inferred wind power data.

"""

import gc
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
WIND_POWER_REAL_DATASET_ID = 181      # Fingrid dataset ID for real wind power (3-min)
WIND_POWER_FORECAST_DATASET_ID = 245  # Fingrid dataset ID for forecast
WIND_POWER_CAPACITY_DATASET_ID = 268

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
    
    time.sleep(3)  # Basic rate-limit buffer
    for attempt in range(3):
        try:
            response = requests.get(api_url, headers=headers, params=params)
            response.raise_for_status()

            if response.status_code == 200:
                try:
                    data = response.json().get('data', [])
                except ValueError:
                    raise ValueError("Failed to decode JSON from response")

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
    Updates the input DataFrame with wind power data using:
      1) Dataset 181 (history data) for past timestamps if available
      2) Dataset 245 (forecast) for future timestamps
      3) XGBoost to infer any remaining gaps
      4) Optionally smooths the XGB output to avoid sudden hour-to-hour jumps
    """
    
    current_utc = datetime.now(pytz.UTC)
    current_date = current_utc.strftime("%Y-%m-%d")
    history_date = (current_utc - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (current_utc + timedelta(days=8)).strftime("%Y-%m-%d")

    print(f"* Fingrid: Fetching history data (ID 181) between {history_date} and {end_date}")
    real_data_df = fetch_fingrid_data(fingrid_api_key, WIND_POWER_REAL_DATASET_ID, history_date, end_date)
    real_data_df.rename(columns={'value': 'WindPowerMW_Real'}, inplace=True)
    if not real_data_df.empty:
        last_real_ts = real_data_df['startTime'].max()
        min_real = real_data_df['WindPowerMW_Real'].min()
        max_real = real_data_df['WindPowerMW_Real'].max()
        avg_real = real_data_df['WindPowerMW_Real'].mean()
        print(f"→ Last real timestamp: {last_real_ts}, Min: {min_real:.0f}, Max: {max_real:.0f}, Avg: {avg_real:.0f}")

    print(f"* Fingrid: Fetching forecast (ID 245) between {history_date} and {end_date}")
    forecast_data_df = fetch_fingrid_data(fingrid_api_key, WIND_POWER_FORECAST_DATASET_ID, history_date, end_date)
    forecast_data_df.rename(columns={'value': 'WindPowerMW_Forecast'}, inplace=True)
    if not forecast_data_df.empty:
        last_fcst_ts = forecast_data_df['startTime'].max()
        min_fcst = forecast_data_df['WindPowerMW_Forecast'].min()
        max_fcst = forecast_data_df['WindPowerMW_Forecast'].max()
        avg_fcst = forecast_data_df['WindPowerMW_Forecast'].mean()
        print(f"→ Last forecast timestamp: {last_fcst_ts}, Min: {min_fcst:.0f}, Max: {max_fcst:.0f}, Avg: {avg_fcst:.0f}")

    print(f"* Fingrid: Fetching wind power capacity (ID 268) between {history_date} and {end_date}")
    wind_power_capacity_df = fetch_fingrid_data(fingrid_api_key, WIND_POWER_CAPACITY_DATASET_ID, history_date, end_date)
    wind_power_capacity_df.rename(columns={'value': 'WindPowerCapacityMW'}, inplace=True)
    if not wind_power_capacity_df.empty:
        last_capacity_ts = wind_power_capacity_df['startTime'].max()
        min_capacity = wind_power_capacity_df['WindPowerCapacityMW'].min()
        max_capacity = wind_power_capacity_df['WindPowerCapacityMW'].max()
        avg_capacity = wind_power_capacity_df['WindPowerCapacityMW'].mean()
        print(f"→ Last capacity timestamp: {last_capacity_ts}, Min: {min_capacity:.0f}, Max: {max_capacity:.0f}, Avg: {avg_capacity:.0f}")

    # Ensure the timestamp column is datetime with UTC
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)

    # Merge history data (181)
    merged_df = pd.merge(
        df,
        real_data_df[['startTime', 'WindPowerMW_Real', 'datasetId', 'endTime']],
        left_on='timestamp',
        right_on='startTime',
        how='left'
    )
    
    # Merge forecast data (245)
    merged_df = pd.merge(
        merged_df,
        forecast_data_df[['startTime', 'WindPowerMW_Forecast', 'datasetId', 'endTime']],
        left_on='timestamp',
        right_on='startTime',
        how='left'
    )

    # Merge capacity data (268), specify suffixes to prevent collisions
    merged_df = pd.merge(
        merged_df,
        wind_power_capacity_df[['startTime', 'WindPowerCapacityMW', 'datasetId', 'endTime']],
        left_on='timestamp',
        right_on='startTime',
        how='left',
        suffixes=('', '_cap')
    )

    # Combine real vs. forecast
    now_mask = merged_df['timestamp'] <= current_utc
    merged_df['WindPowerMW'] = np.nan

    # For timestamps <= now, prefer real if it exists, else forecast
    real_series = merged_df.loc[now_mask, 'WindPowerMW_Real']
    fcst_series = merged_df.loc[now_mask, 'WindPowerMW_Forecast']
    merged_df.loc[now_mask, 'WindPowerMW'] = real_series.combine_first(fcst_series)
    # For timestamps > now, use forecast
    merged_df.loc[~now_mask, 'WindPowerMW'] = merged_df.loc[~now_mask, 'WindPowerMW_Forecast']

    # Forward fill capacity
    merged_df['WindPowerCapacityMW'] = merged_df['WindPowerCapacityMW'].ffill()
    if merged_df['WindPowerCapacityMW'].isnull().any():
        missing_count = merged_df['WindPowerCapacityMW'].isnull().sum()
        print(f"[WARNING] Backfilling {missing_count} missing WindPowerCapacityMW values")
        merged_df['WindPowerCapacityMW'] = merged_df['WindPowerCapacityMW'].bfill()

    # Prepare historic data for training from the database
    db_path = os.getenv('DB_PATH', 'data/prediction.db')
    historical_df = db_query_all(db_path)
    df_training = pd.concat([historical_df, merged_df]).drop_duplicates(subset=['timestamp'], keep='last').reset_index(drop=True)

    # Train on real-data time range only
    if not real_data_df.empty:
        max_real_ts = real_data_df['startTime'].max()
        df_training['timestamp'] = pd.to_datetime(df_training['timestamp'], utc=True)
        df_training = df_training[df_training['timestamp'] <= max_real_ts]
    else:
        print("[ERROR] No history data returned. Skipping model training.")
        # We'll just return the partial merges as-is
        raise RuntimeError("No history data returned from Fingrid API.")

    ws_cols = sorted([col for col in df_training.columns if col.startswith('ws_') or col.startswith('eu_ws_')])

    try:
        ws_model = train_windpower_xgb(df_training)
        trained_columns = list(df_training.columns)  # Save the trained column order
    except Exception as e:
        print(f"[ERROR] XGBoost training failed: {e}")
        raise RuntimeError("XGBoost training for a wind power model failed.")

    # Identify the hour at which Fingrid’s forecast ends
    last_fc_ts = forecast_data_df['startTime'].max()
    ramp_hours = 6  # How many hours of ramping to blend Fingrid forecast with XGBoost
    ramp_end_ts = last_fc_ts + timedelta(hours=ramp_hours)

    # Inference for missing rows
    missing_mask = merged_df['WindPowerMW'].isnull()
    if missing_mask.any():
        t_cols = sorted([col for col in df_training.columns if col.startswith('t_')])
        features = {}
        for ws_col in ws_cols:
            features[ws_col] = merged_df.loc[missing_mask, ws_col]
        for t_col in t_cols:
            features[t_col] = merged_df.loc[missing_mask, t_col]

        # Forward-fill capacity for missing rows
        features['WindPowerCapacityMW'] = merged_df.loc[missing_mask, 'WindPowerCapacityMW'].ffill()

        # Basic stats from the ws columns
        features['Avg_WindSpeed'] = merged_df.loc[missing_mask, ws_cols].mean(axis=1)
        features['WindSpeed_Variance'] = merged_df.loc[missing_mask, ws_cols].var(axis=1)

        X_missing_df = pd.DataFrame(features)
        if not X_missing_df.empty:
            # Filter trained_columns to only include columns present in X_missing_df
            trained_columns = [col for col in trained_columns if col in X_missing_df.columns]
            X_missing_df = X_missing_df[sorted(trained_columns)]  # Reorder columns to match training

            # Predict with XGB
            raw_preds = ws_model.predict(X_missing_df)

            # Exponential smoothing to tame hour-to-hour jumps
            # We'll smooth in chronological order of the missing timestamps
            def smooth_exponential(arr, alpha=0.4):
                if len(arr) < 2:
                    return arr
                smoothed = [arr[0]]
                for i in range(1, len(arr)):
                    smoothed_val = alpha * arr[i] + (1 - alpha) * smoothed[i - 1]
                    smoothed.append(smoothed_val)
                return np.array(smoothed)

            # Sort the missing timestamps so we can smooth them in ascending time
            missing_idx = merged_df.loc[missing_mask].index
            missing_ts_sorted = merged_df.loc[missing_idx, 'timestamp'].sort_values()
            # We'll reindex raw_preds to that sorted order
            raw_preds_series = pd.Series(raw_preds, index=missing_idx).reindex(missing_ts_sorted.index)

            # Smooth the raw predictions
            smoothed_preds = smooth_exponential(raw_preds_series.values)

            # Scale smoothed predictions by capacity
            capacity_vals = merged_df.loc[missing_ts_sorted.index, 'WindPowerCapacityMW']
            final_vals = smoothed_preds * capacity_vals.values

            # Put them back into merged_df
            merged_df.loc[missing_ts_sorted.index, 'WindPowerMW'] = final_vals

            # Identify final non-null Fingrid forecast value
            last_fc_value = forecast_data_df['WindPowerMW_Forecast'].dropna().iloc[-1]

            # Blend Fingrid forecast with XGBoost predictions at the border
            k = 2.5  # adjust for faster or slower snapping
            ramp_mask = (merged_df['timestamp'] > last_fc_ts) & (merged_df['timestamp'] <= ramp_end_ts)
            if ramp_mask.any():
                # Calculate how far (in hours) each timestamp is from last_fc_ts
                time_diffs = (merged_df.loc[ramp_mask, 'timestamp'] - last_fc_ts).dt.total_seconds() / 3600.0
                time_frac = time_diffs / ramp_hours  # goes from 0.0 at last_fc_ts up to 1.0 at ramp_end_ts

                # Use a log-like curve that quickly ramps from 0 toward 1
                alpha = 1 - np.exp(-k * time_frac)

                fc_vals = pd.Series(last_fc_value, index=merged_df.loc[ramp_mask].index)
                xgb_vals = merged_df.loc[ramp_mask, 'WindPowerMW']

                # Blend
                blended = (1 - alpha) * fc_vals + alpha * xgb_vals
                merged_df.loc[ramp_mask, 'WindPowerMW'] = blended

                # Debug prints
                print(f"→ Blending {ramp_mask.sum()} rows from Fingrid to XGB between {last_fc_ts} and {ramp_end_ts}")
                for idx in merged_df.loc[ramp_mask].index:
                    ts = merged_df.loc[idx, 'timestamp']
                    print(
                        f"  {ts}: "
                        f"time_frac={time_frac.loc[idx]:.3f}, alpha={alpha.loc[idx]:.3f}, "
                        f"fc_last={fc_vals.loc[idx]:.2f}, xgb={xgb_vals.loc[idx]:.2f}, "
                        f"blended={blended.loc[idx]:.2f}"
                    )

            # Stats
            predicted_wind_power = merged_df.loc[missing_mask, 'WindPowerMW']
            min_pred = predicted_wind_power.min()
            max_pred = predicted_wind_power.max()
            avg_pred = predicted_wind_power.mean()
            median_pred = predicted_wind_power.median()
            print(f"→ Inferred wind power for {missing_mask.sum()} entries "
                  f"(Min: {min_pred:.0f}, Max: {max_pred:.0f}, "
                  f"Avg: {avg_pred:.0f}, Median: {median_pred:.0f}).")
        else:
            print("→ No rows need inference after filtering.")
    else:
        print("→ No missing wind power values found, no predictions needed.")

    # Free up memory
    del ws_model
    gc.collect()

    # Keep only the original columns plus the new wind power columns
    final_df = cols_cleanup(df, merged_df)

    print(f"→ Returning wind power data with shape {final_df.shape}.")
    return final_df


def cols_cleanup(original_df, merged_df):
    """
    Keep only:
      • The columns originally in the user-supplied df
      • WindPowerMW
      • WindPowerCapacityMW
    All other columns get dropped (e.g. Fingrid merges).
    """
    original_cols = list(original_df.columns)
    # Ensure these are included if not already in the original
    additional = ['WindPowerMW', 'WindPowerCapacityMW']
    keep_cols = list(dict.fromkeys(original_cols + additional))  # preserve order, remove dups
    # Filter out any columns that don't exist in merged_df
    keep_cols = [c for c in keep_cols if c in merged_df.columns]
    
    return merged_df[keep_cols].copy()