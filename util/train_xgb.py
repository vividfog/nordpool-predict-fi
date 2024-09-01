import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.stattools import acf
from sklearn.utils import shuffle
from rich import print
from xgboost import XGBRegressor

def train_model(df, fmisid_ws, fmisid_t):
    # Shuffle the data for a more generalized model
    df = shuffle(df, random_state=42)
    
    # Drop the target column from training data
    df = df.drop(columns=['PricePredict_cpkWh'])

    # Process timestamp
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['day_of_week'] = df['timestamp'].dt.dayofweek + 1
    df['hour'] = df['timestamp'].dt.hour

    # Remove outliers using the IQR method
    Q1 = df['Price_cpkWh'].quantile(0.25)
    Q3 = df['Price_cpkWh'].quantile(0.75)
    IQR = Q3 - Q1
    min_threshold = Q1 - 2.5 * IQR
    max_threshold = Q3 + 2.5 * IQR
    df_filtered = df[(df['Price_cpkWh'] >= min_threshold) & (df['Price_cpkWh'] <= max_threshold)]

    # Define features and target
    X_filtered = df_filtered[['day_of_week', 'hour', 'NuclearPowerMW', 'ImportCapacityMW'] + fmisid_ws + fmisid_t]
    y_filtered = df_filtered['Price_cpkWh']
  
    print("→ Data for training, a sampling:")
    print(X_filtered.head())

    # Split the data
    X_train, X_test, y_train, y_test = train_test_split(
        X_filtered, 
        y_filtered, 
        test_size=0.15,
        random_state=42
    )
    
    # XGBoost model, tuned 2024-04-01
    xgb_model = XGBRegressor(
        n_estimators=904,
        max_depth=8,
        learning_rate=0.0379,
        subsample=0.8068,
        colsample_bytree=0.7123,
        gamma=0.0845,
        reg_alpha=0.2744,
        reg_lambda=0.2672,
        max_delta_step=4,
        random_state=42
    )

    xgb_model.fit(X_train, y_train)
    
    # Feature importances
    feature_importances = xgb_model.feature_importances_
    features = X_train.columns
    importance_df = pd.DataFrame({'Feature': features, 'Importance': feature_importances}).sort_values(by='Importance', ascending=False)
    print("→ Feature Importance:")
    print(importance_df.to_string(index=False))

    # Evaluate the model
    y_pred_filtered = xgb_model.predict(X_test)
    residuals = y_test - y_pred_filtered
    
    # Durbin-Watson test for autocorrelation
    dw_stat = durbin_watson(residuals)
    print(f"→ Durbin-Watson autocorrelation test: {dw_stat:.2f}")
    
    # Autocorrelation Function for the first 5 lags
    acf_values = acf(residuals, nlags=5, fft=False)
    print("→ ACF values for the first 5 lags:")
    for lag, value in enumerate(acf_values, start=1):
        print(f"  Lag {lag}: {value:.4f}")
    
    # Calculate metrics
    mae = mean_absolute_error(y_test, y_pred_filtered)
    mse = mean_squared_error(y_test, y_pred_filtered)
    r2 = r2_score(y_test, y_pred_filtered)

    # Initialize lists to store metrics for random sampling
    mae_list, mse_list, r2_list = [], [], []

    # Perform random sampling and evaluation 10 times
    for _ in range(10):
        random_sample = df.sample(n=500, random_state=None)
        X_random_sample = random_sample[['day_of_week', 'hour', 'NuclearPowerMW', 'ImportCapacityMW'] + fmisid_ws + fmisid_t]
        y_random_sample_true = random_sample['Price_cpkWh']

        y_random_sample_pred = xgb_model.predict(X_random_sample)

        mae_list.append(mean_absolute_error(y_random_sample_true, y_random_sample_pred))
        mse_list.append(mean_squared_error(y_random_sample_true, y_random_sample_pred))
        r2_list.append(r2_score(y_random_sample_true, y_random_sample_pred))

    # Calculate mean of evaluation metrics
    samples_mae = np.mean(mae_list)
    samples_mse = np.mean(mse_list)
    samples_r2 = np.mean(r2_list)
    
    return mae, mse, r2, samples_mae, samples_mse, samples_r2, xgb_model