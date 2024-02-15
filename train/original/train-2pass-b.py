import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
import joblib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Function to preprocess the dataset
def preprocess_data(filepath):
    df = pd.read_csv(filepath, delimiter=';', na_values='-')
    df['datetime_helsinki'] = pd.to_datetime(df['day.month.year_time_helsinki'], format='%d.%m.%Y %H:%M')
    df['timestamp_UTC'] = pd.to_datetime(df['timestamp_UTC'], unit='s')
    df['day_of_week'] = df['datetime_helsinki'].dt.dayofweek + 1
    df['hour'] = df['datetime_helsinki'].dt.hour
    df['month'] = df['datetime_helsinki'].dt.month
    df.rename(columns={'temp_celsius': 'Temp [°C]', 'wind_m/s': 'Wind [m/s]', 'price_cents_per_kWh': 'Price [c/kWh]'}, inplace=True)
    return df

# Load and preprocess the dataset
filepath = 'nordpool-spot-with-weather.csv'
df = preprocess_data(filepath)

# Impute missing values
imputer = SimpleImputer(strategy='mean')
df[['Temp [°C]', 'Wind [m/s]', 'Price [c/kWh]']] = imputer.fit_transform(df[['Temp [°C]', 'Wind [m/s]', 'Price [c/kWh]']])

# Split the data
X = df[['Temp [°C]', 'Wind [m/s]', 'hour', 'day_of_week', 'month']]
y = df['Price [c/kWh]']
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Train a RandomForestRegressor
rf = RandomForestRegressor(n_estimators=150, max_depth=15, min_samples_split=4, min_samples_leaf=2, max_features='sqrt', random_state=42)
rf.fit(X_train, y_train)
joblib.dump(rf, 'electricity_price_rf_model.joblib')

# Predictions for the entire dataset for further use
df['prediction_c_per_kWh'] = rf.predict(X)

# Linear Regression model using both original features and RandomForest predictions
X_lr = df[['Temp [°C]', 'Wind [m/s]', 'hour', 'day_of_week', 'month', 'prediction_c_per_kWh']]
y_lr = df['Price [c/kWh]']

# Split the enhanced dataset
X_train_lr, X_test_lr, y_train_lr, y_test_lr = train_test_split(X_lr, y_lr, test_size=0.2, random_state=42)

# Scale features for Linear Regression
scaler = StandardScaler()
X_train_lr_scaled = scaler.fit_transform(X_train_lr)
X_test_lr_scaled = scaler.transform(X_test_lr)

# Train Linear Regression
lr = LinearRegression()
lr.fit(X_train_lr_scaled, y_train_lr)
joblib.dump(lr, 'linear_regression_model.joblib')

# Evaluate both models
rf_pred = rf.predict(X_test)
lr_pred = lr.predict(X_test_lr_scaled)

print("Random Forest Model Evaluation:")
print(f"MAE: {mean_absolute_error(y_test, rf_pred)}")
print(f"MSE: {mean_squared_error(y_test, rf_pred)}")
print(f"R² score: {r2_score(y_test, rf_pred)}\n")

print("Linear Regression Model Evaluation:")
print(f"MAE: {mean_absolute_error(y_test_lr, lr_pred)}")
print(f"MSE: {mean_squared_error(y_test_lr, lr_pred)}")
print(f"R² score: {r2_score(y_test_lr, lr_pred)}")

# Plotting
def plot_actual_vs_predicted(df):
    plt.figure(figsize=(14, 8))
    df.sort_values('timestamp_UTC', inplace=True)
    df.set_index('timestamp_UTC', inplace=True)
    df[['Price [c/kWh]', 'prediction_c_per_kWh']].plot(figsize=(14, 8), linewidth=1, alpha=0.75)
    plt.title('Actual vs. Predicted Electricity Prices', fontsize=16)
    plt.ylabel('Price [c/kWh]', fontsize=14)
    plt.xlabel('Timestamp', fontsize=14)
    plt.legend(['Actual Price', 'Predicted Price'], fontsize=12)
    plt.gca().xaxis.set_major_locator(mdates.MonthLocator())
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.xticks(rotation=45, fontsize=12)
    plt.yticks(fontsize=12)
    plt.tight_layout()
    plt.savefig('actual_vs_predicted_prices.png', dpi=300)
    plt.close()

plot_actual_vs_predicted(df)
