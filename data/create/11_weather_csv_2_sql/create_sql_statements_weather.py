import pandas as pd
import numpy as np
from datetime import timedelta
import glob

# Use glob to list all CSV files
file_paths = glob.glob('*.csv')  # Adjust path as necessary, e.g., 'path/to/*.csv'

# Function to determine the column name from the file name
def get_column_name(file_path):
    return file_path.split('/')[-1].split('.')[0]

# Step 1: Determine the full timestamp range across all files
all_timestamps = []
for path in file_paths:
    df = pd.read_csv(path, usecols=['Timestamp'])
    all_timestamps.extend(pd.to_datetime(df['Timestamp']).tolist())

min_timestamp = min(all_timestamps)
max_timestamp = max(all_timestamps)

# Step 2: Generate INSERT statements for the entire timestamp range
current_timestamp = min_timestamp
while current_timestamp <= max_timestamp:
    print(f"INSERT INTO prediction (Timestamp) VALUES ('{current_timestamp.isoformat()}');")
    current_timestamp += timedelta(hours=1)

# Function to read, interpolate, and generate UPDATE statements
def process_file(path):
    # At this point, we have the column name as the CSV file name, and the only value is the one we want for that timestamp
    column_name = get_column_name(path)
    db_column_name = column_name  # Assuming the database column names directly map from the file names
    df = pd.read_csv(path, parse_dates=['Timestamp'])
    df.set_index('Timestamp', inplace=True)
    df = df.resample('h').mean().interpolate(method='linear')  # Interpolating missing values
    
    for timestamp, row in df.iterrows():
        value = row[df.columns[0]]  # Assuming the value column is the first column after 'Timestamp'
        print(f"UPDATE prediction SET {db_column_name} = {value} WHERE Timestamp = '{timestamp.isoformat()}';")

# Step 3 & 4: Generate UPDATE statements for each file
for path in file_paths:
    process_file(path)
