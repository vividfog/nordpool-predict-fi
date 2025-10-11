import requests
import pandas as pd
from lxml import etree
from datetime import datetime, timedelta
import pytz
import sys
from rich import print
import time
from .logger import logger
from .dataframes import coalesce_merged_columns

def get_forecast(fmisid, start_date, parameters, end_date=None):
    """
    Fetch weather forecast data for a specified fmisid and date range.
    FMISID list: https://www.ilmatieteenlaitos.fi/havaintoasemat?filterKey=groups&filterQuery=sää

    Parameters:
    - fmisid (int): The location for which to fetch the weather forecast.
    - start_date (str): The start date for which to fetch the forecast, in "YYYY-MM-DD" format.
    - parameters (list of str): A list of strings representing the weather parameters to fetch.
    - end_date (str, optional): The end date for which to fetch the forecast, in "YYYY-MM-DD" format. Defaults to start_date.

    Returns:
    - pd.DataFrame: A pandas DataFrame with a row for each hour of the specified date range and columns for each of the requested parameters.
    """
    
    # If end_date is not provided, use start_date + 8 days as default range
    if end_date is None:
        end_date = (datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=8)).strftime('%Y-%m-%d')
    
    base_url = "https://opendata.fmi.fi/wfs"
    common_params = {
        'service': 'WFS',
        'version': '2.0.0',
        'request': 'getFeature',
        'storedquery_id': 'fmi::forecast::edited::weather::scandinavia::point::simple',
        'fmisid': fmisid,
        'starttime': f"{start_date}T00:00:00Z",
        'endtime': f"{end_date}T23:59:59Z",  # Adjusted to include the entire end day
        'parameters': ",".join(parameters),
        'timestep': '60'  # Hourly intervals
    }
    
    try:
        response = requests.get(base_url, params=common_params)
        response.raise_for_status()
        
        if not response.content:
            logger.warning(f"FMI: Empty response from FMI API for FMISID {fmisid} forecast ({start_date} to {end_date})")
            
    except requests.RequestException as e:
        logger.warning(f"FMI: Error fetching forecast data from FMI for FMISID {fmisid} ({start_date} to {end_date}): {e}")
        
    # Let's not spam the FMI API
    time.sleep(.2)
        
    if response.status_code != 200:
        raise Exception("Failed to fetch data")
    
    try:
        root = etree.fromstring(response.content)
        if len(root.findall('.//BsWfs:BsWfsElement', namespaces=root.nsmap)) == 0:
            logger.warning(f"FMI: No forecast data found for FMISID {fmisid} ({start_date} to {end_date})")
            sys.exit(1)
    except etree.XMLSyntaxError as e:
        logger.warning(f"FMI: Error parsing XML from FMI response for FMISID {fmisid}: {e}")

    data = []
    for member in root.findall('.//BsWfs:BsWfsElement', namespaces=root.nsmap):
        timestamp = member.find('.//BsWfs:Time', namespaces=root.nsmap).text
        parameter = member.find('.//BsWfs:ParameterName', namespaces=root.nsmap).text
        value = member.find('.//BsWfs:ParameterValue', namespaces=root.nsmap).text
        data.append({'timestamp': timestamp, 'Parameter': parameter, 'Value': value})

    # Convert list of dictionaries to DataFrame
    df = pd.DataFrame(data)
    
    try:
        df['Value'] = pd.to_numeric(df['Value'], errors='coerce')
        df_pivot = df.pivot(index='timestamp', columns='Parameter', values='Value').reset_index()
    except Exception as e:
        logger.warning(f"FMI: DataFrame operation failed with FMI data: {e}")

    return df_pivot

def get_history(fmisid, start_date, parameters, end_date=None):
    """
    Fetch historical weather data for a specified fmisid and date range.
    FMISID list: https://www.ilmatieteenlaitos.fi/havaintoasemat?filterKey=groups&filterQuery=sää
    
    Parameters:
    - fmisid (int): The location for which to fetch the historical weather data.
    - start_date (str): The start date for which to fetch the data, in "YYYY-MM-DD" format.
    - parameters (list of str): A list of strings representing the weather parameters to fetch.
    - end_date (str, optional): The end date for which to fetch the data, in "YYYY-MM-DD" format. Defaults to start_date if not provided.
    
    Returns:
    - pd.DataFrame: A pandas DataFrame with a row for each hour of the specified date range and columns for each of the requested parameters.
    """
    
    # If end_date is not provided, use start_date + 7 days as default range
    if end_date is None:
        end_date = (datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=8)).strftime('%Y-%m-%d')

    # Define the start and end time for the specific day or range
    starttime = f"{start_date}T00:00:00Z"
    endtime = f"{end_date}T23:59:59Z"

    # Define the base URL and parameters for the request
    base_url = "https://opendata.fmi.fi/wfs"
    params = {
        'service': 'WFS',
        'version': '2.0.0',
        'request': 'getFeature',
        'storedquery_id': 'fmi::observations::weather::hourly::simple',
        'fmisid': fmisid,
        'starttime': starttime,
        'endtime': endtime,
        'parameters': ",".join(parameters),
    }

    try:
        response = requests.get(base_url, params=params)
        if response.status_code != 200:
            logger.warning(f"FMI: Failed to fetch historical data for FMISID {fmisid} ({start_date} to {end_date}): {response.text}")
            
        if not response.content:
            logger.warning(f"FMI: Empty response from FMI API for FMISID {fmisid} history ({start_date} to {end_date})")
            
        root = etree.fromstring(response.content)
        if len(root.findall('.//BsWfs:BsWfsElement', namespaces=root.nsmap)) == 0:
            logger.warning(f"FMI: No historical data found for FMISID {fmisid} ({start_date} to {end_date})")
            
    except requests.RequestException as e:
        logger.warning(f"FMI: Error fetching historical data from FMI for FMISID {fmisid} ({start_date} to {end_date}): {e}")
        sys.exit(1)
    except etree.XMLSyntaxError as e:
        logger.warning(f"FMI: Error parsing XML from FMI response for FMISID {fmisid}: {e}")

    # Let's not spam the FMI API
    time.sleep(0.1)

    data = []
    for member in root.findall('.//BsWfs:BsWfsElement', namespaces=root.nsmap):
        timestamp = member.find('.//BsWfs:Time', namespaces=root.nsmap).text
        parameter = member.find('.//BsWfs:ParameterName', namespaces=root.nsmap).text
        value = member.find('.//BsWfs:ParameterValue', namespaces=root.nsmap).text
        data.append({'timestamp': timestamp, 'Parameter': parameter, 'Value': value})

    # Convert list of dictionaries to DataFrame
    df = pd.DataFrame(data)

    # Sometimes FMI returns no history data for a station
    if df.empty:
        # Create empty DataFrame with expected structure
        columns = ['timestamp'] + parameters
        logger.warning(f"FMI: Will proceed without {parameters} training data update for FMISID {fmisid} ({start_date} to {end_date})")
        return pd.DataFrame(columns=columns)

    df['Value'] = pd.to_numeric(df['Value'], errors='coerce')
    df_pivot = df.pivot(index='timestamp', columns='Parameter', values='Value').reset_index()
    return df_pivot

# region helpers
def _update_station_series(df, prefix, forecast_param, history_param, log_label):
    """
    Shared workflow for combining FMI forecast and historical data for a group of stations.
    """
    current_utc = datetime.now(pytz.UTC)
    current_date = current_utc.strftime("%Y-%m-%d")
    history_date = (current_utc - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (current_utc + timedelta(days=8)).strftime("%Y-%m-%d")

    logger.info(f"FMI: Fetching {log_label} forecast and historical data between {history_date} and {end_date}")

    for col in [c for c in df.columns if c.startswith(prefix)]:
        fmisid = int(col.split('_')[1])

        forecast_df = get_forecast(fmisid, current_date, [forecast_param], end_date=end_date)
        history_df = get_history(fmisid, history_date, [history_param], end_date=end_date)

        forecast_df.rename(columns={forecast_param: col}, inplace=True)
        history_df.rename(columns={history_param: col}, inplace=True)

        forecast_df[col] = forecast_df[col].interpolate(method='linear')
        history_df[col] = history_df[col].interpolate(method='linear')

        combined_df = pd.concat(
            [forecast_df.set_index('timestamp'), history_df.set_index('timestamp')]
        ).sort_index()
        combined_df = combined_df[~combined_df.index.duplicated(keep='first')]

        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        combined_df.index = pd.to_datetime(combined_df.index, utc=True).unique()

        df = pd.merge(df, combined_df[[col]], left_on='timestamp', right_index=True, how='left')
        df = coalesce_merged_columns(df)

        nan_count = df[col].isna().sum()
        if nan_count > 0:
            logger.warning(f"FMI: The final DataFrame contains {nan_count} NaN values in column '{col}'.")

    return df

def update_wind_speed(df):
    """
    Updates the input DataFrame with wind speed forecast and historical data for specified locations.

    This function fetches wind speed forecasts up to 120 hours into the future and historical wind speed data from the past 7 days for each location specified in the input DataFrame. The locations are identified by 'fmisid' codes in the column names prefixed with 'ws_'. The function then interpolates missing values in both forecast and historical data, combines them while handling overlaps, and updates the original DataFrame with the combined wind speed data.

    Parameters:
    - df (pd.DataFrame): The input DataFrame containing a 'timestamp' column and one or more wind speed columns named with the pattern 'ws_{fmisid}', where '{fmisid}' is the location code.

    Returns:
    - pd.DataFrame: The updated DataFrame with combined forecast and historical wind speed data for each specified location. The wind speed data is merged into the original DataFrame based on the 'timestamp' column, which is also made timezone-aware (UTC) if not already.

    The function ensures that the 'timestamp' column in the input DataFrame and the index of the combined forecast and historical data are aligned and timezone-aware (UTC). It also removes potential duplicates after combining the forecast and historical data. After updating the wind speed data, the function performs a clean-up to handle any issues arising from the merge operation.
    """
    return _update_station_series(df, 'ws_', 'windspeedms', 'WS_PT1H_AVG', 'wind speed')

def update_temperature(df):
    """
    Updates the input DataFrame with temperature forecast and historical data for specified locations.

    This function fetches temperature forecasts up to 120 hours into the future and historical temperature data from the past 7 days for each location specified in the input DataFrame. The locations are identified by 'fmisid' codes in the column names prefixed with 't_'. The function then interpolates missing values in both forecast and historical data, combines them while handling overlaps, and updates the original DataFrame with the combined temperature data.

    Parameters:
    - df (pd.DataFrame): The input DataFrame containing a 'timestamp' column and one or more temperature columns named with the pattern 't_{fmisid}', where '{fmisid}' is the location code.

    Returns:
    - pd.DataFrame: The updated DataFrame with combined forecast and historical temperature data for each specified location. The temperature data is merged into the original DataFrame based on the 'timestamp' column, which is also made timezone-aware (UTC) if not already.

    The function ensures that the 'timestamp' column in the input DataFrame and the index of the combined forecast and historical data are aligned and timezone-aware (UTC). It also removes potential duplicates after combining the forecast and historical data. After updating the temperature data, the function performs a clean-up to handle any issues arising from the merge operation.
    """
    return _update_station_series(df, 't_', 'temperature', 'TA_PT1H_AVG', 'temperature')

# Main function for testing the FMI API functions
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    # Load environment variables
    load_dotenv('.env.local')
    
    # Get FMISID lists from environment
    ws_stations = os.getenv('FMISID_WS').split(',')
    t_stations = os.getenv('FMISID_T').split(',')
    
    # Test dates
    current_date = datetime.today().strftime('%Y-%m-%d')
    past_date = "2024-12-20"
    
    logger.info(f"\n=== Testing Wind Speed Stations ===")
    for station in ws_stations:
        logger.info(f"\nTesting FMISID: {station}")
        # Get current forecast
        forecast = get_forecast(station, current_date, ['windspeedms'])
        logger.info(f"Current forecast sample ({current_date}):")
        logger.info(forecast.describe())
        
        # Get current history
        history = get_history(station, current_date, ['WS_PT1H_AVG'])
        logger.info(f"\nCurrent history sample ({current_date}):")
        logger.info(history.describe())
        
        # Get past history
        past_history = get_history(station, past_date, ['WS_PT1H_AVG'])
        logger.info(f"\nPast history sample ({past_date}):")
        logger.info(past_history.describe())
    
    logger.info(f"\n=== Testing Temperature Stations ===")
    for station in t_stations:
        logger.info(f"\nTesting FMISID: {station}")
        # Get current forecast
        forecast = get_forecast(station, current_date, ['temperature'])
        logger.info(f"Current forecast sample ({current_date}):")
        logger.info(forecast.describe())
        
        # Get current history
        history = get_history(station, current_date, ['TA_PT1H_AVG'])
        logger.info(f"\nCurrent history sample ({current_date}):")
        logger.info(history.describe())
        
        # Get past history
        past_history = get_history(station, past_date, ['TA_PT1H_AVG'])
        logger.info(f"\nPast history sample ({past_date}):")
        logger.info(past_history.describe())
