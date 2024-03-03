import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from tabulate import tabulate  # You might need to install this package

# Adjust this!
model_last_trained = datetime(2024, 2, 29, 4, 34, tzinfo=datetime.utcnow().tzinfo)

now = datetime.now()
timestamp_str = now.strftime("%Y-%m-%d")

# Load the CSV file
file_path = '../../../data/dump.csv'
data = pd.read_csv(file_path)

# Convert the timestamp column to datetime and ensure it's aware of UTC timezone
data['timestamp'] = pd.to_datetime(data['timestamp'], utc=True)

# Find the last 15 days of data
last_date = data['timestamp'].max()
start_date = last_date - timedelta(days=15)

# Filter data for the last 15 days
filtered_data = data[(data['timestamp'] >= start_date) & (data['timestamp'] <= last_date)]

# Resample to daily, calculating mean, min, and max for predictions and actual prices
daily_stats = filtered_data.resample('D', on='timestamp').agg({
    'PricePredict_cpkWh': ['mean', 'min', 'max'],
    'Price_cpkWh': ['mean', 'min', 'max']
})

# Flatten the MultiIndex columns for easier plotting and analysis
daily_stats.columns = ['_'.join(col).strip() for col in daily_stats.columns.values]

# Reorder columns to place means, mins, and maxes side by side
daily_stats = daily_stats.reindex(columns=[
    'PricePredict_cpkWh_mean', 'Price_cpkWh_mean', 
    'PricePredict_cpkWh_min', 'Price_cpkWh_min', 
    'PricePredict_cpkWh_max', 'Price_cpkWh_max'
])

# Calculate difference between the mean values in cents
daily_stats['Error_c'] = (daily_stats['PricePredict_cpkWh_mean'] - daily_stats['Price_cpkWh_mean'])

# Reorder columns to place means, mins, and maxes side by side
daily_stats = daily_stats.reindex(columns=[
    'PricePredict_cpkWh_mean', 'Price_cpkWh_mean', 'Error_c',
    'PricePredict_cpkWh_min', 'Price_cpkWh_min', 
    'PricePredict_cpkWh_max', 'Price_cpkWh_max'
])

# Round data up to one decimal point
daily_stats = daily_stats.round(1)

# Convert daily_stats to markdown table
markdown_table = tabulate(daily_stats.reset_index(), headers='keys', tablefmt='pipe', showindex=False)

# Condense header titles for readability
markdown_table = markdown_table.replace('PricePredict_cpkWh', 'Predict')
markdown_table = markdown_table.replace('Price_cpkWh', 'Actual')

# Create the file name
file_name = f'table-{timestamp_str}.md'

# Write the markdown table to the file
with open(file_name, 'w') as f:
    f.write(markdown_table)

# Plotting
fig, ax = plt.subplots(figsize=(12, 6))

# Plot means
ax.plot(daily_stats.index, daily_stats['PricePredict_cpkWh_mean'], label='Prediction Mean', linewidth=2, color='blue')
ax.plot(daily_stats.index, daily_stats['Price_cpkWh_mean'], label='Actual Mean', linewidth=2, color='green')

# Plot mins and maxes
ax.plot(daily_stats.index, daily_stats['PricePredict_cpkWh_min'], label='Prediction Min', linestyle='--', color='blue', alpha=0.5)
ax.plot(daily_stats.index, daily_stats['PricePredict_cpkWh_max'], label='Prediction Max', linestyle='--', color='blue', alpha=0.5)
ax.plot(daily_stats.index, daily_stats['Price_cpkWh_min'], label='Actual Min', linestyle='--', color='green', alpha=0.5)
ax.plot(daily_stats.index, daily_stats['Price_cpkWh_max'], label='Actual Max', linestyle='--', color='green', alpha=0.5)

# Mark the model's last training date
ax.axvline(x=model_last_trained, color='red', linestyle='-', label='Model Last Trained')

# Enhancing the plot
ax.set_xlabel('Date')
ax.set_ylabel('Price (cpkWh)')
ax.set_title('Nordpool FI Spot Price Prediction vs Actual Prices - Last 15 Days')
ax.legend()
plt.xticks(rotation=45)
plt.grid(True)

# Save the plot as .png format with timestamp
plt.savefig(f"plot_{timestamp_str}.png")