import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.model_selection import permutation_test_score
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.stattools import acf
from sklearn.utils import shuffle
from rich import print

import pandas as pd

def train_model(df, fmisid_ws, fmisid_t):
    
    # Sort the data frame by timestamp
    # df = df.sort_values(by='timestamp')
    
    # Or we can shuffle to get a bit more generalized model and evals
    df = shuffle(df, random_state=42)
    
    # We don't need what we are trying to predict in the training data
    df = df.drop(columns=['PricePredict_cpkWh'])

    # Infer some missing, required time-related features from the timestamp
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['month'] = df['timestamp'].dt.month
    df['day_of_week'] = df['timestamp'].dt.dayofweek + 1
    df['hour'] = df['timestamp'].dt.hour

    # Remove outliers using the IQR method
    Q1 = df['Price_cpkWh'].quantile(0.25)
    Q3 = df['Price_cpkWh'].quantile(0.75)
    IQR = Q3 - Q1

    # Higher multipliers include more data, but also more extreme outliers
    min_threshold = Q1 - 2.5 * IQR
    max_threshold = Q3 + 2.5 * IQR
    df_filtered = df[(df['Price_cpkWh'] >= min_threshold) & (df['Price_cpkWh'] <= max_threshold)]

    # Define features and target for the first model after outlier removal
    # If you defined a different set of FMI stations in your .env.local, they should automatically be reflected here
    # You may need to manually add those ws_ and t_ columns to your SQLite database first though; TODO: Automate this process

    # TODO: 2024-08-10: We're dropping MONTH information for now, as historical month data can be misleading for the model; inspect this again.
    X_filtered = df_filtered[['day_of_week', 'hour', 'NuclearPowerMW', 'ImportCapacityMW'] + fmisid_ws + fmisid_t]
    y_filtered = df_filtered['Price_cpkWh']
  
    # Show the first few rows of the filtered data
    print("→ Data for training, a sampling:")
    print(X_filtered.head())

    # Train the first model (Random Forest) on the filtered data
    X_train, X_test, y_train, y_test = train_test_split(
        X_filtered, 
        y_filtered, 
        test_size=0.15,
        random_state=42
        )
    
    # Grid search (2024-08-31)
    rf = RandomForestRegressor(
        n_estimators=959,
        max_depth=21,
        min_samples_split=2,
        min_samples_leaf=1,
        max_features=0.55,
        bootstrap=False,
        criterion='squared_error',
        random_state=42
    )
    
    rf.fit(X_train, y_train)
    
    # Feature importances
    feature_importances = rf.feature_importances_
    features = X_train.columns
    importance_df = pd.DataFrame({'Feature': features, 'Importance': feature_importances}).sort_values(by='Importance', ascending=False)
    print("→ Feature Importance:")
    print(importance_df.to_string(index=False))

    # Evaluate the model using the filtered dataset
    y_pred_filtered = rf.predict(X_test)
    residuals = y_test - y_pred_filtered
    
    # Durbin-Watson test for autocorrelation
    dw_stat = durbin_watson(residuals)
    print(f"→ Durbin-Watson autocorrelation test: {dw_stat:.2f}")
    
    # Autocorrelation Function for the first 5 lags
    acf_values = acf(residuals, nlags=5, fft=False)
    print("→ ACF values for the first 5 lags:")
    for lag, value in enumerate(acf_values, start=1):
        print(f"  Lag {lag}: {value:.4f}")
        
    # # Permutation Test
    # # This will take long; uncomment if you want to run it
    # print(f"→ Permutation Test Results (will take LONG while):")
    # score, permutation_scores, pvalue = permutation_test_score(
    #     rf, X_train, y_train, 
    #     scoring="neg_mean_squared_error", 
    #     cv=5, 
    #     n_permutations=100, 
    #     n_jobs=1, # One for this hardware, try -1 for yours 
    #     random_state=42
    # )
    # print(f"  Permutations Baseline MSE: {-score:.4f}")  # Negating score because we used neg_mean_squared_error
    # print(f"  Permutation Scores Mean MSE: {-permutation_scores.mean():.4f}")
    # print(f"  p-value: {pvalue:.4f}")
    
    # print("\nResults for the model (Random Forest):")
    mae = mean_absolute_error(y_test, y_pred_filtered)
    mse = mean_squared_error(y_test, y_pred_filtered)
    r2 = r2_score(y_test, y_pred_filtered)

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
        # X_random_sample = random_sample[['day_of_week', 'hour', 'month', 'NuclearPowerMW'] + fmisid_ws + fmisid_t]
        
        # TODO: 2024-08-10: We're dropping MONTH information for now, as historical month data can be misleading for the model; inspect this again.
        X_random_sample = random_sample[['day_of_week', 'hour', 'NuclearPowerMW', 'ImportCapacityMW'] + fmisid_ws + fmisid_t]
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
    
    return mae, mse, r2, samples_mae, samples_mse, samples_r2, rf