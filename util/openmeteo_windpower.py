
"""
This script retrieves and combines wind speed data from the Open-Meteo API for specified European locations, including historical data at 100m and forecast data at 120m.

https://open-meteo.com/en/docs

TODO: Clean up unnecessary debug code once verified stable.

"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
from rich import print

# --- Location data ---
# Each tuple is (code, latitude, longitude).
# 'code' will be used as the column name in the final DataFrame for that location.
LOCATIONS = [
    ("eu_ws_EE01", 58.8960, 22.5605),  # Hiiumaa, Estonia
    ("eu_ws_EE02", 58.6347, 25.1230),  # Sopi-Tootsi Wind Farm, Estonia
    ("eu_ws_DK01", 56.4260, 8.1281),   # Western Jutland (Vesterhav), Denmark
    ("eu_ws_DK02", 56.6013, 11.1047),  # Anholt Offshore Wind Farm, Denmark
    ("eu_ws_DE01", 54.2194, 9.6961),   # Schleswig-Holstein, Germany
    ("eu_ws_DE02", 52.6367, 9.8451),   # Lower Saxony (Niedersachsen), Germany
    ("eu_ws_SE01", 65.2536, 21.6020),  # Markbygden, Norrbotten, Sweden
    ("eu_ws_SE02", 64.5000, 17.0000),  # Blakliden/Fäbodberget, Västerbotten, Sweden
    ("eu_ws_SE03", 59.7852, 13.0042)    # Häjsberget och södra Länsmansberget Wind Farm
]

def fetch_historical_wind_data(locations, start_date, end_date):
    """
    Fetch historical wind speed data (100m) for the given locations within the specified date range.
    
    Args:
        locations (list of tuples): (code, lat, lon) for each location.
        start_date (str): Start date in format 'YYYY-MM-DD'.
        end_date (str): End date in format 'YYYY-MM-DD'.
    
    Returns:
        pd.DataFrame: Wide DataFrame (time index + one column per location code) 
                      of historical wind speeds.
    """
    historical_url = "https://archive-api.open-meteo.com/v1/archive"
    data_frames = []
    
    # Open-Meteo archive data is not available for recent past, but forecast is
    # Adjust end_date to be day before yesterday if it is today or in the future
    end_date_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    if end_date_dt >= datetime.now().date():
        end_date_dt = datetime.now().date() - timedelta(days=3)
        end_date = end_date_dt.strftime("%Y-%m-%d")
    
    # Fetch data for each location separately, then merge into one wide DataFrame
    for code, lat, lon in locations:
        # print(f"→ Fetching historical data for {code} ({lat, lon})")
        response = requests.get(
            historical_url,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date,
                "end_date": end_date,
                "hourly": "wind_speed_100m",  # Historical data uses 100m
                "wind_speed_unit": "ms",
            },
        )
        
        if response.status_code == 200:
            data = response.json()
            # print(f"  • Data shape: {len(data)}")
            # print(data)
            timestamps = data.get('hourly', {}).get('time', [])
            # print(f"  ✓ Got {len(timestamps)} timestamps for {code}")
            # if timestamps:
            #     print(f"    First timestamp: {timestamps[0]}")
            #     print(f"    Last timestamp: {timestamps[-1]}")
            # Check for NaN or empty values
            if not timestamps or all(pd.isna(timestamps)):
                print(f"  [WARNING] No valid timestamps for {code}")
            if "hourly" not in data or "time" not in data["hourly"]:
                print(f"[ERROR] Malformed historical wind data for {code}: missing 'hourly/time'.")
                raise ValueError(f"[ERROR] Malformed historical wind data for {code}: missing 'hourly/time'.")
            
            hourly_data = data["hourly"]
            df = pd.DataFrame({
                "time": pd.to_datetime(hourly_data["time"]).tz_localize("UTC"),  # Ensure timestamps are in UTC
                code: hourly_data["wind_speed_100m"],  # Rename to 120m for consistency
            }).rename(columns={code: code})  # Use the new code directly
            empty_values_count = df[code].isna().sum()
            # print(f"  • {empty_values_count} empty values for {code}")
            data_frames.append(df)
            
        else:
            print(f"  ✗ Failed with status {response.status_code}")
            print(f"[ERROR] Failed to fetch historical data for {code} ({lat, lon}): {response.status_code}")
            print(response.text)
            raise ValueError(
                f"[ERROR] Failed to fetch historical data for {code} ({lat, lon}): "
                f"{response.status_code}, {response.text}"
            )
    
    # If we got multiple data frames, merge them on 'time' to get a wide table
    if data_frames:
        combined_df = data_frames[0]
        for i in range(1, len(data_frames)):
            combined_df = pd.merge(
                combined_df, data_frames[i],
                on="time", how="outer"
            )
        
        # Sort by time
        combined_df = combined_df.sort_values(by="time").reset_index(drop=True)
        
        return combined_df
    else:
        raise ValueError(
            "[ERROR] No historical wind data available from Open-Meteo "
            f"for {start_date} to {end_date}."
        )

def fetch_forecast_wind_data(locations):
    """
    Fetch forecast (and some recent past) wind speed data (120m) for the given locations.
    
    Args:
        locations (list of tuples): (code, lat, lon) for each location.
    
    Returns:
        pd.DataFrame: Wide DataFrame (time index + one column per location code)
                      of forecast wind speeds.
    """
    forecast_url = "https://api.open-meteo.com/v1/forecast"
    data_frames = []
    
    for code, lat, lon in locations:
        # print(f"→ Fetching forecast data for {code} ({lat, lon})")
        response = requests.get(
            forecast_url,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "wind_speed_120m",  # Forecast data uses 120m
                "wind_speed_unit": "ms",
                "past_days": 4, # Overlap with historical data to ensure continuity
                "forecast_days": 10 # Fetch extra days to cover DST borders etc.
            },
        )
        
        if response.status_code == 200:
            data = response.json()
            timestamps = data.get('hourly', {}).get('time', [])
            # print(f"  ✓ Got {len(timestamps)} timestamps for {code}")
            # if timestamps:
            #     print(f"    First timestamp: {timestamps[0]}")
            #     print(f"    Last timestamp: {timestamps[-1]}")
            # Check for NaN or empty values
            if not timestamps or all(pd.isna(timestamps)):
                print(f"  [WARNING] No valid timestamps for {code}")
            if "hourly" not in data or "time" not in data["hourly"]:
                print(f"[ERROR] Malformed forecast wind data for {code}: missing 'hourly/time'.")
                raise ValueError(f"[ERROR] Malformed forecast wind data for {code}: missing 'hourly/time'.")
            
            hourly_data = data["hourly"]
            df = pd.DataFrame({
                "time": pd.to_datetime(hourly_data["time"]).tz_localize("UTC"),  # Ensure timestamps are in UTC
                code: hourly_data["wind_speed_120m"],  # Rename to 120m for consistency
            }).rename(columns={code: code})  # Use the new code directly
            empty_values_count = df[code].isna().sum()
            # print(f"  • {empty_values_count} empty values for {code}")
            data_frames.append(df)
        else:
            print(f"  ✗ Failed with status {response.status_code}")
            raise ValueError(
                f"[ERROR] Failed to fetch forecast data for {code} ({lat, lon}): "
                f"{response.status_code}, {response.text}"
            )
    
    # Merge all forecast data frames on 'time'
    if data_frames:
        combined_df = data_frames[0]
        for i in range(1, len(data_frames)):
            combined_df = pd.merge(
                combined_df, data_frames[i],
                on="time", how="outer"
            )
        
        # Sort by time
        combined_df = combined_df.sort_values(by="time").reset_index(drop=True)
        
        # Print out the last forecasted timestamp for debugging
        print(f"→ Last wind forecast timestamp: {combined_df['time'].max()}")
        
        return combined_df
    else:
        raise ValueError("[ERROR] No forecast wind data available.")

def combine_wind_data(historical_df, forecast_df):
    # print("\n→ Combining historical and forecast data")
    # if historical_df is not None:
    #     print(f"  • Historical data shape: {historical_df.shape}")
    # if forecast_df is not None:
    #     print(f"  • Forecast data shape: {forecast_df.shape}")
    
    if historical_df is None and forecast_df is None:
        raise ValueError("[ERROR] Both historical and forecast data are unavailable.")
    
    # Exclude empty or all-NA entries before concatenation
    historical_df = historical_df.dropna(how='all')
    forecast_df = forecast_df.dropna(how='all')
    
    # Concatenate historical and forecast data
    combined_df = pd.concat([historical_df, forecast_df], ignore_index=True)
    
    # Sort by time and drop duplicates
    combined_df = combined_df.sort_values(by="time").reset_index(drop=True)
    combined_df = combined_df.drop_duplicates(subset="time")
    
    # Resample to hourly frequency and interpolate missing values
    combined_df = combined_df.set_index("time").resample("h").interpolate("linear").reset_index()
    
    # Sanity check for missing values
    total_missing = combined_df.isnull().sum().sum()
    if total_missing > 24:
        raise ValueError(f"[ERROR] Combined EU wind power data has {total_missing} missing values, which exceeds the threshold of 24.")
    elif total_missing > 0:
        print(f"→ Imputing {total_missing} missing values in the combined data.")
        combined_df = combined_df.interpolate(method='linear').ffill().bfill()
    
    return combined_df

def update_eu_ws(df):
    """
    Updates the input DataFrame with wind speed data for a specified date range.
    
    This function fetches historical and forecasted wind speed data, combines them,
    and merges onto the original DataFrame. One column per location code will be added.
    
    Parameters:
    - df (pd.DataFrame): The input DataFrame containing a 'timestamp' column (in UTC).
    
    Returns:
    - pd.DataFrame: The updated DataFrame with columns for each location's wind speed at 100/120m.
    """
    # print("\n* Open-Meteo: Processing request...")
    # print(f"  • Input DataFrame shape: {df.shape}")
    # print(f"  • Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    # Drop existing wind speed columns if they exist
    existing_codes = [loc[0] for loc in LOCATIONS]  # ["eu_ws_EE01", "eu_ws_EE02", ...]
    dropped_cols = [code for code in existing_codes if code in df.columns]
    if dropped_cols:
        # print(f"  • Dropping existing wind columns: {', '.join(dropped_cols)}")
        df = df.drop(columns=dropped_cols, errors='ignore')
    
    # Determine the overall date range from the incoming DataFrame
    start_date = df['timestamp'].min().strftime("%Y-%m-%d")
    end_date = df['timestamp'].max().strftime("%Y-%m-%d")
    
    print(f"* Open-Meteo: Fetching EU wind speed data between {start_date} and {end_date}")
    
    # Fetch historical and forecasted wind data
    historical_data = fetch_historical_wind_data(LOCATIONS, start_date, end_date)
    forecast_data = fetch_forecast_wind_data(LOCATIONS)
    
    # Combine them into a single wide DataFrame
    combined_data = combine_wind_data(historical_data, forecast_data)
    
    # Merge with the original DataFrame
    # print("\n→ Starting data merge")
    # print(f"  • Wind data shape before merge: {combined_data.shape}")
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)  # Ensure timestamps are in UTC
    merged_df = pd.merge(df, combined_data, left_on='timestamp', right_on='time', how='left')
    # print(f"  • Final merged shape: {merged_df.shape}")
    merged_df.drop(columns=['time'], inplace=True)
    
    # Check for missing values after merging
    for code in existing_codes:
        if code in merged_df.columns:
            missing_count = merged_df[code].isnull().sum()
            if missing_count > 0:
                raise ValueError(f"[ERROR] {missing_count} values for {code} not available from Open-Meteo. Data is incomplete.")
    
    # Print a quick overview of the final wind speeds
    # print("→ Final wind data columns:", [c for c in merged_df.columns if c in existing_codes])
    
    # Print descriptive statistics for the merged wind columns
    # print("→ Combined wind speed stats:")
    # print(merged_df[existing_codes].describe())
    
    return merged_df

def main():
    """
    Main function for testing the wind speed code: 
    - Generate two date ranges: 
      1. From 2023-01-01 UTC to today + 8 days UTC
      2. From -7 days to +8 days using UTC
    - Fetch and combine wind speed data
    - Print the merged DataFrame and some basic info
    """
    import numpy as np
    import pandas as pd
    from datetime import datetime, timedelta

    # First date range: from 2023-01-01 UTC to today + 8 days UTC
    start_date_1 = datetime(2023, 1, 1, tzinfo=pytz.UTC)
    end_date_1 = (datetime.now(pytz.UTC) + timedelta(days=8)).replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Create a test DataFrame with hourly timestamps for the first date range
    date_range_1 = pd.date_range(start=start_date_1, end=end_date_1, freq='h')
    df_test_1 = pd.DataFrame({
        'timestamp': date_range_1,
        'random_data': np.random.rand(len(date_range_1)),
    })
    
    # Call the wind update function for the first date range
    updated_df_1 = update_eu_ws(df_test_1)
    
    # Print final results for the first date range
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_rows", 60)  # just as an example
    print("Data frame with wind speeds from 2023-01-01 to today + 8 days UTC:")
    print(updated_df_1)
    
    # Second date range: from -7 days to +8 days using UTC
    start_date_2 = (datetime.now(pytz.UTC) - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date_2 = (datetime.now(pytz.UTC) + timedelta(days=8)).replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Create a test DataFrame with hourly timestamps for the second date range
    date_range_2 = pd.date_range(start=start_date_2, end=end_date_2, freq='h')
    df_test_2 = pd.DataFrame({
        'timestamp': date_range_2,
        'random_data': np.random.rand(len(date_range_2)),
    })
    
    # Call the wind update function for the second date range
    updated_df_2 = update_eu_ws(df_test_2)
    
    # Print final results for the second date range
    print("Data frame with wind speeds from -7 to +8 days UTC:")
    print(updated_df_2)
    
    # Optionally, show statistics for each location for both date ranges
    location_codes = [loc[0] for loc in LOCATIONS]  # e.g. ['eu_ws_EE01','eu_ws_EE02','eu_ws_DK01','...']
    for code in location_codes:
        if code in updated_df_1.columns:
            print(f"— {code} wind speed stats for first date range —")
            print(updated_df_1[code].describe())
        if code in updated_df_2.columns:
            print(f"— {code} wind speed stats for second date range —")
            print(updated_df_2[code].describe())

if __name__ == "__main__":
    main()
