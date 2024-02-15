import pandas as pd
import numpy as np
import joblib  # Import joblib for model persistence
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.impute import SimpleImputer
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

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

# Remove outliers using the IQR method
Q1 = df_preprocessed['Price [c/kWh]'].quantile(0.1)
Q3 = df_preprocessed['Price [c/kWh]'].quantile(0.9)
IQR = Q3 - Q1
min_threshold = Q1 - 1.5 * IQR
max_threshold = Q3 + 1.5 * IQR
df_filtered = df_preprocessed[(df_preprocessed['Price [c/kWh]'] >= min_threshold) & (df_preprocessed['Price [c/kWh]'] <= max_threshold)]

# Define features and target for the first model after outlier removal
X_filtered = df_filtered[['Temp [°C]', 'Wind [m/s]', 'hour', 'day_of_week', 'month']]
y_filtered = df_filtered['Price [c/kWh]']

# Train the first model (Random Forest) on the filtered data
X_train, X_test, y_train, y_test = train_test_split(X_filtered, y_filtered, test_size=0.2, random_state=42)
rf = RandomForestRegressor(n_estimators=150, max_depth=15, min_samples_split=4, min_samples_leaf=2, max_features='sqrt', random_state=42)
rf.fit(X_train, y_train)
joblib.dump(rf, 'electricity_price_rf_model.joblib')

# Now apply predictions to the entire original dataset for plotting
X_full = df_preprocessed[['Temp [°C]', 'Wind [m/s]', 'hour', 'day_of_week', 'month']]
df['prediction_c_per_kWh'] = rf.predict(X_full)

# Evaluate the first model using the filtered dataset
y_pred_filtered = rf.predict(X_test)
print(f"Initial Mean Absolute Error (MAE): {mean_absolute_error(y_test, y_pred_filtered)}")
print(f"Initial Mean Squared Error (MSE): {mean_squared_error(y_test, y_pred_filtered)}")
print(f"Initial Coefficient of Determination (R² score): {r2_score(y_test, y_pred_filtered)}")

# Now plot using the full dataset including outliers
df['timestamp_UTC'] = pd.to_datetime(df['timestamp_UTC'], unit='s')  # Ensure correct conversion

def plot_actual_vs_predicted(df):
    plt.figure(figsize=(14, 8))

    # Ensure the DataFrame is sorted by timestamp if not already
    df.sort_values('timestamp_UTC', inplace=True)

    # Plot using pandas plot for better date handling
    df.set_index('timestamp_UTC', inplace=True)
    df[['price_cents_per_kWh', 'prediction_c_per_kWh']].plot(figsize=(14, 8), linewidth=0.5, alpha=0.75)
    
    plt.title('Actual vs. Predicted Electricity Prices', fontsize=16)
    plt.ylabel('Price [c/kWh]', fontsize=14)
    plt.xlabel('Timestamp', fontsize=14)  # May be redundant as pandas handles datetime index
    plt.legend(['Actual Price', 'Predicted Price'], fontsize=12)

    # Set major ticks format
    plt.gca().xaxis.set_major_locator(mdates.MonthLocator())
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    # Optional: Set minor ticks format
    plt.gca().xaxis.set_minor_locator(mdates.WeekLocator())
    plt.gca().xaxis.set_minor_formatter(mdates.DateFormatter('%d'))

    plt.xticks(rotation=45, fontsize=12)
    plt.yticks(fontsize=12)

    plt.tight_layout()
    plt.savefig('actual_vs_predicted_prices.png', dpi=300)
    plt.close()
