import time
import pandas as pd
import requests
import pytz
from datetime import datetime, timedelta

def fetch_nuclear_power_data(fingrid_api_key, start_date, end_date):
    dataset_id = 188  # Nuclear power production dataset ID
    api_url = f"https://data.fingrid.fi/api/datasets/{dataset_id}/data"
    headers = {'x-api-key': fingrid_api_key}
    params = {
        'startTime': f"{start_date}T00:00:00.000Z",
        'endTime': f"{end_date}T23:59:59.000Z",
        'format': 'json',
        'oneRowPerTimePeriod': False,
        'page': 1,
        'pageSize': 10000,
        'locale': 'en'
    }
    
    for attempt in range(3):  # max_retries = 3
        response = requests.get(api_url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json().get('data', [])
            df = pd.DataFrame(data)
            if not df.empty:
                df['startTime'] = pd.to_datetime(df['startTime'], utc=True)
                df.rename(columns={'value': 'NuclearPowerMW'}, inplace=True)
                return df[['startTime', 'NuclearPowerMW']]
        elif response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            print(f"Rate limited! Waiting for {retry_after} seconds.")
            time.sleep(retry_after)
        else:
            print(f"Failed to fetch data: {response.text}")
            break

    return pd.DataFrame(columns=['startTime', 'NuclearPowerMW'])

def fetch_recent_nuclear_data(fingrid_api_key, base_date, max_hours_back=240):
    search_windows = [6, 12, 24, 48, 96]
    for hours_back in search_windows:
        if hours_back > max_hours_back:
            break
        start_date = (base_date - timedelta(hours=hours_back)).strftime("%Y-%m-%d")
        end_date = base_date.strftime("%Y-%m-%d")
        recent_df = fetch_nuclear_power_data(fingrid_api_key, start_date, end_date)
        if not recent_df.empty:
            final_start_date = base_date - timedelta(hours=6)
            return recent_df[recent_df['startTime'] >= final_start_date]
    return pd.DataFrame(columns=['startTime', 'NuclearPowerMW'])

def add_nuclear_power_to_df(input_df, fingrid_api_key):
    if input_df.empty or 'timestamp' not in input_df.columns:
        raise ValueError("Input DataFrame must have a 'timestamp' column and cannot be empty.")
    
    # Create a copy of the input DataFrame to avoid modifying the original
    input_df = input_df.copy()
    
    # Check if 'timestamp' is already timezone-aware
    if input_df['timestamp'].dt.tz is not None:
        # If it's already timezone-aware but not in UTC, convert to UTC
        if str(input_df['timestamp'].dt.tz) != 'UTC':
            input_df['timestamp'] = input_df['timestamp'].dt.tz_convert('UTC')
    else:
        # If it's not timezone-aware, localize to UTC
        input_df['timestamp'] = input_df['timestamp'].dt.tz_localize('UTC', ambiguous='infer', nonexistent='shift_forward')
    
    start_date = input_df['timestamp'].min().strftime("%Y-%m-%d")
    end_date = input_df['timestamp'].max().strftime("%Y-%m-%d")
    
    nuclear_df = fetch_nuclear_power_data(fingrid_api_key, start_date, end_date)
    
    # Initialize recent_df to ensure it's defined even if not used
    recent_df = pd.DataFrame()
    
    # Fetch recent data if necessary
    if nuclear_df.empty or nuclear_df['startTime'].max() < input_df['timestamp'].max():
        print("Some nuclear power data missing from Fingrid. Inferring from the last available hours.")
        base_date = pd.to_datetime(input_df['timestamp'].max(), utc=True)
        recent_df = fetch_recent_nuclear_data(fingrid_api_key, base_date)
        nuclear_df = pd.concat([nuclear_df, recent_df]).drop_duplicates(subset=['startTime']).reset_index(drop=True)
    
    # Merge and handle 'NuclearPowerMW' column
    merged_df = pd.merge(input_df, nuclear_df, how='left', left_on='timestamp', right_on='startTime', suffixes=('', '_y'))
    merged_df.drop('startTime', axis=1, inplace=True)
    
    # Consolidate 'NuclearPowerMW' columns
    if 'NuclearPowerMW_y' in merged_df.columns:
        merged_df['NuclearPowerMW'] = merged_df['NuclearPowerMW_y'].combine_first(merged_df['NuclearPowerMW'])
        merged_df.drop('NuclearPowerMW_y', axis=1, inplace=True)
    
    return merged_df

# Sample usage:
# output_df = add_nuclear_power_to_df(input_df, fingrid_api_key)

"This script is meant to be used as a module, not independently"
