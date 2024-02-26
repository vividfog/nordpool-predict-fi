import pandas as pd
import requests
from datetime import datetime, timedelta

def fetch_weather_data(location, api_key, start_date):
    """
    Fetch weather data from the Tomorrow.io API starting from the given date.
    
    Args:
    - location (str): Location for which to fetch the weather data.
    - api_key (str): API key for authenticating requests to Tomorrow.io.
    - start_date (datetime): The date from which to start fetching the weather data.
    
    Returns:
    - DataFrame: A DataFrame with weather data including temperature, wind speed, etc.
    """
    # Format the start date to match API requirements
    start_date = start_date.replace(minute=0, second=0, microsecond=0)
    
    # Adjust the end_date to be 5 days from the start_date, not including the start_date's day
    end_date = start_date + timedelta(days=4.9)
    
    # Format the start and end dates to match API requirements
    start_date_str = start_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_date_str = end_date.strftime('%Y-%m-%dT%H:%M:%SZ')

    base_url = "https://api.tomorrow.io/v4/timelines"
    query_params = {
        'location': location,
        'fields': ['temperature', 'windSpeed'],
        'units': 'metric',
        'timesteps': '1h',
        'apikey': api_key,
        'startTime': start_date_str,
        'endTime': end_date_str,
    }
    
    response = requests.get(base_url, params=query_params)
    if response.status_code == 200:
        weather_data = response.json()
        return parse_weather_data(weather_data)
    else:
        raise Exception("API request failed: " + str(response.text))

def parse_weather_data(weather_data):
    """
    Parse the API response into a DataFrame.
    
    Args:
    - weather_data (dict): The raw API response.
    
    Returns:
    - DataFrame: Parsed weather data.
    """
    parsed_data = []
    for item in weather_data['data']['timelines'][0]['intervals']:
        time = item['startTime']
        temp = item['values']['temperature']
        wind_speed = item['values']['windSpeed']
        
        parsed_data.append({
            'timestamp': time,
            'Temp_dC': temp,
            'Wind_mps': wind_speed,
        })
    
    return pd.DataFrame(parsed_data)

def weather_get(df, location, api_key):
    """
    Fetches weather data onwards from the date given in the DataFrame and fills in the DataFrame with this data.
    
    Args:
    - df (DataFrame): Input DataFrame with a 'Date' column.
    - location (str): Location for which to fetch the weather.
    - api_key (str): API key for Tomorrow.io.
    
    Returns:
    - DataFrame: The input DataFrame with weather data filled in.
    """
    # Ensure 'Date' is in datetime format
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    # Get the latest date in the DataFrame
    start_date = df['timestamp'].max()
    
    # Fetch weather data
    # print(f"Fetching weather data from {start_date} for location {location}...")
    weather_df = fetch_weather_data(location, api_key, start_date)
    
    weather_df['timestamp'] = pd.to_datetime(weather_df['timestamp'])
    
    return weather_df