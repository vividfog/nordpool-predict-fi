import os
import json
import pytz
import joblib
import argparse
import numpy as np
import pandas as pd
from rich import print
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from util.eval import eval
from dotenv import load_dotenv
from util.train import train_model
from util.dump import dump_sqlite_db
from util.sahkotin import update_spot
from util.fingrid import update_nuclear
from util.imports import update_import_capacity
from util.llm import narrate_prediction
from datetime import datetime, timedelta
from util.entso_e import entso_e_nuclear
from util.sql import db_update, db_query_all
from util.dataframes import update_df_from_df
from util.fmi import update_wind_speed, update_temperature
from util.models import write_model_stats, stats, list_models
from util.eval import create_prediction_snapshot, rotate_snapshots
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# Fetch environment variables from .env.local (create yours from .env.template)
try:
    load_dotenv('.env.local')
except Exception as e:
    print(f"Error loading .env.local file. Did you create one? See README.md.")

# Fetch mandatory environment variables and raise exceptions if they are missing
def get_mandatory_env_variable(name):
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"Mandatory variable {name} not set in environment")
    return value

# Configuration and secrets, mandatory:
try:
    rf_model_path = get_mandatory_env_variable('RF_MODEL_PATH')
    data_folder_path = get_mandatory_env_variable('DATA_FOLDER_PATH')
    deploy_folder_path = get_mandatory_env_variable('DEPLOY_FOLDER_PATH')
    db_path = get_mandatory_env_variable('DB_PATH')
    predictions_file = get_mandatory_env_variable('PREDICTIONS_FILE')
    averages_file = get_mandatory_env_variable('AVERAGES_FILE')
    fingrid_api_key = get_mandatory_env_variable('FINGRID_API_KEY')
    entso_e_api_key = get_mandatory_env_variable('ENTSO_E_API_KEY')
    fmisid_ws_env = get_mandatory_env_variable('FMISID_WS')
    fmisid_t_env = get_mandatory_env_variable('FMISID_T')
    fmisid_ws = ['ws_' + id for id in fmisid_ws_env.split(',')]
    fmisid_t = ['t_' + id for id in fmisid_t_env.split(',')]

except ValueError as e:
    print(f"Error: {e}")
    exit(1)

# Optional env variables for --narrate:
openai_api_key = os.getenv('OPENAI_API_KEY') # OpenAI API key, used by --narrate
narration_file = os.getenv('NARRATION_FILE') # used by --narrate

# Command line arguments
parser = argparse.ArgumentParser()
parser.add_argument('--train', action='store_true', help='Train a new model candidate using the data in the database')
parser.add_argument('--eval', action='store_true', help='Show evaluation metrics for the current database')
parser.add_argument('--training-stats', action='store_true', help='Show training stats for candidate models in the database as a CSV')
parser.add_argument('--dump', action='store_true', help='Dump the SQLite database to CSV format')
parser.add_argument('--plot', action='store_true', help='Plot all predictions and actual prices to a PNG file in the data folder')
parser.add_argument('--predict', action='store_true', help='Generate price predictions from now onwards')
parser.add_argument('--add-history', action='store_true', help='Add all missing predictions to the database post-hoc; use with --predict')
parser.add_argument('--narrate', action='store_true', help='Narrate the predictions into text using an LLM')
parser.add_argument('--commit', action='store_true', help='Commit the results to DB and deploy folder; use with --predict, --narrate')
parser.add_argument('--deploy', action='store_true', help='Deploy the output files to the deploy folder')

args = parser.parse_args()

# Configure pandas to display all rows
pd.set_option('display.max_rows', None)

# Start with a timestamp intro to STDOUT, but not if we're here to dump the database as CSV
if not args.dump:
    print(datetime.now().strftime("[%Y-%m-%d %H:%M:%S]"), "Nordpool Predict FI")

# --train: Train a model with new data and make it available for the rest of the script
rf_trained = None

if args.train:
    
    print("Training a new model candidate using the data in the database...")
    print("* FMI Weather Stations for Wind:", fmisid_ws)
    print("* FMI Weather Stations for Temperature:", fmisid_t)
    
    # Continuous training: Get all the data from the database
    df = db_query_all(db_path)

    # Ensure 'timestamp' column is in datetime format
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # If WindPowerCapacityMW is null, fill it with the last known value
    df['WindPowerCapacityMW'] = df['WindPowerCapacityMW'].fillna(method='ffill')
    
    # If NuclearPowerMW is null, fill it with the last known value
    df['NuclearPowerMW'] = df['NuclearPowerMW'].fillna(method='ffill')

    # If ImportCapacityMW is null, fill it with the last known value
    df['ImportCapacityMW'] = df['ImportCapacityMW'].fillna(method='ffill')
    
    # Define other required columns
    required_columns = ['timestamp', 'NuclearPowerMW', 'ImportCapacityMW', 'Price_cpkWh'] + fmisid_ws + fmisid_t

    # Drop rows with missing values in the cleaned required columns list
    df = df.dropna(subset=required_columns)
      
    # This will produce a "candidate.joblib" file in the model folder
    # You can rename it to "rf_model.joblib" if you want to use it in the prediction process
    
    # Re-training of a model, and save it to the model folder
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    model_path = f'model/candidate_{timestamp}.joblib'

    # Train a model and fetch the stats for it
    mae, mse, r2, samples_mae, samples_mse, samples_r2, rf_trained = train_model(df, fmisid_ws=fmisid_ws, fmisid_t=fmisid_t)
    
    print(f"→ Model trained:\n  MAE (vs test set): {mae}\n  MSE (vs test set): {mse}\n  R² (vs test set): {r2}\n  MAE (vs 10x500 randoms): {samples_mae}\n  MSE (vs 10x500 randoms): {samples_mse}\n  R² (vs 10x500 randoms): {samples_r2}")

    # If we're moving towards --predict, we're not saving, it's continuous training then
    if args.commit and not args.predict:
        joblib.dump(rf_trained, model_path)
        print(f"→ Model saved to {model_path}")

        # Add the training stats to the database
        write_model_stats(timestamp, mae, mse, r2, samples_mae, samples_mse, samples_r2, model_path)
        print("→ Model stats added to the database.")
        print("→ Training done.")
    else:
        print("→ Model NOT saved to the database but remains available in memory for --prediction.")
        print("→ Training done.")

# --eval: Show evals based on the current database
if args.eval:
    print(eval(db_path))

# --training-stats: Show training stats for all models in the database as CSV
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

# --dump: Dump the SQLite database as CSV to STDOUT
if args.dump: 
    dump_sqlite_db(data_folder_path)
    exit()

# --plot: Plot all predictions and actual prices to a PNG file in the data folder
if args.plot:
    fig, ax = plt.subplots(figsize=(12, 8))  # Huge

    # Convert 'timestamp' to datetime for plotting
    df = db_query_all(db_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Drop rows with missing values
    df = df.dropna()

    ax.plot(df['timestamp'], df['Price_cpkWh'], label='Nordpool', linewidth=0.33)
    ax.plot(df['timestamp'], df['PricePredict_cpkWh'], label='Predicted', linewidth=0.33)

    # Format the x-axis to display dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.xticks(rotation=45)  # Rotate x-axis labels for better readability

    # Add labels and title
    ax.set_xlabel('Timestamp')
    ax.set_ylabel('Price_cpkWh')
    ax.set_title('Nordpool vs predicted prices')
    ax.legend()

    # Set y-axis to log scale and add gridlines
    ax.grid(True, which="both", ls="--", color='0.65')

    # Save the plot to a file (date).png
    output_file = os.path.join(data_folder_path, datetime.now().strftime("plot-%Y-%m-%d") + ".png")
    plt.savefig(output_file)
    print(f"Plot saved to {output_file}")

    exit()

# --predict: Use the model to predict future prices
if args.predict:
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
        
    # Drop rows that are older than a week, unless we intend to do a retrospective prediction update after a model update
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
    # NOTE: To save on API calls, this won't backfill history beyond 7 days even if asked
    df = update_wind_speed(df)
           
    # Get the latest FMI temperature values for the data frame, past and future
    # NOTE: To save on API calls, this won't backfill history beyond 7 days even if asked
    df = update_temperature(df)
       
    # Get the latest nuclear power data for the data frame, and infer the future from last known value
    # NOTE: To save on API calls, this won't backfill history beyond 7 days even if asked
    df = update_nuclear(df, fingrid_api_key=fingrid_api_key)
    
    # Print the head of the DataFrame after updating nuclear power
    # print("→ DataFrame after updating nuclear power:")
    # print(df.head())
    
    # Get the latest import capacity data for the data frame, and infer the future from last known value
    # NOTE: To save on API calls, this won't backfill history beyond 7 days even if asked
    df = update_import_capacity(df, fingrid_api_key=fingrid_api_key)

    # Print the head of the DataFrame after updating import capacity
    # print("→ DataFrame after updating import capacity:")
    # print(df.head())
    
    # BUG: Entso-E data appears to show OL3 downtime for entire rest of 2024, which can't be true; need to investigate; dropping for now
    # Fetch future nuclear downtime information from ENTSO-E unavailability data, h/t github:@pkautio
    # df_entso_e = entso_e_nuclear(entso_e_api_key)
    
    # Refresh the previously inferred nuclear power numbers with the ENTSO-E data
    # df = update_df_from_df(df, df_entso_e)
    
    # Get the latest spot prices for the data frame, past and future if any
    # NOTE: To save on API calls, this won't backfill history beyond 7 days even if asked
    df = update_spot(df)

    # Print the head of the DataFrame after updating spot prices
    # print("→ DataFrame after updating spot prices:")
    # print(df.head())
    
    # TODO: Decide if including wind power capacity is necessary; it seems to worsen the MSE and R2
    # For now we'll drop it
    df = df.drop(columns=['WindPowerCapacityMW'])

    # print("Filled-in dataframe before predict:\n", df)
    print("→ Days of data coverage (should be 7 back, 5 forward for now): ", int(len(df)/24))

    # DEBUG: Save a copy of the df to a CSV file for inspection
    # df.to_csv(os.path.join(data_folder_path + "/private", "debug_df.csv"), index=False)

    # Fill in the 'hour', 'day_of_week', and 'month' columns for the model
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    df['day_of_week'] = df['Timestamp'].dt.dayofweek + 1
    df['hour'] = df['Timestamp'].dt.hour
    df['month'] = df['Timestamp'].dt.month

    prediction_features = ['day_of_week', 'hour', 'NuclearPowerMW', 'ImportCapacityMW'] + fmisid_ws + fmisid_t

    # Print feature names used during prediction
    # print("→ Feature names used during prediction:")
    # print(prediction_features)

    # Print DataFrame columns before prediction
    # print("→ DataFrame columns before prediction:")
    # print(df.columns.tolist())

    # Print the head of the DataFrame before prediction
    # print("→ DataFrame before prediction:")
    # print(df.head())

    # Check for missing values in the prediction features
    # print("→ Checking for missing values in prediction features:")
    # print(df[prediction_features].isnull().sum())
         
    # Use (if coming from --train) or load and apply a Random Forest model for predictions
    if rf_trained is None:
        rf_model = joblib.load(rf_model_path)
        print("→ Loaded the Random Forest model from", rf_model_path)
    else:
        rf_model = rf_trained
        print("→ Found a newly created in-memory model for predictions")

    # TODO: 2024-08-10: We're dropping MONTH information for now, as historical month data can be misleading for the model; inspect this again later.
    # price_df = rf_model.predict(df[['day_of_week', 'hour', 'NuclearPowerMW', 'ImportCapacityMW'] + fmisid_ws + fmisid_t])
    price_df = rf_model.predict(df[prediction_features])
    df['PricePredict_cpkWh'] = price_df
    
    # We drop these columns before commit/display, as we can later compute them from the timestamp
    df = df.drop(columns=['day_of_week', 'hour', 'month'])

    # --add-history: We are going to be verbose and ask before committing a lot of data to the database    
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
   
    # --commit: Update the database with the final data
    if args.commit:    
        if args.add_history:        
            # Ask if the user wants to add the predictions to the database
            if input("Do you want to add the retrospective predictions to the database? (y/n): ").lower() != "y":
                print("Aborting.")
                exit()          
        
        print("Will add/update", len(df), "predictions to the database... ", end="")
        
        if db_update(db_path, df):
            print("Database updated. You may want to --deploy next if you need the JSON predictions for further use.")
    else:
        print(df)
        print("* Predictions NOT committed to the database (no --commit).")
        
    # DEBUG: save to CSV for inspection
    # df.to_csv(os.path.join(data_folder_path + "/private", "predictions_df.csv"), index=False)    
    # exit()

# --narrate: Narrate can be used with the previous arguments
if args.narrate:
    print("Narrating predictions...")
    tomorrow = datetime.now(pytz.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
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

# --deploy: Deploy can be done solo, or with --predict and --narrate
if args.deploy:
    print("Deploing the latest prediction data:", deploy_folder_path, "...")
    
    deploy_df = db_query_all(db_path)

    # Ensure 'timestamp' column is in datetime format
    deploy_df['timestamp'] = pd.to_datetime(deploy_df['timestamp'])

    # Helsinki time zone setup
    helsinki_tz = pytz.timezone('Europe/Helsinki')

    # Get the current time in Helsinki time zone and adjust to the start of yesterday
    start_of_yesterday_helsinki = datetime.now(helsinki_tz).replace(hour=0, minute=0, second=0, microsecond=0) - pd.Timedelta(days=1)

    # Convert the start of yesterday in Helsinki back to UTC
    start_of_yesterday_utc = start_of_yesterday_helsinki.astimezone(pytz.utc)

    # Ensure 'timestamp' column is in datetime format and UTC for comparison
    deploy_df['timestamp'] = pd.to_datetime(deploy_df['timestamp']).dt.tz_localize(None).dt.tz_localize(pytz.utc)

    # Filter out rows where 'timestamp' is earlier than the start of yesterday in Helsinki, adjusted to UTC
    deploy_df = deploy_df[deploy_df['timestamp'] >= start_of_yesterday_utc]
    hourly_predictions = deploy_df[['timestamp', 'PricePredict_cpkWh']].copy()
    hourly_predictions['timestamp'] = hourly_predictions['timestamp'].dt.tz_localize(None) if hourly_predictions['timestamp'].dt.tz is not None else hourly_predictions['timestamp']
    hourly_predictions['timestamp'] = hourly_predictions['timestamp'].apply(
        lambda x: (x - pd.Timestamp("1970-01-01")) // pd.Timedelta('1ms')
    )

    # Write prediction.json to the deploy folder
    json_data_list = hourly_predictions.values.tolist()
    json_data = json.dumps(json_data_list, ensure_ascii=False)
    json_path = os.path.join(deploy_folder_path, predictions_file)
    with open(json_path, 'w') as f:
        f.write(json_data)
    print(f"→ Hourly predictions saved to {json_path}")

    # Create/update the snapshot JSON file for today's predictions
    # TODO: Remove fixed file name, derive from .env.local
    create_prediction_snapshot(deploy_folder_path, json_data_list, "prediction_snapshot")

    # Rotate snapshots to maintain only the latest 6 (+today=7)
    # TODO: Remove fixed file name, derive from .env.local
    rotate_snapshots(deploy_folder_path, pattern="prediction_snapshot*", max_files=6)

    # Normalize 'timestamp' to set the time to 00:00:00 for daily average grouping
    deploy_df['timestamp'] = deploy_df['timestamp'].dt.tz_localize(None) if deploy_df['timestamp'].dt.tz is not None else deploy_df['timestamp']
    deploy_df['timestamp'] = deploy_df['timestamp'].dt.normalize()
    daily_averages = deploy_df.groupby('timestamp')['PricePredict_cpkWh'].mean().reset_index()

    # Before applying lambda, ensure 'timestamp' is timezone-naive for consistency
    daily_averages['timestamp'] = daily_averages['timestamp'].apply(
        lambda x: (x - pd.Timestamp("1970-01-01")) // pd.Timedelta('1ms')
    )

    # Save the daily averages to a JSON file in the deploy folder
    json_data_list = daily_averages[['timestamp', 'PricePredict_cpkWh']].values.tolist()
    json_data = json.dumps(json_data_list, ensure_ascii=False)
    json_path = os.path.join(deploy_folder_path, averages_file)
    with open(json_path, 'w') as f:
        f.write(json_data)
    print(f"→ Daily averages saved to {json_path}")

if __name__ == "__main__":
    # If no arguments were given, print usage
    if not any(vars(args).values()):
        print("No arguments given.")
        parser.print_help()