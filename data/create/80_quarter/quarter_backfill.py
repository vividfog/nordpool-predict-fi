"""
One-off backfill of native 15-min inputs into the `prediction_15min` table.

The live pipeline only fetches the recent -7d/+7d window, so the 15-min model's
training history would otherwise be hourly data interpolated to quarters. This script
fills the history at each source's finest resolution (see util/quarter_data.py):

  prices    Sähkötin &quarter               since 2025-10-01 (15-min market go-live)
  jao       JAO 15-min capacities           since 2025-10-01
  openmeteo Open-Meteo minutely_15 wind + irradiance (archived forecasts)
  fingrid   Fingrid 181/245 wind, 188 nuclear (3 min → quarter means)   needs FINGRID_API_KEY
  fmi       FMI 10-min observations (slow: ~1 request per station-week)

Writes are chunked and idempotent (upserts), so the script can be re-run or resumed.

Usage:
  python -m data.create.80_quarter.quarter_backfill                     # all sources
  python -m data.create.80_quarter.quarter_backfill --sources prices,openmeteo
"""

from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from util.fingrid_nuclear import fetch_nuclear_quarters
from util.fingrid_windpower_xgb import fetch_windpower_quarters
from util.fmi import fetch_station_quarters
from util.jao_imports import fetch_import_capacity_quarters
from util.logger import logger
from util.openmeteo_solar import fetch_irradiance_quarters
from util.openmeteo_windpower import fetch_eu_ws_quarters
from util.quarter_grid import QUARTER_START, combine_fine
from util.sahkotin import fetch_quarter_prices
from util.sql import db_quarter_update

SOURCES = ["prices", "jao", "openmeteo", "fingrid", "fmi"]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Backfill native 15-min inputs into prediction_15min.")
    parser.add_argument("--db-path", default=None, help="SQLite DB (default: DB_PATH from .env.local).")
    parser.add_argument("--start", default="2023-01-01", help="Start date, UTC (default: %(default)s).")
    parser.add_argument("--end", default=None, help="End date, UTC (default: now).")
    parser.add_argument("--sources", default=",".join(SOURCES), help="Comma-separated subset of: " + ", ".join(SOURCES))
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report, write nothing.")
    parser.add_argument("--no-backup", action="store_true", help="Skip the DB backup copy before writes.")
    return parser.parse_args(argv)


def _chunks(start, end, days):
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + pd.Timedelta(days=days), end)
        yield cursor, chunk_end
        cursor = chunk_end


def _write(db_path, df, label, dry_run):
    if df is None or df.empty:
        logger.warning(f"Backfill {label}: no data")
        return
    cols = [c for c in df.columns if c != "timestamp"]
    span = f"{df['timestamp'].min():%Y-%m-%d %H:%M} → {df['timestamp'].max():%Y-%m-%d %H:%M}"
    if dry_run:
        logger.info(f"Backfill {label}: {len(df)} quarters, {len(cols)} columns ({span}) [dry run]")
        return
    written = db_quarter_update(db_path, df, cols)
    logger.info(f"Backfill {label}: wrote {written} quarters, {len(cols)} columns ({span})")


def main(argv=None):
    load_dotenv(".env.local")
    args = parse_args(argv)
    db_path = Path(args.db_path or os.getenv("DB_PATH", "data/prediction.db"))
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC") if args.end else pd.Timestamp.utcnow().floor("15min")
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = set(sources) - set(SOURCES)
    if unknown:
        raise SystemExit(f"Unknown sources: {', '.join(sorted(unknown))}")

    if not args.dry_run and not args.no_backup and db_path.exists():
        backup = db_path.with_suffix(f"{db_path.suffix}.{datetime.now():%Y%m%d%H%M%S}.bak")
        shutil.copyfile(db_path, backup)
        logger.info(f"Created DB backup: {backup}")

    market_start = max(start, QUARTER_START)

    if "prices" in sources and market_start < end:
        _write(db_path, fetch_quarter_prices(market_start, end), "Sähkötin prices", args.dry_run)

    if "jao" in sources and market_start < end:
        for chunk_start, chunk_end in _chunks(market_start, end, 30):
            _write(db_path, fetch_import_capacity_quarters(chunk_start, chunk_end), "JAO capacities", args.dry_run)

    if "openmeteo" in sources:
        # One request per site per year inside the fetchers
        frame = combine_fine(fetch_eu_ws_quarters(start, end), fetch_irradiance_quarters(start, end))
        _write(db_path, frame, "Open-Meteo wind + irradiance", args.dry_run)

    if "fingrid" in sources:
        api_key = os.getenv("FINGRID_API_KEY")
        if not api_key:
            logger.error("Backfill fingrid: FINGRID_API_KEY not set, skipping")
        else:
            # 30 days of 3-min data stays under Fingrid's 20k rows per page
            for chunk_start, chunk_end in _chunks(start, end, 30):
                frame = combine_fine(
                    fetch_windpower_quarters(api_key, chunk_start, chunk_end - pd.Timedelta(days=1)),
                    fetch_nuclear_quarters(api_key, chunk_start, chunk_end - pd.Timedelta(days=1)),
                )
                _write(db_path, frame, f"Fingrid {chunk_start:%Y-%m}", args.dry_run)

    if "fmi" in sources:
        stations = sorted(
            (set(os.getenv("FMISID_WS", "").split(",")) | set(os.getenv("FMISID_T", "").split(","))) - {""}
        )
        for station in stations:
            for chunk_start, chunk_end in _chunks(start, end, 91):
                _write(
                    db_path,
                    fetch_station_quarters([station], chunk_start, chunk_end),
                    f"FMI {station} {chunk_start:%Y-%m}",
                    args.dry_run,
                )


if __name__ == "__main__":
    main()
