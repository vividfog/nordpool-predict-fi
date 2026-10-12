"""
15-min price model, trained alongside the hourly model (`util/train_xgb.py`) so the
hourly model can be deprecated later.

Same estimator and hyperparameters as the hourly model, trained on a 15-min grid:
- rows: every quarter since the start of the DB history (~4x the hourly rows)
- target: actual quarter prices since QUARTER_START; before that the hourly price for
  all four quarters (that was the settlement price), with `mtu15`=0 so the model can
  tell flat pre-go-live quarters from real 15-min ones
- inputs: the hourly feature set at the finest available resolution (see
  `util/quarter_data.py`), 15-min calendar terms (Helsinki time) and one-hour ramps
- validation: random 10% of whole Helsinki days, so the four near-identical quarters
  of an hour never straddle train and test
"""

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupShuffleSplit
from xgboost import XGBRegressor

from .logger import logger
from .train_xgb import PARAMS
from .xgb_utils import configure_cuda, booster_predict
from . import features_pricing as pricing


def train_model_15min(df_q, fmisid_ws, fmisid_t):
    """
    Train the 15-min price model in memory.

    Args:
        df_q: 15-min frame with features already added (`quarter_data.add_quarter_features`)
            and Price_cpkWh as target; rows with missing required inputs dropped.
        fmisid_ws, fmisid_t: FMI station columns.

    Returns:
        Fitted XGBRegressor (refit on all rows with the early-stopping tree count).
    """
    logger.info("Training a 15-min pricing model")
    df = df_q.drop(columns=["PricePredict_cpkWh"], errors="ignore").copy()

    # Same outlier capping as the hourly model
    upper_limit = df["Price_cpkWh"].quantile(0.9995)
    lower_limit = df["Price_cpkWh"].quantile(0.0008)
    df["Price_cpkWh"] = np.clip(df["Price_cpkWh"], lower_limit, upper_limit)

    feature_cols = pricing.cols_quarter(fmisid_ws, fmisid_t)
    X = df[feature_cols]
    y = df["Price_cpkWh"]

    days = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("Europe/Helsinki").dt.date
    train_idx, test_idx = next(GroupShuffleSplit(n_splits=1, test_size=0.10, random_state=42).split(X, y, groups=days))
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    mtu15 = df["mtu15"].to_numpy().astype(bool)
    logger.info(
        f"15-min training data: {X.shape[0]} quarters ({mtu15.sum()} with real 15-min prices), "
        f"{X.shape[1]} features"
    )
    logger.info("15-min pricing model feature columns:")
    logger.info(", ".join(feature_cols))

    params = configure_cuda(dict(PARAMS), logger)
    logger.info("XGBoost for 15-min price prediction: ")
    logger.info(", ".join(f"{k}={v}" for k, v in params.items()))

    logger.info("Fitting 15-min model with early stopping...")
    early_stopping_model = XGBRegressor(**params)
    early_stopping_model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=500)
    best_iteration = early_stopping_model.best_iteration
    logger.info(f"Best iteration from early stopping: {best_iteration}")

    # Hold-out metrics, overall and on real 15-min quarters (where the shape matters)
    y_pred = booster_predict(early_stopping_model, X_test)
    test_mtu15 = mtu15[test_idx]
    lines = [
        f"  MAE (held-out days): {mean_absolute_error(y_test, y_pred):.4f}",
        f"  RMSE (held-out days): {np.sqrt(mean_squared_error(y_test, y_pred)):.4f}",
        f"  R² (held-out days): {r2_score(y_test, y_pred):.4f}",
    ]
    if test_mtu15.any():
        lines.append(
            f"  MAE (held-out 15-min market quarters): "
            f"{mean_absolute_error(y_test[test_mtu15], y_pred[test_mtu15]):.4f}"
        )
    logger.info("15-min training results:\n" + "\n".join(lines))

    training_params = {k: v for k, v in params.items() if k != "early_stopping_rounds"}
    final_model = XGBRegressor(**training_params)
    final_model.set_params(n_estimators=best_iteration)
    logger.info(f"Refitting 15-min model on all data with optimal n_estimators={best_iteration}...")
    final_model.fit(X, y, verbose=500)
    return final_model
