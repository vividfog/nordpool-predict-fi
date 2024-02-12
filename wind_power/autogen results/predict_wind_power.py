# filename: predict_wind_power.py
from sklearn.ensemble import RandomForestRegressor
import joblib
import sys

# Function to load the model and predict wind power
def predict_wind_power(speed):
    # Load the trained model
    model = joblib.load('wind_power_rf_model.joblib')
    # Predict the wind power using the loaded model
    wind_power_pred = model.predict([[speed]])
    return wind_power_pred[0]

# Main execution: parse command line argument and print prediction
if __name__ == "__main__":
    # Check if wind speed argument is provided
    if len(sys.argv) != 2:
        print("Usage: python predict_wind_power.py <wind_speed>")
        sys.exit(1)
    
    # Parse wind speed from command line argument
    wind_speed = float(sys.argv[1])
    
    # Predict and print wind power
    prediction = predict_wind_power(wind_speed)
    print(f"Predicted wind power for wind speed {wind_speed} m/s: {prediction} MWh")