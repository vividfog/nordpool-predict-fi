"""
This script processes weather data from multiple CSV files and generates SQL statements to populate a database table,
specifically for a `prediction` table that stores hourly weather data predictions.

The script performs the following steps:
1. **Determine the Full Timestamp Range**: It scans through all available CSV files to find the minimum and maximum timestamps, 
   thus determining the complete range of timestamps for which data should exist in the database.

2. **Generate INSERT Statements**: For every hour within the determined timestamp range, an INSERT SQL statement is created to ensure 
   the presence of a corresponding entry in the `prediction` table for each timestamp.

3. **Process Each CSV File**: For every CSV file:
   - The script infers the weather station ID from the file name.
   - It reads the file into a DataFrame, ensuring the 'Timestamp' column is parsed as a datetime object and used as an index.
   - Data is resampled to hourly intervals, with any missing data being interpolated.
   
4. **Generate UPDATE Statements**: For each timestamp and the associated value in the resampled DataFrame, an UPDATE SQL statement is 
   created to insert the interpolated data into the appropriate fields in the `prediction` table.

Usage:
- CSV files must be located in the same directory, or the path in the `glob.glob` function should be adjusted accordingly.
- Each CSV file must have a 'Timestamp' column for indexing, and fixed columns 'TA_PT1H_AVG' and 'WS_PT1H_AVG'.

Dependencies: 
- `pandas` for data manipulation, `numpy` for numerical operations, and `glob` for file operations.
- Assumes the presence of a SQLite `prediction` table with columns corresponding to station-specific weather data.

Note:
- Before executing, it is essential to ensure that the database schema corresponds to the expected column names.
- The interpolation method used is linear; adjust as needed for different data requirements.
"""

import pandas as pd
import numpy as np
from datetime import timedelta, datetime
import glob

# Use glob to list all CSV files
file_paths = glob.glob('*.csv')  # Adjust path as necessary, e.g., 'path/to/*.csv'

# Function to derive station ID from the file name
def get_station_id(file_path):
    return file_path.split('/')[-1].split('.')[0]

# Step 1: Determine the full timestamp range across all files
all_timestamps = []
for path in file_paths:
    df = pd.read_csv(path, usecols=['Timestamp'], parse_dates=['Timestamp'])
    df['Timestamp'] = pd.to_datetime(df['Timestamp'], utc=True)
    all_timestamps.extend(df['Timestamp'].tolist())

# Find the minimum and maximum timestamp, ensuring datetime objects
min_timestamp = min(all_timestamps)
max_timestamp = max(all_timestamps)

# Ensure min and max are datetime objects
if isinstance(min_timestamp, str):
    min_timestamp = datetime.fromisoformat(min_timestamp)
if isinstance(max_timestamp, str):
    max_timestamp = datetime.fromisoformat(max_timestamp)

# Step 2: Generate INSERT statements for the entire timestamp range
current_timestamp = min_timestamp
while current_timestamp <= max_timestamp:
    print(f"INSERT INTO prediction (Timestamp) VALUES ('{current_timestamp.isoformat()}');")
    current_timestamp += timedelta(hours=1)


# Function to read, interpolate, and generate UPDATE statements
def process_file(path):
    station_id = get_station_id(path)
    t_column_name = f"t_{station_id}"
    ws_column_name = f"ws_{station_id}"

    df = pd.read_csv(path, parse_dates=['Timestamp'])
    df.set_index('Timestamp', inplace=True)
    df = df.resample('h').mean().interpolate(method='linear')  # Interpolating missing values
    
    for timestamp, row in df.iterrows():
        ta_value = row['TA_PT1H_AVG']
        ws_value = row['WS_PT1H_AVG']
        print(f"UPDATE prediction SET {t_column_name} = {ta_value}, {ws_column_name} = {ws_value} WHERE Timestamp = '{timestamp.isoformat()}';")

# Step 3 & 4: Generate UPDATE statements for each file
for path in file_paths:
    process_file(path)