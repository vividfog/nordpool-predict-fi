# filename: preprocess_data.py
import pandas as pd

# Load the dataset
df = pd.read_csv('hourly_wind_power_price_temp_speed.csv', delimiter=';')

# Parse the dataset
df['timestamp'] = pd.to_datetime(df['timestamp'])
df['wind_power'] = pd.to_numeric(df['wind_power'], errors='coerce')
df['Speed'] = pd.to_numeric(df['Speed'], errors='coerce')

# Drop unnecessary columns
df = df[['Speed', 'wind_power']]

# Handle missing data
df.dropna(inplace=True)

# Save the preprocessed data to a new CSV file
df.to_csv('preprocessed_wind_data.csv', index=False)

print("Data preprocessing complete. Preprocessed data saved to 'preprocessed_wind_data.csv'.")