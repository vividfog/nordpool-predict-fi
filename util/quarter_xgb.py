"""
15-min price predictions on top of the hourly price model.

The hourly model (`util/train_xgb.py`) keeps predicting the hourly mean price; every
feature it uses is hourly, and it trains on the full history back to 2023. This module
adds a second, small XGBoost regressor that predicts the *intra-hour shape*: each
quarter's deviation from its hourly mean. Shapes are re-centred per hour, so the four
quarters always average back to the hourly prediction (and daily averages stay put).

Training data: actual 15-min prices since QUARTER_START (Sähkötin `&quarter`), stored
in the `prediction_quarter` table. Target = quarter price - hourly mean of the quarters.
Inputs = quarter index, Helsinki calendar, the hourly level and its neighbour-hour
gradients, plus hourly fundamentals and their ramps. At inference the hourly level is
the (scaled) hourly prediction, so the neighbour gradients come from the hourly model.
"""

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from .logger import logger
from .sahkotin import QUARTER_START, fetch_quarter_prices
from .sql import db_quarter_query_all, db_quarter_update
from .xgb_utils import booster_predict, configure_cuda

# region constants
LEVEL = "level"
FUND = ["WindPowerMW", "NuclearPowerMW", "ImportCapacityMW", "sum_irradiance"]
COLS = (
    ["qidx", "hel_hour", "dow", "month", LEVEL, "prev", "next", "prev2", "next2"]
    + FUND
    + [f"{c}_d" for c in FUND]
)
MIN_TRAIN_DAYS = 30
VALID_DAYS = 30
# endregion constants


# region features
def quarter_frame(df_hourly, level_col):
    """
    Expand an hourly frame to the 15-min grid with shape-model features.

    Args:
        df_hourly: hourly rows with a 'timestamp' column (or DatetimeIndex) in UTC,
            `level_col` and any of FUND.
        level_col: hourly price level to shape around.

    Returns:
        DataFrame with one row per quarter: 'timestamp', 'hour', LEVEL and COLS.
    """
    hourly = df_hourly.reset_index() if "timestamp" not in df_hourly.columns else df_hourly
    hourly = hourly.copy()
    hourly["timestamp"] = pd.to_datetime(hourly["timestamp"], utc=True)
    hourly = (
        hourly.drop_duplicates(subset="timestamp", keep="last")
        .set_index("timestamp")
        .sort_index()
    )
    # Neighbour lookups must see real gaps, not the next available row
    hourly = hourly.reindex(pd.date_range(hourly.index.min(), hourly.index.max(), freq="h"))

    feats = pd.DataFrame(index=hourly.index)
    level = hourly[level_col].astype(float)
    feats[LEVEL] = level
    for name, k in [("prev", 1), ("next", -1), ("prev2", 2), ("next2", -2)]:
        feats[name] = level.shift(k) - level
    for col in FUND:
        series = hourly[col].astype(float) if col in hourly.columns else pd.Series(np.nan, index=hourly.index)
        feats[col] = series
        feats[f"{col}_d"] = series.shift(-1) - series.shift(1)
    feats = feats[feats[LEVEL].notna()]

    out = feats.loc[feats.index.repeat(4)].copy()
    out.index.name = "hour"
    out = out.reset_index()
    out["qidx"] = np.tile(np.arange(4), len(feats))
    out["timestamp"] = out["hour"] + pd.to_timedelta(out["qidx"] * 15, unit="min")

    hel = out["timestamp"].dt.tz_convert("Europe/Helsinki")
    out["hel_hour"] = hel.dt.hour
    out["dow"] = hel.dt.dayofweek
    out["month"] = hel.dt.month
    return out


def recentre(shape, hour):
    """Shift each hour's four quarter offsets so they average to zero."""
    shape = pd.Series(np.asarray(shape, dtype=float), index=hour.index)
    return shape - shape.groupby(hour).transform("mean")
# endregion features


# region prices
def load_quarter_prices(db_path, commit=False, now=None):
    """
    Return actual 15-min prices (['timestamp', 'Price_cpkWh']) since QUARTER_START.

    Reads the `prediction_quarter` table and fetches anything newer from Sähkötin
    (the whole history on the first run). Fetched prices are written back only with
    `commit`, matching how the hourly table is handled.
    """
    stored = db_quarter_query_all(db_path)
    stored = stored.dropna(subset=["Price_cpkWh"])[["timestamp", "Price_cpkWh"]]

    now = pd.Timestamp.utcnow() if now is None else pd.Timestamp(now)
    # Re-fetch the last two days to pick up late corrections
    start = stored["timestamp"].max() - pd.Timedelta(days=2) if not stored.empty else QUARTER_START
    fetched = fetch_quarter_prices(start, now + pd.Timedelta(days=2))

    if not fetched.empty and commit:
        db_quarter_update(db_path, fetched, "Price_cpkWh")

    frames = [f for f in (stored, fetched) if not f.empty]
    if not frames:
        return pd.DataFrame(columns=["timestamp", "Price_cpkWh"])
    prices = pd.concat(frames, ignore_index=True)
    prices = prices.drop_duplicates(subset="timestamp", keep="last")
    return prices.sort_values("timestamp").reset_index(drop=True)
# endregion prices


# region train
def train_quarter_model(df_hourly, quarter_prices):
    """
    Train the intra-hour shape model in memory.

    Args:
        df_hourly: hourly feature history ('timestamp' + FUND columns).
        quarter_prices: actual 15-min prices ['timestamp', 'Price_cpkWh'].

    Returns:
        Fitted XGBRegressor, or None when there is too little 15-min history.
    """
    logger.info("Training a 15-min shape model")
    q = quarter_prices.dropna(subset=["Price_cpkWh"]).copy()
    q["timestamp"] = pd.to_datetime(q["timestamp"], utc=True)
    q = q[q["timestamp"] >= QUARTER_START]
    q["hour"] = q["timestamp"].dt.floor("h")

    # Keep complete hours only so the hourly mean is the real one
    complete = q.groupby("hour")["Price_cpkWh"].transform("size") == 4
    q = q[complete]
    if q.empty or q["hour"].nunique() < MIN_TRAIN_DAYS * 24:
        logger.warning(
            f"15-min model: only {q['hour'].nunique()} complete hours of 15-min prices, "
            f"need {MIN_TRAIN_DAYS * 24}; quarters will repeat the hourly price."
        )
        return None

    feats = df_hourly.reset_index() if "timestamp" not in df_hourly.columns else df_hourly
    feats = feats[["timestamp"] + [c for c in FUND if c in feats.columns]].copy()
    feats["timestamp"] = pd.to_datetime(feats["timestamp"], utc=True)
    feats = feats.drop_duplicates(subset="timestamp", keep="last")

    hourly = (
        q.groupby("hour")["Price_cpkWh"].mean().rename("hourly_mean")
        .rename_axis("timestamp").reset_index()
        .merge(feats, on="timestamp", how="left")
    )

    data = quarter_frame(hourly, "hourly_mean").merge(
        q[["timestamp", "Price_cpkWh"]], on="timestamp", how="inner"
    )
    data["target"] = data["Price_cpkWh"] - data[LEVEL]

    # Clip rare extreme spikes so a few quarters don't dominate the shape
    lo, hi = data["target"].quantile([0.0005, 0.9995])
    data["target"] = data["target"].clip(lo, hi)

    # Chronological hold-out: the last VALID_DAYS pick the tree count
    valid_start = data["timestamp"].max() - pd.Timedelta(days=VALID_DAYS)
    valid = data["timestamp"] >= valid_start
    X, y = data[COLS], data["target"]
    logger.info(
        f"15-min model: {len(data)} quarters "
        f"({data['timestamp'].min():%Y-%m-%d} → {data['timestamp'].max():%Y-%m-%d}), "
        f"{valid.sum()} held out for early stopping"
    )

    params = {
        "early_stopping_rounds": 100,
        "objective": "reg:pseudohubererror",
        "eval_metric": "mae",
        "n_estimators": 4000,
        "max_depth": 6,
        "learning_rate": 0.02,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": 42,
    }
    params = configure_cuda(params, logger)

    model = XGBRegressor(**params)
    model.fit(X[~valid], y[~valid], eval_set=[(X[valid], y[valid])], verbose=False)
    best_iteration = max(int(model.best_iteration), 1)

    # Report shape skill on the hold-out before refitting on everything
    shape = recentre(booster_predict(model, X[valid]), data.loc[valid, "hour"])
    mae_flat = y[valid].abs().mean()
    mae_shape = (y[valid] - shape).abs().mean()
    logger.info(
        f"15-min model: hold-out intra-hour MAE {mae_shape:.3f} c/kWh "
        f"vs {mae_flat:.3f} flat ({(1 - mae_shape / mae_flat) * 100:.0f}% better), "
        f"best iteration {best_iteration}"
    )

    final_params = {k: v for k, v in params.items() if k != "early_stopping_rounds"}
    final_params["n_estimators"] = best_iteration
    final_model = XGBRegressor(**final_params)
    final_model.fit(X, y, verbose=False)
    return final_model
# endregion train


# region predict
def predict_quarter_prices(model, df_hourly, level_col="PricePredict_cpkWh"):
    """
    Split hourly predictions into 15-min predictions.

    Returns:
        DataFrame ['timestamp', 'PricePredict_cpkWh'] on the quarter grid (UTC). Each
        hour's quarters average to its hourly `level_col`. Without a model the hourly
        price is repeated across the four quarters.
    """
    frame = quarter_frame(df_hourly, level_col)
    if model is None:
        shape = pd.Series(0.0, index=frame.index)
    else:
        shape = recentre(booster_predict(model, frame[COLS]), frame["hour"])

    out = pd.DataFrame(
        {
            "timestamp": frame["timestamp"],
            "PricePredict_cpkWh": (frame[LEVEL] + shape).round(4),
        }
    )
    return out.reset_index(drop=True)
# endregion predict
