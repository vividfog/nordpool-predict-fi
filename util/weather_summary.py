import json
from collections import Counter
from pathlib import Path

import pandas as pd


HELSINKI_TIMEZONE = "Europe/Helsinki"
WEATHER_COLUMN_PREFIX = "weather_symbol_"
WIND_LEVELS = ("calm", "weak", "normal", "strong")

_CONDITION_PRIORITY = {
    "clear-day": 0,
    "partly-cloudy-day": 1,
    "overcast-day": 2,
    "rain": 3,
    "snow": 4,
    "thunderstorms-day": 5,
}


def weather_symbol_condition(value):
    """Map FMI WeatherSymbol3 values to the broad conditions used by the UI."""
    if pd.isna(value):
        return None
    try:
        symbol = int(float(value))
    except (TypeError, ValueError):
        return None

    if symbol == 1:
        return "clear-day"
    if symbol == 2:
        return "partly-cloudy-day"
    if symbol in {3, 91, 92}:
        return "overcast-day"
    if symbol in {21, 22, 23, 31, 32, 33}:
        return "rain"
    if symbol in {41, 42, 43, 51, 52, 53, 71, 72, 73, 81, 82, 83}:
        return "snow"
    if symbol in {61, 62, 63, 64}:
        return "thunderstorms-day"
    return None


def wind_power_level(megawatts):
    """Categorize predicted wind generation using the price-model thresholds."""
    if pd.isna(megawatts):
        return None
    value = float(megawatts)
    if value < 1000:
        return "calm"
    if value < 2500:
        return "weak"
    if value <= 3000:
        return "normal"
    return "strong"


def daily_wind_power_level(values):
    """Summarize a day without letting short peaks hide a long sub-1 GW period."""
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None
    if numeric.quantile(0.25) < 1000:
        return "calm"
    return wind_power_level(numeric.mean())


def _representative_condition(day_frame, weather_columns):
    local_hours = day_frame["_local_timestamp"].dt.hour
    nearest_to_noon = (local_hours - 12).abs().min()
    noon_frame = day_frame[(local_hours - 12).abs() == nearest_to_noon]
    conditions = [
        weather_symbol_condition(value)
        for value in noon_frame[weather_columns].to_numpy().ravel()
    ]
    counts = Counter(condition for condition in conditions if condition)
    if not counts:
        return None
    return max(counts, key=lambda condition: (counts[condition], _CONDITION_PRIORITY[condition]))


def build_daily_weather(df, reference_time=None, days=8):
    """Build daily weather/wind records for today and seven forecast days."""
    weather_columns = sorted(
        column for column in df.columns if column.startswith(WEATHER_COLUMN_PREFIX)
    )
    if not weather_columns or "timestamp" not in df or "WindPowerMW" not in df:
        return []

    frame = df[["timestamp", "WindPowerMW", *weather_columns]].copy()
    frame["_local_timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(
        HELSINKI_TIMEZONE
    )
    reference = pd.Timestamp.now(tz=HELSINKI_TIMEZONE) if reference_time is None else pd.Timestamp(reference_time)
    if reference.tzinfo is None:
        reference = reference.tz_localize(HELSINKI_TIMEZONE)
    else:
        reference = reference.tz_convert(HELSINKI_TIMEZONE)
    first_date = reference.date()
    last_date = (reference + pd.Timedelta(days=days - 1)).date()
    frame["_local_date"] = frame["_local_timestamp"].dt.date
    frame = frame[
        (frame["_local_date"] >= first_date) & (frame["_local_date"] <= last_date)
    ]

    records = []
    for local_date, day_frame in frame.groupby("_local_date", sort=True):
        condition = _representative_condition(day_frame, weather_columns)
        wind_level = daily_wind_power_level(day_frame["WindPowerMW"])
        if condition is None or wind_level is None:
            continue
        local_noon = pd.Timestamp(local_date, tz=HELSINKI_TIMEZONE) + pd.Timedelta(hours=12)
        records.append({
            "timestamp": int(local_noon.tz_convert("UTC").timestamp() * 1000),
            "condition": condition,
            "windLevel": wind_level,
        })
    return records


def write_daily_weather(df, output_path, reference_time=None, days=8):
    """Serialize the daily weather summary consumed by the prediction chart."""
    records = build_daily_weather(df, reference_time=reference_time, days=days)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return records
