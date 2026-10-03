"""
Data layer for the 15-min price model.

The 15-min frame is built in two layers:
1. Base: the enriched hourly frame upsampled to quarters (`quarter_grid.upsample_hourly`),
   so every feature exists for every quarter (incl. the full hourly history since 2023).
2. Overlay: native 15-min (or finer, averaged per quarter) data wherever it exists,
   from the `prediction_15min` table (backfill + previous runs) and this run's fetch.

Native sources (column → source, native resolution):
- Price_cpkWh                 Sähkötin `&quarter`, 15 min (since QUARTER_START)
- SE1_FI/SE3_FI/EE_FI/ImportCapacityMW  JAO, 15 min since go-live
- eu_ws_*                     Open-Meteo minutely_15 wind_speed_120m
- *_irradiance                Open-Meteo minutely_15 global_tilted_irradiance
- WindPowerMW                 Fingrid 181 (3 min, measured) / 245 (forecast)
- NuclearPowerMW              Fingrid 188 (3 min); ENTSO-E outages for the future
- t_*/ws_*                    FMI 10-min observations (past only)
Holidays, hydrology and capacities stay hourly/daily (step) by nature.
"""

import pandas as pd

from .fingrid_nuclear import fetch_nuclear_quarters
from .fingrid_windpower_xgb import fetch_windpower_quarters
from .fmi import fetch_station_quarters
from .jao_imports import fetch_import_capacity_quarters
from .logger import logger
from .openmeteo_solar import fetch_irradiance_quarters
from .openmeteo_windpower import fetch_eu_ws_quarters
from .quarter_grid import QUARTER_START, combine_fine, overlay, upsample_hourly
from .sahkotin import fetch_quarter_prices
from . import features_pricing as pricing

# Stored in prediction_15min but never used as an input feature
NON_FEATURE_COLS = ["PricePredict_cpkWh"]


# region fetch
def fetch_quarter_sources(start, end, *, fingrid_api_key, fmisids, entso_e=None, price_since=None):
    """
    Fetch every native 15-min source for [start, end] and merge them on the quarter grid.

    Each source is optional: a failure is logged and the hourly base covers that column.

    Args:
        start, end: UTC window (the live run uses the same -7d/+7d window as hourly).
        fingrid_api_key: Fingrid API key.
        fmisids: FMI station ids (ints or strings) for 10-min observations.
        entso_e: optional 15-min ENTSO-E nuclear capacity frame (future outages), which
            overrides Fingrid nuclear like in the hourly pipeline.
        price_since: fetch Sähkötin quarter prices from this timestamp instead of
            `start` (used to fill price history the table doesn't have yet).
    """
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    fetchers = [
        ("Sähkötin prices", lambda: fetch_quarter_prices(price_since or start, end)),
        ("JAO capacities", lambda: fetch_import_capacity_quarters(max(start, QUARTER_START), end)),
        ("Open-Meteo wind", lambda: fetch_eu_ws_quarters(start, end)),
        ("Open-Meteo irradiance", lambda: fetch_irradiance_quarters(start, end)),
        ("Fingrid wind power", lambda: fetch_windpower_quarters(fingrid_api_key, start, end)),
        ("Fingrid nuclear", lambda: fetch_nuclear_quarters(fingrid_api_key, start, end)),
        ("FMI observations", lambda: fetch_station_quarters(fmisids, start, end)),
    ]

    frames = []
    for label, fetch in fetchers:
        try:
            frame = fetch()
        except Exception as exc:  # optional layer: fall back to the hourly base
            logger.warning(f"15-min data: {label} unavailable, using hourly values instead: {exc}")
            continue
        if frame is not None and not frame.empty:
            frames.append(frame)
            logger.info(f"15-min data: {label}: {len(frame)} quarters, {len(frame.columns) - 1} columns")

    if entso_e is not None and not entso_e.empty:
        nuclear = entso_e[["timestamp", "NuclearPowerMW"]].copy()
        nuclear["timestamp"] = pd.to_datetime(nuclear["timestamp"], utc=True)
        frames.append(nuclear)

    return combine_fine(*frames)
# endregion fetch


# region build
def build_quarter_frame(df_hourly, fine):
    """Hourly frame upsampled to quarters, overlaid with native 15-min values."""
    base = upsample_hourly(df_hourly)
    fine = fine.drop(columns=[c for c in NON_FEATURE_COLS if c in fine.columns]) if fine is not None else fine
    return overlay(base, fine)


def add_quarter_features(df_q, fmisid_t):
    """Calendar, temperature and ramp features for the 15-min model (in place)."""
    df_q = pricing.add_time_quarter(df_q)
    df_q = pricing.add_temp(df_q, fmisid_t)
    return pricing.add_ramps(df_q)


def coverage(df_q, fine, cols):
    """Share of quarters per column that come from native 15-min data (for logging)."""
    if fine is None or fine.empty:
        return {}
    native = df_q[["timestamp"]].merge(fine, on="timestamp", how="left")
    return {c: float(native[c].notna().mean()) for c in cols if c in native.columns}
# endregion build
