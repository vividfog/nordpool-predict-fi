#!/usr/bin/env python3

import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz

# Define locations for data fetching
LOCATIONS = [
    ("eu_ws_EE01", 58.8960, 22.5605),
    ("eu_ws_EE02", 58.6347, 25.1230),
    ("eu_ws_DK01", 56.4260, 8.1281),
    ("eu_ws_DK02", 56.6013, 11.1047),
    ("eu_ws_DE01", 54.2194, 9.6961),
    ("eu_ws_DE02", 52.6367, 9.8451),
    ("eu_ws_SE01", 65.2536, 21.6020),
    ("eu_ws_SE02", 64.5000, 17.0000),
    ("eu_ws_SE03", 59.7852, 13.0042),
]

# Fetch historical wind speed data
def fetch_historical_wind_data(locations, start_date, end_date):
    """
    Fetch historical wind speed (100m) for each location between start_date and end_date.
    Returns a single wide DataFrame with columns: ['time', 'eu_ws_EE01', 'eu_ws_EE02', ...].
    """
    base_url = "https://archive-api.open-meteo.com/v1/archive"
    data_frames = []

    # Convert end_date string to date; adjust if end_date is greater than or equal to today (UTC)
    end_date_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    today_utc = datetime.utcnow().date()
    if end_date_dt >= today_utc:
        # Archive often only goes up to (today - ~2 days)
        end_date_dt = today_utc - timedelta(days=2)
        end_date = end_date_dt.strftime("%Y-%m-%d")

    for code, lat, lon in locations:
        print(f"-- Fetching historical data for {code} ({lat}, {lon})")
        resp = requests.get(
            base_url,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date,
                "end_date": end_date,
                "hourly": "wind_speed_100m",
                "wind_speed_unit": "ms",
            },
        )
        if resp.status_code != 200:
            print(f"-- Error for {code}: {resp.status_code}")
            continue

        data_json = resp.json()
        times = data_json.get("hourly", {}).get("time", [])
        speeds = data_json.get("hourly", {}).get("wind_speed_100m", [])
        if not times or not speeds:
            print(f"-- No data or empty for {code}")
            continue

        df_loc = pd.DataFrame({
            "time": pd.to_datetime(times, utc=True),
            code: speeds
        })
        data_frames.append(df_loc)

    # Merge all location data frames on "time" into one wide DataFrame
    if not data_frames:
        return pd.DataFrame()

    combined_df = data_frames[0]
    for df_loc in data_frames[1:]:
        combined_df = pd.merge(combined_df, df_loc, on="time", how="outer")

    combined_df.sort_values("time", inplace=True)
    combined_df.reset_index(drop=True, inplace=True)

    return combined_df

# Generate SQL UPDATE statements
def generate_sql_updates(full_hours_df, wind_df):
    """
    Generates SQL UPDATE statements to set wind columns in 'prediction' for each
    existing timestamp in full_hours_df. Timestamps not in full_hours_df are ignored.
    
    Args:
        full_hours_df (pd.DataFrame): Must have a 'timestamp' column (the DB timestamps).
        wind_df (pd.DataFrame): Must have a 'time' column plus wind columns (eu_ws_EE01, etc.).
        
    Returns:
        list of str: One UPDATE statement per row, e.g.:
            UPDATE prediction
            SET eu_ws_EE01=5.5, eu_ws_EE02=6.1
            WHERE timestamp='2023-01-01T00:00:00+00:00';
    """
    # Merge on 'timestamp' (left join to keep only what's in full_hours_df, ignore extra)
    merged_df = pd.merge(
        full_hours_df,
        wind_df,
        left_on='timestamp',
        right_on='time',
        how='left'
    )
    # Now each row in merged_df has the existing 'timestamp' plus columns like eu_ws_EE01, eu_ws_EE02, ...
    # If there's no data from the API, those wind columns will be NaN.

    # Create one UPDATE statement per row that has any valid wind data
    wind_columns = [c for c in merged_df.columns if c.startswith('eu_ws_')]
    
    sql_statements = []
    for _, row in merged_df.iterrows():
        # If all wind columns are NaN for this row, skip
        if row[wind_columns].isna().all():
            continue

        # Convert timestamp to the DB's format: YYYY-MM-DDTHH:MM:SS+00:00
        ts_str = row['timestamp'].strftime('%Y-%m-%dT%H:%M:%S+00:00')

        # Build the SET clause. Skip columns that are NaN (no data).
        set_parts = []
        for wc in wind_columns:
            val = row[wc]
            if pd.notna(val):
                set_parts.append(f'{wc} = {val}')
        
        # If nothing to set, skip
        if not set_parts:
            continue

        set_clause = ", ".join(set_parts)
        sql = (
            f"UPDATE prediction "
            f"SET {set_clause} "
            f"WHERE timestamp = '{ts_str}';"
        )
        sql_statements.append(sql)
    
    return sql_statements

# Main driver function
def main():
    """
    1) Define date range for historical data
    2) Fetch data from Open-Meteo
    3) Create a DataFrame that matches existing DB timestamps
    4) Generate 'UPDATE' statements
    5) Print them inside a transaction
    """
    # Define date range for historical data
    start_date = "2023-01-01"
    end_date = datetime.utcnow().strftime("%Y-%m-%d")

    print(f"-- Fetching historical wind from {start_date} to {end_date}")

    # Fetch the wide DataFrame with one column per location code
    wind_df = fetch_historical_wind_data(LOCATIONS, start_date, end_date)
    print(f"-- Combined wind data shape: {wind_df.shape}")

    # Build the "existing timestamps" DataFrame
    # For demonstration, assume hourly timestamps from the same range
    all_hours = pd.date_range(
        start=pd.to_datetime(start_date, utc=True),
        end=pd.to_datetime(end_date, utc=True),
        freq='h'  # Changed from 'H' to 'h' to address deprecation warning
    )
    full_hours_df = pd.DataFrame({'timestamp': all_hours})

    # Generate the "UPDATE" statements
    sql_updates = generate_sql_updates(full_hours_df, wind_df)

    # Output the statements
    print("-- Begin SQL Updates")
    print("BEGIN;")  # Changed to standard SQL syntax
    for stmt in sql_updates:
        print(stmt)
    print("COMMIT;")
    print("-- End SQL Updates")

if __name__ == "__main__":
    main()
