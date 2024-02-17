"""
A Python package for interacting with SQLite databases, specifically designed for managing and querying timestamped prediction data. This package offers a set of functions to normalize timestamps, insert or update rows in a database, query data based on specific conditions, and run predefined test cases.

Functions:
- normalize_timestamp(ts): Converts a timestamp string into a datetime object and formats it as an ISO8601 string. This function is crucial for ensuring timestamp consistency across database operations.

- db_update(db_path, df): Takes a path to a SQLite database and a pandas DataFrame as inputs. It updates existing rows or inserts new rows into the 'prediction' table based on the 'timestamp' column. The function returns two DataFrames: one containing inserted rows and another containing updated rows.

- db_query(db_path, df): Queries the 'prediction' table in the given SQLite database based on timestamps specified in a pandas DataFrame. It normalizes timestamps in the query DataFrame before executing the query and returns a DataFrame with the query results, sorted by timestamp.

- db_query_all(db_path): Fetches all rows from the 'prediction' table in the specified SQLite database without any filtering conditions. This function is useful for bulk data operations or when all records are needed for analysis.

- db_test(db_path): Runs a series of predefined test cases to demonstrate the functionality of the `db_update` and `db_query` functions. It provides an example of how to use these functions for inserting data, updating existing records, and querying the database.

This package requires pandas for DataFrame operations and sqlite3 for database interaction, making it suitable for data analysis and database management tasks involving time-series prediction data.

Example Usage:
To use these functions, ensure you have a SQLite database with a 'prediction' table that matches the schema expected by the DataFrame operations in the functions.

Schema:
CREATE TABLE prediction (
    timestamp TIMESTAMP PRIMARY KEY,
    "Price [c/kWh]" FLOAT,
    "Temp [°C]" FLOAT,
    "Wind [m/s]" FLOAT,
    "Wind Power [MWh]" FLOAT,
    "Wind Power Capacity [MWh]" FLOAT,
    "hour" INT,
    "day_of_week" INT,
    "month" INT,
    "PricePredict [c/kWh]" FLOAT
);

Sample Data:
timestamp,Price [c/kWh],Temp [°C],Wind [m/s],Wind Power [MWh],Wind Power Capacity [MWh],hour,day_of_week,month,PricePredict [c/kWh]
2023-02-14 00:00:00,5.569,1.6,3.3,2263.3,5451.0,0,2,2,1.9
2023-02-14 01:00:00,8.506,0.8,2.9,1738.8,5451.0,1,2,2,0.9
2023-02-14 02:00:00,10.494,0.0,2.9,1306.4,5451.0,2,2,2,0.1
2023-02-14 03:00:00,10.633,-0.7,2.2,905.89999,5451.0,3,2,2,-0.9

"""

import sqlite3
import pandas as pd

def normalize_timestamp(ts):
    '''
    Internal function to convert a timestamp string into a datetime object and format it as an ISO8601 string. This function is crucial for ensuring timestamp consistency across database operations.
    '''
    # Convert to datetime object using pandas, then format as ISO8601 string
    return pd.to_datetime(ts).strftime('%Y-%m-%d %H:%M:%S')

def db_update(db_path, df):
    '''
    Update existing rows or insert new rows into the 'prediction' table in the specified SQLite database based on the input DataFrame. Returns two DataFrames: one containing inserted rows and another containing updated rows. Does not handle duplicate timestamps. Does not delete rows or columns, always inserts (with defaults) or updates (with new values given).
    '''
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    updated_rows = pd.DataFrame()
    inserted_rows = pd.DataFrame()

    # Normalize timestamp in the dataframe before processing
    df['timestamp'] = df['timestamp'].apply(normalize_timestamp)

    for index, row in df.iterrows():
        # Timestamp is already normalized
        cur.execute("SELECT * FROM prediction WHERE timestamp=?", (row['timestamp'],))
        data = cur.fetchone()
        if data is not None:
            # Update existing row
            for col in df.columns:
                if pd.notnull(row[col]):
                    cur.execute(f"UPDATE prediction SET \"{col}\"=? WHERE timestamp=?", (row[col], row['timestamp']))
            updated_rows = pd.concat([updated_rows, df.loc[[index]]], ignore_index=True)
        else:
            # Insert new row
            cols = ', '.join(f'"{col}"' for col in df.columns)
            placeholders = ', '.join('?' * len(df.columns))
            cur.execute(f"INSERT INTO prediction ({cols}) VALUES ({placeholders})", tuple(row))
            inserted_rows = pd.concat([inserted_rows, df.loc[[index]]], ignore_index=True)

    conn.commit()
    conn.close()

    return inserted_rows, updated_rows

def db_query(db_path, df):
    '''
    Query the 'prediction' table in the specified SQLite database based on timestamps specified in the input DataFrame. Returns a DataFrame with the query results, sorted by timestamp.
    '''
    conn = sqlite3.connect(db_path)

    # Normalize timestamps in query dataframe
    df['timestamp'] = df['timestamp'].apply(normalize_timestamp)

    result_frames = []  # List to store each chunk of dataframes
    for timestamp in df['timestamp']:
        # Timestamp is already normalized
        data = pd.read_sql_query(f"SELECT * FROM prediction WHERE timestamp='{timestamp}'", conn)
        result_frames.append(data)

    result = pd.concat(result_frames, ignore_index=True) if result_frames else pd.DataFrame()
    result = result.sort_values(by='timestamp', ascending=True)

    conn.close()

    return result

def db_query_all(db_path):
    '''
    Query all rows from the 'prediction' table in the specified SQLite database. Returns a DataFrame with the query results.
    '''
    conn = sqlite3.connect(db_path)
    query = "SELECT * FROM prediction"
    data = pd.read_sql_query(query, conn)
    conn.close()
    return data

def db_test(db_path):
    '''
    Run a series of predefined test cases to demonstrate the functionality of the `db_update` and `db_query` functions.
    WARNING: This function modifies the database by inserting and updating records to the 80's. Not to be used in production.
    To fix: DELETE from prediction WHERE timestamp LIKE '1980%';
    '''
    print("Running test cases for db_update and db_query, db_path:", db_path)

    # Test case 1: Update existing data
    df1 = pd.DataFrame({
        'timestamp': ['1980-02-13 23:00:00'],
        'Price [c/kWh]': [3.171],
        'Temp [°C]': [2.4],
        'Wind [m/s]': [4.2],
        'Wind Power [MWh]': [3463.8],
        'Wind Power Capacity [MWh]': [5451.0],
        'hour': [22.0],
        'day_of_week': [1.0],
        'month': [2.0],
        'PricePredict [c/kWh]': [None]
    })
    inserted, updated = db_update(db_path, df1)
    print(f"Test case 1: {len(inserted)} rows inserted, {len(updated)} rows updated")

    # Test case 2: Insert new data
    df2 = pd.DataFrame({
        'timestamp': ['1980-01-20 05:00:00'],
        'Price [c/kWh]': [7.429],
        'Temp [°C]': [-11.2],
        'Wind [m/s]': [1.6],
        'Wind Power [MWh]': [1086.775],
        'Wind Power Capacity [MWh]': [6828.8],
        'hour': [5.0],
        'day_of_week': [6.0],
        'month': [1.0],
        'PricePredict [c/kWh]': [None]
    })
    inserted, updated = db_update(db_path, df2)
    print(f"Test case 2: {len(inserted)} rows inserted, {len(updated)} rows updated")

    # Test case 3: Query data
    df3 = pd.DataFrame({
        'timestamp': ['1980-02-13 23:00:00', '1980-01-20 05:00:00']
    })        
   
    result = db_query(db_path, df3)
    print(f"Test case 3: {len(result)} rows returned")
    print(result)