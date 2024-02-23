import requests
import pandas as pd
import joblib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pytz
import json
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import sqlite3
import argparse
from util.sql import db_update, db_query, db_test, db_query_all
from util.weather import weather_get
from util.spot import add_spot_prices_to_df
from util.foreca import foreca_wind_power_prediction
from util.dump import dump_sqlite_db
from util.github import push_updates_to_github
from util.train import csv_to_df, train_model
from util.llm import narrate_prediction
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import numpy as np

load_dotenv('.env.local')  # take environment variables from .env.local

# Configuration and secrets
location = os.getenv('LOCATION') or "pirkkala airport"
rf_model_path = os.getenv('RF_MODEL_PATH') or "RF_MODEL_PATH not set in environment"
data_folder_path = os.getenv('DATA_FOLDER_PATH') or "DATA_FOLDER_PATH not set in environment"
db_path = os.getenv('DB_PATH') or "DB_PATH not set in environment"
repo_path = os.getenv('REPO_PATH') or "REPO_PATH not set in environment"
predictions_file = os.getenv('PREDICTIONS_FILE') or "PREDICTIONS_FILE not set in environment"
averages_file = os.getenv('AVERAGES_FILE') or "AVERAGES_FILE not set in environment"
past_performance_file = os.getenv('PAST_PERFORMANCE_FILE') or "PAST_PERFORMANCE_FILE not set in environment"
wind_power_prediction = os.getenv('WIND_POWER_PREDICTION') or "WIND_POWER_PREDICTION not set in environment"
api_key = os.getenv('API_KEY') or "Tomorrow.io API_KEY not set in environment"
token = os.getenv('TOKEN') # GitHub token, used by --publish, optional
commit_message = os.getenv('COMMIT_MESSAGE') # Optional, used by --publish
deploy_folder_path = os.getenv('DEPLOY_FOLDER_PATH') # Optional, used by --publish
openai_api_key = os.getenv('OPENAI_API_KEY') # OpenAI API key, used by --narrate, optional
narration_file = os.getenv('NARRATION_FILE') # Optional, used by --narrate

try:
    wind_power_max_capacity = int(os.getenv('WIND_POWER_MAX_CAPACITY'))
except TypeError:
    wind_power_max_capacity = "WIND_POWER_MAX_CAPACITY not set or not a number in environment"

# Arguments
parser = argparse.ArgumentParser()
parser.add_argument('--dump', action='store_true', help='Dump the SQLite database to CSV format')
parser.add_argument('--plot', action='store_true', help='Plot all predictions and actual prices to a PNG file in the data folder')
parser.add_argument('--foreca', action='store_true', help='Update the Foreca wind power prediction file')
parser.add_argument('--predict', action='store_true', help='Generate price predictions from now onwards')
parser.add_argument('--add-history', action='store_true', help='Add all missing predictions to the database post-hoc; use with --predict')
# TODO parser.add_argument('--re-write', action='store_true', help='Overwrite all past predictions based on the current data in the database; use with --predict')
parser.add_argument('--narrate', action='store_true', help='Narrate the predictions into text using an LLM')
parser.add_argument('--past-performance', action='store_true', help='Generate past performance stats for 30 days')
parser.add_argument('--commit', action='store_true', help='Commit the results to DB and deploy folder; use with --predict, --narrate, --past-performance')
parser.add_argument('--publish', action='store_true', help='Publish the deployed files to a GitHub repo')
parser.add_argument('--train', action='store_true', help='Train a model candidate from a CSV file')
# TODO parser.add_argument('--re-train', action='store_true', help='Re-train a model candidate with all the data from the database

args = parser.parse_args()

# Train a model with new data
if args.train:
    # This is a one-time operation to train the model with new data in a CSV file
    df = csv_to_df('data/train/nordpool-spot-with-wind-power-train.csv')
    print(df.head())
    
    # Update the database with the new data, if any
    # db_update(db_path, df)
    
    # This will produce a "candidate.joblib" file in the model folder
    # You can rename it to "rf_model.joblib" if you want to use it in the prediction process

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    train_model(df, output_path=f'model/candidate_{timestamp}.joblib')
    
    exit()

# Update the wind power prediction file
if args.foreca:  
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("Starting the process to fetch and parse the SVG data from Foreca...")
    
    foreca_wind_power_prediction(
        wind_power_prediction=wind_power_prediction,
        data_folder_path=data_folder_path
        )
    exit()

if args.dump: 
    dump_sqlite_db(data_folder_path)
    exit()

if args.plot:
    fig, ax = plt.subplots(figsize=(30, 20))  # Huge

    # Convert 'timestamp' to datetime for plotting
    df = db_query_all(db_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    ax.plot(df['timestamp'], df['Price [c/kWh]'], label='Actual Price', linewidth=0.33)
    ax.plot(df['timestamp'], df['PricePredict [c/kWh]'], label='Predicted Price', linewidth=0.33)

    # Format the x-axis to display dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.xticks(rotation=45)  # Rotate x-axis labels for better readability

    # Add labels and title
    ax.set_xlabel('Timestamp')
    ax.set_ylabel('Price [c/kWh]')
    ax.set_title('Predicted and Actual Prices')
    ax.legend()

    # Set y-axis to log scale and add gridlines
    ax.grid(True, which="both", ls="--", color='0.65')

    # Save the plot to a file (date).png
    output_file = os.path.join(data_folder_path, datetime.now().strftime("plot-%Y-%m-%d") + ".png")
    plt.savefig(output_file)

    exit()
    
if args.predict:
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("Running predictions...")

    # Load the wind power prediction and weather data
    with open(os.path.join(data_folder_path, wind_power_prediction), 'r') as file:
        wind_power_prediction_data = json.load(file)
    wind_power_df = pd.DataFrame(wind_power_prediction_data)
    
    # In the next DB refactoring, we should use MW and not MWh as a unit for wind power production...
    wind_power_df.rename(columns={'datetime': 'timestamp', 'wind_prediction_MWh': 'Wind Power [MWh]'}, inplace=True)
    wind_power_df['timestamp'] = pd.to_datetime(wind_power_df['timestamp'])
    # print("Wind Power Data Sample:\n", wind_power_df.head())

    weather_df = weather_get(pd.DataFrame({'timestamp': [datetime.now()]}), location, api_key)
    weather_df['timestamp'] = pd.to_datetime(weather_df['timestamp'])
    # print("Weather Data Sample:\n", weather_df.head())

    features_df = pd.merge(weather_df, wind_power_df, on='timestamp', how='inner')
    # print("Weather and wind power:\n", features_df.head())

    # We should only use this when we want to compute the predictions to the database post-hoc! It's a complicated merge.
    if args.add_history:
        history_df = db_query_all(db_path)
        history_df['timestamp'] = pd.to_datetime(history_df['timestamp']).dt.tz_localize("UTC")
        # print("History Sample:\n", history_df.sample(50))
        features_df = pd.merge(features_df, history_df, on='timestamp', how='right')

        features_df['Wind Power [MWh]'] = features_df['Wind Power [MWh]_y']
        features_df = features_df.drop(['Wind Power [MWh]_x', 'Wind Power [MWh]_y'], axis=1)

        features_df['Temp [°C]'] = features_df['Temp [°C]_y']
        features_df = features_df.drop(['Temp [°C]_x', 'Temp [°C]_y'], axis=1)
       
        features_df['Wind [m/s]'] = features_df['Wind [m/s]_y']
        features_df = features_df.drop(['Wind [m/s]_x', 'Wind [m/s]_y'], axis=1)
       
        required_columns = ['Temp [°C]', 'Wind [m/s]', 'Wind Power [MWh]', 'Wind Power Capacity [MWh]']
        features_df = features_df.dropna(subset=required_columns)
        
        for col in features_df.columns:
            features_df[col] = pd.to_numeric(features_df[col], errors='coerce')
        
        features_df['timestamp'] = pd.to_datetime(features_df['timestamp'])
        # print("Merged:\n", features_df.sample(50))

    # Fill in the 'hour', 'day_of_week', and 'month' columns for the model
    features_df['timestamp'] = pd.to_datetime(features_df['timestamp'])
    features_df['day_of_week'] = features_df['timestamp'].dt.dayofweek + 1
    features_df['hour'] = features_df['timestamp'].dt.hour
    features_df['month'] = features_df['timestamp'].dt.month

    # Check if 'Wind Power Capacity [MWh]' column exists in features_df, create it filled with NaN if not
    if 'Wind Power Capacity [MWh]' not in features_df.columns:
        features_df['Wind Power Capacity [MWh]'] = np.nan

    # Add or update the wind power capacity for the model only where it's missing
    features_df['Wind Power Capacity [MWh]'] = features_df['Wind Power Capacity [MWh]'].fillna(wind_power_max_capacity)
      
    # Load and apply the Random Forest model for predictions
    rf_model = joblib.load(rf_model_path)
    price_df = rf_model.predict(features_df[['Temp [°C]', 'Wind [m/s]', 'Wind Power [MWh]', 'Wind Power Capacity [MWh]', 'hour', 'day_of_week', 'month']])
    features_df['PricePredict [c/kWh]'] = price_df
    # print("Predictions:\n", features_df)
    
    # Add spot prices to the DataFrame, to the degree available
    spot_df = add_spot_prices_to_df(features_df)

    # We drop these columns before commit/display, as we can later compute them from the timestamp
    spot_df = spot_df.drop(columns=['day_of_week', 'hour', 'month'])

    # We are going to be verbose and ask before committing a lot of data to the database    
    if args.add_history:
        pd.set_option('display.max_columns', None)
        print("Spot Prices random sample of 20:\n", spot_df.sample(20))
        
        # Create a new DataFrame for calculating the metrics
        metrics_df = spot_df[['Price [c/kWh]', 'PricePredict [c/kWh]']].copy()
        
        # Drop the rows with NaN values in 'Price [c/kWh]' or 'PricePredict [c/kWh]'
        metrics_df = metrics_df.dropna(subset=['Price [c/kWh]', 'PricePredict [c/kWh]'])
        
        # Calculate the metrics
        y_true = metrics_df['Price [c/kWh]']
        y_pred = metrics_df['PricePredict [c/kWh]']
        
        mae = mean_absolute_error(y_true, y_pred)
        mse = mean_squared_error(y_true, y_pred)
        rmse = np.sqrt(mse)
        r2 = r2_score(y_true, y_pred)
        
        print("Mean Absolute Error:", mae, "c/kWh")
        print("Mean Squared Error:", mse, "c/kWh")
        print("Root Mean Squared Error:", rmse, "c/kWh")
        print("R-squared:", r2)
   
    # Update the database with the final data
    if args.commit:    
        if args.add_history:        
            # Ask if the user wants to add the predictions to the database
            if input("Do you want to add the predictions to the database? (y/n): ").lower() != "y":
                print("Aborting.")
                exit()          
        
        print("Will add/update", len(spot_df), "predictions to the database... ", end="")
        
        if db_update(db_path, spot_df):
            print("Done.")
    else:
        print(spot_df)
        print("Predictions not committed to the database.")

# Narrate can be used with the previous arguments
if args.narrate:
    tomorrow = datetime.now(pytz.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    # print("Narrating prediction for", tomorrow, "...")
    narration = narrate_prediction(tomorrow)

    if args.commit:
        # Create/update deploy/narration.md
        narration_path = os.path.join(deploy_folder_path, narration_file)
        with open(narration_path, 'w') as f:
            f.write(narration)
        print(narration)
        print(f"Narration saved to {narration_path}")
        
    else:
        print(narration)

# Past performance can be used with the previous arguments
if args.past_performance:
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("Calculating past performance for 30 days...")

    # Fetch the last 30 days of data from the database
    past_df = db_query_all(db_path)
    past_df['timestamp'] = pd.to_datetime(past_df['timestamp'])
    past_df = past_df[past_df['timestamp'] >= datetime.now() - timedelta(days=30)]
    
    # Drop empty or NaN rows
    past_df = past_df.dropna(subset=['Price [c/kWh]', 'PricePredict [c/kWh]'])

    # Calculate the metrics
    past_df = past_df.dropna(subset=['Price [c/kWh]', 'PricePredict [c/kWh]'])
    y_true = past_df['Price [c/kWh]']
    y_pred = past_df['PricePredict [c/kWh]']
    mae = mean_absolute_error(y_true, y_pred)
    mse = mean_squared_error(y_true, y_pred)
    rmse = np.sqrt(mse)
    r2 = r2_score(y_true, y_pred)

    print("Mean Absolute Error:", mae, "c/kWh")
    print("Mean Squared Error:", mse, "c/kWh")
    print("Root Mean Squared Error:", rmse, "c/kWh")
    print("R-squared:", r2)

    if args.commit:
        # Prepare data for Apex Charts
        past_performance_data = {
            "metrics": {
                "mae": mae,
                "mse": mse,
                "rmse": rmse,
                "r2": r2
            },
            "data": [
                {"name": "Actual Price", "data": []},
                {"name": "Predicted Price", "data": []}
            ]
        }

        # Convert timestamps to milliseconds since epoch and pair with values
        for _, row in past_df.iterrows():
            timestamp_ms = int(row['timestamp'].timestamp() * 1000)
            past_performance_data["data"][0]["data"].append([timestamp_ms, row['Price [c/kWh]']])
            past_performance_data["data"][1]["data"].append([timestamp_ms, row['PricePredict [c/kWh]']])

        # Save to JSON file
        past_performance_json_path = os.path.join(deploy_folder_path, past_performance_file)
        with open(past_performance_json_path, 'w') as f:
            json.dump(past_performance_data, f)

        print(f"Past performance data saved to {past_performance_json_path}")

# Publish can be used solo, or with --predict and --narrate
if args.publish:
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("Starting publishing...")
    
    publish_df = db_query_all(db_path)

    # Ensure 'timestamp' column is in datetime format
    publish_df['timestamp'] = pd.to_datetime(publish_df['timestamp'])

    # Filter out rows where 'timestamp' is earlier than now
    # The database timestamp is in UTC time, so no need to convert before filtering
    now = pd.to_datetime('now')
    publish_df = publish_df[publish_df['timestamp'] >= now]

    # Adjust timestamps as if in Helsinki time, accounting for DST
    # ... ACTUALLY, we should not do this, as Apex Charts will convert the timestamps to the user's local time
    # publish_df['timestamp'] = publish_df['timestamp'].apply(lambda x: x.tz_localize(pytz.utc).tz_convert('Europe/Helsinki').tz_localize(None))
   
    # Create a copy of the slice to avoid SettingWithCopyWarning
    hourly_predictions = publish_df[['timestamp', 'PricePredict [c/kWh]']].copy()

    # Now apply the conversion to UNIX timestamp for Apex Charts in Home Assistant
    hourly_predictions['timestamp'] = hourly_predictions['timestamp'].apply(
    lambda x: (x - pd.Timestamp("1970-01-01")) // pd.Timedelta('1ms')
    )

    # Create the list of lists for JSON output
    json_data_list = hourly_predictions.values.tolist()

    # Convert the hourly prediction data to JSON format
    json_data = json.dumps(json_data_list, ensure_ascii=False)

    # Save to JSON in the deploy folder
    json_path = os.path.join(deploy_folder_path, predictions_file)
    with open(json_path, 'w') as f:
        f.write(json_data)
    print(f"Hourly predictions saved to {json_path}")

    # Daily averages: group by day and calculate the mean
    # Normalize 'timestamp' to set the time to 00:00:00 for daily average grouping
    publish_df['timestamp'] = publish_df['timestamp'].dt.normalize()

    # Calculate the mean
    daily_averages = publish_df.groupby('timestamp')['PricePredict [c/kWh]'].mean().reset_index()

    # Convert 'timestamp' to the format required by Apex Charts (milliseconds since epoch)
    daily_averages['timestamp'] = daily_averages['timestamp'].apply(lambda x: (x - pd.Timestamp("1970-01-01")) // pd.Timedelta('1ms'))

    # Create the list of lists for JSON output of daily averages
    json_data_list = daily_averages[['timestamp', 'PricePredict [c/kWh]']].values.tolist()

    # Convert data to JSON format
    json_data = json.dumps(json_data_list, ensure_ascii=False)

    # Save averages to JSON in the deploy folder
    json_path = os.path.join(deploy_folder_path, averages_file)
    with open(json_path, 'w') as f:
        f.write(json_data)
    print(f"Daily averages saved to {json_path}")

    # Commit and push the updates to GitHub
    files_to_push = [predictions_file, averages_file, narration_file]

    try:
        if push_updates_to_github(repo_path, deploy_folder_path, files_to_push, commit_message):
            print("Data pushed to GitHub.")
    except Exception as e:
        print("Error occurred while pushing data to GitHub: ", str(e))

    print("Script execution completed.")
    exit()

if __name__ == "__main__":
    # If no arguments were given, print a message
    if not any(vars(args).values()):
        print("No arguments given. Use --help for more information.")