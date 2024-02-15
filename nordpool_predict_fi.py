import requests
import pandas as pd
import joblib
import matplotlib.pyplot as plt
import pytz  # Make sure to install pytz if you haven't already
import json
from datetime import datetime
import git
import os

# Configuration and Secrets
location = "pirkkala airport"
api_key = "77MKszgZQMSzl81qSbEfE2gqdqK1PTTZ"
rf_model_path = 'electricity_price_rf_model_windpower.joblib'
lr_model_path = 'linear_regression_scaling_model.joblib'
csv_file_path = '5_day_price_predictions.csv'
gist_id = '18970d60ce47a98d6323137c3c581eea'  # Gist ID to update
token = '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'  # GitHub token
deploy_folder_path = '/Users/ph/work.local/autogen-projects/electricity-price/deploy'
repo_path = '/Users/ph/work.local/autogen-projects/electricity-price/deploy'
predictions_path = 'prediction.json'  # This is relative to the repo_path
commit_message = 'Update prediction.json with new data'
wind_power_prediction_path = './wind_power/foreca_wind_power_prediction.json'
wind_power_max_capacity = 6932  # MW

# Define functions here

def read_wind_power_data(filepath):
    with open(filepath, 'r') as file:
        wind_power_data = json.load(file)
    return wind_power_data

def fetch_weather_data(location, api_key):
    base_url = "https://api.tomorrow.io/v4/weather/forecast"
    query_params = {
        'location': location,
        'timesteps': '1h',
        'units': 'metric',
        'apikey': api_key
    }
    headers = {'accept': 'application/json'}
    response = requests.get(base_url, params=query_params, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception("API request failed with status code " + str(response.status_code))

def preprocess_data(weather_data, wind_power_data, wind_power_max_capacity):
    processed_data = []
    hourly_forecast_data = weather_data['timelines']['hourly']
    
    # print("Weather Data Timestamps Sample:", [item['time'] for item in hourly_forecast_data[:5]])  # Debugging line
    # print("Wind Power Data Timestamps Sample:", [item['datetime'] for item in wind_power_data[:5]])  # Debugging line

    for hourly_forecast in hourly_forecast_data:
        time = hourly_forecast['time']
        values = hourly_forecast['values']
        
        # Find matching wind power data
        wind_power = next((item['wind_prediction_MWh'] for item in wind_power_data if item['datetime'] == time), None)
        
        # # Debugging line to check if wind power values are found
        # if wind_power is not None:
        #     print(f"Match found for {time}: {wind_power} MWh")
        # else:
        #     print(f"No match found for {time}")
        
    for hourly_forecast in hourly_forecast_data:
        time = hourly_forecast['time']
        values = hourly_forecast['values']
        temp = values.get('temperature', 0)
        wind_speed = values.get('windSpeed', 0)
        
        # Find matching wind power data
        wind_power = next((item['wind_prediction_MWh'] for item in wind_power_data if item['datetime'] == time), 0)
        
        time_parsed = pd.to_datetime(time)
        hour = time_parsed.hour
        day_of_week = time_parsed.dayofweek + 1
        month = time_parsed.month
        
        processed_data.append({
            'Date': time,
            'Temp [°C]': temp,
            'Wind [m/s]': wind_speed,
            'Wind Power [MWh]': wind_power,
            'Wind Power Capacity [MWh]': wind_power_max_capacity,
            'hour': hour,
            'day_of_week': day_of_week,
            'month': month
        })
    return pd.DataFrame(processed_data)

def predict_prices(df, rf_model_path):
    # Load and apply the Random Forest model for initial predictions
    rf_model = joblib.load(rf_model_path)
    # Ensure all features expected by the model are included
    features = df[['Temp [°C]', 'Wind [m/s]', 'Wind Power [MWh]', 'Wind Power Capacity [MWh]', 'hour', 'day_of_week', 'month']]
    initial_predictions = rf_model.predict(features)
    df['PricePredict [c/kWh]'] = initial_predictions
    return df

def plot_hourly_prices(df):
    # Define color thresholds for price predictions
    color_threshold = [
        {'value': -1000, 'color': 'lime'},
        {'value': 5, 'color': 'green'},
        {'value': 10, 'color': 'orange'},
        {'value': 15, 'color': 'red'},
        {'value': 20, 'color': 'darkred'},
        {'value': 30, 'color': 'black'},
    ]

    # Ensure 'Date' is in datetime format and set as index
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)

    # Convert to Helsinki timezone
    df.index = df.index.tz_localize('UTC').tz_convert('Europe/Helsinki') if df.index.tz is None else df.index.tz_convert('Europe/Helsinki')

    # Determine global minimum and maximum prices for consistent y-axis scaling
    global_min_price = df['PricePredict [c/kWh]'].min()
    global_max_price = df['PricePredict [c/kWh]'].max()

    # Ensure y-axis starts at 0 if all prices are above zero
    y_axis_start = 0 if global_min_price > 0 else global_min_price

    # Group by each day considering the timezone
    grouped = df.groupby(df.index.date)

    for date, group in grouped:
        plt.figure(figsize=(10, 6))
        # Calculate the average price for the day
        daily_avg_price = group['PricePredict [c/kWh]'].mean()
        
        # Plot primary axis (prices)
        ax1 = plt.gca()  # Get current axis for price
        for idx, row in group.iterrows():
            bar_color = get_bar_color(row['PricePredict [c/kWh]'], color_threshold)
            ax1.bar(idx.hour, row['PricePredict [c/kWh]'], color=bar_color, width=0.8, zorder=2)

        ax1.set_xlabel("Hour of the Day")
        ax1.set_ylabel("Price [c/kWh]")
        plt.xticks(range(24))  # Ensure x-axis labels show every hour
        ax1.set_ylim(y_axis_start, global_max_price)  # Y-axis for price
        ax1.axhline(y=daily_avg_price, color='gray', linestyle='--', label=f'Avg Price: {daily_avg_price:.2f} c/kWh', zorder=3)

        # Plot secondary axis (wind power)
        ax2 = ax1.twinx()  # Create a second y-axis sharing the same x-axis
        ax2.plot(group.index.hour, group['Wind Power [MWh]'], color='blue', marker='o', linestyle='-', linewidth=2, label='Wind Power [MWh]', zorder=4)
        ax2.set_ylim(0, 7000)  # Fixed y-axis for wind power
        ax2.set_ylabel('Wind Power [MWh]')

        plt.title(f"Hourly Electricity Price and Wind Power Prediction for {date} (Helsinki Time)")
        ax1.legend(loc='upper left')
        ax2.legend(loc='upper right')

        # Save the plot as a PNG file named after the date
        plt.savefig(f"./png/{date}.png")
        plt.close()
        
def get_bar_color(value, color_threshold):
    """Return the color for the bar based on the specified value."""
    for threshold in color_threshold:
        if value >= threshold['value']:
            color = threshold['color']
        else:
            break
    return color

def convert_csv_to_json(csv_file_path):
    # Load CSV file
    df = pd.read_csv(csv_file_path)

    # Convert 'Date' to a datetime format and then to a timestamp (milliseconds)
    df['Date'] = pd.to_datetime(df['Date'])
    df['timestamp'] = df['Date'].apply(lambda x: int(x.timestamp()) * 1000)  # Convert to milliseconds

    # Select only the columns needed
    apex_data = df[['timestamp', 'PricePredict [c/kWh]']].values.tolist()

    # Convert data to JSON format
    json_data = json.dumps(apex_data)
    return json_data

def save_json_to_deploy_folder(json_data, deploy_folder_path, file_name='prediction.json'):
    full_path = f"{deploy_folder_path}/{file_name}"
    with open(full_path, 'w') as f:
        f.write(json_data)
    print(f"File saved to Deploy folder: {full_path}")
    
def push_updates_to_github(repo_path, file_paths, commit_message):
    try:
        repo = git.Repo(repo_path)
        
        for file_path in file_paths:
            # Check if the file_path is relative, convert it to absolute
            absolute_file_path = os.path.join(repo_path, file_path) if not os.path.isabs(file_path) else file_path
            
            # Stage the file for commit
            repo.index.add([absolute_file_path])
        
        # Commit the changes
        repo.index.commit(commit_message)
        
        # Push the changes
        repo.remotes.origin.push()
        print("Updates pushed to GitHub.")
    except Exception as e:
        print(f"Error pushing updates to GitHub: {e}")

def save_daily_averages_to_json(df, deploy_folder_path, file_name='averages.json'):
    # Ensure 'Date' column is in datetime format and normalize to remove time
    df['Date'] = pd.to_datetime(df['Date']).dt.normalize()
    
    # Calculate daily averages
    daily_averages = df.groupby('Date')['PricePredict [c/kWh]'].mean().reset_index()
    
    # Convert 'Date' to the timestamp format required by Apex Charts (milliseconds since epoch)
    daily_averages['timestamp'] = daily_averages['Date'].apply(lambda x: x.timestamp() * 1000)
    
    # Create the list of lists for JSON output
    json_data_list = daily_averages[['timestamp', 'PricePredict [c/kWh]']].values.tolist()

    # Convert data to JSON format
    json_data = json.dumps(json_data_list, ensure_ascii=False)

    # Save to JSON in the deploy folder
    json_path = os.path.join(deploy_folder_path, file_name)
    with open(json_path, 'w') as f:
        f.write(json_data)
    print(f"Daily averages saved to {json_path}")


# Main execution starts here

wind_power_data = read_wind_power_data(wind_power_prediction_path)
weather_data = fetch_weather_data(location, api_key)
features_df = preprocess_data(weather_data, wind_power_data, wind_power_max_capacity)
predictions_df = predict_prices(features_df, rf_model_path)

# Plot and save daily price predictions with consistent scales
plot_hourly_prices(predictions_df)

# Prepare the CSV file for gist update
predictions_df = predictions_df.drop(['day_of_week', 'month', 'hour'], axis=1)
predictions_df.reset_index(inplace=True)
predictions_df.to_csv(csv_file_path, index=False)

# Convert the CSV to JSON and update the gist
json_data = convert_csv_to_json(csv_file_path)
save_json_to_deploy_folder(json_data, deploy_folder_path)

save_daily_averages_to_json(predictions_df, deploy_folder_path)
averages_json_path = 'averages.json'  # The relative path within the repository
files_to_push = [predictions_path, averages_json_path]

push_updates_to_github(repo_path, files_to_push, commit_message)

print("Script execution completed.")
