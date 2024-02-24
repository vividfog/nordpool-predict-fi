###
### TODO: Convert to a routine rather than a script
###

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

import pandas as pd
import sqlite3
from datetime import datetime
import pytz

def csv_to_df(csv_path):
    # Read the CSV file into a DataFrame
    df = pd.read_csv(csv_path, na_values='-')

    # Convert the timestamp to datetime
    df['timestamp_UTC'] = pd.to_datetime(df['timestamp_UTC'], unit='s')

    # Rename the columns to match the database schema
    df = df.rename(columns={
        'timestamp_UTC': 'timestamp',
        'price_cents_per_kWh': 'Price [c/kWh]',
        'temp_celsius': 'Temp [°C]',
        'wind_m/s': 'Wind [m/s]',
        'wind_power_MWh': 'Wind Power [MWh]',
        'wind_power_capacity_MWh': 'Wind Power Capacity [MWh]'
    })

    df = df.drop(columns=['helsinki'])

    imputer = SimpleImputer(strategy='mean')
    df[['Temp [°C]', 'Wind [m/s]', 'Wind Power [MWh]', 'Wind Power Capacity [MWh]', 'Price [c/kWh]']] = imputer.fit_transform(df[['Temp [°C]', 'Wind [m/s]', 'Wind Power [MWh]', 'Wind Power Capacity [MWh]', 'Price [c/kWh]']])

    # Add the additional columns with NULL values
    df['PricePredict [c/kWh]'] = None

    return df

def train_model(df, output_path):

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['day_of_week'] = df['timestamp'].dt.dayofweek + 1
    df['hour'] = df['timestamp'].dt.hour
    df['month'] = df['timestamp'].dt.month

    # Remove outliers using the IQR method
    Q1 = df['Price [c/kWh]'].quantile(0.25)
    Q3 = df['Price [c/kWh]'].quantile(0.75)
    IQR = Q3 - Q1

    min_threshold = Q1 - 3 * IQR
    max_threshold = Q3 + 100 * IQR
    df_filtered = df[(df['Price [c/kWh]'] >= min_threshold) & (df['Price [c/kWh]'] <= max_threshold)]

    # Define features and target for the first model after outlier removal
    X_filtered = df_filtered[['Temp [°C]', 'Wind [m/s]', 'Wind Power [MWh]', 'Wind Power Capacity [MWh]', 'hour', 'day_of_week', 'month']]
    y_filtered = df_filtered['Price [c/kWh]']

    # Train the first model (Random Forest) on the filtered data
    X_train, X_test, y_train, y_test = train_test_split(X_filtered, y_filtered, test_size=0.2, random_state=42)
    rf = RandomForestRegressor(n_estimators=150, max_depth=15, min_samples_split=4, min_samples_leaf=2, max_features='sqrt', random_state=42)
    rf.fit(X_train, y_train)
    joblib.dump(rf, output_path)

    # Evaluate the model using the filtered dataset
    y_pred_filtered = rf.predict(X_test)
    # print("\nResults for the model (Random Forest):")
    mae = mean_absolute_error(y_test, y_pred_filtered)
    mse = mean_squared_error(y_test, y_pred_filtered)
    r2 = r2_score(y_test, y_pred_filtered)
    # print(f"Mean Absolute Error (MAE): {mae}")
    # print(f"Mean Squared Error (MSE): {mse}")
    # print(f"Coefficient of Determination (R² score): {r2}")

    # Initialize lists to store metrics for each iteration
    mae_list = []
    mse_list = []
    r2_list = []

    # Perform the random sampling and evaluation 10 times
    # print("\nResults for 10 batches of 500 random samples:")
    for _ in range(10):
        # Select 500 truly random points from the original dataset that includes outliers
        random_sample = df.sample(n=500, random_state=None)  # 'None' for truly random behavior

        # Pick input/output features for the random sample
        X_random_sample = random_sample[['Temp [°C]', 'Wind [m/s]', 'Wind Power [MWh]', 'Wind Power Capacity [MWh]', 'hour', 'day_of_week', 'month']]
        y_random_sample_true = random_sample['Price [c/kWh]']

        # Predict the prices for the randomly selected samples
        y_random_sample_pred = rf.predict(X_random_sample)

        # Calculate evaluation metrics for the random sets
        mae_list.append(mean_absolute_error(y_random_sample_true, y_random_sample_pred))
        mse_list.append(mean_squared_error(y_random_sample_true, y_random_sample_pred))
        r2_list.append(r2_score(y_random_sample_true, y_random_sample_pred))

    # Calculate and print the mean of the evaluation metrics across all iterations
    samples_mae = np.mean(mae_list)
    samples_mse = np.mean(mse_list)
    samples_r2 = np.mean(r2_list)
    # print(f"Mean Random Batch MAE: {samples_mae}")
    # print(f"Mean Random Batch MSE: {samples_mse}")
    # print(f"Mean Random Batch R² score: {samples_r2}")
    
    return mae, mse, r2, samples_mae, samples_mse, samples_r2

if __name__ == "__main__":
    print("This is not meant to be executed directly.")
    exit()
