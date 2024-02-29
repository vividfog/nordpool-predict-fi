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

def train_model(df, output_path, fmisid_ws, fmisid_t):
    
    # Sort the data frame by timestamp
    df = df.sort_values(by='timestamp')
    
    print("Training the model with data frame:\n", df)

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['day_of_week'] = df['timestamp'].dt.dayofweek + 1
    df['hour'] = df['timestamp'].dt.hour
    df['month'] = df['timestamp'].dt.month

    # Remove outliers using the IQR method
    Q1 = df['Price_cpkWh'].quantile(0.25)
    Q3 = df['Price_cpkWh'].quantile(0.75)
    IQR = Q3 - Q1

    min_threshold = Q1 - 3 * IQR
    max_threshold = Q3 + 100 * IQR
    df_filtered = df[(df['Price_cpkWh'] >= min_threshold) & (df['Price_cpkWh'] <= max_threshold)]

    # TODO: Training without WindPowerCapacityMW results in a marginally better model, so for now we are not including it. Perhaps it had more importance when we had a direct WindPowerMW feature. We use the wind speed and temperature from the FMI data as proxies for wind power generation. This is something to be studied further, given time. Does increasing the nr of weather stations for wind park wind speeds and urban area temperatures improve the model? Make it worse? Or no difference?

    # Define features and target for the first model after outlier removal
    X_filtered = df_filtered[['day_of_week', 'hour', 'month', 'NuclearPowerMW'] + fmisid_ws + fmisid_t]
    y_filtered = df_filtered['Price_cpkWh']

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
        X_random_sample = random_sample[['day_of_week', 'hour', 'month', 'NuclearPowerMW'] + fmisid_ws + fmisid_t]
        y_filtered = df_filtered['Price_cpkWh']
        y_random_sample_true = random_sample['Price_cpkWh']

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

# If trying to execute this script directly, print a message and exit
"This is not meant to be executed directly."