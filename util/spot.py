import requests
import pandas as pd
import sqlite3
import os

def update_spot_prices_to_db(cache_folder_path):

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
            return pd.DataFrame()  # Return an empty DataFrame if no data

    # Fetch the spot prices
    data = fetch_spot_prices()

    # Create DataFrame
    df = create_data_frame(data)

    # Print the DataFrame
    print(df)

    def open_db():
        db_path = os.path.join(cache_folder_path, 'prediction.db')
        conn = sqlite3.connect(db_path)
        return conn

    def update_db(conn, df):
        # Create a cursor
        cursor = conn.cursor()

        # Iterate over DataFrame rows
        for i, row in df.iterrows():
            # Prepare SQL query
            query = f"""
            INSERT INTO prediction (timestamp, "Price [c/kWh]")
            VALUES ('{row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}', {row['Price [c/kWh]']})
            ON CONFLICT(timestamp) DO UPDATE SET "Price [c/kWh]" = {row['Price [c/kWh]']}
            """
            # Execute SQL query
            cursor.execute(query)
        
        # Commit changes
        conn.commit()

    def close_db(conn):
        conn.close()

    # Open the database connection
    conn = open_db()

    # Update the database with new prices
    update_db(conn, df)

    # Close the database connection
    close_db(conn)
    
    return

if __name__ == "__main__":
    print("This feature is meant to be used as a module. It is not meant to be run as a standalone script.")
    exit(0)