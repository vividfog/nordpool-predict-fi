import pandas as pd
from datetime import timedelta

# Adjust the file path as necessary
file_path_wind_power_capacity = './wind_power_capacity_fingrid.csv'

# Read the CSV file with the correct delimiter
df_capacity = pd.read_csv(file_path_wind_power_capacity,
                          delimiter=';',
                          parse_dates=['Start_UTC'],
                          index_col='Start_UTC')

# Resample to hourly intervals and interpolate missing values
df_capacity_resampled = df_capacity.resample('H').mean().interpolate(method='linear')

# Generate UPDATE statements
for timestamp, row in df_capacity_resampled.iterrows():
    capacity_value = row['Capacity']
    print(f"UPDATE prediction SET WindPowerCapacityMW = {capacity_value} WHERE Timestamp = '{timestamp.isoformat()}';")
