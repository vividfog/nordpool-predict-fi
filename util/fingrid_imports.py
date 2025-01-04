#
# THIS SCRIPT IS NO LONGER IN USE. IT HAS BEEN REPLACED BY THE JAO IMPORT CAPACITY API.
# https://publicationtool.jao.eu/nordic/api
# https://www.fingrid.fi/ajankohtaista/tiedotteet/2024/flow-based-kapasiteetinlaskentamenetelma-otettu-onnistuneesti-kayttoon/
#

import os
import time
import json
import argparse
import pandas as pd
import requests
import pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv
from rich import print

# Define the DEBUG variable
DEBUG = False

# Constants for import dataset IDs
PRIMARY_DATASET_IDS = [24, 25, 112] # SE1, SE3, and EE real import capacities
BACKUP_DATASET_IDS = [142, 144, 367] # SE1, SE3, and EE planned import capacities

def fetch_transfer_capacity_data(fingrid_api_key, dataset_ids, start_date, end_date, backup=False):
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

                if DEBUG:
                    print(f"Fetched data from {'backup' if backup else 'primary'} sets:")
                    print(data)

                df = pd.DataFrame(data)
                if not df.empty:
                    df['startTime'] = pd.to_datetime(df['startTime'], utc=True)
                    df.rename(columns={'value': 'CapacityMW'}, inplace=True)

                    # Pivot, fill, and unpivot
                    df_pivot = df.pivot_table(index='startTime', columns='datasetId', values='CapacityMW', aggfunc='first')
                    df_pivot.ffill(inplace=True)
                    df_unpivot = df_pivot.reset_index().melt(id_vars='startTime', var_name='datasetId', value_name='CapacityMW')

                    if DEBUG:
                        print("Pivoted and unpivoted DataFrame:")
                        print(df_unpivot.sort_values(by='startTime'))
                    return df_unpivot[['startTime', 'CapacityMW']]
            elif response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                print(f"Rate limited! Waiting for {retry_after} seconds.")
                time.sleep(retry_after)
            else:
                print(f"Failed to fetch data: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"Error occurred while requesting Fingrid data: {e}")
            time.sleep(5)
    
    raise RuntimeError("Failed to fetch data after 3 attempts")

def calculate_capacity_sums(df):
    """
    This function calculates the sum of capacities for each time period,
    replacing zero sums with the last known non-zero sum.
    """
    if df.empty:
        return pd.DataFrame(columns=['startTime', 'TotalCapacityMW'])
    
    summed_df = df.groupby('startTime').sum().reset_index()
    summed_df.rename(columns={'CapacityMW': 'TotalCapacityMW'}, inplace=True)
    
    # Identify zero sums and replace them
    edits_made = False
    if not summed_df.empty:
        # Forward fill zero values
        condition = (summed_df['TotalCapacityMW'] == 0)
        last_non_zero_value = None
        for index, row in summed_df.iterrows():
            if condition[index]:
                if last_non_zero_value is not None:
                    summed_df.at[index, 'TotalCapacityMW'] = last_non_zero_value
                    edits_made = True
            else:
                last_non_zero_value = row['TotalCapacityMW']
    
    if edits_made:
        print("[WARNING] Zero sums in Fingrid planned transfer data. Replaced with last known non-zero values.")

    return summed_df


def update_import_capacity(df, fingrid_api_key):
    """
    Updates the input DataFrame with import capacity data.
    """
    # Define the current date and adjust the start and end dates
    current_date = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
    history_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (datetime.now(pytz.UTC) + timedelta(days=8)).strftime("%Y-%m-%d")
    
    print(f"* Fingrid: Fetching import capacities between {history_date} and {end_date}")

    # Fetch primary and backup import capacity data
    primary_df = fetch_transfer_capacity_data(fingrid_api_key, PRIMARY_DATASET_IDS, history_date, end_date)
    backup_df = fetch_transfer_capacity_data(fingrid_api_key, BACKUP_DATASET_IDS, history_date, end_date, backup=True)

    if DEBUG:
        print("Primary DataFrame:")
        print(primary_df)
        print("Backup DataFrame:")
        print(backup_df)

    # Calculate summed import capacities
    summed_primary_df = calculate_capacity_sums(primary_df)
    summed_backup_df = calculate_capacity_sums(backup_df)

    if DEBUG:
        print("Summed Primary DataFrame:")
        print(summed_primary_df)
        print("Summed Backup DataFrame:")
        print(summed_backup_df)

    # Check if the backup dataset is completely zero and set it to None for forward filling
    if summed_backup_df['TotalCapacityMW'].eq(0).all():
        summed_backup_df['TotalCapacityMW'] = None  # Prepare for forward filling by setting to None

    # Merge primary and backup capacities
    if not summed_primary_df.empty and not summed_backup_df.empty:
        merged_df = pd.merge(summed_primary_df, summed_backup_df, on='startTime', how='outer', suffixes=('_primary', '_backup'))
        # Use backup when primary is not available, then forward fill zeros to ensure continuity of data
        merged_df['TotalCapacityMW'] = merged_df['TotalCapacityMW_primary'].where(
            merged_df['TotalCapacityMW_primary'].notna(), merged_df['TotalCapacityMW_backup'])
        merged_df = merged_df[['startTime', 'TotalCapacityMW']]
    elif not summed_primary_df.empty:
        # Use primary directly if backup is not usable
        merged_df = summed_primary_df.rename(columns={'TotalCapacityMW': 'TotalCapacityMW'})
    elif not summed_backup_df.empty:
        # Use backup directly if primary is not available
        merged_df = summed_backup_df.rename(columns={'TotalCapacityMW': 'TotalCapacityMW'})
    else:
        raise ValueError("Failed to retrieve data from both primary and backup datasets.")

    # Forward fill any remaining NaN values
    merged_df['TotalCapacityMW'] = merged_df['TotalCapacityMW'].ffill()

    if DEBUG:
        print("Merged DataFrame:")
        print(merged_df)

    # Prepare to merge with original DataFrame
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)

    # Drop the existing ImportCapacityMW column if it exists
    if 'ImportCapacityMW' in df.columns:
        df = df.drop(columns=['ImportCapacityMW'])

    # Merge import capacity
    final_df = pd.merge(df, merged_df, left_on='timestamp', right_on='startTime', how='left')
    final_df.drop(columns=['startTime'], inplace=True)
    final_df.rename(columns={'TotalCapacityMW': 'ImportCapacityMW'}, inplace=True)

    # Fill missing capacity data with forward and backward fill
    final_df['ImportCapacityMW'] = final_df['ImportCapacityMW'].ffill().bfill()

    # Calculate daily averages of ImportCapacityMW
    temp_df = final_df.copy()
    temp_df['Date'] = temp_df['timestamp'].dt.date
    daily_avg_df = temp_df.groupby('Date')['ImportCapacityMW'].mean().reset_index()
    daily_avg_df.rename(columns={'ImportCapacityMW': 'average_import_capacity_mw'}, inplace=True)

    # Round the average import capacity to 1 decimal
    daily_avg_df['average_import_capacity_mw'] = daily_avg_df['average_import_capacity_mw'].round(1)

    # Define Helsinki timezone
    helsinki_tz = pytz.timezone('Europe/Helsinki')

    # Get the current date in Helsinki time
    today_helsinki = datetime.now(helsinki_tz).date()

    # Filter for today and the next 6 days based on Helsinki time
    future_dates_df = daily_avg_df[daily_avg_df['Date'] >= today_helsinki].head(6)

    # Convert to JSON format
    daily_avg_data = future_dates_df.to_dict(orient='records')
    for entry in daily_avg_data:
        entry['date'] = entry.pop('Date')

    # Wrap the data in a dictionary with a key
    output_data = {"import_capacity_daily_average": daily_avg_data}

    with open('deploy/import_capacity_daily_average.json', 'w') as json_file:
        json.dump(output_data, json_file, indent=4, default=str)

    print("→ Daily average import capacity data saved to deploy/import_capacity_daily_average.json")

    return final_df

# Main function, for testing purposes only
def main():
    global DEBUG

    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Fetch and process Fingrid import capacity data.")
    parser.add_argument('--debug', action='store_true', help="Enable debug mode for detailed logging.")
    args = parser.parse_args()

    # Set DEBUG based on the argument
    DEBUG = args.debug
    
    # Configure pandas to display all rows
    pd.set_option('display.max_rows', None)
    
    # Load the Fingrid API key from the environment
    load_dotenv('.env.local')

    fingrid_api_key = os.getenv('FINGRID_API_KEY')
    if fingrid_api_key is None:
        raise ValueError("Fingrid API key not found in environment variables")

    # Define the date range: 7 days in the past to 5 days in the future
    start_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (datetime.now(pytz.UTC) + timedelta(days=8)).strftime("%Y-%m-%d")

    # Prepare a dummy DataFrame covering the entire period
    print(f"Prepare dummy data from {start_date} to {end_date}")
    timestamps = pd.date_range(start=start_date, end=end_date, freq='h', tz=pytz.UTC)
    
    # Add dummy columns to the DataFrame
    df = pd.DataFrame({
        'timestamp': timestamps, 
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