"""
archive.py

This module manages an SQLite archive of your price prediction snapshots.

Functions:
1. insert_snapshot(db_path, df) - Archive a new prediction snapshot
2. get_predictions(db_path, df) - Retrieve archived predictions for timestamps
3. compute_error(db_path, df) - Calculate error metrics over time ranges

The archive schema follows the prediction data dynamically so newly added
numeric features cannot disappear silently from snapshots.
"""

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .logger import logger

# Suppress FutureWarning messages from pandas for now
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)


ARCHIVE_SCHEMA_VERSION = 2
NORDPOOL_PUBLICATION_HOUR = 14
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_SNAPSHOT_COLUMNS = {"archive_id", "run_id"}


def _quote_identifier(identifier):
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"Unsafe SQLite identifier: {identifier!r}")
    return f'"{identifier}"'


def _base_schema_statements():
    return [
        """
        CREATE TABLE IF NOT EXISTS prediction_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_datetime TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            columns_json TEXT NOT NULL DEFAULT '[]'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS archived_predictions (
            archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            PricePredict_cpkWh REAL NOT NULL,
            Price_cpkWh REAL,
            FOREIGN KEY(run_id) REFERENCES prediction_runs(run_id),
            UNIQUE(run_id, timestamp)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS actual_prices (
            timestamp TEXT PRIMARY KEY,
            Price_cpkWh REAL NOT NULL,
            updated_at TEXT NOT NULL,
            source TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS archive_schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """,
    ]


def _sqlite_type_from_dtype(dtype):
    if pd.api.types.is_bool_dtype(dtype) or pd.api.types.is_integer_dtype(dtype):
        return "INTEGER"
    if pd.api.types.is_numeric_dtype(dtype):
        return "REAL"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "TEXT"
    raise TypeError(f"Unsupported snapshot dtype: {dtype}")


def _sqlite_type_from_declared_type(declared_type):
    normalized = (declared_type or "").upper()
    if "INT" in normalized:
        return "INTEGER"
    if any(token in normalized for token in ("REAL", "FLOA", "DOUB", "NUM")):
        return "REAL"
    if any(token in normalized for token in ("TEXT", "CHAR", "CLOB", "DATE", "TIME")):
        return "TEXT"
    raise TypeError(f"Unsupported SQLite column type: {declared_type!r}")


def _snapshot_column_definitions(df):
    definitions = {}
    for column, dtype in df.dtypes.items():
        if column in _RESERVED_SNAPSHOT_COLUMNS:
            raise ValueError(f"Snapshot contains reserved column {column!r}")
        _quote_identifier(column)
        if column == "timestamp":
            definitions[column] = "TEXT"
        elif column in {"PricePredict_cpkWh", "Price_cpkWh"}:
            definitions[column] = "REAL"
        else:
            definitions[column] = _sqlite_type_from_dtype(dtype)
    return definitions


def _ensure_metadata_columns(conn):
    run_columns = set(_get_table_columns(conn, "prediction_runs"))
    if "schema_version" not in run_columns:
        conn.execute(
            "ALTER TABLE prediction_runs ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1"
        )
    if "columns_json" not in run_columns:
        conn.execute(
            "ALTER TABLE prediction_runs ADD COLUMN columns_json TEXT NOT NULL DEFAULT '[]'"
        )


def ensure_archive_schema(conn, column_definitions=None):
    """Create and idempotently extend the archive schema."""
    conn.execute("PRAGMA foreign_keys = ON")
    for statement in _base_schema_statements():
        conn.execute(statement)
    _ensure_metadata_columns(conn)

    existing = set(_get_table_columns(conn, "archived_predictions"))
    added = []
    for column, sqlite_type in (column_definitions or {}).items():
        if column in _RESERVED_SNAPSHOT_COLUMNS or column in existing:
            continue
        _quote_identifier(column)
        if sqlite_type not in {"INTEGER", "REAL", "TEXT"}:
            raise TypeError(f"Unsupported archive type for {column}: {sqlite_type}")
        conn.execute(
            f"ALTER TABLE archived_predictions ADD COLUMN {_quote_identifier(column)} {sqlite_type}"
        )
        added.append(column)
        existing.add(column)

    conn.execute(
        "INSERT OR IGNORE INTO archive_schema_migrations (version, applied_at) VALUES (?, ?)",
        (ARCHIVE_SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
    )
    return added


def _python_sqlite_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return normalize_timestamp(value)
    return value


def _upsert_actuals_from_frame(conn, df, source="snapshot"):
    if "Price_cpkWh" not in df.columns:
        return 0
    actuals = df.loc[df["Price_cpkWh"].notna(), ["timestamp", "Price_cpkWh"]]
    if actuals.empty:
        return 0
    updated_at = datetime.now(timezone.utc).isoformat()
    values = [
        (normalize_timestamp(row.timestamp), float(row.Price_cpkWh), updated_at, source)
        for row in actuals.itertuples(index=False)
    ]
    conn.executemany(
        """
        INSERT INTO actual_prices (timestamp, Price_cpkWh, updated_at, source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(timestamp) DO UPDATE SET
            Price_cpkWh=excluded.Price_cpkWh,
            updated_at=excluded.updated_at,
            source=excluded.source
        """,
        values,
    )
    return len(values)


def _sync_actuals_from_attached_prediction_db(conn, source_db_path):
    source_path = str(Path(source_db_path).resolve())
    conn.execute("ATTACH DATABASE ? AS prediction_source", (source_path,))
    try:
        updated_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO actual_prices (timestamp, Price_cpkWh, updated_at, source)
            SELECT timestamp, Price_cpkWh, ?, 'prediction.db'
            FROM prediction_source.prediction
            WHERE Price_cpkWh IS NOT NULL
            ON CONFLICT(timestamp) DO UPDATE SET
                Price_cpkWh=excluded.Price_cpkWh,
                updated_at=excluded.updated_at,
                source=excluded.source
            """,
            (updated_at,),
        )
        conn.execute(
            """
            UPDATE archived_predictions
            SET Price_cpkWh = (
                SELECT actual_prices.Price_cpkWh
                FROM actual_prices
                WHERE actual_prices.timestamp = archived_predictions.timestamp
            )
            WHERE EXISTS (
                SELECT 1 FROM actual_prices
                WHERE actual_prices.timestamp = archived_predictions.timestamp
                  AND archived_predictions.Price_cpkWh IS NOT actual_prices.Price_cpkWh
            )
            """
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("DETACH DATABASE prediction_source")


def backup_archive_database(db_path, backup_path=None):
    """Create a consistent SQLite backup and return its path."""
    source_path = Path(db_path)
    if backup_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = source_path.with_name(f"{source_path.stem}_{stamp}.backup.db")
    backup_path = Path(backup_path)
    if backup_path.exists():
        raise FileExistsError(f"Backup already exists: {backup_path}")
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as destination:
        source.backup(destination)
    return backup_path


def _prediction_column_definitions(source_db_path):
    with sqlite3.connect(source_db_path) as source:
        rows = source.execute("PRAGMA table_info(prediction)").fetchall()
    if not rows:
        raise RuntimeError(f"No prediction table found in {source_db_path}")
    definitions = {}
    for row in rows:
        column = row[1]
        if column in _RESERVED_SNAPSHOT_COLUMNS:
            continue
        definitions[column] = (
            "TEXT" if column == "timestamp" else _sqlite_type_from_declared_type(row[2])
        )
    return definitions


def migrate_archive_database(db_path, source_db_path, dry_run=False):
    """Migrate an archive against prediction.db and optionally sync actual prices."""
    definitions = _prediction_column_definitions(source_db_path)
    with sqlite3.connect(db_path) as conn:
        existing = set(_get_table_columns(conn, "archived_predictions"))
        missing = sorted(set(definitions) - existing)
        before_rows = conn.execute(
            "SELECT COUNT(*) FROM archived_predictions"
        ).fetchone()[0] if existing else 0
        report = {
            "dry_run": dry_run,
            "missing_columns": missing,
            "rows_before": before_rows,
        }
        if dry_run:
            return report

        conn.execute("BEGIN")
        added = ensure_archive_schema(conn, definitions)
        conn.commit()
        _sync_actuals_from_attached_prediction_db(conn, source_db_path)
        report["added_columns"] = sorted(added)
        report["rows_after"] = conn.execute(
            "SELECT COUNT(*) FROM archived_predictions"
        ).fetchone()[0]
        report["actual_prices"] = conn.execute(
            "SELECT COUNT(*) FROM actual_prices"
        ).fetchone()[0]
        report["legacy_actuals"] = conn.execute(
            "SELECT COUNT(*) FROM archived_predictions WHERE Price_cpkWh IS NOT NULL"
        ).fetchone()[0]
        return report


def normalize_timestamp(ts):
    """
    Convert ts to a UTC-aware ISO8601 string.
    
    Converts a timestamp string into a datetime object, ensuring it is timezone-aware (UTC),
    and formats it as an ISO8601 string. This standardized format is crucial for consistency 
    across database operations, especially when dealing with timestamps in the schema.
    
    Parameters:
    - ts: A timestamp string or datetime object that may or may not include timezone information.
    
    Returns:
    - A string representing the timestamp in ISO8601 format with UTC timezone information.
    """
    dt = pd.to_datetime(ts)
    if dt.tzinfo is None:
        dt = dt.tz_localize('UTC')
    else:
        dt = dt.tz_convert('UTC')
    return dt.isoformat()


def is_true_prediction(run_datetime, prediction_timestamp):
    """Return whether a local delivery date was unknown when the run started."""
    run = pd.to_datetime(run_datetime)
    prediction = pd.to_datetime(prediction_timestamp)
    if run.tzinfo is None:
        run = run.tz_localize("UTC")
    if prediction.tzinfo is None:
        prediction = prediction.tz_localize("UTC")

    run_local = run.tz_convert("Europe/Helsinki")
    prediction_local = prediction.tz_convert("Europe/Helsinki")
    last_known_local_date = run_local.date()
    if run_local.hour >= NORDPOOL_PUBLICATION_HOUR:
        last_known_local_date += pd.Timedelta(days=1)
    return prediction_local.date() > last_known_local_date


def _get_table_columns(conn, table_name):
    """
    Get the column names of a table in the SQLite database.
    
    Parameters:
    - conn: SQLite database connection
    - table_name: Name of the table
    
    Returns:
    - List of column names
    """
    try:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = [row[1] for row in cursor.fetchall()]
        return columns
    except sqlite3.Error as e:
        logger.error(f"Error fetching table schema: {e}", exc_info=True)
        return []


def insert_snapshot(db_path, df, source_db_path=None):
    """
    Insert a new snapshot run and its forecasts into the archive.
    
    Creates a new entry in prediction_runs and inserts all DataFrame columns
    into archived_predictions. The archive schema is extended transactionally
    when the prediction schema gains a supported column.
    
    Parameters:
    - db_path: Path to the SQLite database
    - df: DataFrame with 'timestamp' column and prediction data
    
    Returns:
    - The ID of the newly created run, or None if insertion failed
    """
    required_columns = {'timestamp', 'PricePredict_cpkWh'}
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        logger.error(f"Required snapshot columns missing: {missing_columns}")
        return None

    try:
        insert_df = df.copy()
        if insert_df.empty:
            raise ValueError("Cannot archive an empty prediction snapshot")
        if insert_df['timestamp'].isna().any():
            raise ValueError("Snapshot contains a missing timestamp")
        if insert_df['PricePredict_cpkWh'].isna().any():
            raise ValueError("Snapshot contains a missing PricePredict_cpkWh")

        insert_df['timestamp'] = insert_df['timestamp'].apply(normalize_timestamp)
        if insert_df['timestamp'].duplicated().any():
            raise ValueError("Snapshot contains duplicate timestamps")
        column_definitions = _snapshot_column_definitions(insert_df)
    except Exception as e:
        logger.error(f"Invalid prediction snapshot: {e}", exc_info=True)
        return None

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        ensure_archive_schema(conn, column_definitions)

        archive_columns = set(_get_table_columns(conn, "archived_predictions"))
        missing_after_migration = sorted(set(insert_df.columns) - archive_columns)
        if missing_after_migration:
            raise RuntimeError(
                f"Archive schema still lacks snapshot columns: {missing_after_migration}"
            )

        columns = list(insert_df.columns)
        run_datetime = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            """
            INSERT INTO prediction_runs
                (run_datetime, schema_version, columns_json)
            VALUES (?, ?, ?)
            """,
            (run_datetime, ARCHIVE_SCHEMA_VERSION, json.dumps(columns)),
        )
        run_id = cursor.lastrowid

        insert_columns = ", ".join(
            [_quote_identifier(column) for column in columns] + ['"run_id"']
        )
        placeholders = ", ".join("?" for _ in range(len(columns) + 1))
        values = [
            tuple(_python_sqlite_value(row[column]) for column in columns) + (run_id,)
            for _, row in insert_df.iterrows()
        ]
        changes_before = conn.total_changes
        conn.executemany(
            f"INSERT INTO archived_predictions ({insert_columns}) VALUES ({placeholders})",
            values,
        )
        inserted_count = conn.total_changes - changes_before
        if inserted_count != len(values):
            raise RuntimeError(
                f"Archived {inserted_count} of {len(values)} prediction rows"
            )

        _upsert_actuals_from_frame(conn, insert_df)
        conn.commit()
        logger.info(
            f"→ Inserted new prediction run (ID: {run_id}) "
            f"with {inserted_count} predictions"
        )
    except Exception as e:
        if conn is not None:
            conn.rollback()
        logger.error(f"Error inserting snapshot: {e}", exc_info=True)
        return None
    finally:
        if conn is not None:
            conn.close()

    if source_db_path is not None:
        try:
            with sqlite3.connect(db_path) as sync_conn:
                ensure_archive_schema(sync_conn)
                sync_conn.commit()
                _sync_actuals_from_attached_prediction_db(sync_conn, source_db_path)
        except Exception as e:
            logger.error(
                f"Prediction run {run_id} was archived, but actual-price sync failed: {e}",
                exc_info=True,
            )

    return run_id


def get_predictions(db_path, df):
    """
    Fetch archived forecasts + actuals for given hours.

    Inputs:
      - df['timestamp'] (datetime or ISO8601 strings)

    Output:
      DataFrame with:
        ['run_id', 'timestamp', 'PricePredict_cpkWh', 'Price_cpkWh']
        
    Parameters:
    - db_path: Path to the SQLite database
    - df: DataFrame with 'timestamp' column
    
    Returns:
    - DataFrame with archived predictions
    """
    if 'timestamp' not in df.columns:
        logger.error("DataFrame must contain 'timestamp' column")
        return pd.DataFrame()
        
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error as e:
        logger.error(f"SQLite connection error in get_predictions: {e}", exc_info=True)
        sys.exit(1)
        
    # Normalize timestamps
    normalized_timestamps = [normalize_timestamp(ts) for ts in df['timestamp']]
    
    # Create placeholders for SQL query
    placeholders = ','.join(['?'] * len(normalized_timestamps))
    
    try:
        ensure_archive_schema(conn)
        conn.commit()
        query = f"""
        SELECT a.*, COALESCE(p.Price_cpkWh, a.Price_cpkWh) AS canonical_Price_cpkWh,
               r.run_datetime
        FROM archived_predictions a
        JOIN prediction_runs r ON a.run_id = r.run_id
        LEFT JOIN actual_prices p ON p.timestamp = a.timestamp
        WHERE a.timestamp IN ({placeholders})
        ORDER BY a.timestamp, a.run_id
        """
        
        result = pd.read_sql_query(query, conn, params=tuple(normalized_timestamps))
        
        # Convert timestamp strings back to datetime objects
        if not result.empty and 'timestamp' in result.columns:
            result['timestamp'] = pd.to_datetime(result['timestamp'])
            result['Price_cpkWh'] = result.pop('canonical_Price_cpkWh')
            
        logger.info(f"Retrieved {len(result)} archived predictions")
        return result
        
    except Exception as e:
        logger.error(f"Error retrieving predictions: {e}", exc_info=True)
        return pd.DataFrame()
    finally:
        conn.close()


def compute_error(db_path, df):
    """
    Compute error metrics over time ranges.

    Inputs:
      - df['start'], df['end'] (datetime or ISO8601 strings)

    Output:
      Same df with added columns:
        - mae   (mean absolute error)
        - rmse  (root mean squared error)
        - mape  (mean absolute percentage error)
        
    Parameters:
    - db_path: Path to the SQLite database
    - df: DataFrame with 'start' and 'end' columns
    
    Returns:
    - Original DataFrame with added error metrics columns
    """
    if 'start' not in df.columns or 'end' not in df.columns:
        logger.error("DataFrame must contain 'start' and 'end' columns")
        return df
        
    # Create a copy of the input dataframe to add metrics
    result_df = df.copy()
    
    # Add empty columns for the metrics
    result_df['mae'] = np.nan
    result_df['rmse'] = np.nan
    result_df['mape'] = np.nan
    
    try:
        conn = sqlite3.connect(db_path)
        ensure_archive_schema(conn)
        conn.commit()
        
        # Process each range
        for i, row in result_df.iterrows():
            # Normalize timestamps
            start_ts = normalize_timestamp(row['start'])
            end_ts = normalize_timestamp(row['end'])
            
            # Query for predictions within the range where actual prices exist
            query = """
            SELECT a.run_id, a.timestamp, a.PricePredict_cpkWh,
                   COALESCE(p.Price_cpkWh, a.Price_cpkWh) AS Price_cpkWh
            FROM archived_predictions a
            LEFT JOIN actual_prices p ON p.timestamp = a.timestamp
            WHERE a.timestamp >= ? AND a.timestamp <= ?
              AND COALESCE(p.Price_cpkWh, a.Price_cpkWh) IS NOT NULL
            ORDER BY a.timestamp, a.run_id
            """
            
            predictions = pd.read_sql_query(query, conn, params=(start_ts, end_ts))
            
            # Skip if no data found
            if predictions.empty:
                logger.info(f"No data found for range {start_ts} to {end_ts}")
                continue
                
            # Calculate error metrics
            errors = predictions['PricePredict_cpkWh'] - predictions['Price_cpkWh']
            abs_errors = np.abs(errors)
            squared_errors = errors ** 2
            
            # Mean Absolute Error
            mae = abs_errors.mean()
            
            # Root Mean Squared Error
            rmse = np.sqrt(squared_errors.mean())
            
            # Mean Absolute Percentage Error (handling zeros with small epsilon)
            epsilon = 1e-10  # Small value to avoid division by zero
            abs_percentage_errors = abs_errors / (np.abs(predictions['Price_cpkWh']) + epsilon) * 100
            mape = abs_percentage_errors.mean()
            
            # Update the dataframe
            result_df.loc[i, 'mae'] = mae
            result_df.loc[i, 'rmse'] = rmse
            result_df.loc[i, 'mape'] = mape
            
        logger.info(f"Computed error metrics for {len(result_df)} ranges")
        return result_df
        
    except Exception as e:
        logger.error(f"Error computing metrics: {e}", exc_info=True)
        return result_df
    finally:
        conn.close()


def get_run_info(db_path, run_id=None):
    """
    Get information about prediction runs.
    
    Parameters:
    - db_path: Path to the SQLite database
    - run_id: Optional specific run ID to query (None returns all runs)
    
    Returns:
    - DataFrame with run information
    """
    try:
        conn = sqlite3.connect(db_path)
        
        if run_id is not None:
            query = """
            SELECT r.run_id, r.run_datetime, COUNT(a.archive_id) as prediction_count
            FROM prediction_runs r
            LEFT JOIN archived_predictions a ON r.run_id = a.run_id
            WHERE r.run_id = ?
            GROUP BY r.run_id
            ORDER BY r.run_datetime DESC
            """
            params = (run_id,)
        else:
            query = """
            SELECT r.run_id, r.run_datetime, COUNT(a.archive_id) as prediction_count
            FROM prediction_runs r
            LEFT JOIN archived_predictions a ON r.run_id = a.run_id
            GROUP BY r.run_id
            ORDER BY r.run_datetime DESC
            """
            params = ()
            
        runs = pd.read_sql_query(query, conn, params=params)
        
        if not runs.empty:
            runs['run_datetime'] = pd.to_datetime(runs['run_datetime'])
            
        return runs
        
    except Exception as e:
        logger.error(f"Error retrieving run info: {e}", exc_info=True)
        return pd.DataFrame()
    finally:
        conn.close()


"This script is not meant to be executed directly."
