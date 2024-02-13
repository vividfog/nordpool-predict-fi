# filename: predict_sample_wind_power.py
import joblib

# Load the trained model
model = joblib.load('wind_power_rf_model.joblib')

# Sample input for prediction
wind_speed_sample = 1  # m/s

# Predict the wind power using the loaded model
wind_power_pred = model.predict([[wind_speed_sample]])

# Output the prediction
print(f"Predicted wind power for wind speed {wind_speed_sample} m/s: {wind_power_pred[0]} MWh")