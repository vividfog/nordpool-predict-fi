import requests
import pandas as pd
import joblib
import matplotlib.pyplot as plt
import pytz  # Make sure to install pytz if you haven't already
import json
from datetime import datetime
import git
import os
from dotenv import load_dotenv
import sqlite3
import argparse

load_dotenv('.env.local')  # take environment variables from .env.local.

# Configuration and secrets
location = os.getenv('LOCATION') or "LOCATION not set in environment"
api_key = os.getenv('API_KEY') or "API_KEY not set in environment"
rf_model_path = os.getenv('RF_MODEL_PATH') or "RF_MODEL_PATH not set in environment"
lr_model_path = os.getenv('LR_MODEL_PATH') or "LR_MODEL_PATH not set in environment"
csv_file_path = os.getenv('CSV_FILE_PATH') or "CSV_FILE_PATH not set in environment"
gist_id = os.getenv('GIST_ID') or "GIST_ID not set in environment"
token = os.getenv('TOKEN') or "TOKEN not set in environment"
deploy_folder_path = os.getenv('DEPLOY_FOLDER_PATH') or "DEPLOY_FOLDER_PATH not set in environment"
cache_folder_path = os.getenv('CACHE_FOLDER_PATH') or "CACHE_FOLDER_PATH not set in environment"
repo_path = os.getenv('REPO_PATH') or "REPO_PATH not set in environment"
predictions_path = os.getenv('PREDICTIONS_PATH') or "PREDICTIONS_PATH not set in environment"
commit_message = os.getenv('COMMIT_MESSAGE') or "COMMIT_MESSAGE not set in environment"
wind_power_prediction_path = os.getenv('WIND_POWER_PREDICTION_PATH') or "WIND_POWER_PREDICTION_PATH not set in environment"
try:
    wind_power_max_capacity = int(os.getenv('WIND_POWER_MAX_CAPACITY'))
except TypeError:
    wind_power_max_capacity = "WIND_POWER_MAX_CAPACITY not set or not a number in environment"

parser = argparse.ArgumentParser()
parser.add_argument('--foreca', action='store_true', help='Update the Foreca wind power prediction file')
parser.add_argument('--spot', action='store_true', help='Update the spot prices to database')
parser.add_argument('--dump', action='store_true', help='Dump the SQLite database to CSV format')
args = parser.parse_args()

if args.foreca:
    from util.foreca import foreca_wind_power_prediction
    print("Updating Foreca wind power prediction:", wind_power_prediction_path)
    foreca_wind_power_prediction(
        wind_power_prediction_path=wind_power_prediction_path,
        cache_folder_path=cache_folder_path
        )
    exit()

if args.spot:
    from util.spot import update_spot_prices_to_db
    print("Updating spot prices to database")
    update_spot_prices_to_db(cache_folder_path)
    exit()

if args.dump:
    from util.dump import dump_sqlite_db
    print("Dumping SQLite database to CSV format")
    dump_sqlite_db(cache_folder_path)
    exit()

def save_to_sqlite_db(df, db_name):
    try:
        with sqlite3.connect(f'{cache_folder_path}/{db_name}.db') as conn:
            df.to_sql(db_name, conn, if_exists='append')
        print(f"Data saved to {db_name} database.")
    except Exception as e:
        print(f"Error occurred while saving data to {db_name} database: ", str(e))

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
    
    # Return both the JSON data and the modified dataframe
    return json_data, df

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

    # Return the daily_averages dataframe
    return daily_averages


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
json_data, predictions_df = convert_csv_to_json(csv_file_path)
save_json_to_deploy_folder(json_data, deploy_folder_path)

daily_averages = save_daily_averages_to_json(predictions_df, deploy_folder_path)

averages_json_path = 'averages.json'  # The relative path within the repository
files_to_push = [predictions_path, averages_json_path]

try:
    # Check if 'timestamp' column exists
    if 'timestamp' in predictions_df.columns and 'timestamp' in daily_averages.columns:
        # Save new unique time stamps and values to SQLite databases
        save_to_sqlite_db(predictions_df[['timestamp', 'PricePredict [c/kWh]']], 'prediction')
        save_to_sqlite_db(daily_averages[['timestamp', 'PricePredict [c/kWh]']], 'averages')
        print("Data saved to SQLite databases.")
    else:
        print("'timestamp' column not found in the DataFrames.")
except Exception as e:
    print("Error occurred while saving data to SQLite databases: ", str(e))

try:
    push_updates_to_github(repo_path, files_to_push, commit_message)
    print("Data pushed to GitHub.")
except Exception as e:
    print("Error occurred while pushing data to GitHub: ", str(e))


print("Script execution completed.")
