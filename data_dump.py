import sqlite3
import pandas as pd
import sys

def dump_sqlite_db(db_name, table_name):
    # Connect to the SQLite database
    conn = sqlite3.connect(f'cache/{db_name}.db')

    # Read the table into a DataFrame
    df = pd.read_sql_query(f'SELECT timestamp, "PricePredict [c/kWh]" FROM {table_name}', conn)

    # Close the connection
    conn.close()

    # Convert the timestamp to datetime and format it
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Group the DataFrame by timestamp and calculate the mean price prediction for each timestamp
    df = df.groupby('timestamp')['PricePredict [c/kWh]'].mean().reset_index()

    # Print the DataFrame in CSV format
    print(df.to_csv(index=False))

def main():
    # Check if the correct number of command line arguments were provided
    if len(sys.argv) != 2:
        print("Usage: python dump_db.py <db_name>")
        return

    # Get the database name from the command line arguments
    db_name = sys.argv[1]

    # If 'predictions' is provided as db_name, change it to 'prediction'
    if db_name == 'predictions':
        db_name = 'prediction'

    # Dump the contents of the table
    dump_sqlite_db(db_name, db_name)

if __name__ == "__main__":
    main()
