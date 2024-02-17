import requests
import pandas as pd
import sqlite3
import os
from datetime import datetime

def update_spot_prices_to_db(data_folder_path):
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

    def create_data_frame(data):
        if data is not None and 'data' in data:
            df = pd.json_normalize(data['data'])
            df = df[['DateTime', 'PriceWithTax']]
            df.columns = ['timestamp', 'Price [c/kWh]']
            # Convert timestamp strings to datetime objects
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            # If the datetimes are not timezone-aware, localize to UTC first
            if df['timestamp'].dt.tz is None:
                df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
            return df
        else:
            return pd.DataFrame() # Return an empty DataFrame if no data

    def open_db():
        db_path = os.path.join(data_folder_path, 'prediction.db')
        conn = sqlite3.connect(db_path)
        return conn

    def update_db(conn, df):
        cursor = conn.cursor()
        updates = []
        for i, row in df.iterrows():
            cursor.execute("SELECT * FROM prediction WHERE timestamp = ?", (row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),))
            data = cursor.fetchone()
            if data is not None:
                # Update the price in the existing data
                data = list(data)
                data[1] = row['Price [c/kWh]']
                updates.append(("update", tuple(data)))
            else:
                # Prepare to insert a new row with default values for other columns
                updates.append(("insert", (row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'), row['Price [c/kWh]'], None, None, None, None, None, None, None, None)))
                
        for operation, data in updates:
            if operation == "update":
                cursor.execute("INSERT OR REPLACE INTO prediction VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", data)
            else: # operation == "insert"
                cursor.execute("INSERT INTO prediction VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", data)
        conn.commit()
        print(f'Updated {len(updates)} prices in the database')

    def close_db(conn):
        conn.close()

    def update_prediction_table(conn):
        cursor = conn.cursor()
        rows = cursor.execute('SELECT * FROM prediction').fetchall()
        update_stmt = '''UPDATE prediction
        SET hour = ?, day_of_week = ?, month = ?
        WHERE timestamp = ?'''
        changes = []
        for row in rows:
            timestamp, _, _, _, _, _, hour, day_of_week, month, _ = row
            try:
                timestamp_dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                timestamp_dt = datetime.strptime(timestamp, '%Y%m%dT%H%M%SZ')
            if hour is None or day_of_week is None or month is None:
                hour = hour if hour is not None else timestamp_dt.hour
                day_of_week = day_of_week if day_of_week is not None else (timestamp_dt.weekday() + 1) % 7
                month = month if month is not None else timestamp_dt.month
                changes.append((hour, day_of_week, month, timestamp))
        if changes:
            for change in changes:
                cursor.execute(update_stmt, change)
            conn.commit()
            print(f'Updated {len(changes)} hours/day_of_week/day in the prediction table')

    # Fetch the spot prices
    data = fetch_spot_prices()
    # Create DataFrame
    df = create_data_frame(data)
    # Print the DataFrame
    # print(df)
    # Open the database connection
    conn = open_db()
    # Update the database with new prices
    update_db(conn, df)
    # Update the prediction table
    update_prediction_table(conn)
    # Close the database connection
    close_db(conn)
    return

if __name__ == "__main__":
    print("This feature is meant to be used as a module. It is not meant to be run as a standalone script.")
    exit(0)
