import sqlite3
import pandas as pd
import sys
import os

def dump_sqlite_db(cache_folder_path):

    # Connect to the SQLite database
    conn = sqlite3.connect(f'{cache_folder_path}/prediction.db')

    # Read the table into a DataFrame
    df = pd.read_sql_query(f'SELECT timestamp, "Price [c/kWh]" FROM prediction', conn)

    # Close the connection
    conn.close()

    # Convert the timestamp to datetime and format it
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Group the DataFrame by timestamp and calculate the mean price prediction for each timestamp
    df = df.groupby('timestamp')['Price [c/kWh]'].mean().reset_index()

    # Print the DataFrame in CSV format
    print(df.to_csv(index=False))

if __name__ == "__main__":
    print("This is the dump.py file. It is not meant to be executed directly. Please execute the main.py file instead.")
    exit()