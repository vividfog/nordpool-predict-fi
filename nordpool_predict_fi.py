import requests
import pandas as pd
import joblib
import matplotlib.pyplot as plt
import pytz
import json
from datetime import datetime, timedelta
import git
import os
from dotenv import load_dotenv
import sqlite3
import argparse
from util.sql import db_update, db_query, db_test, db_query_all
from util.weather import weather_get
from util.weekdays import weekdays_get
from util.spot import add_spot_prices_to_df
from util.foreca import foreca_wind_power_prediction
from util.dump import dump_sqlite_db

load_dotenv('.env.local')  # take environment variables from .env.local

# Configuration and secrets
location = os.getenv('LOCATION') or "LOCATION not set in environment"
api_key = os.getenv('API_KEY') or "API_KEY not set in environment"
rf_model_path = os.getenv('RF_MODEL_PATH') or "RF_MODEL_PATH not set in environment"
lr_model_path = os.getenv('LR_MODEL_PATH') or "LR_MODEL_PATH not set in environment"
csv_file_path = os.getenv('CSV_FILE_PATH') or "CSV_FILE_PATH not set in environment"
gist_id = os.getenv('GIST_ID') or "GIST_ID not set in environment"
token = os.getenv('TOKEN') or "TOKEN not set in environment"
deploy_folder_path = os.getenv('DEPLOY_FOLDER_PATH') or "DEPLOY_FOLDER_PATH not set in environment"
data_folder_path = os.getenv('DATA_FOLDER_PATH') or "DATA_FOLDER_PATH not set in environment"
db_path = os.getenv('DB_PATH') or "DB_PATH not set in environment"
repo_path = os.getenv('REPO_PATH') or "REPO_PATH not set in environment"
predictions_file = os.getenv('PREDICTIONS_FILE') or "PREDICTIONS_FILE not set in environment"
averages_file = os.getenv('AVERAGES_FILE') or "AVERAGES_FILE not set in environment"
commit_message = os.getenv('COMMIT_MESSAGE') or "COMMIT_MESSAGE not set in environment"
wind_power_prediction = os.getenv('WIND_POWER_PREDICTION') or "WIND_POWER_PREDICTION not set in environment"
try:
    wind_power_max_capacity = int(os.getenv('WIND_POWER_MAX_CAPACITY'))
except TypeError:
    wind_power_max_capacity = "WIND_POWER_MAX_CAPACITY not set or not a number in environment"

# Argument parsing
parser = argparse.ArgumentParser()
parser.add_argument('--dump', action='store_true', help='Dump the SQLite database to CSV format')
parser.add_argument('--foreca', action='store_true', help='Update the Foreca wind power prediction file')
parser.add_argument('--predict', action='store_true', help='Run the full prediction process')
parser.add_argument('--commit', action='store_true', help='Commit to DB and push updates to GitHub, use with --predict')
parser.add_argument('--publish', action='store_true', help='Publish the predictions to the GitHub repo')
args = parser.parse_args()

# Predict prices for a data frame
def predict_prices(df, rf_model_path):
    rf_model = joblib.load(rf_model_path)
    # Ensure all features expected by the model are included
    features = df[['Temp [°C]', 'Wind [m/s]', 'Wind Power [MWh]', 'Wind Power Capacity [MWh]', 'hour', 'day_of_week', 'month']]
    initial_predictions = rf_model.predict(features)
    df['PricePredict [c/kWh]'] = initial_predictions
    return df

# Push updates to GitHub from the deployment repo
def push_updates_to_github(repo_path, files, commit_message):    
    try:
        repo = git.Repo(repo_path)
        
        for file in files:
            # Check if the file_path is relative, convert it to absolute
            absolute_file_path = os.path.join(repo_path, file) if not os.path.isabs(file) else file
            
            # Stage the file for commit
            repo.index.add([absolute_file_path])
        
        # Commit the changes
        repo.index.commit(commit_message)
        
        # Push the changes
        repo.remotes.origin.push()
        print("Updates pushed to GitHub.")
    except Exception as e:
        print(f"Error pushing updates to GitHub: {e}")

# Update the wind power prediction file
if args.foreca:  
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S:\nStarting the process to fetch and parse the SVG data from Foreca..."))
    
    foreca_wind_power_prediction(
        wind_power_prediction=wind_power_prediction,
        data_folder_path=data_folder_path
        )
    exit()

if args.dump: 
    dump_sqlite_db(data_folder_path)
    exit()
    
if args.predict:
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S:\nRunning predictions..."))

    # Load the wind power prediction and weather data
    with open(os.path.join(data_folder_path, wind_power_prediction), 'r') as file:
        wind_power_prediction_data = json.load(file)
    wind_power_df = pd.DataFrame(wind_power_prediction_data)
    wind_power_df.rename(columns={'datetime': 'timestamp', 'wind_prediction_MWh': 'Wind Power [MWh]'}, inplace=True)
    wind_power_df['timestamp'] = pd.to_datetime(wind_power_df['timestamp'])
    # print("Wind Power Data Sample:\n", wind_power_df.head())

    weather_df = weather_get(pd.DataFrame({'timestamp': [datetime.now()]}), location, api_key)
    weather_df['timestamp'] = pd.to_datetime(weather_df['timestamp'])
    # print("Weather Data Sample:\n", weather_df.head())

    features_df = pd.merge(weather_df, wind_power_df, on='timestamp', how='inner')
    # print("Weather and wind power:\n", features_df.head())

    # # We only use this when we want to compute the predictions to the database post-hoc! It's a complicated merge.
    # if args.add_predict_to_db:
    #     history_df = db_query_all(db_path)
    #     history_df['timestamp'] = pd.to_datetime(history_df['timestamp']).dt.tz_localize('UTC')
    #     print("History Sample:\n", history_df.head())
    #     features_df = pd.merge(features_df, history_df, on='timestamp', how='right')

    #     features_df['Wind Power [MWh]'] = features_df['Wind Power [MWh]_y']
    #     features_df = features_df.drop(['Wind Power [MWh]_x', 'Wind Power [MWh]_y'], axis=1)

    #     features_df['Temp [°C]'] = features_df['Temp [°C]_y']
    #     features_df = features_df.drop(['Temp [°C]_x', 'Temp [°C]_y'], axis=1)
        
    #     features_df['Wind [m/s]'] = features_df['Wind [m/s]_y']
    #     features_df = features_df.drop(['Wind [m/s]_x', 'Wind [m/s]_y'], axis=1)
        
    #     required_columns = ['Temp [°C]', 'Wind [m/s]', 'Wind Power [MWh]', 'Wind Power Capacity [MWh]', 'hour', 'day_of_week', 'month']
    #     features_df = features_df.dropna(subset=required_columns)
        
    #     for col in features_df.columns:
    #         features_df[col] = pd.to_numeric(features_df[col], errors='coerce')
        
    #     # print("Merged:\n", features_df)

    # Fill in the 'hour', 'day_of_week', and 'month' columns for the model
    features_df = weekdays_get(features_df)
    # print("With weekdays:\n", features_df.head())

    # Add the wind power capacity for the model
    features_df['Wind Power Capacity [MWh]'] = wind_power_max_capacity
      
    # Load and apply the Random Forest model for predictions
    rf_model = joblib.load(rf_model_path)
    price_df = rf_model.predict(features_df[['Temp [°C]', 'Wind [m/s]', 'Wind Power [MWh]', 'Wind Power Capacity [MWh]', 'hour', 'day_of_week', 'month']])
    features_df['PricePredict [c/kWh]'] = price_df
    # print("Predictions:\n", features_df)
    
    # Add spot prices to the DataFrame, to the degree available
    spot_df = add_spot_prices_to_df(features_df)
    # print("Spot Prices:\n", spot_df)
    
    # Update the database with the final data
    if args.commit:
        print("Will add/update", len(spot_df), "predictions to the database... ", end="")
        if db_update(db_path, spot_df):
            print("Done.")
    
    exit()

if args.publish:
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S:\nStarting publishing..."))
    
    publish_df = db_query_all(db_path)

    # Ensure 'timestamp' column is in datetime format
    publish_df['timestamp'] = pd.to_datetime(publish_df['timestamp'])

    # Filter out rows where 'timestamp' is earlier than the current datetime
    now = pd.to_datetime('now')
    publish_df = publish_df[publish_df['timestamp'] >= now]

    # Adjust timestamps as if in Helsinki time, accounting for DST
    publish_df['timestamp'] = publish_df['timestamp'].apply(lambda x: x.tz_localize(pytz.utc).tz_convert('Europe/Helsinki').tz_localize(None))
   
    # Create a copy of the slice to avoid SettingWithCopyWarning
    hourly_predictions = publish_df[['timestamp', 'PricePredict [c/kWh]']].copy()

    # Now apply the conversion safely
    hourly_predictions['timestamp'] = hourly_predictions['timestamp'].apply(
    lambda x: (x - pd.Timestamp("1970-01-01")) // pd.Timedelta('1ms')
    )

    # Create the list of lists for JSON output
    json_data_list = hourly_predictions.values.tolist()

    # Convert data to JSON format
    json_data = json.dumps(json_data_list, ensure_ascii=False)

    # Save to JSON in the deploy folder
    json_path = os.path.join(deploy_folder_path, "prediction.json")
    with open(json_path, 'w') as f:
        f.write(json_data)
    print(f"Hourly predictions saved to {json_path}")

    # Normalize 'timestamp' to remove time for daily averages
    publish_df['timestamp'] = publish_df['timestamp'].dt.normalize()

    # Calculate daily averages
    daily_averages = publish_df.groupby('timestamp')['PricePredict [c/kWh]'].mean().reset_index()

    # Convert 'timestamp' to the format required by Apex Charts (milliseconds since epoch)
    daily_averages['timestamp'] = daily_averages['timestamp'].apply(lambda x: (x - pd.Timestamp("1970-01-01")) // pd.Timedelta('1ms'))

    # Create the list of lists for JSON output
    json_data_list = daily_averages[['timestamp', 'PricePredict [c/kWh]']].values.tolist()

    # Convert data to JSON format
    json_data = json.dumps(json_data_list, ensure_ascii=False)

    # Save to JSON in the deploy folder
    json_path = os.path.join(deploy_folder_path, "averages.json")
    with open(json_path, 'w') as f:
        f.write(json_data)
    print(f"Daily averages saved to {json_path}")

    # Commit and push the updates to GitHub
    files_to_push = [predictions_file, averages_file]

    try:
        push_updates_to_github(repo_path, files_to_push, commit_message)
        print("Data pushed to GitHub.")
    except Exception as e:
        print("Error occurred while pushing data to GitHub: ", str(e))

    print("Script execution completed.")
    exit()

if __name__ == "__main__":
    print("No arguments given. Use --help for more information.")