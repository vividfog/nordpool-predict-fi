"""
This script fetches (or uses cached) Finnish holiday data from pyhäpäivä.fi, then updates
an existing DataFrame to mark which rows correspond to public holidays. If a 'holiday'
column already exists, its non-missing values are preserved; only NaN entries
get filled based on the fetched holiday data. It uses an hourly approach to avoid
merge gaps at non-midnight timestamps.

Usage:
- As a module, call update_holidays(df) to add/fill a 'holiday' column.
- Run this script directly to test it with a dummy DataFrame.
"""

import sys
import pytz
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from rich import print

_holiday_cache = None  # Will hold a DataFrame with UTC hour + holiday_fetched=int(kind_id)

def _fetch_holidays():
    """
    Fetch holiday data from pyhäpäivä.fi if not already cached.
    Returns a DataFrame with columns:
      - 'timestamp': each UTC hour in the holiday day
      - 'holiday_fetched': the integer value of kind_id
    """
    global _holiday_cache
    if _holiday_cache is None:
        print("* Pyhäpäivä: Fetching Finnish holiday data")
        try:
            response = requests.get("https://pyhäpäivä.fi/?output=json")
            response.raise_for_status()
            holidays_json = response.json()

            helsinki_tz = pytz.timezone('Europe/Helsinki')
            # Use a dict to store hour -> kind_id (int).
            # If multiple items land on the same hour, keep the max kind_id.
            holiday_map = {}

            for item in holidays_json:
                kind_id_int = int(item.get("kind_id", 0))  # default 0 if missing
                local_date = pd.to_datetime(item["date"])
                local_midnight = helsinki_tz.localize(local_date)

                # Build the 24-hour range for that local day
                day_hours_local = pd.date_range(
                    start=local_midnight,
                    end=local_midnight + pd.Timedelta(hours=23),
                    freq='h'
                )
                # Convert each hour to UTC
                day_hours_utc = day_hours_local.tz_convert(pytz.UTC)

                for hour_utc in day_hours_utc:
                    # If hour_utc not seen yet or this kind_id is "larger," store it
                    if (hour_utc not in holiday_map) or (kind_id_int > holiday_map[hour_utc]):
                        holiday_map[hour_utc] = kind_id_int

            # Convert dict -> DataFrame
            holiday_list = [(ts, val) for ts, val in holiday_map.items()]
            holiday_df = pd.DataFrame(holiday_list, columns=['timestamp', 'holiday_fetched'])
            holiday_df.sort_values('timestamp', inplace=True, ignore_index=True)

            _holiday_cache = holiday_df
            print(f"→ Total holiday hours: {len(_holiday_cache)}")

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Unable to fetch or process holiday data: {e}")
            sys.exit(1)
    else:
        print(f"→ Using cached Finnish holiday data. Total holiday hours in cache: {_holiday_cache.shape[0]}")

    return _holiday_cache

def update_holidays(df):
    """
    Updates the DataFrame with a 'holiday' column for each row, using the integer value
    of kind_id from pyhäpäivä.fi. Example: official holidays are 1, "Ei virallinen"
    might be 3, etc.

    Existing 'holiday' values are preserved unless they are NaN. Prints debug info.
    1. Ensures the DF has a 'timestamp' column in UTC for merges.
    2. Merges the holiday DataFrame (hourly) on 'timestamp'.
    3. Only fills NaN values in 'holiday'.
    4. Converts the final 'holiday' column to integer (fill leftover NaNs with 0).
    """

    # print(f"[DEBUG] Initial DataFrame shape: {df.shape}")
    # print(f"[DEBUG] DataFrame columns: {df.columns}")

    if 'timestamp' not in df.columns:
        print("[ERROR] Holidays: No 'timestamp' column found in input data frame. Exiting.")
        sys.exit(1)

    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
    min_dt = df['timestamp'].min()
    max_dt = df['timestamp'].max()

    # print(f"[DEBUG] Min timestamp in DataFrame: {min_dt}")
    # print(f"[DEBUG] Max timestamp in DataFrame: {max_dt}")

    if pd.isnull(min_dt) or pd.isnull(max_dt):
        print("[WARNING] DF has no valid timestamps. Marking 'holiday' as 0 for all.")
        if 'holiday' not in df.columns:
            df['holiday'] = 0
        else:
            df['holiday'] = df['holiday'].fillna(0)
        return df

    # Fetch or use cached holiday DataFrame
    holiday_df = _fetch_holidays()
    # print(f"[DEBUG] Sample holiday rows:\n{holiday_df.head(5)}")

    # Merge on timestamp
    # print("[DEBUG] Merging holiday data back into the main DataFrame on an hourly basis...")
    merged_df = pd.merge(
        df,
        holiday_df,
        on='timestamp',
        how='left',
        suffixes=('', '_fetched')
    )

    # print(f"[DEBUG] Merged DataFrame shape: {merged_df.shape}")

    # If 'holiday' doesn't exist, create it
    if 'holiday' not in merged_df.columns:
        print("[DEBUG] 'holiday' column does not exist. Creating with NaNs.")
        merged_df['holiday'] = pd.NA

    pre_fill_na_count = merged_df['holiday'].isna().sum()
    # print(f"[DEBUG] 'holiday' column NaNs before fill: {pre_fill_na_count}")

    # Fill NaN values with 'holiday_fetched'
    merged_df['holiday'] = merged_df['holiday'].fillna(merged_df['holiday_fetched'])
    post_fill_na_count = merged_df['holiday'].isna().sum()
    # print(f"[DEBUG] 'holiday' column NaNs after fill: {post_fill_na_count}")

    # Convert to integer, filling leftover NaNs with 0
    merged_df['holiday'] = merged_df['holiday'].fillna(0).astype(int)

    # Remove the helper column
    merged_df.drop(columns=['holiday_fetched'], inplace=True, errors='ignore')

    # print("[DEBUG] Holiday column updated in DataFrame.")
    # print(merged_df.head(72))
    # print("[DEBUG] Rows where holiday > 0 (first 72):")
    # print(merged_df[merged_df['holiday'] > 0].head(72))

    return merged_df

def main():
    """
    Test routine that builds a dummy DataFrame from 7 days in the past
    to 5 days in the future, partially populates a holiday column, then
    calls update_holidays. Prints debug info.
    """
    print("=== Holiday Updater Test Routine ===")

    # Set "now" to December 30, 2024, midnight Helsinki time
    helsinki_tz = pytz.timezone('Europe/Helsinki')
    now_helsinki = helsinki_tz.localize(datetime(2024, 12, 30, 0, 0, 0))

    now_utc = now_helsinki.astimezone(pytz.UTC)
    start_utc = now_utc - timedelta(days=7)
    end_utc = now_utc + timedelta(days=8)

    timestamps = pd.date_range(start=start_utc, end=end_utc, freq='h', tz='UTC')
    df_test = pd.DataFrame({'timestamp': timestamps})

    # Partially fill a holiday column with random values, leaving others NaN
    rng = np.random.default_rng(seed=42)
    random_vals = rng.integers(-1, 3, size=len(df_test))  # some -1, 0, 1, 2
    partial_col = []
    for v in random_vals:
        if v == 0:
            partial_col.append(0)
        elif v == 1:
            partial_col.append(1)
        else:
            partial_col.append(np.nan)

    df_test['holiday'] = partial_col

    pd.set_option('display.max_rows', None)

    print("Initial DF:")
    print(df_test)

    df_test['timestamp'] = df_test['timestamp'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    updated_df = update_holidays(df_test)

    print("Updated DF:")
    print(updated_df)
    print("=== End of Holiday Updater Test ===")

if __name__ == "__main__":
    main()
