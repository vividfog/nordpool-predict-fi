import pandas as pd

# Read the input CSV file into a DataFrame
df = pd.read_csv("nordpool-spot-with-wind-power.csv")

# Drop the 'helsinki' column
df = df.drop('helsinki', axis=1)

# Rename the columns to match the database schema
df = df.rename(columns={
    'timestamp_UTC': 'timestamp',
    'temp_celsius': 'Temp [°C]',
    'wind_m/s': 'Wind [m/s]',
    'wind_power_MWh': 'Wind Power [MWh]',
    'wind_power_capacity_MWh': 'Wind Power Capacity [MWh]',
    'price_cents_per_kWh': 'Price [c/kWh]'
})

# Convert the timestamp to the 'YYYYMMDDTHHMMSSZ' format
df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
df['timestamp'] = df['timestamp'].dt.strftime('%Y%m%dT%H%M%SZ')

# Write the DataFrame to the output CSV file
df.to_csv("data_dump.csv", index=False)
