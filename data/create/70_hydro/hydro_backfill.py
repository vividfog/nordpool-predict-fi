from __future__ import annotations

import argparse
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import MetricConfig, metrics as hydro_metrics
from .syke_odata import FetchSpec, fetch_rows
from util.logger import logger
from util.sql import normalize_timestamp


HYDRO_COLUMNS = [
    "HydroPrecip_5d_median",
    "HydroPrecip_5d_p10",
    "HydroSWE_median",
    "HydroSWE_p10",
]


@dataclass(frozen=True)
class BackfillConfig:
    db_path: Path
    start: datetime
    end: datetime
    coverage_threshold: int
    carry_days: int
    chunk_days: int
    top: int
    dry_run: bool
    no_backup: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "DEV backfill for SYKE hydrology aggregate features into prediction.db.\n"
            "Writes 4 columns: HydroPrecip_5d_{median,p10}, HydroSWE_{median,p10}.\n"
            "Algorithm: per-place forward-fill + coverage guard to avoid 'today is incomplete' issues."
        )
    )
    parser.add_argument(
        "--db-path",
        default="data/prediction.db",
        help="Path to prediction SQLite DB (default: %(default)s).",
    )
    parser.add_argument(
        "--start",
        default="2023-01-01T00:00:00Z",
        help="Start timestamp (inclusive), ISO format (default: %(default)s).",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End timestamp (inclusive), ISO format. Default: last full UTC day (00:00).",
    )
    parser.add_argument(
        "--coverage-threshold",
        type=int,
        default=7,
        help="Minimum number of places (out of 10) required to accept a day's observation (default: %(default)s).",
    )
    parser.add_argument(
        "--carry-days",
        type=int,
        default=60,
        help="How many days of carry-in history to fetch to seed forward-fill (default: %(default)s).",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=31,
        help="SYKE fetch chunk size in days (default: %(default)s).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=500,
        help="SYKE OData page size ($top) (default: %(default)s).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute features and print summary, but do not write to DB.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a backup copy of the database file before writes.",
    )
    return parser.parse_args(argv)


def _parse_ts(value: str) -> datetime:
    ts = pd.to_datetime(value, utc=True)
    if ts.tzinfo is None:
        ts = ts.tz_localize(timezone.utc)
    ts = ts.tz_convert(timezone.utc)
    return ts.to_pydatetime()


def _default_end_utc_day() -> datetime:
    # Avoid today's potentially incomplete SYKE day; use yesterday 00:00 UTC.
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=1)


def _backup_db(db_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_suffix(f"{db_path.suffix}.{stamp}.bak")
    shutil.copyfile(db_path, backup_path)
    logger.info("Created DB backup: %s", backup_path)
    return backup_path


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))


def _ensure_columns(conn: sqlite3.Connection, columns: list[str]) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(prediction)")
    existing = {row[1] for row in cur.fetchall()}

    for col in columns:
        if col in existing:
            continue
        logger.info("Adding missing column '%s' to prediction table.", col)
        cur.execute(f'ALTER TABLE prediction ADD COLUMN "{col}" FLOAT')
    conn.commit()


def _load_timestamps(conn: sqlite3.Connection, start: datetime, end: datetime) -> pd.Series:
    start_s = normalize_timestamp(start.isoformat())
    end_s = normalize_timestamp(end.isoformat())
    query = (
        "SELECT timestamp FROM prediction "
        "WHERE timestamp >= ? AND timestamp <= ? "
        "ORDER BY timestamp ASC"
    )
    df = pd.read_sql_query(query, conn, params=(start_s, end_s))
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce").dropna()
    return ts.sort_values()


def _build_daily_index(start: datetime, end: datetime) -> pd.DatetimeIndex:
    start_day = start.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = end.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return pd.date_range(start=start_day, end=end_day, freq="D", tz=timezone.utc)


def _compute_daily_quantiles(
    df_rows: pd.DataFrame,
    *,
    places: list[int],
    daily_index: pd.DatetimeIndex,
    coverage_threshold: int,
    carry_in: bool,
) -> tuple[pd.Series, pd.Series]:
    """
    Returns (median_series, p10_series) indexed by daily_index.

    Algorithm:
    - pivot to daily rows x place columns
    - compute raw coverage per day (count non-null)
    - forward-fill per place (with carry-in if enabled)
    - compute per-day median and p10 across places
    - apply coverage guard: if raw coverage < threshold on a day, treat it as missing and ffill from previous accepted day
    """
    if df_rows.empty:
        empty = pd.Series(index=daily_index, dtype=float)
        return empty, empty

    pivot = df_rows.pivot(index="Aika", columns="Paikka_Id", values="Arvo").sort_index()
    pivot = pivot.reindex(columns=places)

    if carry_in:
        ext_index = pd.date_range(
            start=min(pivot.index.min(), daily_index.min()),
            end=daily_index.max(),
            freq="D",
            tz=timezone.utc,
        )
        pivot_ext = pivot.reindex(ext_index)
        coverage_raw = pivot_ext.notna().sum(axis=1).reindex(daily_index)
        pivot_ext = pivot_ext.ffill().reindex(daily_index)
    else:
        pivot_win = pivot.reindex(daily_index)
        coverage_raw = pivot_win.notna().sum(axis=1)
        pivot_ext = pivot_win.ffill()

    median = pivot_ext.median(axis=1, skipna=True)
    p10 = pivot_ext.quantile(0.10, axis=1, interpolation="linear")

    good = coverage_raw >= coverage_threshold
    median = median.where(good).ffill()
    p10 = p10.where(good).ffill()
    return median, p10


def _fetch_metric_rows(
    metric: MetricConfig,
    *,
    start: datetime,
    end: datetime,
    carry_days: int,
    chunk_days: int,
    top: int,
) -> pd.DataFrame:
    carry_start = start - timedelta(days=carry_days)
    spec = FetchSpec(
        entity=metric.entity,
        places=metric.places,
        start=carry_start,
        end=end,
        extra_filter=metric.extra_filter,
    )
    return fetch_rows(spec, chunk_days=chunk_days, top=top)


def _expand_daily_to_hourly(
    daily: pd.Series, hourly_index: pd.DatetimeIndex
) -> pd.Series:
    s = daily.copy()
    s.index = pd.to_datetime(s.index, utc=True)
    hourly = s.reindex(hourly_index, method="ffill")
    return hourly


def _build_feature_frame(cfg: BackfillConfig) -> pd.DataFrame:
    end = cfg.end.astimezone(timezone.utc)
    start = cfg.start.astimezone(timezone.utc)

    daily_index = _build_daily_index(start, end)
    hourly_index = pd.date_range(
        start=start,
        end=end.replace(hour=23, minute=0, second=0, microsecond=0),
        freq="h",
        tz=timezone.utc,
    )

    metric_by_name = {m.name: m for m in hydro_metrics()}
    swe = metric_by_name["HydroSWE"]
    precip = metric_by_name["HydroPrecip_5d"]

    logger.info("Fetching SYKE rows for HydroSWE and HydroPrecip_5d (with carry-in).")
    swe_rows = _fetch_metric_rows(
        swe,
        start=start,
        end=end,
        carry_days=cfg.carry_days,
        chunk_days=cfg.chunk_days,
        top=cfg.top,
    )
    precip_rows = _fetch_metric_rows(
        precip,
        start=start,
        end=end,
        carry_days=cfg.carry_days,
        chunk_days=cfg.chunk_days,
        top=cfg.top,
    )

    swe_median_d, swe_p10_d = _compute_daily_quantiles(
        swe_rows,
        places=swe.places,
        daily_index=daily_index,
        coverage_threshold=cfg.coverage_threshold,
        carry_in=True,
    )
    precip_median_d, precip_p10_d = _compute_daily_quantiles(
        precip_rows,
        places=precip.places,
        daily_index=daily_index,
        coverage_threshold=cfg.coverage_threshold,
        carry_in=True,
    )

    df = pd.DataFrame(
        {
            "timestamp": hourly_index,
            "HydroPrecip_5d_median": _expand_daily_to_hourly(precip_median_d, hourly_index).to_numpy(),
            "HydroPrecip_5d_p10": _expand_daily_to_hourly(precip_p10_d, hourly_index).to_numpy(),
            "HydroSWE_median": _expand_daily_to_hourly(swe_median_d, hourly_index).to_numpy(),
            "HydroSWE_p10": _expand_daily_to_hourly(swe_p10_d, hourly_index).to_numpy(),
        }
    )
    return df


def _bulk_update(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0

    # Update only existing rows.
    cur = conn.cursor()
    stmt = (
        "UPDATE prediction SET "
        "\"HydroPrecip_5d_median\"=?, "
        "\"HydroPrecip_5d_p10\"=?, "
        "\"HydroSWE_median\"=?, "
        "\"HydroSWE_p10\"=? "
        "WHERE timestamp=?"
    )

    # Normalize timestamps to match DB convention.
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.copy()
    df["timestamp"] = ts.dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    params = list(
        zip(
            df["HydroPrecip_5d_median"].astype(float).tolist(),
            df["HydroPrecip_5d_p10"].astype(float).tolist(),
            df["HydroSWE_median"].astype(float).tolist(),
            df["HydroSWE_p10"].astype(float).tolist(),
            df["timestamp"].tolist(),
        )
    )
    cur.executemany(stmt, params)
    conn.commit()
    return int(cur.rowcount)


def _print_summary(df: pd.DataFrame) -> None:
    if df.empty:
        logger.warning("No feature rows produced.")
        return

    def describe(col: str) -> str:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            return f"{col}: (empty)"
        return (
            f"{col}: min={s.min():.2f} p10={s.quantile(0.10):.2f} "
            f"median={s.median():.2f} p90={s.quantile(0.90):.2f} max={s.max():.2f}"
        )

    logger.info("Feature frame hours: %s (%s..%s)", len(df), df["timestamp"].min(), df["timestamp"].max())
    for col in HYDRO_COLUMNS:
        logger.info(describe(col))


def run_backfill(cfg: BackfillConfig) -> int:
    if cfg.coverage_threshold < 1 or cfg.coverage_threshold > 10:
        raise ValueError("coverage_threshold must be between 1 and 10 for a 10-place aggregate")

    if not cfg.db_path.exists():
        raise FileNotFoundError(f"DB not found: {cfg.db_path}")

    conn = _connect(cfg.db_path)
    try:
        # The feature frame is hourly until end-day 23:00 UTC, so DB timestamp
        # selection must cover the full end day as well.
        db_end = cfg.end.replace(hour=23, minute=0, second=0, microsecond=0)
        ts = _load_timestamps(conn, cfg.start, db_end)
        if ts.empty:
            logger.warning("No timestamps found in DB between %s and %s", cfg.start, cfg.end)
            return 0

        df_features = _build_feature_frame(cfg)
        _print_summary(df_features)

        # Only update timestamps that exist in the DB and are within the window.
        df_features["timestamp"] = pd.to_datetime(df_features["timestamp"], utc=True)
        df_features = df_features[df_features["timestamp"].isin(ts)]

        if cfg.dry_run:
            logger.info("Dry-run: would update %s DB rows.", len(df_features))
            return 0

        if not cfg.no_backup:
            _backup_db(cfg.db_path)

        _ensure_columns(conn, HYDRO_COLUMNS)
        updated = _bulk_update(conn, df_features)
        logger.info("Updated %s DB rows.", updated)
        return 0
    finally:
        conn.close()


def main() -> None:
    args = parse_args()

    end = _parse_ts(args.end) if args.end else _default_end_utc_day()
    start = _parse_ts(args.start)

    cfg = BackfillConfig(
        db_path=Path(args.db_path),
        start=start,
        end=end,
        coverage_threshold=int(args.coverage_threshold),
        carry_days=int(args.carry_days),
        chunk_days=int(args.chunk_days),
        top=int(args.top),
        dry_run=bool(args.dry_run),
        no_backup=bool(args.no_backup),
    )

    raise SystemExit(run_backfill(cfg))


if __name__ == "__main__":
    main()
