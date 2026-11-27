"""
15-min grid helpers for the quarter-hour price model.

Every input is brought to the 15-min grid at its finest available resolution:
- finer than 15 min (Fingrid 3-min, FMI 10-min): mean of the samples in each quarter
- exactly 15 min (Sähkötin, JAO since go-live, Open-Meteo minutely_15): as is
- coarser (hourly DB columns, FMI forecasts): linear interpolation between hours for
  continuous series, step (hold) for prices, capacities, flags and daily aggregates

The hourly DB is the base layer; native 15-min data overlays it wherever it exists.
"""

import numpy as np
import pandas as pd

from .dataframes import update_df_from_df

# First delivery quarter of the Nordic 15-min day-ahead market (2025-10-01 00:00 CET)
QUARTER_START = pd.Timestamp("2025-09-30T22:00:00", tz="UTC")

QUARTER = pd.Timedelta(minutes=15)
HOUR = pd.Timedelta(hours=1)

# Columns held constant within the hour when upsampling hourly data
STEP_PREFIXES = ("Hydro",)
STEP_COLS = {
    "Price_cpkWh",
    "PricePredict_cpkWh",
    "holiday",
    "WindPowerCapacityMW",
    "ImportCapacityMW",
    "SE1_FI",
    "SE3_FI",
    "EE_FI",
    "NuclearPowerMW",
    "volatile_likelihood",
}


def _is_step(col):
    return col in STEP_COLS or col.startswith(STEP_PREFIXES)


# region upsample
def _upsample(frame, step, step_cols):
    """Upsample a regular `step` cadence frame (UTC DatetimeIndex) to quarters."""
    quarters = pd.date_range(frame.index.min(), frame.index.max() + step - QUARTER, freq=QUARTER)
    anchors = quarters.floor(step)
    current = frame.reindex(anchors).to_numpy()
    following = frame.reindex(anchors + step).to_numpy()
    frac = np.asarray((quarters - anchors) / step)[:, None]

    values = current + (following - current) * frac
    # Hold the value when the next sample is missing (series end or gap)
    values = np.where(np.isnan(following), current, values)

    out = pd.DataFrame(values, index=quarters, columns=frame.columns)
    held = [c for c in frame.columns if c in step_cols]
    out[held] = frame.reindex(anchors)[held].to_numpy()
    return out


def upsample_hourly(df, ts="timestamp"):
    """
    Expand an hourly frame to the 15-min grid.

    Continuous columns are interpolated linearly towards the next hour (held when the
    next hour is missing); STEP_COLS repeat the hourly value. Non-numeric columns are
    dropped.
    """
    hourly = df.reset_index() if ts not in df.columns else df
    hourly = hourly.copy()
    hourly[ts] = pd.to_datetime(hourly[ts], utc=True)
    hourly = hourly.drop_duplicates(subset=ts, keep="last").set_index(ts).sort_index()
    hourly = hourly.select_dtypes(include=[np.number, "bool"]).astype(float)
    if hourly.empty:
        return pd.DataFrame(columns=[ts])

    out = _upsample(hourly, HOUR, {c for c in hourly.columns if _is_step(c)})
    out.index.name = ts
    return out.reset_index()
# endregion upsample


# region aggregate
def to_quarters(df, cols, ts="timestamp", how="mean"):
    """
    Bring native-resolution samples to the 15-min grid.

    Samples at 15 min or finer are averaged per quarter ([t, t+15min)). Coarser samples
    are interpolated linearly (how="mean") or held (how="step") until the next sample.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=[ts, *cols])

    data = df[[ts, *cols]].copy()
    data[ts] = pd.to_datetime(data[ts], utc=True)
    data[cols] = data[cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=cols, how="all").groupby(ts)[cols].mean().sort_index()
    if data.empty:
        return pd.DataFrame(columns=[ts, *cols])

    cadence = data.index.to_series().diff().median()
    if pd.isna(cadence) or cadence <= QUARTER:
        out = data.resample(QUARTER).mean()
    else:
        out = _upsample(data, cadence, set(cols) if how == "step" else set())

    out.index.name = ts
    return out.reset_index().dropna(subset=cols, how="all")
# endregion aggregate


# region overlay
def overlay(base, fine, cols=None, ts="timestamp"):
    """
    Replace base values with native 15-min values wherever the latter exist.
    Rows only present in `fine` are not added.
    """
    if fine is None or fine.empty:
        return base
    cols = [c for c in (cols or fine.columns) if c != ts and c in fine.columns]
    if not cols:
        return base
    return update_df_from_df(base, fine.rename(columns={ts: "timestamp"}), cols=cols)


def combine_fine(*frames, ts="timestamp"):
    """Merge several native 15-min frames; later frames win where they have values."""
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame(columns=[ts])
    out = frames[0].copy()
    out[ts] = pd.to_datetime(out[ts], utc=True)
    for frame in frames[1:]:
        frame = frame.copy()
        frame[ts] = pd.to_datetime(frame[ts], utc=True)
        new_rows = frame.loc[~frame[ts].isin(out[ts]), [ts]]
        out = pd.concat([out, new_rows], ignore_index=True)
        out = update_df_from_df(out, frame, cols=[c for c in frame.columns if c != ts])
    return out.sort_values(ts).reset_index(drop=True)
# endregion overlay
