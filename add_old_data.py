import pandas as pd
from util.sql import db_update  # Assuming your sql functions are in util.sql module
from util.sql import db_query_all  # Assuming your sql functions are in util.sql module

def add_csv_to_db(csv_path, db_path):
    # Read CSV file into DataFrame, specifying the correct column names
    df = pd.read_csv(csv_path)

    # Drop the "helsinki" column
    df.drop(columns=['helsinki'], inplace=True)

    # Convert Unix timestamp to datetime
    df['timestamp_UTC'] = pd.to_datetime(df['timestamp_UTC'], unit='s')

    # Rename columns to match the database schema if necessary
    df.rename(columns={
        'timestamp_UTC': 'timestamp',
        'temp_celsius': 'Temp [°C]',
        'wind_m/s': 'Wind [m/s]',
        'wind_power_MWh': 'Wind Power [MWh]',
        'wind_power_capacity_MWh': 'Wind Power Capacity [MWh]',
        'price_cents_per_kWh': 'Price [c/kWh]'
    }, inplace=True)

    # Convert timestamp to a more standard format
    df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')

    # Add 'PricePredict [c/kWh]' column with None values as placeholders
    df['PricePredict [c/kWh]'] = None

    # Update database with DataFrame
    inserted_rows, updated_rows = db_update(db_path, df)

    print(f"{len(inserted_rows)} rows inserted, {len(updated_rows)} rows updated.")


csv_path = 'data/nordpool-spot-with-wind-power.csv'  # Replace with the path to your CSV file
db_path = 'data/prediction.db'  # Replace with the path to your database file
add_csv_to_db(csv_path, db_path)
