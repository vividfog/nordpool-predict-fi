# filename: predict_prices_from_weather.py
import pandas as pd
import joblib

# Load the saved Random Forest model
model = joblib.load('electricity_price_rf_model.joblib')

# Load the weather data
weather_df = pd.read_csv("weather.csv")

# Ensure the numerical data is in the correct format, replacing commas with dots if necessary
weather_df['Temp [°C]'] = weather_df['Temp [°C]'].astype(str).str.replace(',', '.').astype(float)
weather_df['Wind [m/s]'] = weather_df['Wind [m/s]'].astype(str).str.replace(',', '.').astype(float)

# Extract Date Time for additional features
weather_df['Date Time'] = pd.to_datetime(weather_df['Date Time'])

# Add required features based on Date Time
weather_df['hour'] = weather_df['Date Time'].dt.hour
weather_df['day_of_week'] = weather_df['Date Time'].dt.dayofweek + 1  # +1 to match original model training
weather_df['month'] = weather_df['Date Time'].dt.month

# Define the features for the model
X = weather_df[['Temp [°C]', 'Wind [m/s]', 'hour', 'day_of_week', 'month']]

# Predict the price
weather_df['PricePredict [c/kWh]'] = model.predict(X)

# Select the desired columns for the output
output_df = weather_df[['Date Time', 'Temp [°C]', 'Wind [m/s]', 'PricePredict [c/kWh]']]

# Save the output to a new CSV file
output_df.to_csv("predicted_prices.csv", index=False)

print("Predictions saved to predicted_prices.csv.")
