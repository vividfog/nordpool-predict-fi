# filename: merge_wind_power_data.py
import pandas as pd
import requests
from io import StringIO

# Step 1: Download the CSV file
url = "https://filebin.net/kz1gr81v727hizdo/wind_power_history_data.csv"
response = requests.get(url)
if response.status_code != 200:
    print("Failed to download the file.")
    exit()

# Step 2: Read the CSV file into a pandas DataFrame
csv_data = StringIO(response.text)
df = pd.read_csv(csv_data, delimiter=",")

# Step 3: Convert the timestamps to pandas datetime objects
df['Alkuaika UTC'] = pd.to_datetime(df['Alkuaika UTC'])

# Step 4: Group the data by hour and calculate the mean of the wind power values
# We will use the 'Alkuaika UTC' column to group by hour
df['hour'] = df['Alkuaika UTC'].dt.floor('h')
# Use the correct column name by accessing the third column in the DataFrame
hourly_mean = df.groupby('hour')[df.columns[2]].mean().reset_index()

# Step 5: Create a new DataFrame with the hourly timestamps and the corresponding mean wind power values
hourly_mean.columns = ['timestamp', 'wind_power']

# Step 6: Print the resulting DataFrame
print(hourly_mean)

# Step 7: Save the resulting DataFrame to a new CSV file
hourly_mean.to_csv('hourly_wind_power.csv', index=False)