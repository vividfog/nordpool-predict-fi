import shap
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.stattools import acf
from rich import print
from xgboost import XGBRegressor
import pytz

def train_model(df, fmisid_ws, fmisid_t):
        
    print("* Training a pricing model")
    
    # Drop the target column from training data
    df = df.drop(columns=['PricePredict_cpkWh'])

    # Process timestamp
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['day_of_week'] = df['timestamp'].dt.dayofweek + 1
    df['hour'] = df['timestamp'].dt.hour
    df['year'] = df['timestamp'].dt.year

    # Cap extreme outliers based on percentiles and filter the DataFrame
    upper_limit = df['Price_cpkWh'].quantile(0.9995)

    # lower_limit = df['Price_cpkWh'].quantile(0.0008) # 2024
    lower_limit = df['Price_cpkWh'].quantile(0.004) # 2025-01-18 optimized?

    df['Price_cpkWh'] = np.clip(df['Price_cpkWh'], lower_limit, upper_limit)
    print(f"→ Capped 'Price_cpkWh' at lower_limit: {lower_limit} and upper_limit: {upper_limit}")

    # Preprocess cyclical time-based features
    df['day_of_week_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
    df['day_of_week_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)

    # Calculate temp_mean and temp_variance
    df['temp_mean'] = df[fmisid_t].mean(axis=1)
    df['temp_variance'] = df[fmisid_t].var(axis=1)

    # Feature selection
    X_filtered = df[['year', 'day_of_week_sin', 'day_of_week_cos', 'hour_sin', 'hour_cos', 
                     'NuclearPowerMW', 'ImportCapacityMW', 'WindPowerMW', 
                     'temp_mean', 'temp_variance', 'holiday', 
                     'sum_irradiance', 'mean_irradiance', 'std_irradiance', 'min_irradiance', 'max_irradiance',
                     'SE1_FI', 'SE3_FI', 'EE_FI',
                     'eu_ws_EE01', 'eu_ws_EE02', 'eu_ws_DK01', 'eu_ws_DK02', 'eu_ws_DE01', 'eu_ws_DE02', 'eu_ws_SE01', 'eu_ws_SE02', 'eu_ws_SE03'] + fmisid_t + fmisid_ws]

    # Target variable
    y_filtered = df['Price_cpkWh']
  
    # Split the data
    X_train, X_test, y_train, y_test = train_test_split(
        X_filtered, 
        y_filtered, 
        test_size=0.10, # Using almost all data, as the model is used instantly and evaluation has its own routines elsewhere
        random_state=42,
        shuffle=True
    )
  
    print(f"→ Training data shape: {X_train.shape}, sample:")
    print(X_train.sample(10, random_state=42))

    # Print feature columns used in training
    print("→ Pricing model feature columns:")
    print(", ".join(X_train.columns))

    # See train_xgb.txt for history of hyperparameter tuning
    # Last update: 2025-01-19
    params = {
        'early_stopping_rounds': 50,
        'objective': 'reg:squarederror',
        'eval_metric': 'rmse',
        'n_estimators': 11655,
        'max_depth': 6,
        'learning_rate': 0.012158906047644169,
        'subsample': 0.6717186457667352,
        'colsample_bytree': 0.5938032371628845,
        'gamma': 0.02297259369577767,
        'reg_alpha': 1.4624622196040324,
        'reg_lambda': 0.09870580997491653,
        'random_state': 42,
    }

    # Train the model
    print("→ XGBoost: ", end="")
    print(", ".join(f"{k}={v}" for k, v in params.items()))

    xgb_model = XGBRegressor(**params)
    xgb_model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=500)

    # SHAP analysis
    # print("→ SHAP feature importances (Mean Absolute SHAP Values per Feature):")
    # explainer = shap.TreeExplainer(xgb_model)
    # shap_values = explainer.shap_values(X_test, check_additivity=False)

    # # Aggregate mean absolute SHAP values per feature for console display
    # shap_summary = np.abs(shap_values).mean(axis=0)
    # shap_summary_df = pd.DataFrame({
    #     'Feature': X_test.columns,
    #     'Mean |SHAP Value|': shap_summary
    # }).sort_values(by='Mean |SHAP Value|', ascending=False)

    # print(shap_summary_df.to_string(index=False))

    # Residual analysis
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

    # Initialize lists to store metrics for random sampling (sanity check)
    mae_list, mse_list, r2_list = [], [], []

    # Perform random sampling and evaluation 10 times
    for _ in range(10):
        random_sample = df.sample(n=500, random_state=None)
        
        # Compute cyclical features
        random_sample['day_of_week_sin'] = np.sin(2 * np.pi * random_sample['day_of_week'] / 7)
        random_sample['day_of_week_cos'] = np.cos(2 * np.pi * random_sample['day_of_week'] / 7)
        random_sample['hour_sin'] = np.sin(2 * np.pi * random_sample['hour'] / 24)
        random_sample['hour_cos'] = np.cos(2 * np.pi * random_sample['hour'] / 24)

        # Compute temp_mean and temp_variance
        random_sample['temp_mean'] = random_sample[fmisid_t].mean(axis=1)
        random_sample['temp_variance'] = random_sample[fmisid_t].var(axis=1)
        
        # Match the feature selection used for training
        X_random_sample = random_sample[['year','day_of_week_sin', 'day_of_week_cos', 'hour_sin', 'hour_cos',
                                        'NuclearPowerMW', 'ImportCapacityMW', 'WindPowerMW',
                                        'temp_mean', 'temp_variance', 'holiday',
                                        'sum_irradiance', 'mean_irradiance', 'std_irradiance', 'min_irradiance', 'max_irradiance',
                                        'SE1_FI', 'SE3_FI', 'EE_FI',
                                        'eu_ws_EE01', 'eu_ws_EE02', 'eu_ws_DK01', 'eu_ws_DK02', 'eu_ws_DE01', 'eu_ws_DE02', 'eu_ws_SE01', 'eu_ws_SE02', 'eu_ws_SE03'] + fmisid_t + fmisid_ws]
        
        y_random_sample_true = random_sample['Price_cpkWh']
        y_random_sample_pred = xgb_model.predict(X_random_sample)
        
        mae_list.append(mean_absolute_error(y_random_sample_true, y_random_sample_pred))
        mse_list.append(mean_squared_error(y_random_sample_true, y_random_sample_pred))
        r2_list.append(r2_score(y_random_sample_true, y_random_sample_pred))
        
    # Calculate mean of evaluation metrics
    samples_mae = np.mean(mae_list)
    samples_mse = np.mean(mse_list)
    samples_r2 = np.mean(r2_list)

    print(f"→ Training results:\n  MAE (vs test set): {mae}\n  MSE (vs test set): {mse}\n  R² (vs test set): {r2}"
          f"\n  MAE (vs 10x500 randoms): {samples_mae}\n  MSE (vs 10x500 randoms): {samples_mse}\n  R² (vs 10x500 randoms): {samples_r2}")

    return xgb_model
