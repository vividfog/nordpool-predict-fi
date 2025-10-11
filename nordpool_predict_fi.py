import os
import json
import pytz
import argparse
import numpy as np
import pandas as pd
from rich import print
from datetime import datetime
from dotenv import load_dotenv
from util.dump import dump_sqlite_db
from util.sahkotin import update_spot
from util.train_xgb import train_model
from util.llm import narrate_prediction
from util.entso_e import entso_e_nuclear
from util.archive import insert_snapshot
from util.holidays import update_holidays
from util.sql import db_update, db_query_all
from util.dataframes import update_df_from_df
from util.openmeteo_solar import update_solar
from util.fingrid_nuclear import update_nuclear
from util.openmeteo_windpower import update_eu_ws
from util.jao_imports import update_import_capacity
from util.fmi import update_wind_speed, update_temperature
from util.eval import create_prediction_snapshot, rotate_snapshots
from util.volatility_xgb import train_volatility_model, predict_daily_volatility
# from util.volatility_bayes import train_volatility_model, predict_daily_volatility
from util.scaler import scale_predicted_prices
from util.logger import logger

# Wind power model choices: nn vs xgb
# from util.fingrid_windpower_nn import update_windpower
from util.fingrid_windpower_xgb import update_windpower

# -----------------------------------------------------------------------------------------------------------------------------
# Configure pandas to display all rows
pd.set_option('display.max_rows', None)

# Set the global print option for float format
pd.options.display.float_format = '{:.2f}'.format

# -----------------------------------------------------------------------------------------------------------------------------
# Fetch environment variables from .env.local (create yours from .env.template)
try:
    load_dotenv('.env.local')
except Exception as e:
    logger.error(f"Can't find .env.local. Did you create one? See README.md.")

# Fetch mandatory environment variables and raise exceptions if they are missing
def get_mandatory_env_variable(name):
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"Mandatory variable {name} not set in environment")
    return value

# Configuration and secrets, mandatory:
try:
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
    logger.error(f"Error: {e}", exc_info=True)
    exit(1)

# region args
# -----------------------------------------------------------------------------------------------------------------------------
# Command line arguments
parser = argparse.ArgumentParser()
parser.add_argument('--train', action='store_true', help='[Deprecated] Train a new model candidate using the data in the database')
parser.add_argument('--predict', action='store_true', help='Train a model (in memory) and display price predictions')
parser.add_argument('--narrate', action='store_true', help='Narrate the predictions into text using an LLM')
parser.add_argument('--commit', action='store_true', help='Commit the predictions/narrations results to DB; use with --predict, --narrate')
parser.add_argument('--deploy', action='store_true', help='Deploy the output files to the web folder')
parser.add_argument('--dump', action='store_true', help='Dump the SQLite database to CSV format')
parser.add_argument('--nn', action='store_true', help='Use neural network model(s) instead of XGBoost')
args = parser.parse_args()

# -----------------------------------------------------------------------------------------------------------------------------
# --dump: Dump the SQLite database as CSV to STDOUT
if args.dump:
    dump_sqlite_db(data_folder_path)
    exit()
else:
    # Startup message
    logger.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Nordpool Predict FI")

# -----------------------------------------------------------------------------------------------------------------------------
# Deprecate --train option
if args.train:
    logger.warning("The --train option is deprecated and is no longer used. Training is now performed automatically during --prediction.")

# region predict
# -----------------------------------------------------------------------------------------------------------------------------
if args.predict:
    logger.info(f"Loading training data from '{db_path}'")
    df_full = db_query_all(db_path)
    df_full['timestamp'] = pd.to_datetime(df_full['timestamp'])
    df_full.set_index('timestamp', inplace=True)
    df_full.reset_index(inplace=True)

    # Print the head of the DataFrame
    logger.debug(df_full.head(48))

    df_full.set_index('timestamp', inplace=True)

    # Temporarily restore "timestamp" column for the update functions
    df_full.reset_index(inplace=True)

    # Update the DF with holiday indicators
    df_full = update_holidays(df_full)

    # Update the DF with solar irradiation data
    # The API call is quick, including for historical data; these won't be committed to the DB for now (2024-12-28)
    df_full = update_solar(df_full)

    # Restore the index
    df_full.set_index('timestamp', inplace=True)

    # Define 'now' and the recent period
    now = pd.Timestamp.utcnow()
    if now.minute > 0 or now.second > 0 or now.microsecond > 0:
        now = now.ceil('h')  # Rounds up to the nearest hour

    start_recent = now - pd.Timedelta(days=7)
    end_recent = now + pd.Timedelta(days=7)

    # Create df_recent for data updates and predictions
    df_recent = df_full.loc[start_recent:end_recent].copy()

    # Forward-fill the timestamp column for future dates
    start_time = now + pd.Timedelta(hours=1)  # Start from the next hour
    end_time = now + pd.Timedelta(days=7)  # 7 days ahead

    # Actually end_time should be now + 7 days, but to the end of the day
    end_time = end_time.replace(hour=23, minute=59, second=59)

    future_index = pd.date_range(start=start_time, end=end_time, freq='h')
    df_recent = df_recent.reindex(df_recent.index.union(future_index))

    # Since FMI can remove weather stations from their API without notice, we should rely on .env.local
    # rather than the database as the source of truth. Filter df_recent to include only columns
    # corresponding to specified FMI weather station/temperature IDs, or columns that do not have
    # the 'ws_'/'t_' prefix.
    df_recent = df_recent[list(set(fmisid_ws + fmisid_t)
                       | {col for col in set(df_recent.columns)
                          if not col.startswith(('ws_', 't_'))})]

    # Reset the index to turn 'timestamp' back into a column before the update functions
    df_recent.reset_index(inplace=True)
    df_recent.rename(columns={'index': 'timestamp'}, inplace=True)

    # region [updates]
    # Update wind speed and temperature data
    df_recent = update_wind_speed(df_recent)
    df_recent = update_temperature(df_recent)
    
    # Update nuclear power data
    df_recent = update_nuclear(df_recent, fingrid_api_key=fingrid_api_key)
    
    # Update import capacity data
    df_recent = update_import_capacity(df_recent, write_daily_average=args.commit)

    # Update Baltic Sea area wind speed data
    df_recent = update_eu_ws(df_recent)

    # Update wind power data
    df_recent = update_windpower(df_recent, fingrid_api_key=fingrid_api_key)

    # Fetch future nuclear downtime information from ENTSO-E unavailability data
    df_entso_e = entso_e_nuclear(entso_e_api_key)
    if df_entso_e is not None:
        # Refresh the previously inferred nuclear power numbers with the ENTSO-E data
        df_recent = update_df_from_df(df_recent, df_entso_e)
    else:
        logger.error("ENTSO-E data is unavailable. Will exit.", exc_info=True)
        exit(1)

    # Get the latest spot prices for the data frame, past and future if any
    df_recent = update_spot(df_recent)

    # Update holidays in the recent data
    df_recent = update_holidays(df_recent)
    
    # Update solar irradiation data
    df_recent = update_solar(df_recent)

    # Set 'timestamp' as index in df_recent
    df_recent.set_index('timestamp', inplace=True)

    # Update df_full with df_recent
    df_full.update(df_recent)

    # Train volatility prediction model
    volatility_model = train_volatility_model(df_full)
    
    # Apply volatile_likelihood to the full data for pricing model training
    logger.info("Predicting price volatility likelihood for training data")
    df_full = predict_daily_volatility(df_full, volatility_model)

    # Apply volatile_likelihood to the recent data for price prediction
    logger.info("Predicting price volatility likelihood for recent/future data")
    df_recent = predict_daily_volatility(df_recent, volatility_model)

    # Reset the index of df_full
    df_full.reset_index(inplace=True)

    # region [train]
    # Prepare df_full for pricing model training
    logger.debug("Preparing data for training")
    df_full['WindPowerCapacityMW'] = df_full['WindPowerCapacityMW'].ffill()
    df_full['NuclearPowerMW'] = df_full['NuclearPowerMW'].ffill()
    df_full['ImportCapacityMW'] = df_full['ImportCapacityMW'].ffill()

    required_columns = [
        'timestamp', 'NuclearPowerMW', 'ImportCapacityMW', 'Price_cpkWh', 'WindPowerMW', 'holiday', 'sum_irradiance', 'mean_irradiance', 'std_irradiance', 'min_irradiance', 'max_irradiance', # 'volatile_likelihood'
    ] + fmisid_t + fmisid_ws
    df_full = df_full.dropna(subset=required_columns)

    # Train the pricing model
    logger.debug("Training the model with updated data")
    model_trained = train_model(
        df_full, fmisid_ws=fmisid_ws, fmisid_t=fmisid_t
    )

    # Prepare df_recent for price prediction
    # Convert timestamp to datetime if it's not already
    if not pd.api.types.is_datetime64_any_dtype(df_recent['timestamp']):
        df_recent['timestamp'] = pd.to_datetime(df_recent['timestamp'])
        
    df_recent['month'] = df_recent['timestamp'].dt.month
    df_recent['day_of_week'] = df_recent['timestamp'].dt.dayofweek + 1
    df_recent['hour'] = df_recent['timestamp'].dt.hour
    df_recent['year'] = df_recent['timestamp'].dt.year

    # Add cyclical transformations
    df_recent['day_of_week_sin'] = np.sin(2 * np.pi * df_recent['day_of_week'] / 7)
    df_recent['day_of_week_cos'] = np.cos(2 * np.pi * df_recent['day_of_week'] / 7)
    df_recent['hour_sin'] = np.sin(2 * np.pi * df_recent['hour'] / 24)
    df_recent['hour_cos'] = np.cos(2 * np.pi * df_recent['hour'] / 24)

    # Calculate temp_mean and temp_variance
    df_recent['temp_mean'] = df_recent[fmisid_t].mean(axis=1)
    df_recent['temp_variance'] = df_recent[fmisid_t].var(axis=1)

    # region [predict]
    # Define prediction features
    prediction_features = [
        'year', 'day_of_week_sin', 'day_of_week_cos', 'hour_sin', 'hour_cos',
        'NuclearPowerMW', 'ImportCapacityMW', 'WindPowerMW',
        'temp_mean', 'temp_variance', 'holiday', 
        'sum_irradiance', 'mean_irradiance', 'std_irradiance', 'min_irradiance', 'max_irradiance',
        'SE1_FI', 'SE3_FI', 'EE_FI',
        'eu_ws_EE01', 'eu_ws_EE02', 'eu_ws_DK01', 'eu_ws_DK02', 'eu_ws_DE01', 'eu_ws_DE02', 'eu_ws_SE01', 'eu_ws_SE02', 'eu_ws_SE03',
        # 'volatile_likelihood'
    ] + fmisid_t + fmisid_ws
    
    # Predict the prices
    logger.info("Predicting prices with the trained model")
    price_df = model_trained.predict(df_recent[prediction_features])
    df_recent['PricePredict_cpkWh'] = price_df

    # region [scale]
    # Apply the price scaler (creates a JSON file to be used in the frontend)
    logger.info("Applying price prediction scaler")
    df_recent = scale_predicted_prices(df_recent, deploy=args.deploy, deploy_folder_path=deploy_folder_path)

    # Apply the volatility scaler to the price predictions only where scaled values are available (not NaN)
    mask = df_recent['PricePredict_cpkWh_scaled'].notna()
    if mask.any():
        logger.info(f"Applying scaled prices to {mask.sum()} predictions")
        df_recent.loc[mask, 'PricePredict_cpkWh'] = df_recent.loc[mask, 'PricePredict_cpkWh_scaled']
    else:
        logger.info("No scaled prices to apply (all NaN)")

    # Clean up all unnecessary columns before DB commit or display
    df_recent = df_recent.drop(columns=[
        'year', 'day_of_week', 'hour', 'month',
        'day_of_week_sin', 'day_of_week_cos',
        'hour_sin', 'hour_cos', 
        'temp_mean', 'temp_variance',
    ])

    # Describe the predictions
    print(df_recent)
    print(df_recent.describe())    

# region commit
# --commit: Update the database with the final data
# This needs to happen *before* narrate or deploy if they are to use the latest data
if args.commit:
    # Drop unnecessary columns before committing to the database
    # These columns were needed for prediction/scaling but are not stored
    columns_to_drop_before_commit = [
        'year', 'month', 'day_of_week', 'hour',
        'day_of_week_sin', 'day_of_week_cos',
        'hour_sin', 'hour_cos', 
        'temp_mean', 'temp_variance',
        'volatile_likelihood', 'PricePredict_cpkWh_scaled',
    ]
    # Ensure columns exist before trying to drop them
    columns_to_drop_existing = [col for col in columns_to_drop_before_commit if col in df_recent.columns]
    if columns_to_drop_existing:
        df_recent_to_commit = df_recent.drop(columns=columns_to_drop_existing)
    else:
        df_recent_to_commit = df_recent.copy() # Or just df_recent if no columns needed dropping

    logger.info(f"* Will add/update {len(df_recent_to_commit)} predictions to the database ")
    if db_update(db_path, df_recent_to_commit):
        logger.info("→ Database updated with new predictions.")
        
        # Archive a snapshot of the predictions
        archive_db_path = os.path.join(data_folder_path, 'archive.db')
        run_id = insert_snapshot(archive_db_path, df_recent_to_commit)
        if not run_id:
            logger.error("Failed to archive prediction snapshot")
    else:
        logger.error("Failed to update database with new predictions")

elif args.predict: # Only show this message if predict was run but not committed
    logger.info("* Predictions generated but NOT committed to the database (no --commit).")

# region narrate
# -----------------------------------------------------------------------------------------------------------------------------
# --narrate: Generate narration
if args.narrate:
    logger.info("* Narrating predictions")
    narration = narrate_prediction(deploy=args.deploy, commit=args.commit)

# region deploy
# -----------------------------------------------------------------------------------------------------------------------------
# --deploy: Deploy the output files
if args.deploy:
    logger.info(f"Deploying the latest prediction data to: '{deploy_folder_path}' ...")

    deploy_df = db_query_all(db_path)
    deploy_df['timestamp'] = pd.to_datetime(deploy_df['timestamp'])

    # Helsinki time zone setup
    helsinki_tz = pytz.timezone('Europe/Helsinki')

    # Get the current time in Helsinki time zone and adjust to the start of yesterday
    start_of_yesterday_helsinki = datetime.now(helsinki_tz).replace(hour=0, minute=0, second=0, microsecond=0) - pd.Timedelta(days=1)

    # Convert the start of yesterday in Helsinki back to UTC
    start_of_yesterday_utc = start_of_yesterday_helsinki.astimezone(pytz.utc)

    # Ensure 'timestamp' column is in datetime format and UTC for comparison
    deploy_df['timestamp'] = deploy_df['timestamp'].dt.tz_localize(None).dt.tz_localize(pytz.utc)

    # Filter out rows where 'timestamp' is earlier than the start of yesterday in Helsinki, adjusted to UTC
    deploy_df = deploy_df[deploy_df['timestamp'] >= start_of_yesterday_utc]

    # Hourly Price Predictions
    hourly_price_predictions = deploy_df[['timestamp', 'PricePredict_cpkWh']].copy()
    hourly_price_predictions['timestamp'] = hourly_price_predictions['timestamp'].dt.tz_localize(None) if hourly_price_predictions['timestamp'].dt.tz is not None else hourly_price_predictions['timestamp']
    hourly_price_predictions['timestamp'] = hourly_price_predictions['timestamp'].apply(
        lambda x: (x - pd.Timestamp("1970-01-01")) // pd.Timedelta('1ms')
    )

    # Write price prediction.json to the deploy folder
    json_data_list = hourly_price_predictions.values.tolist()
    json_data = json.dumps(json_data_list, ensure_ascii=False)
    json_path = os.path.join(deploy_folder_path, predictions_file)
    with open(json_path, 'w') as f:
        f.write(json_data)
    logger.info(f"→ Hourly price predictions saved to '{json_path}'")

    # Create/update the snapshot JSON file for today's predictions
    create_prediction_snapshot(deploy_folder_path, json_data_list, "prediction_snapshot")

    # Rotate snapshots to maintain the latest X snapshots
    rotate_snapshots(deploy_folder_path, pattern="prediction_snapshot*", max_files=40)

    # Hourly Wind Power Predictions
    windpower_preds = deploy_df[['timestamp', 'WindPowerMW']].copy()
    windpower_preds['timestamp'] = windpower_preds['timestamp'].dt.tz_localize(None) if windpower_preds['timestamp'].dt.tz is not None else windpower_preds['timestamp']
    windpower_preds['timestamp'] = windpower_preds['timestamp'].apply(
        lambda x: (x - pd.Timestamp("1970-01-01")) // pd.Timedelta('1ms')
    )

    # Write wind power prediction JSON to the deploy folder
    json_data_list = windpower_preds.values.tolist()
    json_data = json.dumps(json_data_list, ensure_ascii=False)
    json_path_wind = os.path.join(deploy_folder_path, 'windpower.json')
    with open(json_path_wind, 'w') as f:
        f.write(json_data)
    logger.info(f"→ Hourly wind power predictions saved to '{json_path_wind}'")

    # Convert timestamps to Helsinki timezone
    deploy_df['timestamp'] = deploy_df['timestamp'].dt.tz_convert(helsinki_tz)

    # Save the full prediction data to a JSON file in the deploy folder
    prediction_full_json = deploy_df.to_json(orient='records', date_format='iso', indent=2)
    full_json_path = os.path.join(deploy_folder_path, 'prediction_full.json')
    with open(full_json_path, 'w') as f:
        f.write(prediction_full_json)
        logger.info(f"→ Full prediction data saved to '{full_json_path}'")

    # Normalize 'timestamp' to set the time to 00:00:00 for daily average grouping in local time
    deploy_df['timestamp'] = deploy_df['timestamp'].dt.normalize()

    # Calculate daily averages in Helsinki time
    daily_averages = deploy_df.groupby('timestamp')['PricePredict_cpkWh'].mean().reset_index()

    # Convert timestamps back to UTC for the JSON output
    daily_averages['timestamp'] = daily_averages['timestamp'].dt.tz_convert(pytz.utc)
    daily_averages['timestamp'] = daily_averages['timestamp'].apply(
        lambda x: int((x - pd.Timestamp("1970-01-01", tz='utc')) // pd.Timedelta('1ms'))
        
    )

    # Save the daily averages to a JSON file in the deploy folder
    json_data_list = daily_averages[['timestamp', 'PricePredict_cpkWh']].values.tolist()
    json_data = json.dumps(json_data_list, ensure_ascii=False)
    json_path = os.path.join(deploy_folder_path, averages_file)
    with open(json_path, 'w') as f:
        f.write(json_data)
    logger.info(f"→ Daily averages saved to '{json_path}'")

# region end
# -----------------------------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    
    # If no arguments were given, print usage
    if not any(vars(args).values()):
        logger.error("No arguments given.")
        parser.print_help()
