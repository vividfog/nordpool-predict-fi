"""
archive.py

This module manages an SQLite archive of your price prediction snapshots.

Functions:
1. insert_snapshot(db_path, df) - Archive a new prediction snapshot
2. get_predictions(db_path, df) - Retrieve archived predictions for timestamps
3. compute_error(db_path, df) - Calculate error metrics over time ranges

All functions use the existing table structure in the database 
and follow the established pattern from sql.py.
"""

import sqlite3
import pandas as pd
import sys
import numpy as np
from datetime import datetime
from .logger import logger

# Suppress FutureWarning messages from pandas for now
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)


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


def insert_snapshot(db_path, df):
    """
    Insert a new snapshot run and its forecasts into the archive.
    
    Creates a new entry in prediction_runs and inserts the DataFrame rows
    into archived_predictions. Only columns that exist in the database
    table will be used; any additional columns will be dropped.
    
    Parameters:
    - db_path: Path to the SQLite database
    - df: DataFrame with 'timestamp' column and prediction data
    
    Returns:
    - The ID of the newly created run, or None if insertion failed
    """
    if 'timestamp' not in df.columns:
        logger.error("DataFrame must contain a 'timestamp' column")
        return None
    
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
    except sqlite3.Error as e:
        logger.error(f"SQLite connection error in insert_snapshot: {e}", exc_info=True)
        sys.exit(1)

    try:
        # Create a new entry in prediction_runs with current UTC time
        now_utc = datetime.utcnow().isoformat()
        cur.execute("INSERT INTO prediction_runs (run_datetime) VALUES (?)", (now_utc,))
        run_id = cur.lastrowid
        
        # Make a copy to avoid modifying the original
        insert_df = df.copy()
        
        # Normalize timestamps
        insert_df['timestamp'] = insert_df['timestamp'].apply(normalize_timestamp)
        
        # Get the list of columns in the archived_predictions table
        table_columns = _get_table_columns(conn, "archived_predictions")
        
        # Filter insert_df to include only columns in the table (plus run_id)
        available_columns = [col for col in insert_df.columns if col in table_columns or col == 'run_id']
        available_columns = [col for col in available_columns if col != 'archive_id']  # Remove auto-increment column
        
        # Check if we have at least timestamp and PricePredict_cpkWh
        required_columns = ['timestamp', 'PricePredict_cpkWh']
        missing_columns = [col for col in required_columns if col not in available_columns]
        if missing_columns:
            logger.error(f"Required columns missing: {missing_columns}")
            conn.rollback()
            return None
        
        # Prepare for insertion
        insert_columns = ', '.join(available_columns + ['run_id'])
        placeholders = ', '.join(['?'] * (len(available_columns) + 1))
        
        # Prepare and execute bulk insert
        values = []
        for _, row in insert_df.iterrows():
            row_values = [row[col] if col in row else None for col in available_columns]
            row_values.append(run_id)
            values.append(tuple(row_values))
        
        cur.executemany(
            f"INSERT OR IGNORE INTO archived_predictions ({insert_columns}) VALUES ({placeholders})",
            values
        )
        
        # Commit and close
        conn.commit()
        
        # Log summary
        logger.info(f"→ Inserted new prediction run (ID: {run_id}) with {len(values)} predictions")
        return run_id
        
    except Exception as e:
        logger.error(f"Error inserting snapshot: {e}", exc_info=True)
        conn.rollback()
        return None
    finally:
        conn.close()


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
        query = f"""
        SELECT a.*, r.run_datetime
        FROM archived_predictions a
        JOIN prediction_runs r ON a.run_id = r.run_id
        WHERE a.timestamp IN ({placeholders})
        ORDER BY a.timestamp, a.run_id
        """
        
        result = pd.read_sql_query(query, conn, params=tuple(normalized_timestamps))
        
        # Convert timestamp strings back to datetime objects
        if not result.empty and 'timestamp' in result.columns:
            result['timestamp'] = pd.to_datetime(result['timestamp'])
            
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
        
        # Process each range
        for i, row in result_df.iterrows():
            # Normalize timestamps
            start_ts = normalize_timestamp(row['start'])
            end_ts = normalize_timestamp(row['end'])
            
            # Query for predictions within the range where actual prices exist
            query = """
            SELECT run_id, timestamp, PricePredict_cpkWh, Price_cpkWh
            FROM archived_predictions
            WHERE timestamp >= ? AND timestamp <= ? AND Price_cpkWh IS NOT NULL
            ORDER BY timestamp, run_id
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
