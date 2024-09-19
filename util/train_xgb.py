import shap
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

    # Cap extreme outliers based on percentiles and filter the DataFrame
    upper_limit = df['Price_cpkWh'].quantile(0.9995)
    lower_limit = df['Price_cpkWh'].quantile(0.0008)
    df['Price_cpkWh'] = np.clip(df['Price_cpkWh'], lower_limit, upper_limit)

    # Preprocess cyclical time-based features
    df['day_of_week_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
    df['day_of_week_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)

    # Use the updated feature selection
    X_filtered = df[['day_of_week_sin', 'day_of_week_cos', 'hour_sin', 'hour_cos',
                     'NuclearPowerMW', 'ImportCapacityMW', 'WindPowerMW'] + fmisid_t]
    y_filtered = df['Price_cpkWh']
  
    print("→ Data for training, a sampling:")
    print(X_filtered.head())

    # Split the data
    X_train, X_test, y_train, y_test = train_test_split(
        X_filtered, 
        y_filtered, 
        test_size=0.15,
        random_state=42
    )
    
    # XGBoost model, tuned 2024-09-15
    # xgb_model = XGBRegressor(
    #     n_estimators=961,
    #     max_depth=8,
    #     learning_rate=0.0305,
    #     subsample=0.7256,
    #     colsample_bytree=0.5344,
    #     gamma=0.0247,
    #     reg_alpha=0.8735,
    #     reg_lambda=0.7603,
    #     random_state=42
    # )
        
    # XGBoost 10000 rounds with nested CV and K-split, 2024-09-19
    xgb_model = XGBRegressor(
        n_estimators=7467,
        max_depth=6,
        learning_rate=0.02484589286162099,
        subsample=0.35399400017778704,
        colsample_bytree=0.6830482625298456,
        gamma=0.0032089426199345406,
        reg_alpha=3.6905699541222847,
        reg_lambda=0.005134966919362188,
        random_state=42
    )

    #      Model Performance Comparison - Test Set Metrics
    # ┏━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┓
    # ┃ Model   ┃    MAE ┃    MSE ┃   RMSE ┃     R² ┃   SMAPE ┃
    # ┡━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━┩
    # │ XGBoost │ 1.1606 │ 6.0288 │ 2.4554 │ 0.8690 │ 38.6508 │
    # └─────────┴────────┴────────┴────────┴────────┴─────────┘
    #               5-Fold Cross-Validation Results
    # ┏━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┓
    # ┃ Model   ┃ CV MAE ┃ CV MSE ┃ CV RMSE ┃  CV R² ┃ CV SMAPE ┃
    # ┡━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━┩
    # │ XGBoost │ 1.2358 │ 6.1301 │  2.4759 │ 0.8878 │  41.9760 │
    # └─────────┴────────┴────────┴─────────┴────────┴──────────┘
    #                       Autocorrelation Analysis
    # ┏━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
    # ┃ Model   ┃ Durbin-Watson ┃ ACF (Lag 1) ┃ ACF (Lag 2) ┃ ACF (Lag 3) ┃
    # ┡━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
    # │ XGBoost │        1.9841 │      0.0074 │      0.0102 │      0.0093 │
    # └─────────┴───────────────┴─────────────┴─────────────┴─────────────┘

    # Top 10 Feature Importance for XGBoost:
    #             Feature  Importance
    # 0   day_of_week_sin    0.089599
    # 9          t_101661    0.077820
    # 19         t_101485    0.061823
    # 6       WindPowerMW    0.051509
    # 3          hour_cos    0.049792
    # 17         t_101256    0.048891
    # 4    NuclearPowerMW    0.047275
    # 8          t_101673    0.045575
    # 1   day_of_week_cos    0.043805
    # 25         t_100932    0.041732

    xgb_model.fit(X_train, y_train)
    
    # XGB feature importances
    feature_importances = xgb_model.feature_importances_
    features = X_train.columns
    importance_df = pd.DataFrame({'Feature': features, 'Importance': feature_importances}).sort_values(by='Importance', ascending=False)
    print("→ XGB feature importances:")
    print(importance_df.to_string(index=False))

    # SHAP analysis
    explainer = shap.TreeExplainer(xgb_model)
    shap_values = explainer.shap_values(X_test, check_additivity=False)

    # Aggregate mean absolute SHAP values per feature for console display
    shap_summary = np.abs(shap_values).mean(axis=0)
    shap_summary_df = pd.DataFrame({
        'Feature': X_test.columns,
        'Mean |SHAP Value|': shap_summary
    }).sort_values(by='Mean |SHAP Value|', ascending=False)

    print("\n→ SHAP feature importances (Mean Absolute SHAP Values per Feature):")
    print(shap_summary_df.to_string(index=False))

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

    # Initialize lists to store metrics for random sampling
    mae_list, mse_list, r2_list = [], [], []

    # Perform random sampling and evaluation 10 times
    for _ in range(10):
        random_sample = df.sample(n=500, random_state=None)
        
        # Compute cyclical features
        random_sample['day_of_week_sin'] = np.sin(2 * np.pi * random_sample['day_of_week'] / 7)
        random_sample['day_of_week_cos'] = np.cos(2 * np.pi * random_sample['day_of_week'] / 7)
        random_sample['hour_sin'] = np.sin(2 * np.pi * random_sample['hour'] / 24)
        random_sample['hour_cos'] = np.cos(2 * np.pi * random_sample['hour'] / 24)
        
        # Match the feature selection used for training
        X_random_sample = random_sample[['day_of_week_sin', 'day_of_week_cos', 'hour_sin', 'hour_cos',
                                        'NuclearPowerMW', 'ImportCapacityMW', 'WindPowerMW'] + fmisid_t]
        
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