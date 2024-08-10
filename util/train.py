import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.model_selection import permutation_test_score
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.stattools import acf
from sklearn.utils import shuffle

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
    df['day_of_week'] = df['timestamp'].dt.dayofweek + 1
    df['hour'] = df['timestamp'].dt.hour
    df['month'] = df['timestamp'].dt.month

    # Remove outliers using the IQR method
    Q1 = df['Price_cpkWh'].quantile(0.25)
    Q3 = df['Price_cpkWh'].quantile(0.75)
    IQR = Q3 - Q1

    # This leaves a lot of "outliers" into the data, but that was necessary to retain the exteme price spikes that are the most interesting to predict.
    min_threshold = Q1 - 3 * IQR
    max_threshold = Q3 + 100 * IQR
    df_filtered = df[(df['Price_cpkWh'] >= min_threshold) & (df['Price_cpkWh'] <= max_threshold)]

    # TODO: Training without WindPowerCapacityMW results in a marginally better model, so for now we are not including it. Perhaps it had more importance when we had a direct WindPowerMW feature. We use the wind speed and temperature from the FMI data as proxies for wind power generation. This is something to be studied further, given time. Does increasing the nr of weather stations for wind park wind speeds and urban area temperatures improve the model? Make it worse? Or no difference?

    # Define features and target for the first model after outlier removal
    # If you defined a different set of FMI stations in your .env.local, they should automatically be reflected here
    # You may need to manually add those ws_ and t_ columns to your SQLite database first though; TODO: Automate this process
    # X_filtered = df_filtered[['day_of_week', 'hour', 'month', 'NuclearPowerMW'] + fmisid_ws + fmisid_t]

    # TODO: 2024-08-10: We're dropping MONTH information for now, as historical month data can be misleading for the model; inspect this again.
    X_filtered = df_filtered[['day_of_week', 'hour', 'NuclearPowerMW'] + fmisid_ws + fmisid_t]
    y_filtered = df_filtered['Price_cpkWh']

    # Train the first model (Random Forest) on the filtered data
    # TODO: Make a --continuous option explicit, not implicit like it is now, if also running --prediction
    X_train, X_test, y_train, y_test = train_test_split(
        X_filtered, 
        y_filtered, 
        test_size=0.15, # a compromise between 0.1 and 0.2 with limited data available
        random_state=42
        )
    
    # These do make a difference.
    # Original set:
    # rf = RandomForestRegressor(
    #     n_estimators=150, 
    #     max_depth=15, 
    #     min_samples_split=4, 
    #     min_samples_leaf=2, 
    #     max_features='sqrt', 
    #     random_state=42
    #     )
    
    # Updated model training code with new best parameters found via grid search (2024-03-07)
    rf = RandomForestRegressor(
        n_estimators=150,          # Same as before
        max_depth=20,              # Increased from 15 to 20 based on best parameters
        min_samples_split=2,       # Reduced from 4 to 2, allowing finer decision boundaries
        min_samples_leaf=4,        # Increased from 2 to 4, providing more generalization at leaves
        random_state=42            # Keeping the random state for reproducibility
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
        # X_random_sample = random_sample[['day_of_week', 'hour', 'month', 'NuclearPowerMW'] + fmisid_ws + fmisid_t]
        
        # TODO: 2024-08-10: We're dropping MONTH information for now, as historical month data can be misleading for the model; inspect this again.
        X_random_sample = random_sample[['day_of_week', 'hour', 'NuclearPowerMW'] + fmisid_ws + fmisid_t]
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
    
    return mae, mse, r2, samples_mae, samples_mse, samples_r2, rf

"This is not meant to be executed directly."