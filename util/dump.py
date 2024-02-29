import sqlite3
import pandas as pd
import sys
import os

def dump_sqlite_db(data_folder_path):
    # Connect to the SQLite database
    conn = sqlite3.connect(f'{data_folder_path}/prediction.db')
    # Read the entire table into a DataFrame
    df = pd.read_sql_query('SELECT * FROM prediction', conn)
    # Close the connection
    conn.close()
    # Convert the timestamp to datetime
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')
    # Replace NULL values with empty string
    df = df.fillna('')
    # Print the DataFrame in CSV format
    print(df.to_csv(index=False))

if __name__ == "__main__":
    print("This is not meant to be executed directly.")
    exit()

# Usage:
# python nordpool_predict_fi.py --dump | sort > data/dump.csv