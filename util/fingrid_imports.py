"""
Fetch electricity transfer import capacity data from the Fingrid API, summarize the data, 
and integrate it into a given DataFrame. Fetches from -7 to +5 days from the current date.

Works the same as fingrid.py, but for import capacity data instead of nuclear power production data.
"""

import os
import time
import pandas as pd
import requests
import pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv
from rich import print

# Constants for import dataset IDs: SE1, SE3, and EE
IMPORT_DATASET_IDS = [24, 25, 112]

def fetch_transfer_capacity_data(fingrid_api_key, dataset_ids, start_date, end_date):
    dataset_ids_str = ','.join(map(str, dataset_ids))
    api_url = f"https://data.fingrid.fi/api/data"
    headers = {'x-api-key': fingrid_api_key}
    params = {
        'datasets': dataset_ids_str,
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
                    
                    df.rename(columns={'value': 'CapacityMW'}, inplace=True)
                    return df[['startTime', 'CapacityMW']]
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

def calculate_capacity_sums(df):
    """
    This function calculates the sum of capacities for each time period.
    """
    if df.empty:
        return pd.DataFrame(columns=['startTime', 'TotalCapacityMW'])
    
    summed_df = df.groupby('startTime').sum().reset_index()
    summed_df.rename(columns={'CapacityMW': 'TotalCapacityMW'}, inplace=True)
    return summed_df

def update_import_capacity(df, fingrid_api_key):
    """
    Updates the input DataFrame with import capacity data.
    """
    # Define the current date and adjust the start and end dates
    current_date = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
    history_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (datetime.now(pytz.UTC) + timedelta(hours=120)).strftime("%Y-%m-%d")
    
    print(f"* Fingrid: Fetching import capacities between {history_date} and {end_date}")

    # Fetch import capacity data
    import_df = fetch_transfer_capacity_data(fingrid_api_key, IMPORT_DATASET_IDS, history_date, end_date)
    summed_import_df = calculate_capacity_sums(import_df)

    # Prepare to merge with original DataFrame
    df['Timestamp'] = pd.to_datetime(df['Timestamp'], utc=True)

    # Drop the existing ImportCapacityMW column if it exists
    if 'ImportCapacityMW' in df.columns:
        df = df.drop(columns=['ImportCapacityMW'])

    # Merge import capacity
    merged_df = pd.merge(df, summed_import_df, left_on='Timestamp', right_on='startTime', how='left')
    merged_df.drop(columns=['startTime'], inplace=True)
    merged_df.rename(columns={'TotalCapacityMW': 'ImportCapacityMW'}, inplace=True)

    # Fill missing capacity data with forward fill
    merged_df['ImportCapacityMW'] = merged_df['ImportCapacityMW'].fillna(method='ffill')

    return merged_df

# Main function, for testing purposes only
def main():
    
    # Configure pandas to display all rows
    pd.set_option('display.max_rows', None)
    
    # Load the Fingrid API key from the environment
    load_dotenv('.env.local')

    fingrid_api_key = os.getenv('FINGRID_API_KEY')
    if fingrid_api_key is None:
        raise ValueError("Fingrid API key not found in environment variables")

    # Define the date range: 7 days in the past to 5 days in the future
    start_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (datetime.now(pytz.UTC) + timedelta(days=5)).strftime("%Y-%m-%d")

    # Prepare a dummy DataFrame covering the entire period
    print(f"Prepare dummy data from {start_date} to {end_date}")
    timestamps = pd.date_range(start=start_date, end=end_date, freq='h', tz=pytz.UTC)
    
    # Add dummy columns to the DataFrame
    df = pd.DataFrame({
        'Timestamp': timestamps, 
        'DummyColumn1': range(len(timestamps)),
        'DummyColumn2': range(len(timestamps), 2 * len(timestamps))
    })
    
    # Output the initial DataFrame
    print("Initial DataFrame:")
    print(df)
    
    # Update the DataFrame with import capacity
    updated_df = update_import_capacity(df, fingrid_api_key)

    # Output the DataFrame after updating with import capacity
    print("DataFrame After Import Capacity Update:")
    print(updated_df)

    # Drop rows with any NaN values before printing
    cleaned_df = updated_df.dropna()

    # Output the cleaned DataFrame
    print("Updated and Cleaned DataFrame:")
    print(cleaned_df)

if __name__ == "__main__":
    main()
