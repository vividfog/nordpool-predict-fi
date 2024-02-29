import os
import json
import pytz
import joblib
import sqlite3
import requests
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from util.eval import eval
from dotenv import load_dotenv
from util.train import train_model
from util.dump import dump_sqlite_db
from util.sahkotin import update_spot
from util.fingrid import update_nuclear
from datetime import datetime, timedelta
from util.llm import narrate_prediction
from util.github import push_updates_to_github
from util.sql import db_update, db_query, db_query_all
from util.fmi import update_wind_speed, update_temperature
from util.models import write_model_stats, stats_json, stats, list_models
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
print("Nordpool Predict FI")

load_dotenv('.env.local')  # take environment variables from .env.local

# Configuration and secrets
rf_model_path = os.getenv('RF_MODEL_PATH') or "RF_MODEL_PATH not set in environment"
data_folder_path = os.getenv('DATA_FOLDER_PATH') or "DATA_FOLDER_PATH not set in environment"
db_path = os.getenv('DB_PATH') or "DB_PATH not set in environment"
repo_path = os.getenv('REPO_PATH') or "REPO_PATH not set in environment"
predictions_file = os.getenv('PREDICTIONS_FILE') or "PREDICTIONS_FILE not set in environment"
averages_file = os.getenv('AVERAGES_FILE') or "AVERAGES_FILE not set in environment"
past_performance_file = os.getenv('PAST_PERFORMANCE_FILE') or "PAST_PERFORMANCE_FILE not set in environment"
wind_power_prediction = os.getenv('WIND_POWER_PREDICTION') or "WIND_POWER_PREDICTION not set in environment"
fingrid_api_key = os.getenv('FINGRID_API_KEY') or "FINGRID_API_KEY not set in environment"
token = os.getenv('TOKEN') # GitHub token, used by --publish, optional
commit_message = os.getenv('COMMIT_MESSAGE') # Optional, used by --publish
deploy_folder_path = os.getenv('DEPLOY_FOLDER_PATH') # Optional, used by --publish
openai_api_key = os.getenv('OPENAI_API_KEY') # OpenAI API key, used by --narrate, optional
narration_file = os.getenv('NARRATION_FILE') # Optional, used by --narrate
fmisid_ws = ['ws_' + id for id in os.getenv('FMISID_WS', '').split(',')] if os.getenv('FMISID_WS') else ["FMISID_WS not set in environment"]
fmisid_t = ['t_' + id for id in os.getenv('FMISID_T', '').split(',')] if os.getenv('FMISID_T') else ["FMISID_T not set in environment"]

try:
    wind_power_max_capacity = int(os.getenv('WIND_POWER_MAX_CAPACITY'))
except TypeError:
    wind_power_max_capacity = "WIND_POWER_MAX_CAPACITY not set or not a number in environment"

# Arguments
parser = argparse.ArgumentParser()
parser.add_argument('--dump', action='store_true', help='Dump the SQLite database to CSV format')
parser.add_argument('--plot', action='store_true', help='Plot all predictions and actual prices to a PNG file in the data folder')
parser.add_argument('--predict', action='store_true', help='Generate price predictions from now onwards')
parser.add_argument('--add-history', action='store_true', help='Add all missing predictions to the database post-hoc; use with --predict')
parser.add_argument('--narrate', action='store_true', help='Narrate the predictions into text using an LLM')
parser.add_argument('--past-performance', action='store_true', help='Generate past performance stats for 30 days')
parser.add_argument('--commit', action='store_true', help='Commit the results to DB and deploy folder; use with --predict, --narrate, --past-performance')
parser.add_argument('--publish', action='store_true', help='Publish the deployed files to a GitHub repo')
parser.add_argument('--train', action='store_true', help='Train a new model candidate using the data in the database')
parser.add_argument('--eval', action='store_true', help='Show evaluation metrics for the current database')
parser.add_argument('--training-stats', action='store_true', help='Show training stats for candidate models in the database as a CSV')

args = parser.parse_args()

# Train a model with new data
if args.train:
    
    print("FMI Weather Stations for Wind:", fmisid_ws)
    print("FMI Weather Stations for Temperature:", fmisid_t)
    
    # Continuous training: Get all the data from the database
    df = db_query_all(db_path)

    # Ensure 'timestamp' column is in datetime format
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # If WindPowerCapacityMW is null, fill it with the last known value
    df['WindPowerCapacityMW'] = df['WindPowerCapacityMW'].fillna(method='ffill')
    
    # If NuclearPowerMW is null, fill it with the last known value
    df['NuclearPowerMW'] = df['NuclearPowerMW'].fillna(method='ffill')
    
    # Define other required columns
    required_columns = ['timestamp', 'NuclearPowerMW', 'Price_cpkWh'] + fmisid_ws + fmisid_t

    # Drop rows with missing values in the cleaned required columns list
    df = df.dropna(subset=required_columns)
      
    # This will produce a "candidate.joblib" file in the model folder
    # You can rename it to "rf_model.joblib" if you want to use it in the prediction process
    
    # Re-training of a model, and save it to the model folder
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    model_path = f'model/candidate_{timestamp}.joblib'

    # Train a model and fetch the stats for it
    mae, mse, r2, samples_mae, samples_mse, samples_r2 = train_model(df, output_path=model_path, fmisid_ws=fmisid_ws, fmisid_t=fmisid_t)
    
    print(f"Model trained with MAE: {mae}, MSE: {mse}, r2: {r2}, samples MAE: {samples_mae}, samples MSE: {samples_mse}, samples R2: {samples_r2}, saved to {model_path}")
    
    # Add the training stats to the database
    write_model_stats(timestamp, mae, mse, r2, samples_mae, samples_mse, samples_r2, model_path)
    print("Model stats added to the database: ", stats(timestamp))
    
    exit()

# Show evals based on the current database
if args.eval:
    print(eval(db_path))
    exit()

# Show training stats for all models in the database as CSV
if args.training_stats:
    print("Training stats for all models in the database:")

    model_timestamps = list_models()
    # Sort the timestamps in ascending order
    model_timestamps.sort()
    print("Model Timestamps:", model_timestamps)

    # Define the header
    header = ['training_id', 'training_timestamp', 'MAE', 'MSE', 'R2', 'samples_MAE', 'samples_MSE', 'samples_R2', 'model_path']

    # Print the header, joined by commas
    print(','.join(header))

    # Iterate through each model and print its stats
    for model in model_timestamps:
        model_stats = stats(model)

        # Create a list of the model's stats, converted to strings
        row = [str(model_stats.get(field, '')) for field in header]

        # Print the row, joined by commas
        print(','.join(row))
        
    exit()

if args.plot:
    fig, ax = plt.subplots(figsize=(15, 10))  # Huge

    # Convert 'timestamp' to datetime for plotting
    df = db_query_all(db_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Drop rows with missing values
    df = df.dropna()

    ax.plot(df['timestamp'], df['Price_cpkWh'], label='Actual Price', linewidth=0.33)
    ax.plot(df['timestamp'], df['PricePredict_cpkWh'], label='Predicted Price', linewidth=0.33)

    # Format the x-axis to display dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.xticks(rotation=45)  # Rotate x-axis labels for better readability

    # Add labels and title
    ax.set_xlabel('Timestamp')
    ax.set_ylabel('Price_cpkWh')
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

    # Fetch all the data, as we have more memory than time and it's not that large
    df = db_query_all(db_path)
    
    # Ensure 'timestamp' column is in datetime format
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
        
    # We operate from this moment back and forward
    now = pd.Timestamp.utcnow()

    # Round up to the next full hour if not already on a full hour
    if now.minute > 0 or now.second > 0 or now.microsecond > 0:
        now = now.ceil('h')  # Rounds up to the nearest hour
        
    # Drop rows that are older than a week, unless we're rewriting historical predictions after a model update
    # Not dropping will backfill the prediction column, which what we want for retrospective predictions
    if not args.add_history:
        # Use the now for filtering
        df = df[df.index > now - pd.Timedelta(days=7)]

    # Forward-fill the timestamp column for 5*24 = 120 hours ahead
    start_time = now + pd.Timedelta(hours=1)  # Start from the next hour
    end_time = now + pd.Timedelta(hours=120)  # 5 days ahead
    new_index = pd.date_range(start=start_time, end=end_time, freq='h')
    df = df.reindex(df.index.union(new_index))

    # Reset the index to turn 'timestamp' back into a column before the update functions
    df.reset_index(inplace=True)
    df.rename(columns={'index': 'Timestamp'}, inplace=True)

    # Get the latest FMI wind speed values for the data frame, past and future
    # NOTE: To save on API calls, we don't fill in weather history beyond 7 days even if asked
    df = update_wind_speed(df)
           
    # Get the latest FMI temperature values for the data frame, past and future
    # NOTE: To save on API calls, we don't fill in weather history beyond 7 days even if asked
    df = update_temperature(df)
       
    # Get the latest nuclear power data for the data frame, and infer the future
    # NOTE: To save on API calls, we don't fill in weather history beyond 7 days even if asked
    df = update_nuclear(df, fingrid_api_key=fingrid_api_key)
        
    # Get the latest spot prices for the data frame, past and future if any
    # NOTE: To save on API calls, we don't fill in weather history beyond 7 days even if asked
    df = update_spot(df)
    
    # TODO: Decide if including wind power capacity is necessary; it seems to worsen the MSE and R2
    # For now we'll drop it
    df = df.drop(columns=['WindPowerCapacityMW'])

    # print("Filled-in dataframe before predict:\n", df)
    print("Days of data coverage (should be 7 back, 5 forward for now): ", int(len(df)/24))

    # DEBUG: Save a copy of the df to a CSV file for inspection
    # df.to_csv(os.path.join(data_folder_path + "/private", "debug_df.csv"), index=False)

    # Fill in the 'hour', 'day_of_week', and 'month' columns for the model
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    df['day_of_week'] = df['Timestamp'].dt.dayofweek + 1
    df['hour'] = df['Timestamp'].dt.hour
    df['month'] = df['Timestamp'].dt.month
         
    # Load and apply the Random Forest model for predictions
    rf_model = joblib.load(rf_model_path)
    price_df = rf_model.predict(df[['day_of_week', 'hour', 'month', 'NuclearPowerMW'] + fmisid_ws + fmisid_t])
    df['PricePredict_cpkWh'] = price_df
    
    # We drop these columns before commit/display, as we can later compute them from the timestamp
    df = df.drop(columns=['day_of_week', 'hour', 'month'])

    # We are going to be verbose and ask before committing a lot of data to the database    
    if args.add_history:
        pd.set_option('display.max_columns', None)
        print("Spot Prices random sample of 20:\n", df.sample(20))
        
        # Create a new DataFrame for calculating the metrics
        metrics_df = df[['Price_cpkWh', 'PricePredict_cpkWh']].copy()
        
        # Drop the rows with NaN values in 'Price_cpkWh' or 'PricePredict_cpkWh'
        metrics_df = metrics_df.dropna(subset=['Price_cpkWh', 'PricePredict_cpkWh'])
        
        # Calculate the metrics
        y_true = metrics_df['Price_cpkWh']
        y_pred = metrics_df['PricePredict_cpkWh']
        
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
        
        print("Will add/update", len(df), "predictions to the database... ", end="")
        
        if db_update(db_path, df):
            print("Done.")
    else:
        print(df)
        print("Predictions not committed to the database.")
        
    # DEBUG: save to CSV for inspection
    # df.to_csv(os.path.join(data_folder_path + "/private", "predictions_df.csv"), index=False)    
    # exit()

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
    # print("Calculating past performance for X days...")

    past_df = db_query_all(db_path)
    past_df = past_df.sort_values(by='timestamp')

    # print("Fetched Data:", past_df)  # Debug print to see initial data

    past_df['timestamp'] = pd.to_datetime(past_df['timestamp'])
    before_filtering_length = len(past_df)

    # Filter out rows where 'timestamp' is earlier than 90 days ago or later than now
    now = datetime.now(pytz.utc)
    past_df = past_df[(past_df['timestamp'] >= now - timedelta(days=90)) & (past_df['timestamp'] <= now)]

    # print("Data after filtering:", past_df)

    # print(f"Data length before filtering: {before_filtering_length}, after filtering: {len(past_df)}")

    nan_rows = past_df[past_df['Price_cpkWh'].isna() | past_df['PricePredict_cpkWh'].isna()]
    # print("Rows with NaN values before dropping:")
    # print(nan_rows)

    # Drop empty or NaN rows
    past_df = past_df.dropna(subset=['Price_cpkWh', 'PricePredict_cpkWh'])

    # print("Data after dropping NaNs:", past_df)
    # print(f"Data length after dropping NaNs: {len(past_df)}")

    # Calculate the metrics
    past_df = past_df.dropna(subset=['Price_cpkWh', 'PricePredict_cpkWh'])
    y_true = past_df['Price_cpkWh']
    y_pred = past_df['PricePredict_cpkWh']
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
            "data": [
                {"name": "Actual Price", "data": []},
                {"name": "Predicted Price", "data": []}
            ],
            "metrics": {
                "mae": mae,
                "mse": mse,
                "rmse": rmse,
                "r2": r2
            }
        }

        # Convert timestamps to milliseconds since epoch and pair with values
        for _, row in past_df.iterrows():
            timestamp_ms = int(row['timestamp'].timestamp() * 1000)
            past_performance_data["data"][0]["data"].append([timestamp_ms, row['Price_cpkWh']])
            past_performance_data["data"][1]["data"].append([timestamp_ms, row['PricePredict_cpkWh']])

        # print("Final Actual Price Data Points:", past_performance_data["data"][0]["data"][:5])  # Debug print
        # print("Final Predicted Price Data Points:", past_performance_data["data"][1]["data"][:5])  # Debug print
        
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

    # Helsinki time zone setup
    helsinki_tz = pytz.timezone('Europe/Helsinki')

    # Get the current time in Helsinki time zone and adjust to the start of yesterday
    start_of_yesterday_helsinki = datetime.now(helsinki_tz).replace(hour=0, minute=0, second=0, microsecond=0) - pd.Timedelta(days=1)

    # Convert the start of yesterday in Helsinki back to UTC
    start_of_yesterday_utc = start_of_yesterday_helsinki.astimezone(pytz.utc)

    # Ensure 'timestamp' column is in datetime format and UTC for comparison
    publish_df['timestamp'] = pd.to_datetime(publish_df['timestamp']).dt.tz_localize(None).dt.tz_localize(pytz.utc)

    # Filter out rows where 'timestamp' is earlier than the start of yesterday in Helsinki, adjusted to UTC
    publish_df = publish_df[publish_df['timestamp'] >= start_of_yesterday_utc]

    hourly_predictions = publish_df[['timestamp', 'PricePredict_cpkWh']].copy()
    hourly_predictions['timestamp'] = hourly_predictions['timestamp'].dt.tz_localize(None) if hourly_predictions['timestamp'].dt.tz is not None else hourly_predictions['timestamp']
    hourly_predictions['timestamp'] = hourly_predictions['timestamp'].apply(
        lambda x: (x - pd.Timestamp("1970-01-01")) // pd.Timedelta('1ms')
    )

    json_data_list = hourly_predictions.values.tolist()
    json_data = json.dumps(json_data_list, ensure_ascii=False)
    json_path = os.path.join(deploy_folder_path, predictions_file)
    with open(json_path, 'w') as f:
        f.write(json_data)
    print(f"Hourly predictions saved to {json_path}")

    # Normalize 'timestamp' to set the time to 00:00:00 for daily average grouping
    publish_df['timestamp'] = publish_df['timestamp'].dt.tz_localize(None) if publish_df['timestamp'].dt.tz is not None else publish_df['timestamp']
    publish_df['timestamp'] = publish_df['timestamp'].dt.normalize()

    daily_averages = publish_df.groupby('timestamp')['PricePredict_cpkWh'].mean().reset_index()

    # Before applying lambda, ensure 'timestamp' is timezone-naive for consistency
    daily_averages['timestamp'] = daily_averages['timestamp'].apply(
        lambda x: (x - pd.Timestamp("1970-01-01")) // pd.Timedelta('1ms')
    )

    json_data_list = daily_averages[['timestamp', 'PricePredict_cpkWh']].values.tolist()
    json_data = json.dumps(json_data_list, ensure_ascii=False)
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