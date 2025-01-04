
'''
A sample Python program to demonstrate how to fetch predictions.json, convert it into a dataframe and save it to a CSV file.
'''

import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import argparse
import pytz

def fetch_data_from_github(url):
    '''
    Fetch prediction.json from GitHub

    Parameters:
    url (str): The URL of the prediction.json file on GitHub

    Returns:
    df (DataFrame): A pandas DataFrame containing the fetched data
    '''
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        df = pd.DataFrame(data, columns=['timestamp', 'price'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    else:
        print(f"Failed to fetch data. Status code: {response.status_code}")
        return None

def date_range_filter(df, start_date=None, end_date=None):
    '''
    Filter the data based on a datetime range

    Parameters:
    df (DataFrame): The original DataFrame
    start_date (datetime): The start date of the range
    end_date (datetime): The end date of the range

    Returns:
    df (DataFrame): The filtered DataFrame
    '''
    if start_date:
        df = df[df['timestamp'] >= start_date]
    if end_date:
        df = df[df['timestamp'] <= end_date]
    return df

def convert_to_helsinki_time(df):
    '''
    Convert the default UTC timestamp to Helsinki timestamp

    Parameters:
    df (DataFrame): The original DataFrame

    Returns:
    df (DataFrame): The DataFrame with timestamps converted to Helsinki time
    '''
    helsinki_tz = pytz.timezone('Europe/Helsinki')
    df['timestamp'] = df['timestamp'].dt.tz_localize('UTC').dt.tz_convert(helsinki_tz)
    return df

# A command line option to convert the timestamp to Helsinki timestamp
parser = argparse.ArgumentParser()
parser.add_argument("--helsinki", help="output the CSV in Helsinki time", action="store_true")
args = parser.parse_args()

url = "https://raw.githubusercontent.com/vividfog/nordpool-predict-fi/main/deploy/prediction.json"

df = fetch_data_from_github(url)

if df is not None:
    # Define a start and end date for filtering
    start_date = datetime.now()
    end_date = datetime.now() + timedelta(days=7)

    # Filter the data based on the defined range
    filtered_df = date_range_filter(df, start_date, end_date)

    # Convert the timestamp to Helsinki timestamp if --helsinki option is used
    if args.helsinki:
        filtered_df = convert_to_helsinki_time(filtered_df)
        print("Helsinki time /w price in c/kWh VAT:")
    else:
        print("UTC time, price in c/kWh VAT:")

    # Show what the filtered data looks like
    print(filtered_df)

    # Save the filtered data to a CSV file
    csv_file_path = './prediction.csv'
    df.to_csv(csv_file_path, index=False)
    print(f"Data saved to {csv_file_path}")

else:
    print("Sorry, couldn't fetch the file or it may be missing from the server.")
