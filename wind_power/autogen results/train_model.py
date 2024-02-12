# filename: train_model.py
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import pandas as pd

# Load the preprocessed data
df = pd.read_csv('preprocessed_wind_data.csv')

# Split the data into features and target
X = df[['Speed']]  # Features (wind speed)
y = df['wind_power']  # Target (wind power)

# Split the dataset into training and testing sets
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Initialize the Random Forest Regressor
rf = RandomForestRegressor(n_estimators=100, random_state=42)

# Train the model
rf.fit(X_train, y_train)

# Predict on the test set
y_pred = rf.predict(X_test)

# Calculate performance metrics
mae = mean_absolute_error(y_test, y_pred)
mse = mean_squared_error(y_test, y_pred)
r2 = r2_score(y_test, y_pred)

# Print performance metrics
print(f"Mean Absolute Error (MAE): {mae}")
print(f"Mean Squared Error (MSE): {mse}")
print(f"R-squared Value: {r2}")

# Save the trained model to a file
import joblib
joblib.dump(rf, 'wind_power_rf_model.joblib')

print("Model training complete. Model saved to 'wind_power_rf_model.joblib'.")