import requests
import pandas as pd
import joblib
import matplotlib.pyplot as plt
import pytz  # Make sure to install pytz if you haven't already
import json
from datetime import datetime
import git
import os
from sklearn.preprocessing import StandardScaler

# Configuration and Secrets
location = "pirkkala airport"
api_key = "77MKszgZQMSzl81qSbEfE2gqdqK1PTTZ"
rf_model_path = 'electricity_price_rf_model.joblib'
lr_model_path = 'linear_regression_model.joblib'
csv_file_path = '5_day_price_predictions.csv'
gist_id = '18970d60ce47a98d6323137c3c581eea'  # Gist ID to update
token = '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'  # GitHub token
deploy_folder_path = '/Users/ph/work.local/autogen-projects/electricity-price/deploy'
repo_path = '/Users/ph/work.local/autogen-projects/electricity-price/deploy'
file_path = 'prediction.json'  # This is relative to the repo_path
commit_message = 'Update prediction.json with new data'

# Define functions here

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

def preprocess_data(weather_data):
    processed_data = []
    hourly_forecast_data = weather_data['timelines']['hourly']
    for hourly_forecast in hourly_forecast_data:
        time = hourly_forecast['time']
        values = hourly_forecast['values']
        temp = values.get('temperature', 0)
        wind_speed = values.get('windSpeed', 0)
        
        time_parsed = pd.to_datetime(time)
        hour = time_parsed.hour
        day_of_week = time_parsed.dayofweek + 1
        month = time_parsed.month
        
        processed_data.append({
            'Date': time,
            'Temp [°C]': temp,
            'Wind [m/s]': wind_speed,
            'hour': hour,
            'day_of_week': day_of_week,
            'month': month
        })
    return pd.DataFrame(processed_data)


def predict_prices(df, rf_model_path, lr_model_path):
    # Load models
    rf_model = joblib.load(rf_model_path)
    lr_model = joblib.load(lr_model_path)
    
    # Prepare features for RF prediction
    rf_features = df[['Temp [°C]', 'Wind [m/s]', 'hour', 'day_of_week', 'month']]
    initial_predictions = rf_model.predict(rf_features)
    
    # Add RF predictions to the DataFrame for LR model
    df['RF_PricePredict [c/kWh]'] = initial_predictions
    
    # StandardScaler for LR model features
    scaler = StandardScaler()
    lr_features = scaler.fit_transform(df[['Temp [°C]', 'Wind [m/s]', 'hour', 'day_of_week', 'month', 'RF_PricePredict [c/kWh]']])
    
    # Predict with LR model
    scaled_predictions = lr_model.predict(lr_features)
    df['LR_Scaled_PricePredict [c/kWh]'] = scaled_predictions
    
    return df

# Modify the plot_hourly_prices and other functions as needed to use the LR_Scaled_PricePredict [c/kWh] for plotting and analysis

# Other functions (plot_hourly_prices, get_bar_color, convert_csv_to_json, update_gist) remain unchanged
def plot_hourly_prices(df):
    # Define color thresholds
    color_threshold = [
        {'value': -1000, 'color': 'lime'},
        {'value': 5, 'color': 'green'},
        {'value': 10, 'color': 'orange'},
        {'value': 15, 'color': 'red'},
        {'value': 20, 'color': 'darkred'},
        {'value': 30, 'color': 'black'},
    ]

    # Ensure 'Date' is in datetime format
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)

    # Convert to Helsinki timezone
    df.index = df.index.tz_localize('UTC').tz_convert('Europe/Helsinki') if df.index.tz is None else df.index.tz_convert('Europe/Helsinki')

    # Determine global minimum and maximum prices for consistent y-axis scaling
    global_min_price = df['LR_Scaled_PricePredict [c/kWh]'].min()
    global_max_price = df['LR_Scaled_PricePredict [c/kWh]'].max()

    # Ensure y-axis starts at 0 if all prices are above zero
    y_axis_start = 0 if global_min_price > 0 else global_min_price

    # Group by each day considering the timezone
    grouped = df.groupby(df.index.date)

    for date, group in grouped:
        plt.figure(figsize=(10, 6))
        # Calculate the average price for the day
        daily_avg_price = group['LR_Scaled_PricePredict [c/kWh]'].mean()
        
        for idx, row in group.iterrows():
            bar_color = get_bar_color(row['LR_Scaled_PricePredict [c/kWh]'], color_threshold)
            plt.bar(idx.hour, row['LR_Scaled_PricePredict [c/kWh]'], color=bar_color, width=0.8)
        
        # Add the average price line with the specified color #488FC2
        plt.axhline(y=daily_avg_price, color='#488FC2', linestyle='--', label=f'Avg Price: {daily_avg_price:.2f} c/kWh')
        
        plt.title(f"Hourly Electricity Price Prediction for {date} (Helsinki Time)")
        plt.xlabel("Hour of the Day")
        plt.ylabel("Price [c/kWh]")
        plt.xticks(range(24))  # Ensure x-axis labels show every hour
        plt.ylim(y_axis_start, global_max_price)  # Ensure y-axis starts at 0 if applicable
        plt.legend()  # Show legend to identify the average price line
        
        # Save the plot as a PNG file named after the date
        plt.savefig(f"hourly_price_prediction_{date}.png")
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
    apex_data = df[['timestamp', 'LR_Scaled_PricePredict [c/kWh]']].values.tolist()

    # Convert data to JSON format
    json_data = json.dumps(apex_data)
    return json_data

def update_gist(json_data, gist_id, token):
    # Prepare the GitHub API URL for the gist
    url = f'https://api.github.com/gists/{gist_id}'

    # Prepare the data payload for the gist update
    files = {
        '5_day_price_predictions_for_apex.json': {
            'content': json_data
        }
    }
    data = {
        'files': files
    }

    # Prepare the headers for authentication
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
    }

    # Make the request to update the gist
    response = requests.patch(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        print("Gist updated successfully.")
    else:
        print(f"Failed to update gist. Status code: {response.status_code}")

def save_json_to_deploy_folder(json_data, deploy_folder_path, file_name='prediction.json'):
    """
    Saves the given JSON data to a file in the specified deploy folder path.

    Parameters:
    - json_data: JSON data to save.
    - deploy_folder_path: Path to the deploy folder where the file will be saved.
    - file_name: Name of the file to save the JSON data in. Defaults to 'prediction.json'.
    """
    full_path = f"{deploy_folder_path}/{file_name}"
    with open(full_path, 'w') as f:
        f.write(json_data)
    print(f"File saved to Deploy folder: {full_path}")
    
def push_updates_to_github(repo_path, file_path, commit_message):
    """
    Pushes updates to GitHub for a specified file.

    Parameters:
    - repo_path: Path to the local git repository.
    - file_path: Path to the file within the repository to update.
    - commit_message: Commit message for the update.
    """
    try:
        # Initialize the repository object
        repo = git.Repo(repo_path)
        
        # Check if the file_path is relative, convert it to absolute
        if not os.path.isabs(file_path):
            file_path = os.path.join(repo_path, file_path)
        
        # Relative path of the file from the repo root
        file_path_relative = os.path.relpath(file_path, repo_path)
        
        # Stage the file for commit
        repo.git.add(file_path_relative)
        
        # Commit the changes
        repo.git.commit('-m', commit_message)
        
        # Push the changes
        repo.git.push()
        print("Update pushed to GitHub.")
    except Exception as e:
        print(f"Error pushing updates to GitHub: {e}")

# Main execution starts here

weather_data = fetch_weather_data(location, api_key)
features_df = preprocess_data(weather_data)
predictions_df = predict_prices(features_df, rf_model_path, lr_model_path)

# Plot and save daily price predictions with consistent scales
plot_hourly_prices(predictions_df)

# Prepare the CSV file for gist update
predictions_df = predictions_df.drop(['day_of_week', 'month', 'hour', 'RF_PricePredict [c/kWh]'], axis=1)
predictions_df.reset_index(inplace=True, drop=True)
predictions_df.to_csv(csv_file_path, index=False)

# Convert the CSV to JSON and update the gist or save to deploy folder
json_data = convert_csv_to_json(csv_file_path)
# update_gist(json_data, gist_id, token)
save_json_to_deploy_folder(json_data, deploy_folder_path, file_path)
push_updates_to_github(repo_path, file_path, commit_message)

print("Script execution completed.")
