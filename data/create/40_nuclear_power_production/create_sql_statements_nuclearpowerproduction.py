import pandas as pd

# Path to the nuclear power production data file
file_path_nuclear_power = './nuclear_power_production_MW.csv'

# Read the CSV file, ensuring timestamps are parsed correctly
df_nuclear_power = pd.read_csv(file_path_nuclear_power,
                               parse_dates=['Alkuaika UTC'],
                               index_col='Alkuaika UTC')

# Aggregate to hourly intervals by taking the mean of the 3-minute values
df_nuclear_power_hourly = df_nuclear_power.resample('h').mean()

# Interpolate missing hourly values
df_nuclear_power_hourly_interpolated = df_nuclear_power_hourly.interpolate(method='linear')

# Generate and print UPDATE statements for the NuclearPowerMW column
for timestamp, row in df_nuclear_power_hourly_interpolated.iterrows():
    nuclear_power_value = row['Ydinvoimatuotanto - reaaliaikatieto']
    print(f"UPDATE prediction SET NuclearPowerMW = {nuclear_power_value} WHERE Timestamp = '{timestamp.isoformat()}';")
