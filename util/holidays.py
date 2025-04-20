# -*- coding: utf-8 -*-
"""
This script fetches (or uses cached) Finnish holiday data from pyhäpäivä.fi,
incorporating retry logic for network requests. It updates an existing DataFrame
to mark which rows correspond to public holidays. If a 'holiday' column already
exists, its non-missing values are preserved (conceptually, type may become int);
only NaN entries get filled based on the fetched holiday data. The final 'holiday'
column is ensured to be integer type. The process uses an hourly timestamp approach
to ensure accurate merging with time-series data.

Usage:
- As a module: Import and call `update_holidays(df)` to add or update the 'holiday' column.
- As a script: Execute directly to run a test routine using a sample DataFrame.

# TODO: 2025-03-27, Pyhäpäivä.fi is down. Do we need a new API for this? Ideally one with the same data, 'kind' field.

"""

import sys
import time
import pytz
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from rich import print
from .logger import logger

_holiday_cache = None  # Will hold a DataFrame with UTC hour + holiday_fetched=int(kind_id)

def _fetch_holidays():
    """
    Fetches Finnish holiday data from pyhäpäivä.fi API, using a cache if available.
    Implements a retry mechanism for network resilience.

    Returns:
        pd.DataFrame: A DataFrame with hourly UTC timestamps ('timestamp') for each holiday
                      and the corresponding holiday type ('holiday_fetched', as integer kind_id).
                      Returns an empty DataFrame if fetching fails after all retry attempts.
    """
    global _holiday_cache
    if _holiday_cache is not None:
        logger.info("Using cached Finnish holiday data. Total holiday hours in cache: %d", _holiday_cache.shape[0])
        return _holiday_cache

    # Configuration for fetching holiday data
    max_attempts = 3
    delay_seconds = 10
    request_timeout = 15 # seconds
    url = "https://pyhäpäivä.fi/?output=json"

    # Define the structure of the DataFrame in case of fetch failure or empty data
    empty_holiday_df = pd.DataFrame({
        'timestamp': pd.Series(dtype='datetime64[ns, UTC]'),
        'holiday_fetched': pd.Series(dtype='int')
    })

    for attempt in range(1, max_attempts + 1):
        logger.info("Pyhäpäivä: Attempt %d/%d to fetch Finnish holiday data from %s", attempt, max_attempts, url)
        try:
            response = requests.get(url, timeout=request_timeout)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            holidays_json = response.json()

            if not holidays_json:
                 logger.warning("Pyhäpäivä: API response was empty.")
                 _holiday_cache = empty_holiday_df # Cache empty result
                 return _holiday_cache

            # Process the received JSON data
            helsinki_tz = pytz.timezone('Europe/Helsinki')
            # Map: UTC hour timestamp -> max(kind_id) for that hour
            holiday_map = {}

            for item in holidays_json:
                kind_id_int = int(item.get("kind_id", 0)) # Default to 0 if kind_id is missing
                # Parse date assuming it's in 'YYYY-MM-DD' format
                local_date = pd.to_datetime(item["date"])
                # Localize the date to midnight in Helsinki timezone
                local_midnight = helsinki_tz.localize(local_date)

                # Generate hourly timestamps for the entire local day
                day_hours_local = pd.date_range(
                    start=local_midnight,
                    end=local_midnight + pd.Timedelta(hours=23),
                    freq='h'
                )
                # Convert these local hourly timestamps to UTC
                day_hours_utc = day_hours_local.tz_convert(pytz.UTC)

                # Store the kind_id for each UTC hour, keeping the highest if overlaps occur
                for hour_utc in day_hours_utc:
                    current_kind = holiday_map.get(hour_utc, -1) # Use -1 to ensure first ID or higher ID wins
                    if kind_id_int > current_kind:
                        holiday_map[hour_utc] = kind_id_int

            if not holiday_map:
                 logger.warning("Pyhäpäivä: Fetched data contained no processable holiday entries.")
                 _holiday_cache = empty_holiday_df
                 return _holiday_cache

            # Convert the map to a list of tuples for DataFrame creation
            holiday_list = list(holiday_map.items())
            holiday_df = pd.DataFrame(holiday_list, columns=['timestamp', 'holiday_fetched'])

            # Ensure correct data types and sort by timestamp
            holiday_df['timestamp'] = pd.to_datetime(holiday_df['timestamp'], utc=True)
            holiday_df['holiday_fetched'] = holiday_df['holiday_fetched'].astype(int)
            holiday_df.sort_values('timestamp', inplace=True, ignore_index=True)

            _holiday_cache = holiday_df # Cache the processed data
            logger.info("Successfully fetched and processed holiday data on attempt %d. Total holiday hours: %d", attempt, len(_holiday_cache))
            return _holiday_cache # Return the populated DataFrame

        except requests.exceptions.RequestException as e:
            logger.warning("Pyhäpäivä: Attempt %d/%d failed during request: %s", attempt, max_attempts, e)
            if attempt < max_attempts:
                logger.info("Waiting %d seconds before next attempt...", delay_seconds)
                time.sleep(delay_seconds)
            # Continue to the next attempt or exit loop if max attempts reached

        except (ValueError, KeyError, TypeError) as e:
             # Catch potential errors during JSON parsing or data processing
             logger.error("Pyhäpäivä: Attempt %d/%d failed during data processing: %s", attempt, max_attempts, e, exc_info=True)
             if attempt < max_attempts:
                 logger.info("Waiting %d seconds before next attempt...", delay_seconds)
                 time.sleep(delay_seconds)
             # Continue to the next attempt or exit loop

    # If loop completes without returning, all attempts failed
    logger.error("Pyhäpäivä: All %d attempts to fetch holiday data failed. Continuing without new holiday data.", max_attempts)
    _holiday_cache = empty_holiday_df # Cache the empty DataFrame to prevent retries until cache expires/clears
    return _holiday_cache


def update_holidays(df):
    """
    Updates or adds a 'holiday' column to the input DataFrame based on fetched Finnish holiday data.

    The function merges holiday information based on an hourly UTC 'timestamp' column.
    If a 'holiday' column exists, existing non-NaN values are preserved (final type will be int).
    NaN values are filled using the fetched holiday `kind_id`. If fetching fails or no holiday data
    is available for a timestamp, the holiday value defaults to 0. The final column is integer type.

    Args:
        df (pd.DataFrame): The input DataFrame. Must contain a 'timestamp' column
                           convertible to UTC datetime objects.

    Returns:
        pd.DataFrame: The DataFrame with the 'holiday' column added or updated (as integer type).
                      Returns the original DataFrame structure with holiday=0 (int) if timestamps
                      are invalid or holiday fetching fails completely.
    """
    logger.debug("Updating holiday column. Initial DataFrame shape: %s", df.shape)
    logger.debug("Initial DataFrame columns: %s", df.columns.tolist())

    if 'timestamp' not in df.columns:
        logger.error("Input DataFrame must contain a 'timestamp' column.")
        sys.exit(1) # Current behavior: exit if 'timestamp' is missing

    # Standardize timestamp column to UTC datetime objects, coercing errors to NaT
    try:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
    except Exception as e:
        logger.error("Failed to convert 'timestamp' column to datetime: %s", e, exc_info=True)
        sys.exit(1) # Exit if conversion fails fundamentally

    min_dt = df['timestamp'].min()
    max_dt = df['timestamp'].max()
    logger.debug("DataFrame time range (UTC): %s to %s", min_dt, max_dt)

    # Check if any valid timestamps exist after conversion
    if df['timestamp'].isnull().all():
        logger.warning("No valid timestamps found in 'timestamp' column after conversion. Setting 'holiday' to 0.")
        if 'holiday' not in df.columns:
            df['holiday'] = 0
        else:
            # Ensure consistency: fill existing NaNs with 0 and set type to int
            # ** FIX 1: Ensure int type even if timestamps were invalid **
            df['holiday'] = df['holiday'].fillna(0).astype(int)
        return df

    # Fetch holiday data (uses cache or retries API call)
    holiday_df = _fetch_holidays()

    # If fetching failed or returned no data, handle gracefully
    if holiday_df.empty:
        logger.warning("No holiday data available (fetch failed or API returned empty). Setting new 'holiday' values to 0.")
        if 'holiday' not in df.columns:
             logger.info("Creating 'holiday' column, initializing with 0.")
             df['holiday'] = 0 # Will be integer type
        else:
             # Fill existing NaNs in the 'holiday' column with 0
             nan_count_before = df['holiday'].isna().sum()
             if nan_count_before > 0:
                 logger.info("Filling %d existing NaN values in 'holiday' column with 0.", nan_count_before)
             # ** FIX 2: Ensure int type in API failure case **
             df['holiday'] = df['holiday'].fillna(0).astype(int)
        return df # Return df as no merge is possible

    # --- Merge holiday data if available ---
    logger.debug("Merging fetched holiday data with DataFrame on 'timestamp'.")
    # Perform a left merge to keep all original rows and add holiday info where timestamps match
    merged_df = pd.merge(
        df,
        holiday_df,  # Contains 'timestamp' and 'holiday_fetched'
        on='timestamp',
        how='left',
        suffixes=('', '_fetched') # Avoid renaming original 'holiday' if it exists
    )
    logger.debug("DataFrame shape after merge: %s", merged_df.shape)

    # Determine how to handle the 'holiday' column based on its existence pre-merge
    if 'holiday' not in df.columns:
        # If 'holiday' column didn't exist, create it directly from 'holiday_fetched'
        logger.info("Creating 'holiday' column from fetched data.")
        # Use fillna(0) and ensure integer type
        merged_df['holiday'] = merged_df['holiday_fetched'].fillna(0).astype(int)
    else:
        # If 'holiday' column existed, preserve its non-NaN values and fill NaNs
        nan_count_before = merged_df['holiday'].isna().sum()
        logger.debug("Existing 'holiday' column found. NaN count before fill: %d", nan_count_before)

        # Fill NaN values in the original 'holiday' column using the merged 'holiday_fetched'
        merged_df['holiday'] = merged_df['holiday'].fillna(merged_df['holiday_fetched'])

        # Any remaining NaNs occur if 'holiday' was NaN and no match was found in holiday_df
        # Fill these remaining NaNs with 0 and ensure final integer type
        merged_df['holiday'] = merged_df['holiday'].fillna(0).astype(int)
        nan_count_after = merged_df['holiday'].isna().sum() # Should be 0 after fillna(0)
        logger.debug("NaN count in 'holiday' column after fill: %d", nan_count_after)


    # Clean up the temporary merge column
    merged_df.drop(columns=['holiday_fetched'], inplace=True, errors='ignore')

    logger.debug("Holiday column update complete. Final DataFrame shape: %s", merged_df.shape)
    return merged_df


def main():
    """
    Provides a test execution environment for the `update_holidays` function.
    Creates a sample DataFrame spanning a period around New Year's, partially
    populates a 'holiday' column (as float due to NaN), calls the update function,
    and logs results, verifying preservation of numeric value.
    """
    logger.info("=== Holiday Updater Test Routine Start ===")

    # Define a time range for the test data, centered around potential holidays
    helsinki_tz = pytz.timezone('Europe/Helsinki')
    # Using a fixed date for repeatable tests, e.g., around New Year 2024/2025
    test_center_date = datetime(2024, 12, 30, 0, 0, 0)
    now_helsinki = helsinki_tz.localize(test_center_date)
    now_utc = now_helsinki.astimezone(pytz.UTC)

    start_utc = now_utc - timedelta(days=7)
    end_utc = now_utc + timedelta(days=10) # Include days after New Year

    # Create hourly timestamps in UTC
    timestamps = pd.date_range(start=start_utc, end=end_utc, freq='h', tz='UTC')
    df_test = pd.DataFrame({'timestamp': timestamps})
    df_test['value'] = range(len(df_test)) # Include some dummy data

    # Create a 'holiday' column with some pre-existing values and many NaNs
    rng = np.random.default_rng(seed=42)
    # Populate with a mix of values (-1, 1, 2 representing hypothetical existing data) and NaN
    # Note: np.nan forces this column to be float type initially
    holiday_values = rng.choice([-1, 1, 2, np.nan], size=len(df_test), p=[0.02, 0.03, 0.03, 0.92])
    df_test['holiday'] = holiday_values

    # Store original non-NaN values for later verification
    original_non_nan_holiday = df_test['holiday'].dropna()

    # Optionally limit pandas display rows for console output
    pd.set_option('display.max_rows', 20)

    logger.info("Sample of initial test DataFrame:")
    print(df_test.head()) # Using rich print for potentially better formatting
    logger.info("Initial 'holiday' value distribution (including NaN):")
    print(df_test['holiday'].value_counts(dropna=False))

    # --- Execute the main function ---
    # Pass a copy to avoid modifying df_test if it's reused elsewhere in a larger script
    # To test the failure scenario, temporarily modify the URL in _fetch_holidays to an invalid one.
    updated_df = update_holidays(df_test.copy())
    # ---------------------------------

    logger.info("Sample of updated DataFrame:")
    print(updated_df.head())
    logger.info("Updated 'holiday' value distribution:")
    print(updated_df['holiday'].value_counts(dropna=False))

    # Verification Step: Check if original non-NaN values were preserved numerically
    updated_values_at_original_indices = updated_df.loc[original_non_nan_holiday.index, 'holiday']
    # ** FIX 3: Adjust verification to compare numeric value, allowing for intended float->int conversion **
    if original_non_nan_holiday.astype(int).equals(updated_values_at_original_indices):
        logger.info("Verification successful: Original non-NaN 'holiday' numeric values were preserved.")
    else:
        logger.warning("Verification failed: Some original non-NaN 'holiday' numeric values may have been altered.")
        # Details
        # print("Original (as int):")
        # print(original_non_nan_holiday.astype(int))
        # print("Updated:")
        # print(updated_values_at_original_indices)
        # diff = original_non_nan_holiday.astype(int) != updated_values_at_original_indices
        # print("Indices with differences:", diff[diff].index.tolist())

    # Display some rows likely identified as holidays (kind_id > 0)
    logger.info("Sample of rows where 'holiday' > 0 after update:")
    print(updated_df[updated_df['holiday'] > 0].head(15))

    logger.info("=== Holiday Updater Test Routine End ===")


if __name__ == "__main__":
    main()
