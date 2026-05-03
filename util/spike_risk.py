"""Shared hourly spike-risk calculation for price scaling and narration."""

import math

import numpy as np
import pandas as pd
import pytz

from .logger import logger

# region constants
WIND_SCALE_MAX_MW = 1004.1304
WIND_SCALE_MIN_MW = 412.8883
MAX_WIND_MULTIPLIER = 1.3340
MIN_WIND_MULTIPLIER = 1.0

DAILY_PRICE_RANK_FRACTION = 0.19

SPIKE_RISK_COLUMNS = [
    "wind_multiplier",
    "helsinki_date",
    "helsinki_hour",
    "is_top_daily_price_hour",
    "is_future_hour",
    "is_spike_risk_hour",
]
# endregion constants


def _as_utc_timestamp(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def spike_risk_future_start(now=None, helsinki_tz=None):
    """Return the UTC cutoff that matches the existing scaler future-window rule."""
    if helsinki_tz is None:
        helsinki_tz = pytz.timezone("Europe/Helsinki")

    now_utc = pd.Timestamp.utcnow().ceil("h") if now is None else _as_utc_timestamp(now).ceil("h")
    now_helsinki = now_utc.tz_convert(helsinki_tz)

    if 0 <= now_helsinki.hour < 14:
        tomorrow_helsinki = now_helsinki + pd.Timedelta(days=1)
        future_start_helsinki = tomorrow_helsinki.replace(hour=1, minute=0, second=0)
    else:
        tomorrow_helsinki = now_helsinki + pd.Timedelta(days=1)
        tomorrow_helsinki = tomorrow_helsinki.replace(hour=0, minute=0, second=0)
        future_start_helsinki = tomorrow_helsinki + pd.Timedelta(days=1, hours=1)

    return future_start_helsinki.tz_convert("UTC")


def _wind_multiplier(wind_power):
    clipped_wind = wind_power.clip(WIND_SCALE_MIN_MW, WIND_SCALE_MAX_MW)
    denominator = WIND_SCALE_MIN_MW - WIND_SCALE_MAX_MW

    if denominator == 0:
        multiplier = np.where(
            wind_power <= WIND_SCALE_MIN_MW,
            MAX_WIND_MULTIPLIER,
            MIN_WIND_MULTIPLIER,
        )
    else:
        multiplier = MIN_WIND_MULTIPLIER + (
            (clipped_wind - WIND_SCALE_MAX_MW)
            * (MAX_WIND_MULTIPLIER - MIN_WIND_MULTIPLIER)
            / denominator
        )

    multiplier = pd.Series(multiplier, index=wind_power.index)
    multiplier.loc[wind_power >= WIND_SCALE_MAX_MW] = MIN_WIND_MULTIPLIER
    multiplier.loc[wind_power <= WIND_SCALE_MIN_MW] = MAX_WIND_MULTIPLIER
    return multiplier.clip(MIN_WIND_MULTIPLIER, MAX_WIND_MULTIPLIER)


def _top_daily_price_hours(df_result, price_col):
    is_top_daily_hour = pd.Series(False, index=df_result.index)
    helsinki_time_filter = (df_result["helsinki_hour"] >= 6) & (df_result["helsinki_hour"] < 22)

    def get_top_hours_indices(group):
        valid_hours = group[helsinki_time_filter.loc[group.index]]
        valid_prices = valid_hours[price_col].dropna()
        if valid_prices.empty:
            return pd.Series(False, index=group.index)

        n_top_hours = math.ceil(len(valid_prices) * DAILY_PRICE_RANK_FRACTION)
        if n_top_hours == 0:
            return pd.Series(False, index=group.index)

        morning_mask = (valid_hours["helsinki_hour"] >= 6) & (valid_hours["helsinki_hour"] < 12)
        evening_mask = (valid_hours["helsinki_hour"] >= 16) & (valid_hours["helsinki_hour"] < 22)

        morning_prices = valid_prices[morning_mask.loc[valid_prices.index]]
        evening_prices = valid_prices[evening_mask.loc[valid_prices.index]]

        n_morning_hours = math.ceil(n_top_hours / 2)
        n_evening_hours = math.ceil(n_top_hours / 2)

        if len(morning_prices) < n_morning_hours:
            n_morning_hours = len(morning_prices)
            n_evening_hours = min(len(evening_prices), n_top_hours - n_morning_hours)
        elif len(evening_prices) < n_evening_hours:
            n_evening_hours = len(evening_prices)
            n_morning_hours = min(len(morning_prices), n_top_hours - n_evening_hours)

        top_indices = []
        if not morning_prices.empty:
            top_indices.extend(morning_prices.nlargest(n_morning_hours).index)
        if not evening_prices.empty:
            top_indices.extend(evening_prices.nlargest(n_evening_hours).index)

        is_top = pd.Series(False, index=group.index)
        is_top.loc[top_indices] = True
        return is_top

    try:
        for _, group in df_result.groupby("helsinki_date", sort=False):
            group_top_hours = get_top_hours_indices(group)
            is_top_daily_hour.loc[group_top_hours.index] = group_top_hours
    except Exception as exc:
        logger.error(f"Spike risk: could not identify top daily hours: {exc}", exc_info=True)

    return is_top_daily_hour.astype(bool)


def compute_spike_risk_hours(
    df,
    *,
    now=None,
    helsinki_tz=None,
    price_col="PricePredict_cpkWh",
    wind_col="WindPowerMW",
):
    """
    Compute the canonical hourly spike-risk mask.

    A spike-risk hour is a future hour where wind is below the no-risk threshold
    and the hour is among the day's selected high-price morning/evening hours.
    """
    df_result = df.copy()
    if helsinki_tz is None:
        helsinki_tz = pytz.timezone("Europe/Helsinki")

    for column in SPIKE_RISK_COLUMNS:
        if column not in df_result.columns:
            df_result[column] = False

    if price_col not in df_result.columns:
        logger.error(f"Spike risk: missing '{price_col}' column.")
        df_result["wind_multiplier"] = MIN_WIND_MULTIPLIER
        return df_result

    try:
        timestamps = pd.to_datetime(df_result["timestamp"])
        if timestamps.dt.tz is None:
            df_result["timestamp"] = timestamps.dt.tz_localize("UTC")
            logger.warning("Spike risk: input timestamp column was timezone-naive, assuming UTC.")
        else:
            df_result["timestamp"] = timestamps.dt.tz_convert("UTC")
    except Exception as exc:
        logger.error(f"Spike risk: failed to process timestamp column: {exc}", exc_info=True)
        df_result["wind_multiplier"] = MIN_WIND_MULTIPLIER
        return df_result

    df_result["helsinki_hour"] = df_result["timestamp"].dt.tz_convert(helsinki_tz).dt.hour
    df_result["helsinki_date"] = df_result["timestamp"].dt.tz_convert(helsinki_tz).dt.date
    df_result["is_top_daily_price_hour"] = _top_daily_price_hours(df_result, price_col)

    if wind_col not in df_result.columns:
        logger.warning(f"Spike risk: missing '{wind_col}' column. No wind-based risk applied.")
        df_result["wind_multiplier"] = MIN_WIND_MULTIPLIER
    else:
        df_result["wind_multiplier"] = _wind_multiplier(df_result[wind_col])

    future_start = spike_risk_future_start(now=now, helsinki_tz=helsinki_tz)
    df_result["is_future_hour"] = df_result["timestamp"] >= future_start
    df_result["is_spike_risk_hour"] = (
        df_result["is_future_hour"]
        & df_result[price_col].notna()
        & df_result["is_top_daily_price_hour"]
        & (df_result["wind_multiplier"] > MIN_WIND_MULTIPLIER)
    )

    return df_result
