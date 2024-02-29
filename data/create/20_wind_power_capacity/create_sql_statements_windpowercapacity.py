import pandas as pd
from datetime import timedelta

# Adjust the file path as necessary
file_path_wind_power_capacity = './wind_power_capacity_fingrid.csv'

# Read the CSV file, ensuring timestamps are parsed correctly
df_capacity = pd.read_csv(file_path_wind_power_capacity,
                          parse_dates=['Alkuaika UTC'],
                          index_col='Alkuaika UTC')

# Resample to hourly intervals and interpolate missing values
df_capacity_resampled = df_capacity.resample('h').mean().interpolate(method='linear')

# Generate UPDATE statements
for timestamp, row in df_capacity_resampled.iterrows():
    capacity_value = row['Tuulivoimaennusteessa käytetty kokonaiskapasiteetti']
    print(f"UPDATE prediction SET WindPowerCapacityMW = {capacity_value} WHERE Timestamp = '{timestamp.isoformat()}';")
