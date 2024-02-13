import pandas as pd
import numpy as np
import joblib  # Import joblib for model persistence
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.impute import SimpleImputer
from datetime import datetime, timedelta

# Function to preprocess the new dataset
def preprocess_data(filepath):
    df = pd.read_csv(filepath, delimiter=';', na_values='-')
    df['datetime_helsinki'] = pd.to_datetime(df['day.month.year_time_helsinki'], format='%d.%m.%Y %H:%M')
    df['timestamp_UTC'] = pd.to_datetime(df['timestamp_UTC'], unit='s')
    df['day_of_week'] = df['datetime_helsinki'].dt.dayofweek + 1
    df['hour'] = df['datetime_helsinki'].dt.hour
    df['month'] = df['datetime_helsinki'].dt.month
    df.rename(columns={'temp_celsius': 'Temp [°C]', 'wind_m/s': 'Wind [m/s]', 'price_cents_per_kWh': 'Price [c/kWh]'}, inplace=True)
    imputer = SimpleImputer(strategy='mean')
    df[['Temp [°C]', 'Wind [m/s]', 'Price [c/kWh]']] = imputer.fit_transform(df[['Temp [°C]', 'Wind [m/s]', 'Price [c/kWh]']])
    return df[['Temp [°C]', 'Wind [m/s]', 'hour', 'day_of_week', 'month', 'Price [c/kWh]']]

# Preprocess the dataset
df = pd.read_csv('nordpool-spot-with-weather.csv', delimiter=';')
df_preprocessed = preprocess_data('nordpool-spot-with-weather.csv')

# Define features and target for the first model
X = df_preprocessed[['Temp [°C]', 'Wind [m/s]', 'hour', 'day_of_week', 'month']]
y = df_preprocessed['Price [c/kWh]']

# Train the first model (Random Forest)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
rf = RandomForestRegressor(n_estimators=150, max_depth=15, min_samples_split=4, min_samples_leaf=2, max_features='sqrt', random_state=42)
rf.fit(X_train, y_train)
joblib.dump(rf, 'electricity_price_rf_model.joblib')

# Evaluate the first model
y_pred = rf.predict(X_test)
print(f"Initial Mean Absolute Error (MAE): {mean_absolute_error(y_test, y_pred)}")
print(f"Initial Mean Squared Error (MSE): {mean_squared_error(y_test, y_pred)}")
print(f"Initial Coefficient of Determination (R² score): {r2_score(y_test, y_pred)}")

# Prepare data for the second pass
df['prediction_c_per_kWh'] = rf.predict(X)
X_second_pass = df[['prediction_c_per_kWh']].values
y_second_pass = y.values

# Train the second model (Linear Regression) for adjustment
X_train_sp, X_test_sp, y_train_sp, y_test_sp = train_test_split(X_second_pass, y_second_pass, test_size=0.2, random_state=42)
lr_model = LinearRegression()
lr_model.fit(X_train_sp, y_train_sp)

# After training the Linear Regression model
joblib.dump(lr_model, 'linear_regression_scaling_model.joblib')

# Apply and evaluate the second model
df['scaled_prediction_c_per_kWh'] = lr_model.predict(X_second_pass)
scaled_y_pred = lr_model.predict(X_test_sp)
print(f"Scaled Mean Absolute Error (MAE): {mean_absolute_error(y_test_sp, scaled_y_pred)}")
print(f"Scaled Mean Squared Error (MSE): {mean_squared_error(y_test_sp, scaled_y_pred)}")
print(f"Scaled Coefficient of Determination (R² score): {r2_score(y_test_sp, scaled_y_pred)}")

# Save the DataFrame with both initial and scaled predictions
df.to_csv('nordpool-spot-with-weather-and-scaled-prediction.csv', index=False)
print("Saved the dataset with initial and scaled predictions to 'nordpool-spot-with-weather-and-scaled-prediction.csv'")