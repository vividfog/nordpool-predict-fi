import requests
import pandas as pd
import joblib
import matplotlib.pyplot as plt
import pytz  # Make sure to install pytz if you haven't already

def fetch_weather_data(location, api_key):
    base_url = "https://api.tomorrow.io/v4/weather/forecast"
    query_params = {
        'location': location,
        'timesteps': '1h',
        'units': 'metric',  # Assuming you want metric units
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
    # Assuming 'hourly' timeline is what we're interested in. Adjust if needed.
    hourly_forecast_data = weather_data['timelines']['hourly']
    for hourly_forecast in hourly_forecast_data:
        time = hourly_forecast['time']
        values = hourly_forecast['values']
        temp = values.get('temperature', 0)  # Default to 0 if not available
        wind_speed = values.get('windSpeed', 0)  # Default to 0 if not available
        
        # Parse time to extract additional features
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

def predict_prices(df, rf_model_path='electricity_price_rf_model.joblib'):
    # Load and apply the Random Forest model
    rf_model = joblib.load(rf_model_path)
    features = df[['Temp [°C]', 'Wind [m/s]', 'hour', 'day_of_week', 'month']]
    initial_predictions = rf_model.predict(features)
    df['PricePredict [c/kWh]'] = initial_predictions
    
    return df

def get_bar_color(value, color_threshold):
    """Return the color for the bar based on the specified value."""
    for threshold in color_threshold:
        if value >= threshold['value']:
            color = threshold['color']
        else:
            break
    return color

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
        
        for idx, row in group.iterrows():
            bar_color = get_bar_color(row['PricePredict [c/kWh]'], color_threshold)
            plt.bar(idx.hour, row['PricePredict [c/kWh]'], color=bar_color, width=0.8)
        
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


# Example usage
location = "pirkkala airport"
api_key = "77MKszgZQMSzl81qSbEfE2gqdqK1PTTZ"

weather_data = fetch_weather_data(location, api_key)
features_df = preprocess_data(weather_data)
print(features_df)
predictions_df = predict_prices(features_df)
print(predictions_df)

# Plot and save daily price predictions with consistent scales
plot_hourly_prices(predictions_df)

# Output the predictions to a CSV file, including the predicted price
# Drop 'day_of_week' and 'month' columns from the dataframe
predictions_df = predictions_df.drop(['day_of_week', 'month', 'hour'], axis=1)

# Reset the index if you have made 'Date' the index of your dataframe
predictions_df.reset_index(inplace=True)

# Save the dataframe to CSV without the 'day_of_week' and 'month' columns
predictions_df.to_csv("5_day_price_predictions.csv", index=False)
print("Predictions saved to 5_day_price_predictions.csv with the Date included and unnecessary columns removed.")