# region imports
import argparse
import os
import random
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd
from dotenv import load_dotenv, dotenv_values

from util.fmi import get_history
from util.logger import logger
from util.sql import db_update
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

# region constants

HISTORY_PARAMETERS = ["TA_PT1H_AVG", "WS_PT1H_AVG"]
DEFAULT_CHUNK_DAYS = 7
DEFAULT_BACKUP_SUFFIX = "%Y%m%d-%H%M%S"

console = Console()


# region exceptions
class FMIScriptError(Exception):
    """Raised when the script cannot proceed."""


# region cli_args
def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and backfill FMI station data in the prediction database."
    )
    parser.add_argument(
        "--env-file",
        default=".env.local",
        help="Path to the environment file containing DB_PATH (default: %(default)s).",
    )
    parser.add_argument(
        "--db-path",
        help="Override the SQLite database path (otherwise read from the env file).",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=DEFAULT_CHUNK_DAYS,
        help="Maximum number of days to request from FMI per API call (default: %(default)s).",
    )

    subparsers = parser.add_subparsers(dest="command")

    def add_shared_station_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--fmisid",
            type=int,
            required=True,
            help="FMISID of the station to validate/backfill.",
        )
        subparser.add_argument(
            "--start",
            required=True,
            help="Start timestamp (inclusive) in ISO format (UTC assumed if none).",
        )
        subparser.add_argument(
            "--end",
            required=True,
            help="End timestamp (inclusive) in ISO format (UTC assumed if none).",
        )

    validate_parser = subparsers.add_parser(
        "validate", help="Check FMI coverage and database gaps without writing."
    )
    add_shared_station_args(validate_parser)
    backfill_parser = subparsers.add_parser(
        "backfill", help="Fetch missing FMI history and update the database."
    )
    add_shared_station_args(backfill_parser)
    backfill_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch data and show the plan without touching the database.",
    )
    backfill_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a safety backup of the database file.",
    )
    backfill_parser.add_argument(
        "--keep-sql",
        type=Path,
        help="Optional path to emit the SQL statements that would be executed.",
    )

    audit_parser = subparsers.add_parser(
        "audit",
        help="Sample random historical windows (from project history) to assess FMI coverage.",
    )
    audit_target_group = audit_parser.add_mutually_exclusive_group(required=True)
    audit_target_group.add_argument(
        "--fmisid",
        type=int,
        help="FMISID to audit.",
    )
    audit_target_group.add_argument(
        "--all",
        action="store_true",
        help="Audit every FMISID referenced in the environment file (FMISID_WS ∪ FMISID_T).",
    )
    audit_parser.add_argument(
        "--samples",
        type=int,
        default=5,
        help="Number of random historical windows to test (default: %(default)s).",
    )
    audit_parser.add_argument(
        "--window-days",
        type=int,
        default=7,
        help="Length of each sampled window in days (default: %(default)s).",
    )
    audit_parser.add_argument(
        "--seed",
        type=int,
        help="Optional random seed for reproducible samples.",
    )
    audit_parser.add_argument(
        "--ensure-columns",
        action="store_true",
        help="Create missing DB columns during audit (default: off, audit stays read-only).",
    )

    return parser.parse_args(argv)


# region helpers
def load_db_path(env_file: str, override: Optional[str]) -> Path:
    if override:
        return Path(override).expanduser()

    env_path = Path(env_file)
    if not env_path.exists():
        raise FMIScriptError(f"Environment file '{env_file}' was not found.")

    load_dotenv(env_file)
    db_path = os.getenv("DB_PATH")
    if not db_path:
        raise FMIScriptError("DB_PATH is missing from the environment file.")
    return Path(db_path).expanduser()


def parse_timestamp(value: str) -> pd.Timestamp:
    ts = pd.to_datetime(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize(timezone.utc)
    else:
        ts = ts.tz_convert(timezone.utc)
    return ts


def build_expected_index(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    if start > end:
        raise FMIScriptError("Start timestamp must be less than or equal to end timestamp.")
    return pd.date_range(start=start, end=end, freq="h", tz=timezone.utc)


def backup_database(db_path: Path, suffix_format: str = DEFAULT_BACKUP_SUFFIX) -> Path:
    timestamp = datetime.now(timezone.utc).strftime(suffix_format)
    backup_path = db_path.with_suffix(f"{db_path.suffix}.{timestamp}.bak")
    shutil.copyfile(db_path, backup_path)
    console.print(f"[green]Created backup at[/green] {backup_path}")
    return backup_path


def load_fmisids_from_env(env_file: str) -> List[int]:
    env_path = Path(env_file)
    if not env_path.exists():
        raise FMIScriptError(f"Environment file '{env_file}' was not found.")

    env_values = dotenv_values(env_file)
    if not env_values:
        return []

    def parse_ids(key: str) -> List[int]:
        raw = env_values.get(key)
        if not raw:
            return []
        ids: List[int] = []
        for value in raw.split(","):
            value = value.strip()
            if not value:
                continue
            try:
                ids.append(int(value))
            except ValueError as exc:
                raise FMIScriptError(
                    f"Invalid FMISID '{value}' in environment variable '{key}'."
                ) from exc
        return ids

    ids = set(parse_ids("FMISID_WS")) | set(parse_ids("FMISID_T"))
    return sorted(ids)


# region schema
def ensure_station_columns(conn: sqlite3.Connection, fmisid: int) -> Set[str]:
    required_columns = {f"t_{fmisid}", f"ws_{fmisid}"}
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(prediction)")
    existing = {row[1] for row in cur.fetchall()}
    missing = required_columns - existing

    if missing:
        for column in sorted(missing):
            logger.info(f"Adding missing column '{column}' to prediction table.")
            cur.execute(f'ALTER TABLE prediction ADD COLUMN "{column}" FLOAT')
        conn.commit()

    return missing


# region fetch
def fetch_history_range(
    fetch_fn: Callable[..., pd.DataFrame],
    fmisid: int,
    start: pd.Timestamp,
    end: pd.Timestamp,
    parameters: Sequence[str],
    chunk_days: int,
) -> pd.DataFrame:
    """
    Fetch history in chunks to respect FMI limits and avoid large single queries.
    """
    frames: List[pd.DataFrame] = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + timedelta(days=chunk_days - 1))
        start_str = chunk_start.strftime("%Y-%m-%d")
        end_str = chunk_end.strftime("%Y-%m-%d")
        logger.debug(
            f"Fetching FMI history for FMISID {fmisid} between {start_str} and {end_str}."
        )
        df_chunk = fetch_fn(fmisid, start_str, parameters, end_date=end_str)
        if not df_chunk.empty:
            df_chunk = df_chunk.rename(columns=str)
            df_chunk["timestamp"] = pd.to_datetime(df_chunk["timestamp"], utc=True)
            df_chunk = df_chunk[(df_chunk["timestamp"] >= chunk_start) & (df_chunk["timestamp"] <= end)]
            frames.append(df_chunk)
        chunk_start = chunk_end + timedelta(days=1)

    if not frames:
        return pd.DataFrame(columns=["timestamp"] + list(parameters))

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
    return combined


# region db_queries
def reindex_prediction_slice(
    conn: sqlite3.Connection,
    index: pd.DatetimeIndex,
    columns: Sequence[str],
) -> pd.DataFrame:
    quoted_columns = ", ".join(f'"{col}"' for col in columns)
    query = f"""
        SELECT timestamp, {quoted_columns}
        FROM prediction
        WHERE timestamp BETWEEN ? AND ?
    """
    df = pd.read_sql_query(
        query,
        conn,
        params=(index[0].isoformat(), index[-1].isoformat()),
        parse_dates=["timestamp"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").reindex(index)
    for column in columns:
        if column not in df.columns:
            df[column] = pd.Series(index=df.index, dtype=float)
    return df


# region gaps
def compress_gaps(mask: pd.Series) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    ranges: List[Tuple[pd.Timestamp, pd.Timestamp]] = []
    current_start: Optional[pd.Timestamp] = None
    previous_ts: Optional[pd.Timestamp] = None
    for ts, is_missing in mask.items():
        if is_missing:
            if current_start is None:
                current_start = ts
            previous_ts = ts
        elif current_start is not None:
            ranges.append((current_start, previous_ts))
            current_start = None
            previous_ts = None
    if current_start is not None and previous_ts is not None:
        ranges.append((current_start, previous_ts))
    return ranges


# region plan_model
@dataclass
class BackfillPlan:
    fmisid: int
    range_start: pd.Timestamp
    range_end: pd.Timestamp
    expected_hours: int
    missing_before: Dict[str, int]
    missing_ranges: List[Tuple[pd.Timestamp, pd.Timestamp]]
    updates: pd.DataFrame
    filled_counts: Dict[str, int]
    remaining_missing: Dict[str, int]
    columns_added: Set[str] = field(default_factory=set)
    warnings: List[str] = field(default_factory=list)

    def has_updates(self) -> bool:
        return not self.updates.empty

    def summary_lines(self) -> List[str]:
        lines = [
            f"FMISID {self.fmisid}: {self.expected_hours} expected hourly records "
            f"between {self.range_start.isoformat()} and {self.range_end.isoformat()}",
        ]
        if self.columns_added:
            lines.append(f"- Added columns: {', '.join(sorted(self.columns_added))}")

        for column in sorted(self.missing_before):
            lines.append(
                f"- {column}: missing before fetch {self.missing_before[column]}, "
                f"filled {self.filled_counts.get(column, 0)}, "
                f"remaining {self.remaining_missing.get(column, 0)}"
            )
        if self.missing_ranges:
            formatted_ranges = ", ".join(
                f"{start.isoformat()} → {end.isoformat()}" for start, end in self.missing_ranges
            )
            lines.append(f"- Missing ranges prior to fetch: {formatted_ranges}")
        if self.warnings:
            lines.append("- Warnings:")
            lines.extend(f"  * {warning}" for warning in self.warnings)
        if not self.has_updates():
            lines.append("- No updates available from FMI for the requested window.")
        return lines


@dataclass
class AuditAggregate:
    fmisid: int
    expected_hours: Dict[str, int]
    remaining_hours: Dict[str, int]
    warnings: List[str]


# region display
def display_plan(
    plan: BackfillPlan,
    heading: str,
    show_columns_added: bool,
    compact: bool = False,
) -> None:
    if compact:
        console.print(f"[bold]{heading}[/bold]")
    else:
        console.rule(Text.from_markup(f"[bold]{heading}[/bold]"))

    if not compact:
        meta_table = Table(show_header=False, box=None)
        meta_table.add_row("Window start", plan.range_start.isoformat())
        meta_table.add_row("Window end", plan.range_end.isoformat())
        meta_table.add_row("Expected hours", str(plan.expected_hours))
        console.print(meta_table)

    coverage_table = Table(box=None)
    coverage_table.add_column("Column", style="bold")
    coverage_table.add_column("Missing before", justify="right")
    coverage_table.add_column("Filled", justify="right")
    coverage_table.add_column("Remaining", justify="right")
    coverage_table.add_column("Coverage", justify="right")

    for column in sorted(plan.missing_before):
        missing_before = plan.missing_before[column]
        remaining = plan.remaining_missing[column]
        filled = plan.filled_counts.get(column, 0)
        expected = plan.expected_hours
        coverage = 1.0 - (remaining / expected) if expected else 1.0
        coverage_table.add_row(
            column,
            f"{missing_before}",
            f"{filled}",
            f"{remaining}",
            f"{coverage*100:.1f}%",
        )

    console.print(coverage_table)

    if show_columns_added and plan.columns_added:
        console.print(
            Panel(
                f"Created columns: {', '.join(sorted(plan.columns_added))}",
                title="Schema Updates",
                style="green",
                expand=False,
            )
        )

    if plan.missing_ranges:
        ranges_table = Table(title="Missing ranges", box=None)
        ranges_table.add_column("Start")
        ranges_table.add_column("End")
        ranges_table.add_column("Hours", justify="right")
        for start, end in plan.missing_ranges:
            hours = int((end - start).total_seconds() // 3600) + 1
            ranges_table.add_row(start.isoformat(), end.isoformat(), str(hours))
        console.print(ranges_table)

    if plan.warnings:
        console.print(
            Panel(
                "\n".join(plan.warnings),
                title="Warnings",
                style="yellow",
                expand=False,
            )
        )


# region manager
class StationBackfillManager:
    def __init__(
        self,
        db_path: Path,
        fetch_fn: Callable[..., pd.DataFrame] = get_history,
        chunk_days: int = DEFAULT_CHUNK_DAYS,
        now_provider: Optional[Callable[[], pd.Timestamp]] = None,
    ):
        self.db_path = db_path
        self.fetch_fn = fetch_fn
        self.chunk_days = chunk_days
        self.now_provider = now_provider or (lambda: pd.Timestamp.now(tz=timezone.utc))

    def prepare_plan(
        self,
        fmisid: int,
        start: pd.Timestamp,
        end: pd.Timestamp,
        ensure_columns: bool = True,
    ) -> BackfillPlan:
        current_utc = self.now_provider().floor("h")
        plan_warnings: List[str] = []

        if start > current_utc:
            raise FMIScriptError(
                "Start timestamp is in the future. No historical data is available yet."
            )

        if end > current_utc:
            plan_warnings.append(
                f"Clipped requested end {end.isoformat()} to {current_utc.isoformat()} "
                "because historical data is only available up to the current hour."
            )
            end = current_utc

        index = build_expected_index(start, end)
        columns = [f"t_{fmisid}", f"ws_{fmisid}"]

        with sqlite3.connect(self.db_path) as conn:
            columns_added: Set[str] = set()
            schema_missing: Set[str] = set()
            if ensure_columns:
                missing = ensure_station_columns(conn, fmisid)
                columns_added = set(missing)
                slice_df = reindex_prediction_slice(conn, index, columns)
            else:
                cur = conn.cursor()
                cur.execute("PRAGMA table_info(prediction)")
                existing = {row[1] for row in cur.fetchall()}
                schema_missing = set(columns) - existing
                if schema_missing:
                    data = {
                        col: pd.Series(float("nan"), index=index, dtype=float)
                        for col in columns
                    }
                    slice_df = pd.DataFrame(data, index=index)
                else:
                    slice_df = reindex_prediction_slice(conn, index, columns)

        missing_mask = slice_df[columns].isna()
        missing_ranges = compress_gaps(missing_mask.any(axis=1))
        missing_before = {col: int(missing_mask[col].sum()) for col in columns}

        if missing_mask.any(axis=None):
            history_df = fetch_history_range(
                self.fetch_fn,
                fmisid,
                start,
                end,
                HISTORY_PARAMETERS,
                self.chunk_days,
            )
        else:
            history_df = pd.DataFrame(columns=["timestamp"] + HISTORY_PARAMETERS)

        column_mapping = {
            "TA_PT1H_AVG": f"t_{fmisid}",
            "WS_PT1H_AVG": f"ws_{fmisid}",
        }
        if history_df.empty:
            updates = pd.DataFrame(columns=["timestamp"] + list(column_mapping.values()))
        else:
            history_df = history_df.rename(columns=column_mapping)
            history_df = history_df[["timestamp"] + list(column_mapping.values())]
            history_df["timestamp"] = pd.to_datetime(history_df["timestamp"], utc=True)
            history_df = history_df[
                (history_df["timestamp"] >= start) & (history_df["timestamp"] <= end)
            ]
            history_df = history_df.sort_values("timestamp").drop_duplicates(subset=["timestamp"])

            combined = slice_df.copy()
            combined.update(history_df.set_index("timestamp"))
            updates_mask = missing_mask.any(axis=1) & slice_df.index.isin(history_df["timestamp"])
            updates = history_df[history_df["timestamp"].isin(slice_df.index[updates_mask])]
            updates = updates.dropna(how="all", subset=list(column_mapping.values()))

        if not history_df.empty:
            # Evaluate fill ratios within slice only
            merged = slice_df.copy()
            merged.update(history_df.set_index("timestamp"))
        else:
            merged = slice_df

        remaining_missing = {
            col: int(merged[col].isna().sum()) for col in columns
        }
        filled_counts = {
            col: missing_before[col] - remaining_missing[col] for col in columns
        }

        warnings: List[str] = []
        for col in columns:
            if remaining_missing[col] > 0:
                warnings.append(
                    f"{col} still missing for {remaining_missing[col]} hours after fetching FMI history."
                )
        if not ensure_columns and schema_missing:
            warnings.append(
                "Schema is missing columns "
                + ", ".join(sorted(schema_missing))
                + ". Run the backfill command with the same FMISID to create them."
            )

        warnings = plan_warnings + warnings

        return BackfillPlan(
            fmisid=fmisid,
            range_start=start,
            range_end=end,
            expected_hours=len(index),
            missing_before=missing_before,
            missing_ranges=missing_ranges,
            updates=updates,
            filled_counts=filled_counts,
            remaining_missing=remaining_missing,
            columns_added=columns_added,
            warnings=warnings,
        )

    def apply_plan(self, plan: BackfillPlan, dry_run: bool = False) -> None:
        if dry_run:
            console.print("[yellow]Dry run enabled – no database changes will be made.[/yellow]")
            return
        if not plan.has_updates():
            console.print("[cyan]No updates to apply.[/cyan]")
            return
        console.print(
            f"[green]Applying {len(plan.updates)} updates for FMISID {plan.fmisid} "
            f"to database '{self.db_path}'.[/green]"
        )
        inserted, updated = db_update(self.db_path, plan.updates.copy())
        console.print(
            f"[green]db_update inserted {len(inserted)} rows and updated {len(updated)} rows.[/green]"
        )


# region handlers
def emit_sql_preview(plan: BackfillPlan, path: Path) -> None:
    if plan.updates.empty:
        console.print("[cyan]No SQL preview generated because there are no updates.[/cyan]")
        return
    lines = ["BEGIN TRANSACTION;"]
    for _, row in plan.updates.iterrows():
        ts = row["timestamp"].isoformat()
        for column in (f"t_{plan.fmisid}", f"ws_{plan.fmisid}"):
            value = row.get(column)
            if pd.isna(value):
                continue
            lines.append(
                f"UPDATE prediction SET \"{column}\" = {float(value):.3f} WHERE timestamp = '{ts}';"
            )
    lines.append("COMMIT;")
    path.write_text("\n".join(lines))
    console.print(f"[green]Wrote SQL preview to[/green] {path}")


def handle_validate(args: argparse.Namespace) -> None:
    db_path = load_db_path(args.env_file, args.db_path)
    manager = StationBackfillManager(db_path, chunk_days=args.chunk_days)
    start = parse_timestamp(args.start)
    end = parse_timestamp(args.end)

    plan = manager.prepare_plan(args.fmisid, start, end, ensure_columns=False)
    display_plan(
        plan,
        heading=f"Validation for FMISID {args.fmisid}",
        show_columns_added=False,
    )


def handle_backfill(args: argparse.Namespace) -> None:
    db_path = load_db_path(args.env_file, args.db_path)
    if not args.no_backup:
        backup_database(db_path)

    manager = StationBackfillManager(db_path, chunk_days=args.chunk_days)
    start = parse_timestamp(args.start)
    end = parse_timestamp(args.end)

    plan = manager.prepare_plan(args.fmisid, start, end, ensure_columns=True)
    display_plan(
        plan,
        heading=f"Backfill plan for FMISID {args.fmisid}",
        show_columns_added=True,
    )

    if args.keep_sql:
        emit_sql_preview(plan, args.keep_sql)

    manager.apply_plan(plan, dry_run=args.dry_run)


def determine_history_bounds(db_path: Path, current_utc: pd.Timestamp) -> Tuple[pd.Timestamp, pd.Timestamp]:
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM prediction")
        min_ts, max_ts = cur.fetchone()

    if min_ts is None or max_ts is None:
        raise FMIScriptError("Unable to determine historical range: prediction table is empty.")

    earliest = pd.to_datetime(min_ts, utc=True)
    latest_db = pd.to_datetime(max_ts, utc=True)
    latest = min(latest_db, current_utc.floor("h"))
    if latest < earliest:
        raise FMIScriptError("Database latest timestamp precedes earliest timestamp.")
    return earliest, latest


def sample_windows(
    earliest: pd.Timestamp,
    latest: pd.Timestamp,
    window: pd.Timedelta,
    samples: int,
    rng: random.Random,
) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    if window <= pd.Timedelta(0):
        raise FMIScriptError("Window length must be positive.")

    if earliest + window > latest:
        # Not enough room for full window; return single truncated window.
        return [(earliest, latest)]

    latest_start = latest - window
    total_seconds = (latest_start - earliest).total_seconds()
    windows: List[Tuple[pd.Timestamp, pd.Timestamp]] = []
    for _ in range(samples):
        offset = rng.uniform(0, total_seconds)
        start = (earliest + pd.to_timedelta(offset, unit="s")).floor("h")
        if start < earliest:
            start = earliest
        end = start + window
        if end > latest:
            end = latest
            start = end - window
        windows.append((start, end))
    return windows


def perform_station_audit(
    manager: StationBackfillManager,
    fmisid: int,
    earliest: pd.Timestamp,
    latest: pd.Timestamp,
    window_days: int,
    samples: int,
    ensure_columns: bool,
    seed: Optional[int],
) -> AuditAggregate:
    window = pd.Timedelta(days=window_days)
    rng = random.Random(seed) if seed is not None else random.Random()
    windows = sample_windows(earliest, latest, window, samples, rng)

    aggregate_expected: Dict[str, int] = {}
    aggregate_remaining: Dict[str, int] = {}
    aggregated_warnings: List[str] = []

    console.rule(
        Text.from_markup(
            f"Audit for FMISID [bold]{fmisid}[/bold] · [italic]{len(windows)} sample(s)[/italic]"
        )
    )
    console.print(
        f"[cyan]Sampling between {earliest.isoformat()} and {latest.isoformat()} "
        f"({window_days}-day windows).[/cyan]"
    )

    for idx, (start, end) in enumerate(windows, start=1):
        plan = manager.prepare_plan(
            fmisid,
            start,
            end,
            ensure_columns=ensure_columns,
        )
        display_plan(
            plan,
            heading=f"Sample {idx}/{len(windows)} · {start.isoformat()} → {plan.range_end.isoformat()}",
            show_columns_added=ensure_columns,
            compact=True,
        )

        for col in plan.remaining_missing.keys():
            aggregate_expected[col] = aggregate_expected.get(col, 0) + plan.expected_hours
            aggregate_remaining[col] = aggregate_remaining.get(col, 0) + plan.remaining_missing[col]
        aggregated_warnings.extend(plan.warnings)

    if not aggregate_expected:
        console.print("[yellow]No data was evaluated during audit.[/yellow]")
        return AuditAggregate(fmisid, {}, {}, aggregated_warnings)

    console.rule("Aggregate Coverage Across Samples")
    agg_table = Table(box=None)
    agg_table.add_column("Column", style="bold")
    agg_table.add_column("Sampled hours", justify="right")
    agg_table.add_column("Missing hours", justify="right")
    agg_table.add_column("Coverage", justify="right")
    for col, expected in aggregate_expected.items():
        remaining = aggregate_remaining.get(col, expected)
        coverage = 1.0 - (remaining / expected) if expected else 1.0
        agg_table.add_row(
            col,
            f"{expected}",
            f"{remaining}",
            f"{coverage*100:.1f}%",
        )
    console.print(agg_table)
    unique_warnings = sorted(set(aggregated_warnings))
    if unique_warnings:
        warning_panel = Panel(
            "\n".join(unique_warnings),
            title="Warnings",
            style="yellow",
        )
        console.print(warning_panel)

    return AuditAggregate(fmisid, aggregate_expected, aggregate_remaining, unique_warnings)


def handle_audit(args: argparse.Namespace) -> None:
    db_path = load_db_path(args.env_file, args.db_path)
    manager = StationBackfillManager(db_path, chunk_days=args.chunk_days)

    current_utc = manager.now_provider().floor("h")
    earliest, latest = determine_history_bounds(db_path, current_utc)
    if latest <= earliest:
        raise FMIScriptError("Historical range too small for auditing.")

    if getattr(args, "all", False):
        env_fmisids = load_fmisids_from_env(args.env_file)
        if not env_fmisids:
            raise FMIScriptError(
                "No FMISIDs found in the environment file. Populate FMISID_WS or FMISID_T."
            )
        target_fmisids = env_fmisids
    else:
        target_fmisids = [args.fmisid]

    aggregates: List[AuditAggregate] = []
    overall_expected: Dict[str, int] = {}
    overall_remaining: Dict[str, int] = {}
    overall_warnings: List[str] = []

    for offset, fmisid in enumerate(target_fmisids):
        station_seed = None if args.seed is None else args.seed + offset
        aggregate = perform_station_audit(
            manager,
            fmisid,
            earliest,
            latest,
            args.window_days,
            args.samples,
            args.ensure_columns,
            station_seed,
        )
        aggregates.append(aggregate)
        for col, expected in aggregate.expected_hours.items():
            overall_expected[col] = overall_expected.get(col, 0) + expected
            remaining = aggregate.remaining_hours.get(col, expected)
            overall_remaining[col] = overall_remaining.get(col, 0) + remaining
        overall_warnings.extend(aggregate.warnings)

    if len(target_fmisids) <= 1:
        return

    console.rule("Overall Coverage Summary")
    summary_table = Table(box=None)
    summary_table.add_column("FMISID", style="bold")
    summary_table.add_column("sampled_h", justify="right")
    summary_table.add_column("t_missing", justify="right")
    summary_table.add_column("t_cov", justify="right")
    summary_table.add_column("ws_missing", justify="right")
    summary_table.add_column("ws_cov", justify="right")
    summary_table.add_column("worst_cov", justify="right")
    summary_table.add_column("total_missing", justify="right")

    station_summaries: List[Dict[str, float]] = []
    for aggregate in aggregates:
        fmisid = aggregate.fmisid
        t_col = f"t_{fmisid}"
        ws_col = f"ws_{fmisid}"
        expected_t = aggregate.expected_hours.get(t_col, 0)
        remaining_t = aggregate.remaining_hours.get(t_col, expected_t)
        expected_ws = aggregate.expected_hours.get(ws_col, 0)
        remaining_ws = aggregate.remaining_hours.get(ws_col, expected_ws)
        coverage_t = 1.0 - (remaining_t / expected_t) if expected_t else 1.0
        coverage_ws = 1.0 - (remaining_ws / expected_ws) if expected_ws else 1.0
        sampled_hours = max(expected_t, expected_ws)
        worst_cov = min(coverage_t, coverage_ws)
        station_summaries.append(
            {
                "fmisid": fmisid,
                "sampled_hours": sampled_hours,
                "remaining_t": remaining_t,
                "coverage_t": coverage_t,
                "remaining_ws": remaining_ws,
                "coverage_ws": coverage_ws,
                "worst_cov": worst_cov,
                "total_missing": remaining_t + remaining_ws,
            }
        )

    station_summaries.sort(
        key=lambda row: (
            row["worst_cov"],
            -row["total_missing"],
            row["fmisid"],
        )
    )

    for summary in station_summaries:
        summary_table.add_row(
            str(summary["fmisid"]),
            f"{int(summary['sampled_hours'])}",
            f"{summary['remaining_t']}",
            f"{summary['coverage_t']*100:.1f}%",
            f"{summary['remaining_ws']}",
            f"{summary['coverage_ws']*100:.1f}%",
            f"{summary['worst_cov']*100:.1f}%",
            f"{summary['total_missing']}",
        )
    console.print(summary_table)

    if overall_expected:
        console.rule("Combined Coverage Across All Columns")
        combined_table = Table(box=None)
        combined_table.add_column("Column", style="bold")
        combined_table.add_column("Sampled hours", justify="right")
        combined_table.add_column("Missing hours", justify="right")
        combined_table.add_column("Coverage", justify="right")
        for col in sorted(overall_expected):
            expected = overall_expected[col]
            remaining = overall_remaining.get(col, expected)
            coverage = 1.0 - (remaining / expected) if expected else 1.0
            combined_table.add_row(
                col,
                f"{expected}",
                f"{remaining}",
                f"{coverage*100:.1f}%",
            )
        console.print(combined_table)

    unique_overall_warnings = sorted(set(overall_warnings))
    if unique_overall_warnings:
        console.print(
            Panel(
                "\n".join(unique_overall_warnings),
                title="Warnings (any station)",
                style="yellow",
            )
        )


# region entrypoint
def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_arguments(argv)
    if args.command is None:
        raise FMIScriptError("Please specify a command. Use --help for usage instructions.")

    if args.command == "validate":
        handle_validate(args)
    elif args.command == "backfill":
        handle_backfill(args)
    elif args.command == "audit":
        handle_audit(args)
    else:
        raise FMIScriptError(f"Unknown command '{args.command}'.")


if __name__ == "__main__":
    try:
        main()
    except FMIScriptError as exc:
        logger.error(exc)
        raise SystemExit(1)
