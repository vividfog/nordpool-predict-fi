import time
import pandas as pd
import requests
import pytz
from datetime import datetime, timedelta
from rich import print

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
        try:
            response = requests.get(api_url, headers=headers, params=params)
            response.raise_for_status()  # Raises an HTTPError for bad responses
        except requests.exceptions.RequestException as e:
            print(f"Error occurred while requesting Fingrid data: {e}")
            exit(1)

        if response.status_code == 200:
            try:
                data = response.json().get('data', [])
            except ValueError:
                print("Failed to decode JSON from response from Fingrid")
                exit(1)

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

def clean_up_df_after_merge(df):
    """
    This function removes duplicate columns resulting from a merge operation,
    and fills the NaN values in the original columns with the values from the
    duplicated columns. Assumes duplicated columns have suffixes '_x' and '_y',
    with '_y' being the most recent values to retain.
    """
    # Identify duplicated columns by their suffixes
    cols_to_remove = []
    for col in df.columns:
        if col.endswith('_x'):
            original_col = col[:-2]  # Remove the suffix to get the original column name
            duplicate_col = original_col + '_y'
            
            # Check if the duplicate column exists
            if duplicate_col in df.columns:
                # Fill NaN values in the original column with values from the duplicate
                df[original_col] = df[col].fillna(df[duplicate_col])
                
                # Mark the duplicate column for removal
                cols_to_remove.append(duplicate_col)
                
            # Also mark the original '_x' column for removal as it's now redundant
            cols_to_remove.append(col)
    
    # Drop the marked columns
    df.drop(columns=cols_to_remove, inplace=True)
    
    return df

def update_nuclear(df, fingrid_api_key):
    """
    Updates the input DataFrame with nuclear power production data for a specified range.

    This function fetches nuclear power production data for the past 7 days and up to X days into the future, aggregates the data from 3-minute intervals to hourly averages, and updates the original DataFrame with the aggregated nuclear power data.

    Parameters:
    - df (pd.DataFrame): The input DataFrame containing a 'timestamp' column.
    - fingrid_api_key (str): The API key for accessing Fingrid data.

    Returns:
    - pd.DataFrame: The updated DataFrame with nuclear power production data.
    """
    # Define the current date and adjust the start date to look 7 days into the past
    current_date = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
    history_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (datetime.now(pytz.UTC) + timedelta(days=8)).strftime("%Y-%m-%d")
    
    print(f"* Fingrid: Fetching nuclear power production data between {history_date} and {end_date} and inferring missing values")
    
    # Fetch nuclear power production data
    try:
        nuclear_df = fetch_nuclear_power_data(fingrid_api_key, history_date, end_date)
    except Exception as e:
        print(f"[ERROR] Failed to fetch or process nuclear power data from Fingrid: {e}")
        exit(1)
    
    if not nuclear_df.empty:
        nuclear_df['startTime'] = pd.to_datetime(nuclear_df['startTime'], utc=True)
        nuclear_df.set_index('startTime', inplace=True)
        hourly_nuclear_df = nuclear_df.resample('H').mean().reset_index()

        # Log the Fingrid data fetch and aggregation results        
        print(f"→ Fetched {len(nuclear_df)} rows, aggregated to {len(hourly_nuclear_df)} hourly averages spanning from {hourly_nuclear_df['startTime'].min().strftime('%Y-%m-%d')} to {hourly_nuclear_df['startTime'].max().strftime('%Y-%m-%d')}")
        
        # print("* Fingrid: DEBUG: Last few rows of nuclear power production data:\n", hourly_nuclear_df.tail())
        
        # Log the last known nuclear power production value
        last_known = hourly_nuclear_df['NuclearPowerMW'].dropna().iloc[-1]
        print(f"→ Using last known nuclear power production value: {round(last_known)} MW")
        
        # Drop the past NuclearPowerMW column from the original DataFrame
        if 'NuclearPowerMW' in df.columns:
            df.drop(columns=['NuclearPowerMW'], inplace=True)
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        merged_df = pd.merge(df, hourly_nuclear_df, left_on='timestamp', right_on='startTime', how='left')
        merged_df.drop(columns=['startTime'], inplace=True)
        
        # Combine the _x and _y columns after the merge operation back to the original column
        merged_df = clean_up_df_after_merge(merged_df)
        
        # Ensure 'NuclearPowerMW' column is filled at the end with the last known value
        if 'NuclearPowerMW' in merged_df.columns:
            merged_df['NuclearPowerMW'] = merged_df['NuclearPowerMW'].fillna(method='ffill')
        else:
            print("Warning: 'NuclearPowerMW' column not found after merge. Check data integration logic.")
        
        return merged_df
    else:
        print("Warning: No data fetched for nuclear power production; unable to update DataFrame.")
        return df


"This script is meant to be used as a module, not independently"
