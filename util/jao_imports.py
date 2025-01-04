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

# Define the border keys we're interested in
BORDER_KEYS = ["border_SE1_FI", "border_SE3_FI", "border_EE_FI"]

def fetch_transfer_capacity_data(start_date, end_date):
    api_url = "https://publicationtool.jao.eu/nordic/api/data/maxBorderFlow"
    
    # Convert start_date and end_date to datetime objects
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=pytz.UTC)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=pytz.UTC) + timedelta(days=1)
    
    params = {
        'FromUtc': start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        'ToUtc': end_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    }
    
    # Rate limit handling
    time.sleep(3)
    
    for attempt in range(3):
        try:
            response = requests.get(api_url, params=params)
            response.raise_for_status()
            
            if response.status_code == 200:
                try:
                    data = response.json().get('data', [])
                except ValueError:
                    raise ValueError("Failed to decode JSON from response from JAO")
    
                if not data:
                    raise ValueError("No data returned from JAO API")
    
                if DEBUG:
                    print(f"Fetched data from JAO API:")
                    print(data)
    
                # Convert data to DataFrame
                df = pd.DataFrame(data)
                if not df.empty:
                    df['dateTimeUtc'] = pd.to_datetime(df['dateTimeUtc'], utc=True)
                    
                    # Keep only the columns we're interested in
                    columns_to_keep = ['dateTimeUtc'] + BORDER_KEYS
                    df = df[columns_to_keep]
    
                    # Melt the DataFrame to have one row per time and border
                    df_melted = df.melt(id_vars=['dateTimeUtc'], var_name='border', value_name='CapacityMW')
                    
                    # Modify the melted DataFrame to use simplified border names
                    df_melted['border'] = df_melted['border'].map({
                        'border_SE1_FI': 'SE1_FI',
                        'border_SE3_FI': 'SE3_FI',
                        'border_EE_FI': 'EE_FI'
                    })
                    
                    # Remove any missing data
                    df_melted.dropna(subset=['CapacityMW'], inplace=True)
    
                    if DEBUG:
                        print("Melted DataFrame:")
                        print(df_melted)
                    return df_melted[['dateTimeUtc', 'border', 'CapacityMW']]
                else:
                    raise ValueError("Empty DataFrame after fetching data")
            elif response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                print(f"[WARNING] Rate limited! Waiting for {retry_after} seconds.")
                time.sleep(retry_after)
            else:
                print(f"[ERROR] Failed to fetch data: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Error occurred while requesting JAO data: {e}")
            time.sleep(5)
        
    raise RuntimeError("Failed to fetch data after 3 attempts")

def calculate_capacity_sums(df):
    """
    Calculates both individual border capacities and their sum for each time period.
    """
    if df.empty:
        return pd.DataFrame(columns=['startTime', 'SE1_FI', 'SE3_FI', 'EE_FI', 'TotalCapacityMW'])
    
    # Pivot the data to get individual border columns
    df['startTime'] = df['dateTimeUtc']
    pivot_df = df.pivot(index='startTime', columns='border', values='CapacityMW').reset_index()
    
    # Calculate the sum
    pivot_df['TotalCapacityMW'] = pivot_df[['SE1_FI', 'SE3_FI', 'EE_FI']].sum(axis=1)
    
    # Forward fill zero values in total capacity
    last_non_zero_value = None
    edits_made = False
    for index, row in pivot_df.iterrows():
        if row['TotalCapacityMW'] == 0:
            if last_non_zero_value is not None:
                pivot_df.at[index, 'TotalCapacityMW'] = last_non_zero_value
                edits_made = True
        else:
            last_non_zero_value = row['TotalCapacityMW']
    
    if edits_made:
        print("[WARNING] Zero sums in JAO transfer data. Replaced with last known non-zero values.")
    
    return pivot_df

def update_import_capacity(df):
    """
    Updates the input DataFrame with import capacity data.
    """
    # Define the current date and adjust the start and end dates
    current_date = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
    history_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (datetime.now(pytz.UTC) + timedelta(days=8)).strftime("%Y-%m-%d")
    
    print(f"* JAO: Fetching import capacities between {history_date} and {end_date}")
    
    try:
        # Fetch import capacity data
        capacity_df = fetch_transfer_capacity_data(history_date, end_date)
    except Exception as e:
        print(f"[ERROR] Failed to fetch import capacities: {e}")
        return df  # Return the original DataFrame if fetching fails
    
    if DEBUG:
        print("Capacity DataFrame:")
        print(capacity_df)
    
    # Calculate summed import capacities
    summed_capacity_df = calculate_capacity_sums(capacity_df)
    
    if DEBUG:
        print("Summed Capacity DataFrame:")
        print(summed_capacity_df)
    
    # Forward fill any missing TotalCapacityMW values
    summed_capacity_df['TotalCapacityMW'] = summed_capacity_df['TotalCapacityMW'].ffill()
    
    # Prepare to merge with original DataFrame
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    
    # Drop the existing capacity columns if they exist
    columns_to_drop = ['ImportCapacityMW', 'SE1_FI', 'SE3_FI', 'EE_FI']
    for col in columns_to_drop:
        if col in df.columns:
            df = df.drop(columns=[col])
    
    # Merge import capacity (now includes individual borders and total)
    final_df = pd.merge(df, summed_capacity_df, left_on='timestamp', right_on='startTime', how='left')
    final_df.drop(columns=['startTime'], inplace=True)
    
    # Ensure all capacity columns exist with initial NaN values
    capacity_columns = ['SE1_FI', 'SE3_FI', 'EE_FI', 'TotalCapacityMW']
    for col in capacity_columns:
        if col not in final_df.columns:
            final_df[col] = pd.NA

    # Fill missing capacity data with forward and backward fill
    for col in capacity_columns:
        final_df[col] = final_df[col].ffill().bfill()
    
    # Rename only the total capacity column
    final_df.rename(columns={'TotalCapacityMW': 'ImportCapacityMW'}, inplace=True)
    
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
    
    # Produce a one-liner report
    total_capacity = final_df['ImportCapacityMW']
    avg_capacity = total_capacity.mean()
    max_capacity = total_capacity.max()
    min_capacity = total_capacity.min()
    
    print(f"→ JAO imports: Avg: {avg_capacity:.1f} MW, Max: {max_capacity:.1f} MW, Min: {min_capacity:.1f} MW")
    
    return final_df

# Main function, for testing purposes only
def main():
    global DEBUG

    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Fetch and process JAO import capacity data.")
    parser.add_argument('--debug', action='store_true', help="Enable debug mode for detailed logging.")
    args = parser.parse_args()

    # Set DEBUG based on the argument
    DEBUG = args.debug
    
    # Configure pandas to display all rows
    pd.set_option('display.max_rows', None)
    
    # Define the date range: 7 days in the past to 8 days in the future
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
    if DEBUG:
        print("Initial DataFrame:")
        print(df)
    
    # Update the DataFrame with import capacity
    updated_df = update_import_capacity(df)

    # Output the DataFrame after updating with import capacity
    if DEBUG:
        print("DataFrame After Import Capacity Update:")
        print(updated_df)
        
    # Drop rows with any NaN values before printing
    cleaned_df = updated_df.dropna()

    # Output the cleaned DataFrame
    if DEBUG:
        print("Updated and Cleaned DataFrame:")
        print(cleaned_df)

if __name__ == "__main__":
    main()
