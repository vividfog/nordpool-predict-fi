import pandas as pd
import requests
from datetime import datetime, timedelta

# A set of functions to work with the Fingrid API

def fetch_nuclear_power_data(fingrid_api_key, start_date, end_date):
    """
    Fetches nuclear power production data from Fingrid's API within the specified date range.
    
    Parameters:
    - fingrid_api_key: str, the API key for authenticating with the Fingrid API.
    - start_date: str, the start date in "YYYY-MM-DD" format.
    - end_date: str, the end date in "YYYY-MM-DD" format.
    
    Returns:
    - DataFrame with two columns ['startTime', 'NuclearPowerMW'] where 'startTime' is in UTC and timezone-aware.
    """
    dataset_id = 188
    api_url = f"https://data.fingrid.fi/api/datasets/{dataset_id}/data"
    headers = {'x-api-key': fingrid_api_key}
    params = {
        'startTime': f"{start_date}T00:00:00.000Z",
        'endTime': f"{end_date}T23:59:59.000Z",
        'format': 'json',
        'oneRowPerTimePeriod': False,
        'page': 1,
        'pageSize': 10000,  # Assuming this is enough for one day; adjust if necessary.
        'locale': 'en'
    }
    
    response = requests.get(api_url, headers=headers, params=params)
    if response.status_code == 200:
        data = response.json().get('data', [])
        df = pd.DataFrame(data)
        if not df.empty:
            # Ensure the 'startTime' column is converted to datetime with UTC timezone
            df['startTime'] = pd.to_datetime(df['startTime'], utc=True)
            df.rename(columns={'value': 'NuclearPowerMW'}, inplace=True)
            return df[['startTime', 'NuclearPowerMW']]
    return pd.DataFrame(columns=['startTime', 'NuclearPowerMW'])

def add_nuclear_power_to_df(input_df, fingrid_api_key):
    """
    Adds nuclear power production data to the input DataFrame.
    
    Parameters:
    - input_df: DataFrame, the input data frame with a 'timestamp' column in UTC.
    - fingrid_api_key: str, the API key for authenticating with the Fingrid API.
    
    Returns:
    - DataFrame, the input DataFrame with an added 'NuclearPowerMW' column.
    """
    if input_df.empty or 'timestamp' not in input_df.columns:
        raise ValueError("Input DataFrame must have a 'timestamp' column and cannot be empty.")
    
    # Ensure the 'timestamp' column in input_df is timezone-aware UTC
    if not input_df['timestamp'].dt.tz:
        input_df['timestamp'] = input_df['timestamp'].dt.tz_localize('UTC')
    
    # Get the range of dates from the input DataFrame
    start_date = input_df['timestamp'].min().strftime("%Y-%m-%d")
    end_date = input_df['timestamp'].max().strftime("%Y-%m-%d")
    
    # Fetch nuclear power production data
    nuclear_df = fetch_nuclear_power_data(fingrid_api_key, start_date, end_date)
    
    # Merge the fetched data with the input DataFrame
    merged_df = pd.merge(input_df, nuclear_df, how='left', left_on='timestamp', right_on='startTime')
    merged_df.drop('startTime', axis=1, inplace=True)  # Drop the extra 'startTime' column
    
    return merged_df

# Sample usage:
# Assuming `features_df` is your input DataFrame with a 'timestamp' column
# and `fingrid_api_key` is your Fingrid API key
# enriched_df = add_nuclear_power_to_df(features_df, fingrid_api_key)

# This code needs to be run in a suitable environment with API access.

"This script is meant to be used as a module, not independently"
