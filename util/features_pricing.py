import numpy as np
import pandas as pd

from .openmeteo_windpower import LOCATIONS


solar = [
    "sum_irradiance",
    "mean_irradiance",
    "std_irradiance",
    "min_irradiance",
    "max_irradiance",
]

border = ["SE1_FI", "SE3_FI", "EE_FI"]

eu_wind = [code for code, _, _ in LOCATIONS]

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
    )

    combined = base + t + ws
    return list(dict.fromkeys(combined))


__all__ = [
    "add_time",
    "add_temp",
    "border",
    "cols",
    "eu_wind",
    "feat",
    "solar",
    "temp",
    "time",
    "tmp",
]
