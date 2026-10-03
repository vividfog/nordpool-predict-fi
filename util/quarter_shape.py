"""
Intra-hour shape stage for the 15-min price model.

The 15-min model (`util/train_xgb_15min.py`) sets each hour's price level well, but it
only sees fundamentals, not the shape of the price curve around a quarter. Most
intra-hour movement is the market spreading steps between hourly blocks over the
first and last quarters, so this small XGBoost regressor predicts each quarter's offset
from its hourly mean using the neighbour-hour price gradients of the 15-min model's
own hourly means (plus quarter index, Helsinki calendar, fundamentals and ramps).
Offsets are re-centred per hour, so quarters always average to the 15-min model's
hourly mean. Held-out Aug–Sep 2026: intra-hour MAE 0.701 → 0.630 c/kWh.

Training data: actual 15-min prices since QUARTER_START (target = quarter price minus
the hourly mean of the quarters) and hourly fundamentals. No dependency on the hourly
price model.
"""

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from .logger import logger
from .quarter_grid import QUARTER_START
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


# region train
def train_shape_model(df_hourly, quarter_prices):
    """
    Train the intra-hour shape model in memory.

    Args:
        df_hourly: hourly feature history ('timestamp' + FUND columns).
        quarter_prices: actual 15-min prices ['timestamp', 'Price_cpkWh'].

    Returns:
        Fitted XGBRegressor, or None when there is too little 15-min history.
    """
    logger.info("Training the 15-min intra-hour shape stage")
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
def apply_shape(model, df_hourly, level_col="PricePredict_cpkWh"):
    """
    Split hourly price levels into 15-min prices.

    Returns:
        DataFrame ['timestamp', 'PricePredict_cpkWh'] on the quarter grid (UTC). Each
        hour's quarters average to its hourly `level_col`. Without a model the hourly
        level is repeated across the four quarters.
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
