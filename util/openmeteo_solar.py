import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
from rich import print

# FMI's solar irradiation monitoring stations, supposedly well-distributed across Finland
# Helsinki Kumpula, Jokioinen Ilmala, Jyväskylä lentoasema, Kuopio Savilahti, Parainen Utö, Sodankylä Tähtelä, Sotkamo Kuolaniemi

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

    # Adjust end_date to be day before yesterday if it is today or in the future
    end_date_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    if end_date_dt >= datetime.now().date():
        end_date_dt = datetime.now().date() - timedelta(days=2)
        end_date = end_date_dt.strftime("%Y-%m-%d")

    for lat, lon in zip(latitudes, longitudes):
        response = requests.get(
            historical_url,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date,
                "end_date": end_date,
                "hourly": "global_tilted_irradiance",
            },
        )
        
        if response.status_code == 200:
            data = response.json()
            hourly_data = data["hourly"]
            df = pd.DataFrame({
                "time": pd.to_datetime(hourly_data["time"]).tz_localize(pytz.UTC),
                "global_tilted_irradiance": hourly_data["global_tilted_irradiance"],
            })
            
            # Open-Meteo had a bug where it returned negative values for irradiance; this is a workaround
            neg_values = df[df['global_tilted_irradiance'] < 0]
            if not neg_values.empty:
                print(f"[WARNING] Found and replaced negative irradiance values for {lat}, {lon}:")
                for _, row in neg_values.iterrows():
                    print(f"  Time: {row['time']}, Value: {row['global_tilted_irradiance']} → 0")
                df['global_tilted_irradiance'] = df['global_tilted_irradiance'].clip(lower=0)

            data_frames.append(df)
            
            # DEBUG:
            # print(f"Fetched historical data for {lat}, {lon}, from {start_date} to {end_date}: {len(df)} hourly values:")
            # print(df)
            # print(df.describe())
            
        else:
            print(f"[ERROR] Failed to fetch historical data for {lat}, {lon}: {response.status_code}")
            print(response.text)
            exit(1)

    if data_frames:
        combined_df = pd.concat(data_frames, ignore_index=True)
        combined_df = combined_df.groupby("time").agg({
            "global_tilted_irradiance": ["sum", "mean", "std", "min", "max"]
        }).reset_index()
        combined_df.columns = ["time", "sum_irradiance", "mean_irradiance", "std_irradiance", "min_irradiance", "max_irradiance"]
        # print(f"Fetched historical data for {len(data_frames)} locations:")
        # print(combined_df)
        return combined_df
    else:
        raise ValueError(f"[ERROR] No historical irradiation data available for {start_date} to {end_date}: {response.status_code}, {response.text}")

def fetch_forecast_irradiation_data(latitudes, longitudes):
    """
    Fetch forecasted irradiation data for given latitudes and longitudes.

    Args:
        latitudes (list): List of latitudes.
        longitudes (list): List of longitudes.

    Returns:
        pd.DataFrame: DataFrame containing the forecasted irradiation data.
    """
    forecast_url = "https://api.open-meteo.com/v1/forecast"
    data_frames = []

    for lat, lon in zip(latitudes, longitudes):
        response = requests.get(
            forecast_url,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "global_tilted_irradiance",
                "past_days": 2,
                "forecast_days": 10
            },
        )
        
        if response.status_code == 200:
            data = response.json()
            hourly_data = data["hourly"]
            df = pd.DataFrame({
                "time": pd.to_datetime(hourly_data["time"]).tz_localize(pytz.UTC),
                "global_tilted_irradiance": hourly_data["global_tilted_irradiance"],
            })

            # Open-Meteo had a bug where it returned negative values for irradiance; this is a workaround
            neg_values = df[df['global_tilted_irradiance'] < 0]
            if not neg_values.empty:
                print(f"[WARNING] Found and replaced negative irradiance values for {lat}, {lon}:")
                for _, row in neg_values.iterrows():
                    print(f"  Time: {row['time']}, Value: {row['global_tilted_irradiance']} → 0")
                df['global_tilted_irradiance'] = df['global_tilted_irradiance'].clip(lower=0)

            data_frames.append(df)

            # DEBUG:
            # print(f"Fetched forecast data for {lat}, {lon}, from {df['time'].min()} to {df['time'].max()}: {len(df)} hourly values:")
            # print(df)
            # print(df.describe())
            
        else:
            raise ValueError(f"[ERROR] Failed to fetch forecast data for {lat}, {lon}: {response.status_code}, {response.text}")

    if data_frames:
        combined_df = pd.concat(data_frames, ignore_index=True)
        combined_df = combined_df.groupby("time").agg({
            "global_tilted_irradiance": ["sum", "mean", "std", "min", "max"]
        }).reset_index()
        combined_df.columns = ["time", "sum_irradiance", "mean_irradiance", "std_irradiance", "min_irradiance", "max_irradiance"]
        
        # Print out the last forecasted timestamp for debugging
        print(f"→ Last irradiation forecast timestamp: {combined_df['time'].max()}")
        
        return combined_df

    else:
        raise ValueError("[ERROR] No forecast irradiation data available.")

def combine_irradiation_data(historical_df, forecast_df):
    """
    Combine historical and forecasted irradiation data into a continuous timeline.

    Args:
        historical_df (pd.DataFrame): DataFrame containing the historical irradiation data.
        forecast_df (pd.DataFrame): DataFrame containing the forecasted irradiation data.

    Returns:
        pd.DataFrame: DataFrame containing the combined irradiation data.
    """
    if historical_df is None and forecast_df is None:
        raise ValueError("Both historical and forecast data are unavailable.")
    elif historical_df is None:
        print("→ Historical data is unavailable, using forecast data only.")
        combined_df = forecast_df
    elif forecast_df is None:
        print("→ Forecast data is unavailable, using historical data only.")
        combined_df = historical_df
    else:
        combined_df = pd.concat([historical_df, forecast_df], ignore_index=True)
        
    # Debugging information
    # print("Combined data before processing:")
    # print(combined_df.head())
    
    combined_df = combined_df.sort_values(by="time").reset_index(drop=True)
    
    # Remove duplicate labels
    combined_df = combined_df.drop_duplicates(subset="time")
    
    # Check for missing values
    missing_values = combined_df["sum_irradiance"].isna().sum()
    
    # Print out the time stamps with missing values
    if missing_values > 0:
        print(f"[WARNING] Missing sum_irradiance values in the following timestamps:")
        print(combined_df[combined_df["sum_irradiance"].isna()]["time"])
    
    if missing_values > 24:
        raise ValueError("[ERROR] More than 24 hourly values are missing from irradiation data, stopping execution.")

    # Fill missing historical values with forecast data
    combined_df["sum_irradiance"] = combined_df["sum_irradiance"].bfill().ffill()

    # Interpolate missing hourly values
    combined_df = combined_df.set_index("time").resample("h").interpolate(method="linear")
    
    combined_df = combined_df.reset_index()
    return combined_df

def update_solar(df):
    """
    Updates the input DataFrame with irradiation data for a specified range.

    This function fetches historical and forecasted irradiation data, combines them, and updates the original DataFrame with the combined irradiation data.

    Parameters:
    - df (pd.DataFrame): The input DataFrame containing a 'timestamp' column.

    Returns:
    - pd.DataFrame: The updated DataFrame with irradiation data.

    Note:
    - Historical data is preferred for past dates (e.g., 3 days ago).
    - Forecast data is used for future dates and recent past dates where historical data is not available.
    """
    # Drop existing irradiance columns if they exist
    irradiance_columns = ['sum_irradiance', 'mean_irradiance', 'std_irradiance', 'min_irradiance', 'max_irradiance']
    df = df.drop(columns=[col for col in irradiance_columns if col in df.columns], errors='ignore')
    
    # Infer history and end dates from the incoming DataFrame
    start_date = df['timestamp'].min().strftime("%Y-%m-%d")
    end_date = df['timestamp'].max().strftime("%Y-%m-%d")

    # Revisit the end date: make it 8 days in the future from now, end of day
    # end_date = (datetime.now(pytz.timezone('Europe/Helsinki')).replace(hour=23, minute=59, second=59) + timedelta(days=8)).strftime("%Y-%m-%d")
    
    print(f"* Open-Meteo: Fetching solar irradiation data between {start_date} and {end_date} and inferring missing values")
    # print(f"→ Initial DataFrame:\n{df.head()}")
    
    # Fetch historical and forecasted irradiation data
    historical_data = fetch_historical_irradiation_data(LATITUDES, LONGITUDES, start_date, end_date)
    forecast_data = fetch_forecast_irradiation_data(LATITUDES, LONGITUDES)
    
    # Debugging information
    # print("→ Historical data tail:")
    # print(historical_data.tail() if historical_data is not None else "None")
    # print("→ Forecast data tail:")
    # print(forecast_data.tail() if forecast_data is not None else "None")
    
    # Combine the data
    combined_data = combine_irradiation_data(historical_data, forecast_data)
    # print("→ Combined data head and tail after processing:")
    # print(combined_data.head())
    # print(combined_data.tail())
    
    # Merge the irradiation data with the input DataFrame
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    merged_df = pd.merge(df, combined_data, left_on='timestamp', right_on='time', how='left')
    merged_df.drop(columns=['time'], inplace=True)

    # Print the updated DataFrame
    # print("→ Merged DataFrame description:")
    # print(merged_df.describe())

    # Ensure 'sum_irradiance' column is filled at the end with the last known value; warn if filling had to be done
    if 'sum_irradiance' in merged_df.columns:
        nr_missing_irradiance = merged_df['sum_irradiance'].isnull().sum()
        if nr_missing_irradiance > 0:
            print(f"→ {nr_missing_irradiance} values not available from Open-Meteo. Will fill with last known value.")
        merged_df['sum_irradiance'] = merged_df['sum_irradiance'].ffill()
    else:
        raise ValueError("[ERROR] 'sum_irradiance' column not found after merge. Check data integration logic.")

    # Print the statistics of the irradiation data for sanity check
    if all(col in merged_df.columns for col in ['sum_irradiance', 'mean_irradiance', 'std_irradiance', 'min_irradiance', 'max_irradiance']):
        # print("→ Irradiation stats:")
        # print(merged_df[['sum_irradiance', 'mean_irradiance', 'std_irradiance', 'min_irradiance', 'max_irradiance']].describe())
        pass
    else:
        raise ValueError("[ERROR] Irradiation statistics not found after merge. Check data integration logic.")
    
    # Calculate and print the statistics for 'sum_irradiance'
    avg_irradiance = merged_df['sum_irradiance'].mean()
    max_irradiance = merged_df['sum_irradiance'].max()
    min_irradiance = merged_df['sum_irradiance'].min()
    print(f"→ Irradiance stats: Avg: {avg_irradiance:.0f} W/m², Max: {max_irradiance:.0f} W/m², Min: {min_irradiance:.0f} W/m²")

    return merged_df

def main():
    """
    Main function for testing: Fetch and combine irradiation data, and display the combined data.
    """
    helsinki_tz = pytz.timezone('Europe/Helsinki')

    # Test with data frame from 2023-01-01 onwards
    # start_date_1 = datetime(2023, 1, 1, tzinfo=helsinki_tz)
    # end_date_1 = datetime.now(helsinki_tz)
    # df1 = pd.DataFrame({
    #     'timestamp': pd.date_range(start=start_date_1, end=end_date_1, freq='h').round('h', ambiguous='NaT'),
    #     'random_data1': np.random.rand(len(pd.date_range(start=start_date_1, end=end_date_1, freq='h'))),
    #     'random_data2': np.random.rand(len(pd.date_range(start=start_date_1, end=end_date_1, freq='h')))
    # })
    # updated_df1 = update_solar(df1)
    # print("Data frame from 2023-01-01 onwards:")
    # print(updated_df1)
    # print("Irradiation stats (2023-01-01 onwards):")
    # print(updated_df1['sum_irradiance'].describe().apply(lambda x: f"{x:.0f}"))

    # Test with data frame from -7 to +8 days
    start_date_2 = (datetime.now(helsinki_tz) - timedelta(days=7))
    end_date_2 = (datetime.now(helsinki_tz) + timedelta(days=8))
    df2 = pd.DataFrame({
        'timestamp': pd.date_range(start=start_date_2, end=end_date_2, freq='h').round('h', ambiguous='NaT'),
        'random_data1': np.random.rand(len(pd.date_range(start=start_date_2, end=end_date_2, freq='h'))),
    })
    updated_df2 = update_solar(df2)
    
    # # Set Pandas to print all columns and rows
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_rows", None)
    
    print("Data frame from -7 to +8 days:")
    print(updated_df2)
    print("Irradiation stats (-7 to +8 days):")
    print(updated_df2['sum_irradiance'].describe().apply(lambda x: f"{x:.0f}"))

if __name__ == "__main__":
    main()