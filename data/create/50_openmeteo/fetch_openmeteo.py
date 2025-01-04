import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

# FMI's solar irradiation monitoring stations, well-distributed across Finland
LATITUDES = [60.2, 60.81, 62.4, 62.89, 59.78, 67.37, 64.11]
LONGITUDES = [24.96, 23.5, 25.67, 27.63, 21.37, 26.63, 28.34]

def fetch_historical_irradiation_data(latitudes, longitudes, start_date, end_date):
    """
    Fetch historical irradiation data for given latitudes and longitudes within the specified date range.

    Args:
        latitudes (list): List of latitudes.
        longitudes (list): List of longitudes.
        start_date (str): Start date in the format 'YYYY-MM-DD'.
        end_date (str): End date in the format 'YYYY-MM-DD'.

    Returns:
        pd.DataFrame: DataFrame containing the historical irradiation data.
    """
    historical_url = "https://archive-api.open-meteo.com/v1/archive"
    data_frames = []

    for lat, lon in zip(latitudes, longitudes):
        response = requests.get(
            historical_url,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date,
                "end_date": end_date,
                "hourly": "global_tilted_irradiance",
                "timezone": "UTC",
            },
        )
        
        if response.status_code == 200:
            data = response.json()
            if "hourly" in data and "time" in data["hourly"] and "global_tilted_irradiance" in data["hourly"]:
                hourly_data = data["hourly"]
                df = pd.DataFrame({
                    "time": pd.to_datetime(hourly_data["time"]).tz_localize(pytz.UTC),
                    "global_tilted_irradiance": hourly_data["global_tilted_irradiance"],
                })
                data_frames.append(df)
        # No print statements to ensure clean SQL output

    if data_frames:
        combined_df = pd.concat(data_frames, ignore_index=True)
        combined_df = combined_df.groupby("time").agg({
            "global_tilted_irradiance": ["sum", "mean", "std", "min", "max"]
        }).reset_index()
        combined_df.columns = ["time", "sum_irradiance", "mean_irradiance", "std_irradiance", "min_irradiance", "max_irradiance"]
        return combined_df
    else:
        return None

def generate_sql_updates(irradiation_df):
    """
    Generate SQL UPDATE statements for the irradiation data.

    Args:
        irradiation_df (pd.DataFrame): DataFrame containing the aggregated irradiation data.

    Returns:
        list: List of SQL UPDATE statements as strings.
    """
    sql_statements = []
    for _, row in irradiation_df.iterrows():
        timestamp = row['time'].strftime('%Y-%m-%dT%H:%M:%S+00:00')
        sum_irradiance = row['sum_irradiance']
        mean_irradiance = row['mean_irradiance']
        std_irradiance = row['std_irradiance']
        min_irradiance = row['min_irradiance']
        max_irradiance = row['max_irradiance']
        
        # Handle NaN values by setting them to NULL
        sum_val = 'NULL' if pd.isna(sum_irradiance) else f"{sum_irradiance:.6f}"
        mean_val = 'NULL' if pd.isna(mean_irradiance) else f"{mean_irradiance:.6f}"
        std_val = 'NULL' if pd.isna(std_irradiance) else f"{std_irradiance:.6f}"
        min_val = 'NULL' if pd.isna(min_irradiance) else f"{min_irradiance:.6f}"
        max_val = 'NULL' if pd.isna(max_irradiance) else f"{max_irradiance:.6f}"
        
        sql = (
            f"UPDATE prediction SET "
            f"sum_irradiance = {sum_val}, "
            f"mean_irradiance = {mean_val}, "
            f"std_irradiance = {std_val}, "
            f"min_irradiance = {min_val}, "
            f"max_irradiance = {max_val} "
            f"WHERE timestamp = '{timestamp}';"
        )
        sql_statements.append(sql)
    return sql_statements

def main():
    """
    Main function to fetch historical irradiation data and generate SQL UPDATE statements.
    """
    # Define the UTC timezone
    UTC = pytz.UTC
    
    # Define the exact start datetime in UTC
    start_datetime_utc = UTC.localize(datetime(2023, 1, 1, 0, 0, 0))
    
    # Define the end datetime as two days before the current UTC time
    end_datetime_utc = datetime.now(UTC) - timedelta(days=2)
    
    # Format dates as 'YYYY-MM-DD'
    start_date_utc_str = start_datetime_utc.strftime("%Y-%m-%d")
    end_date_utc_str = end_datetime_utc.strftime("%Y-%m-%d")
    
    # Fetch historical irradiation data
    historical_data = fetch_historical_irradiation_data(LATITUDES, LONGITUDES, start_date_utc_str, end_date_utc_str)
    
    if historical_data is None:
        # Exit silently if no data fetched
        return
    
    # Define the exact start datetime in UTC for filtering
    exact_start_datetime_utc = start_datetime_utc
    
    # Filter out any data before the exact start datetime
    historical_data = historical_data[historical_data['time'] >= exact_start_datetime_utc]
    
    if historical_data.empty:
        # Exit silently if no data after filtering
        return
    
    # Generate SQL UPDATE statements
    sql_updates = generate_sql_updates(historical_data)
    
    # Output SQL statements
    print("-- Begin SQL Updates")
    print("BEGIN TRANSACTION;")
    for sql in sql_updates:
        print(sql)
    print("COMMIT;")
    print("-- End SQL Updates")

    # Optionally, save to a file (uncomment if needed)
    # with open('update_irradiation.sql', 'w') as file:
    #     file.write("-- Begin SQL Updates\n")
    #     file.write("BEGIN TRANSACTION;\n")
    #     for sql in sql_updates:
    #         file.write(sql + "\n")
    #     file.write("COMMIT;\n")
    #     file.write("-- End SQL Updates\n")
    # print("SQL statements saved to update_irradiation.sql")

if __name__ == "__main__":
    main()
