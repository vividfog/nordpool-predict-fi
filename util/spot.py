import requests
import pandas as pd
import sqlite3
import os
from datetime import datetime
import numpy as np
import pytz

def fetch_spot_prices():
    url = 'https://api.spot-hinta.fi/TodayAndDayForward?HomeAssistant=true'
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to fetch data, status code: {response.status_code}")
            return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

def create_spot_prices_df(data):
    if data is not None and 'data' in data:
        df = pd.json_normalize(data['data'])
        df = df[['DateTime', 'PriceWithTax']]
        df.columns = ['timestamp', 'Price [€/kWh]']  # Temporarily name the column for clarity
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        if df['timestamp'].dt.tz is None:
            df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
        # Convert prices from euros to cents
        df['Price_cpkWh'] = df['Price [€/kWh]'] * 100
        # Drop the original euros column as it's no longer needed
        df.drop(columns=['Price [€/kWh]'], inplace=True)
        return df
    else:
        return pd.DataFrame()  # Return an empty DataFrame if no data

def add_spot_prices_to_df(input_df):
    # Fetch the spot prices
    spot_prices_data = fetch_spot_prices()
    # Create a DataFrame from the spot prices data
    spot_prices_df = create_spot_prices_df(spot_prices_data)

    # Convert the 'timestamp' column to datetime
    spot_prices_df['timestamp'] = pd.to_datetime(spot_prices_df['timestamp'])

    # Convert the 'timestamp' column to UTC
    spot_prices_df['timestamp'] = spot_prices_df['timestamp'].dt.tz_convert('UTC')
    
    # Ensure the input DataFrame has its 'timestamp' column in the right format
    input_df['timestamp'] = pd.to_datetime(input_df['timestamp'])
    if input_df['timestamp'].dt.tz is None:
        input_df['timestamp'] = input_df['timestamp'].dt.tz_localize('UTC')

    # Merge the input DataFrame with the spot prices DataFrame based on the 'timestamp'
    # If 'Price_cpkWh_new' does not exist, it means there were no conflicts and no action is needed
    merged_df = pd.merge(input_df, spot_prices_df, on='timestamp', how='left', suffixes=('', '_new'))
    
    # Check if 'Price_cpkWh_new' column exists in the merged DataFrame
    if 'Price_cpkWh_new' in merged_df.columns:
        # Only update 'Price_cpkWh' where it's NaN in the input_df
        merged_df['Price_cpkWh'] = np.where(merged_df['Price_cpkWh'].isna(), merged_df['Price_cpkWh_new'], merged_df['Price_cpkWh'])
        # Drop the temporary '_new' column after updating
        merged_df.drop(columns=['Price_cpkWh_new'], inplace=True)
    
    return merged_df

if __name__ == "__main__":
    print("This feature is meant to be used as a module. It is not meant to be run as a standalone script.")
    exit(0)
