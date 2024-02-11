# filename: load_and_predict_model.py
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import pandas as pd
import joblib  # Import joblib to load the model

# Load the model from the file
rf = joblib.load('electricity_price_rf_model.joblib')

# Load the same preprocessed dataset (assuming you want to use the same dataset for consistency)
df = pd.read_csv("preprocessed_electricity_prices_dataset.csv")

# Sample 1000 random instances from the dataset
df_sampled = df.sample(n=1000, random_state=42)

# Define the features and target variable for the sampled dataset
X_sampled = df_sampled[['Temp [°C]', 'Wind [m/s]', 'hour', 'day_of_week', 'month']]
y_sampled = df_sampled['Price [c/kWh]']

# No need to split the dataset since we're only predicting and comparing, not retraining
# Predict on the sampled data
y_pred = rf.predict(X_sampled)

# Print 30 random sample predictions along with the actual prices for comparison
comparison_df = pd.DataFrame({'Actual Price [c/kWh]': y_sampled, 'Predicted Price [c/kWh]': y_pred})
print(comparison_df.sample(30, random_state=42))  # Randomly select and print 30 rows


# If desired, you can still calculate and print performance metrics
mae = mean_absolute_error(y_sampled, y_pred)
mse = mean_squared_error(y_sampled, y_pred)
r2 = r2_score(y_sampled, y_pred)

# Print the performance metrics
print(f"Mean Absolute Error (MAE): {mae:.2f}")
print(f"Mean Squared Error (MSE): {mse:.2f}")
print(f"R-squared (R2): {r2:.2f}")
