import numpy as np
import pandas as pd

from .openmeteo_windpower import LOCATIONS
from .quarter_grid import QUARTER_START


solar = [
    "sum_irradiance",
    "mean_irradiance",
    "std_irradiance",
    "min_irradiance",
    "max_irradiance",
]

border = ["SE1_FI", "SE3_FI", "EE_FI"]

eu_wind = [code for code, _, _ in LOCATIONS]

hydro = [
    "HydroPrecip_5d_median",
    "HydroPrecip_5d_p10",
    "HydroSWE_median",
    "HydroSWE_p10",
]

time = [
    "year",
    "day_of_week",
    "hour",
    "day_of_week_sin",
    "day_of_week_cos",
    "hour_sin",
    "hour_cos",
]

temp = ["temp_mean", "temp_variance"]

feat = time + temp

tmp = feat + ["volatile_likelihood", "PricePredict_cpkWh_scaled"]

# region quarter
quarter_time = [
    "year",
    "day_of_week",
    "quarter_of_day",
    "qidx",
    "mtu15",
    "day_of_week_sin",
    "day_of_week_cos",
    "quarter_of_day_sin",
    "quarter_of_day_cos",
]

# One-hour ramps (t+1h minus t-1h) of supply-side drivers on the 15-min grid
ramp_src = ["WindPowerMW", "sum_irradiance", "ImportCapacityMW", "NuclearPowerMW"]
ramp = [f"{c}_ramp" for c in ramp_src]

feat_quarter = quarter_time + temp + ramp


def add_time(df: pd.DataFrame, *, ts: str = "timestamp") -> pd.DataFrame:
    if ts not in df.columns:
        raise ValueError(f"Expected column '{ts}'")

    df[ts] = pd.to_datetime(df[ts])
    df["day_of_week"] = df[ts].dt.dayofweek + 1
    df["hour"] = df[ts].dt.hour
    df["year"] = df[ts].dt.year

    df["day_of_week_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["day_of_week_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)

    return df


def add_temp(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    available = [col for col in cols if col in df.columns]
    if not available:
        df["temp_mean"] = np.nan
        df["temp_variance"] = np.nan
        return df

    df["temp_mean"] = df[available].mean(axis=1)
    df["temp_variance"] = df[available].var(axis=1)
    return df


def add_time_quarter(df: pd.DataFrame, *, ts: str = "timestamp") -> pd.DataFrame:
    """Calendar features on the 15-min grid, in Helsinki local time (DST-aware)."""
    if ts not in df.columns:
        raise ValueError(f"Expected column '{ts}'")

    df[ts] = pd.to_datetime(df[ts], utc=True)
    local = df[ts].dt.tz_convert("Europe/Helsinki")
    df["year"] = local.dt.year
    df["day_of_week"] = local.dt.dayofweek + 1
    df["qidx"] = local.dt.minute // 15
    df["quarter_of_day"] = local.dt.hour * 4 + df["qidx"]
    # 1 once the day-ahead market settles per quarter; quarters repeat the hourly price before
    df["mtu15"] = (df[ts] >= QUARTER_START).astype(int)

    df["day_of_week_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["day_of_week_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)
    df["quarter_of_day_sin"] = np.sin(2 * np.pi * df["quarter_of_day"] / 96)
    df["quarter_of_day_cos"] = np.cos(2 * np.pi * df["quarter_of_day"] / 96)
    return df


def add_ramps(df: pd.DataFrame, *, ts: str = "timestamp") -> pd.DataFrame:
    """Value one hour ahead minus one hour behind, looked up by timestamp (gap-safe)."""
    stamps = pd.to_datetime(df[ts], utc=True)
    hour = pd.Timedelta(hours=1)
    for col in ramp_src:
        if col not in df.columns:
            df[f"{col}_ramp"] = np.nan
            continue
        series = pd.Series(df[col].to_numpy(dtype=float), index=stamps)
        series = series[~series.index.duplicated(keep="last")]
        df[f"{col}_ramp"] = series.reindex(stamps + hour).to_numpy() - series.reindex(stamps - hour).to_numpy()
    return df


def cols_quarter(ws: list[str], t: list[str]) -> list[str]:
    """15-min model features: the hourly set with 15-min calendar terms and ramps."""
    hourly = [c for c in cols(ws, t) if c not in ("hour_sin", "hour_cos")]
    extra = ["qidx", "mtu15", "quarter_of_day_sin", "quarter_of_day_cos"] + ramp
    return list(dict.fromkeys(hourly[:3] + extra + hourly[3:]))


def cols(ws: list[str], t: list[str]) -> list[str]:
    base = (
        [
            "year",
            "day_of_week_sin",
            "day_of_week_cos",
            "hour_sin",
            "hour_cos",
            "NuclearPowerMW",
            "ImportCapacityMW",
            "WindPowerMW",
            "temp_mean",
            "temp_variance",
            "holiday",
        ]
        + solar
        + border
        + eu_wind
        + hydro
    )

    combined = base + t + ws
    return list(dict.fromkeys(combined))


__all__ = [
    "add_ramps",
    "add_time",
    "add_time_quarter",
    "add_temp",
    "border",
    "cols",
    "cols_quarter",
    "eu_wind",
    "feat",
    "feat_quarter",
    "hydro",
    "quarter_time",
    "ramp",
    "solar",
    "temp",
    "time",
    "tmp",
]
