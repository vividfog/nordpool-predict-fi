import pandas as pd
import requests
import json
from datetime import datetime

# Configuration
csv_file_path = '5_day_price_predictions.csv'
gist_id = '18970d60ce47a98d6323137c3c581eea'  # Gist ID to update
token = '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'  # GitHub token

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

# Convert the CSV to JSON
json_data = convert_csv_to_json(csv_file_path)

# Update the gist with the new JSON data
update_gist(json_data, gist_id, token)

