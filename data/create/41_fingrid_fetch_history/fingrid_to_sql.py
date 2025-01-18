"""
This script fetches data from the Fingrid API for a given dataset ID,
aggregates the data hourly, imputes missing values, and outputs the SQL statements to update
a specified column in the "prediction" SQLite database. If more than 24 hours of data
are missing consecutively, an error is raised.

Usage:
    python fingrid_to_sql.py --dataset_id DATASET_ID --column_name COLUMN_NAME [--start_date YYYY-MM-DD] [--end_date YYYY-MM-DD] [--debug]
    
Example:
    python fingrid_to_sql.py --dataset_id 181 --column_name WindPowerMW --start_date 2023-11-01 --end_date 2023-12-31
    
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import argparse
import os
import time

def fetch_data(api_url, headers, params):
    
    # Add delay to avoid hitting the rate limit
    time.sleep(1)

    try:
        response = requests.get(api_url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json().get('data', [])
        return data
    except requests.exceptions.RequestException as e:
        print(f"-- Request failed: {e}")
        raise SystemExit(e)

def process_data(data):
    if not data:
        print("-- No data to process.")
        return None

    df = pd.DataFrame(data)
    df['startTime'] = pd.to_datetime(df['startTime'])
    df['value'] = pd.to_numeric(df['value'], errors='coerce')
    df = df.dropna(subset=['value'])  # Drop rows where 'value' could not be converted to numeric
    df.set_index('startTime', inplace=True)
    df = df.drop(columns=['endTime'])  # Drop the 'endTime' column

    # Resample to hourly and average the values
    df = df.resample('1h').mean()

    # Impute missing values
    missing_hours = df['value'].isna().sum()
    if missing_hours > 24:
        raise ValueError(f"More than 24 hours of data are missing: {missing_hours} hours")

    df['value'] = df['value'].interpolate(method='time')
    df['WindPowerMW'] = df['value'].round(0)
    return df[['WindPowerMW']]

def output_sql(aggregated_df, column_name):
    for _, row in aggregated_df.iterrows():
        timestamp = row.name.strftime('%Y-%m-%dT%H:%M:%S+00:00')
        value = row[column_name]
        print(f"UPDATE prediction SET {column_name} = {value:.0f} WHERE timestamp = '{timestamp}';")

def main():
    parser = argparse.ArgumentParser(description="Fetch and aggregate data from Fingrid API for a given dataset ID.")
    parser.add_argument("--dataset_id", type=int, required=True, help="Dataset ID")
    parser.add_argument("--column_name", type=str, required=True, help="Column name to update in the database")
    parser.add_argument("--start_date", type=str, default=(datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"), help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", type=str, default=datetime.now().strftime("%Y-%m-%d"), help="End date (YYYY-MM-DD)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    api_key = os.getenv("FINGRID_API_KEY")
    if not api_key:
        print("-- FINGRID_API_KEY environment variable not set.")
        return

    api_url = f"https://data.fingrid.fi/api/datasets/{args.dataset_id}/data"
    headers = {'x-api-key': api_key}

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    current_date = start_date

    all_data = []

    while current_date < end_date:
        next_date = current_date + timedelta(days=30)
        if next_date > end_date:
            next_date = end_date

        params = {
            'startTime': f"{current_date.strftime('%Y-%m-%dT00:00:00.000Z')}",
            'endTime': f"{next_date.strftime('%Y-%m-%dT23:59:59.000Z')}",
            'format': 'json',
            'oneRowPerTimePeriod': False,
            'page': 1,
            'pageSize': 20000,
            'locale': 'en'
        }

        data = fetch_data(api_url, headers, params)
        if data:
            all_data.extend(data)

        current_date = next_date + timedelta(days=1)

        # Process and output data for the current month
        aggregated_df = process_data(all_data)
        if aggregated_df is not None:
            output_sql(aggregated_df, args.column_name)
            all_data = []  # Clear the data for the next month

    if aggregated_df is not None:
        output_sql(aggregated_df, args.column_name)

if __name__ == "__main__":
    main()
