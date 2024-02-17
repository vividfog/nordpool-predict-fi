import pandas as pd
from util.sql import db_update, db_query_all  # Import the updated db_query_all instead if created

def update_datetime_columns(db_path):
    # Fetch all data from the database
    all_data = db_query_all(db_path)  # Use the revised db_query_all function

    if not all_data.empty:
        # Ensure 'timestamp' is in datetime format
        all_data['timestamp'] = pd.to_datetime(all_data['timestamp'])

        # Update 'month', 'hour', 'day_of_week'
        all_data['month'] = all_data['timestamp'].dt.month
        all_data['hour'] = all_data['timestamp'].dt.hour
        all_data['day_of_week'] = all_data['timestamp'].dt.dayofweek + 1  # +1 to match your requirement Monday=1

        # Update the database with the new columns
        _, updated_rows = db_update(db_path, all_data)
        print(f"{len(updated_rows)} rows updated.")
    else:
        print("No data found in the database.")

db_path = 'data/prediction.db'  # Update with your actual database path
update_datetime_columns(db_path)
