import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.stattools import acf
from xgboost import XGBRegressor
from .logger import logger
from .xgb_utils import configure_cuda, booster_predict
from . import features_pricing as pricing


def train_model(df, fmisid_ws, fmisid_t):
    logger.info("Training a pricing model")

    # Drop the target column from training data
    df = df.drop(columns=["PricePredict_cpkWh"])

    df = pricing.add_time(df)
    df = pricing.add_temp(df, fmisid_t)

    # Cap extreme outliers based on percentiles and filter the DataFrame
    upper_limit = df["Price_cpkWh"].quantile(0.9995)
    lower_limit = df["Price_cpkWh"].quantile(0.0008)
    df["Price_cpkWh"] = np.clip(df["Price_cpkWh"], lower_limit, upper_limit)

    X_filtered = df[pricing.cols(fmisid_ws, fmisid_t)]

    # Target variable
    y_filtered = df["Price_cpkWh"]

    # Split the data
    X_train, X_test, y_train, y_test = train_test_split(
        X_filtered, y_filtered, test_size=0.10, random_state=42, shuffle=True
    )

    logger.info(f"Training data shape: {X_train.shape}, sample:")
    print(X_train.sample(10, random_state=42))

    # Print feature columns used in training
    logger.info("Pricing model feature columns:")
    logger.info(", ".join(X_train.columns))

    # See train_xgb.txt for history of hyperparameter tuning
    # Last update: 2025-01-19
    params = {
        "early_stopping_rounds": 50,
        "objective": "reg:squarederror",
        "eval_metric": "rmse",
        "n_estimators": 11655,
        "max_depth": 6,
        "learning_rate": 0.012158906047644169,
        "subsample": 0.6717186457667352,
        "colsample_bytree": 0.5938032371628845,
        "gamma": 0.02297259369577767,
        "reg_alpha": 1.4624622196040324,
        "reg_lambda": 0.09870580997491653,
        "random_state": 42,
    }
    params = configure_cuda(params, logger)

    # Train the model
    logger.info("XGBoost for price prediction: ")
    logger.info(", ".join(f"{k}={v}" for k, v in params.items()))

    # First, create a model with early stopping to find the optimal number of trees
    logger.info("Fitting model with early stopping...")
    early_stopping_model = XGBRegressor(**params)
    early_stopping_model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=500)

    # Get the best iteration from early stopping
    best_iteration = early_stopping_model.best_iteration
    logger.info(f"Best iteration from early stopping: {best_iteration}")

    # Create a copy of params without early_stopping_rounds for the final fit
    training_params = {k: v for k, v in params.items() if k != "early_stopping_rounds"}

    # Set the optimal number of trees and refit on all data without early stopping
    final_model = XGBRegressor(**training_params)
    final_model.set_params(n_estimators=best_iteration)
    logger.info(
        f"Refitting model on all data with optimal n_estimators={best_iteration}..."
    )
    final_model.fit(X_filtered, y_filtered, verbose=500)

    # Use the final model (trained on all data) for further evaluation
    xgb_model = final_model

    # SHAP analysis
    # logger.info(f"SHAP feature importances (Mean Absolute SHAP Values per Feature):")
    # explainer = shap.TreeExplainer(xgb_model)
    # shap_values = explainer.shap_values(X_test, check_additivity=False)

    # # Aggregate mean absolute SHAP values per feature for console display
    # shap_summary = np.abs(shap_values).mean(axis=0)
    # shap_summary_df = pd.DataFrame({
    #     'Feature': X_test.columns,
    #     'Mean |SHAP Value|': shap_summary
    # }).sort_values(by='Mean |SHAP Value|', ascending=False)

    # logger.info(shap_summary_df.to_string(index=False))

    # Residual analysis
    y_pred_filtered = booster_predict(xgb_model, X_test)
    residuals = y_test - y_pred_filtered

    # Durbin-Watson test for autocorrelation
    dw_stat = durbin_watson(residuals)
    logger.info(f"Durbin-Watson autocorrelation test: {dw_stat:.2f}")

    # Autocorrelation Function for the first 5 lags
    acf_values = acf(residuals, nlags=5, fft=False)
    logger.info("ACF values for the first 5 lags:")
    for lag, value in enumerate(acf_values, start=1):
        logger.info(f"  Lag {lag}: {value:.4f}")

    # Calculate metrics
    mae = mean_absolute_error(y_test, y_pred_filtered)
    mse = mean_squared_error(y_test, y_pred_filtered)
    r2 = r2_score(y_test, y_pred_filtered)

    # Initialize lists to store metrics for random sampling (sanity check)
    mae_list, mse_list, r2_list = [], [], []

    # Perform random sampling and evaluation 10 times
    for _ in range(10):
        random_sample = df.sample(n=500, random_state=None)

        random_sample = pricing.add_time(random_sample)
        random_sample = pricing.add_temp(random_sample, fmisid_t)
        X_random_sample = random_sample[pricing.cols(fmisid_ws, fmisid_t)]

        y_random_sample_true = random_sample["Price_cpkWh"]
        y_random_sample_pred = booster_predict(xgb_model, X_random_sample)

        mae_list.append(mean_absolute_error(y_random_sample_true, y_random_sample_pred))
        mse_list.append(mean_squared_error(y_random_sample_true, y_random_sample_pred))
        r2_list.append(r2_score(y_random_sample_true, y_random_sample_pred))

    # Calculate mean of evaluation metrics
    samples_mae = np.mean(mae_list)
    samples_mse = np.mean(mse_list)
    samples_r2 = np.mean(r2_list)

    logger.info(
        f"Training results:\n  MAE (vs test set): {mae}\n  MSE (vs test set): {mse}\n  R² (vs test set): {r2}"
        f"\n  MAE (vs 10x500 randoms): {samples_mae}\n  MSE (vs 10x500 randoms): {samples_mse}\n  R² (vs 10x500 randoms): {samples_r2}"
    )

    return xgb_model
