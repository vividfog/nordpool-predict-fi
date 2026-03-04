from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import urlopen

import pandas as pd

from .logger import logger


SYKE_ODATA_BASE = "https://rajapinnat.ymparisto.fi/api/Hydrologiarajapinta/1.1/odata"


@dataclass(frozen=True)
class HydroMetric:
    name: str
    entity: str
    places: list[int]
    extra_filter: str = ""

    @property
    def median_col(self) -> str:
        return f"{self.name}_median"

    @property
    def p10_col(self) -> str:
        return f"{self.name}_p10"


HYDRO_METRICS = [
    HydroMetric(
        name="HydroPrecip_5d",
        entity="SadantaAlue",
        extra_filter="Jakso_Id eq 2",
        places=[848, 852, 810, 811, 834, 837, 879, 881, 885, 886],
    ),
    HydroMetric(
        name="HydroSWE",
        entity="LumiAlue",
        places=[196, 200, 159, 160, 183, 185, 226, 228, 232, 233],
    ),
]


def _odata_qs(params: dict[str, str]) -> str:
    return urlencode(params, quote_via=quote, safe="$',=()")


def _fetch_json(url: str, *, timeout_s: int = 60) -> dict[str, Any]:
    with urlopen(url, timeout=timeout_s) as response:
        payload = response.read()
    return json.loads(payload)


def _format_dt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _place_filter(places: list[int]) -> str:
    return " or ".join([f"Paikka_Id eq {pid}" for pid in places])


def fetch_metric_rows(
    metric: HydroMetric,
    *,
    start: datetime,
    end: datetime,
    chunk_days: int = 31,
    top: int = 500,
) -> pd.DataFrame:
    if not metric.places:
        return pd.DataFrame(columns=["Aika", "Paikka_Id", "Arvo"])

    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    if start > end:
        return pd.DataFrame(columns=["Aika", "Paikka_Id", "Arvo"])

    frames: list[pd.DataFrame] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=chunk_days))
        start_s = _format_dt(cursor)
        end_s = _format_dt(chunk_end)

        filt = (
            f"Aika ge datetime'{start_s}' and Aika le datetime'{end_s}' and "
            f"({_place_filter(metric.places)})"
        )
        if metric.extra_filter:
            filt = f"{filt} and {metric.extra_filter}"

        skip = 0
        while True:
            qs = _odata_qs(
                {
                    "$top": str(top),
                    "$skip": str(skip),
                    "$select": "Paikka_Id,Aika,Arvo",
                    "$filter": filt,
                    "$orderby": "Aika asc",
                }
            )
            url = f"{SYKE_ODATA_BASE}/{metric.entity}?{qs}"
            rows = _fetch_json(url).get("value", [])
            if rows:
                frames.append(pd.DataFrame(rows))
            if len(rows) < top:
                break
            skip += top

        cursor = chunk_end + timedelta(seconds=1)

    if not frames:
        return pd.DataFrame(columns=["Aika", "Paikka_Id", "Arvo"])

    df = pd.concat(frames, ignore_index=True)
    df["Aika"] = pd.to_datetime(df["Aika"], utc=True, errors="coerce")
    df["Paikka_Id"] = pd.to_numeric(df["Paikka_Id"], errors="coerce").astype("Int64")
    df["Arvo"] = pd.to_numeric(df["Arvo"], errors="coerce")
    df = df.dropna(subset=["Aika", "Paikka_Id", "Arvo"])
    df["Paikka_Id"] = df["Paikka_Id"].astype(int)
    df = df.drop_duplicates(subset=["Paikka_Id", "Aika"], keep="last")
    return df.sort_values(["Aika", "Paikka_Id"]).reset_index(drop=True)


def _compute_daily_quantiles(
    rows: pd.DataFrame,
    *,
    places: list[int],
    day_index: pd.DatetimeIndex,
) -> tuple[pd.Series, pd.Series]:
    if rows.empty:
        empty = pd.Series(index=day_index, dtype=float)
        return empty, empty

    pivot = rows.pivot(index="Aika", columns="Paikka_Id", values="Arvo").sort_index()
    pivot = pivot.reindex(columns=places)

    ext_index = pd.date_range(
        start=min(pivot.index.min(), day_index.min()),
        end=day_index.max(),
        freq="D",
        tz=timezone.utc,
    )
    pivot = pivot.reindex(ext_index).ffill().reindex(day_index)

    median = pivot.median(axis=1, skipna=True)
    p10 = pivot.quantile(0.10, axis=1, interpolation="linear")
    return median, p10


def _merge_col(df: pd.DataFrame, *, col: str, values: pd.Series) -> pd.DataFrame:
    mapped = df["timestamp_day"].map(values)
    if col in df.columns:
        df[col] = mapped.combine_first(df[col])
    else:
        df[col] = mapped
    return df


def _coverage_line(df: pd.DataFrame, *, columns: list[str], valid_mask: pd.Series) -> str:
    parts: list[str] = []
    valid_count = int(valid_mask.sum())
    for col in columns:
        if col not in df.columns:
            parts.append(f"{col}=missing")
            continue
        filled = int(df.loc[valid_mask, col].notna().sum())
        ratio = (filled / valid_count * 100.0) if valid_count else 0.0
        parts.append(f"{col}={ratio:.1f}%")
    return ", ".join(parts)


def update_hydrology(
    df: pd.DataFrame,
    *,
    carry_days: int = 60,
    chunk_days: int = 31,
    top: int = 500,
    now_utc: datetime | None = None,
) -> pd.DataFrame:
    """
    Update DF with 4 hydrology features using complete-day SYKE observations only.

    Rules:
    - Never use today's SYKE values (day may be incomplete).
    - Build daily metrics from selected places:
      HydroPrecip_5d_{median,p10}, HydroSWE_{median,p10}
    - Fill hourly timestamps by day mapping (daily value repeated over day).
    """
    if "timestamp" not in df.columns:
        raise ValueError("update_hydrology expects a 'timestamp' column")

    out = df.copy()
    try:
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
        valid = out["timestamp"].notna()
        if not valid.any():
            logger.warning("Hydrology: no valid timestamps in input dataframe")
            return out

        out["timestamp_day"] = out["timestamp"].dt.floor("D")

        ts_min_day = out.loc[valid, "timestamp_day"].min()
        ts_max_day = out.loc[valid, "timestamp_day"].max()

        if now_utc is None:
            now = datetime.now(timezone.utc)
        else:
            now = now_utc.astimezone(timezone.utc)
        today_utc = pd.Timestamp(now).floor("D")
        last_complete_day = today_utc - pd.Timedelta(days=1)

        if last_complete_day < ts_min_day:
            logger.warning("Hydrology: no complete SYKE days available for current window")
            out.drop(columns=["timestamp_day"], inplace=True)
            return out

        fetch_start = (ts_min_day - pd.Timedelta(days=carry_days)).to_pydatetime()
        fetch_end = min(ts_max_day, last_complete_day).to_pydatetime()
        day_index = pd.date_range(start=ts_min_day, end=ts_max_day, freq="D", tz=timezone.utc)
        logger.info(
            (
                "Hydrology: Fetching SYKE daily aggregates between %s and %s "
                "(complete days only; excluding %s)."
            ),
            fetch_start.date(),
            fetch_end.date(),
            today_utc.date(),
        )

        for metric in HYDRO_METRICS:
            rows = fetch_metric_rows(
                metric,
                start=fetch_start,
                end=fetch_end,
                chunk_days=chunk_days,
                top=top,
            )
            median, p10 = _compute_daily_quantiles(
                rows,
                places=metric.places,
                day_index=day_index,
            )
            out = _merge_col(out, col=metric.median_col, values=median)
            out = _merge_col(out, col=metric.p10_col, values=p10)

        hydro_cols = [metric.median_col for metric in HYDRO_METRICS] + [
            metric.p10_col for metric in HYDRO_METRICS
        ]
        logger.info(
            "Hydrology: Updated %s rows. Coverage: %s",
            len(out),
            _coverage_line(out, columns=hydro_cols, valid_mask=valid),
        )

        out.drop(columns=["timestamp_day"], inplace=True)
        return out
    except Exception as exc:
        logger.warning("Hydrology update failed: %s", exc, exc_info=True)
        if "timestamp_day" in out.columns:
            out.drop(columns=["timestamp_day"], inplace=True)
        return out


__all__ = ["HYDRO_METRICS", "HydroMetric", "fetch_metric_rows", "update_hydrology"]
