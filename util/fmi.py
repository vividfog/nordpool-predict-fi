import requests
import pandas as pd
from lxml import etree
from datetime import datetime, timedelta
import pytz
import sys

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
    
    # If end_date is not provided, use start_date as end_date
    if end_date is None:
        end_date = start_date
    
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
    except requests.RequestException as e:
        print(f"Error fetching data from FMI: {e}")
        sys.exit(1)
    if response.status_code != 200:
        raise Exception("Failed to fetch data")
    
    try:
        root = etree.fromstring(response.content)
    except etree.XMLSyntaxError as e:
        print(f"Error parsing XML from FMI response: {e}")
        sys.exit(1)

    data = []
    for member in root.findall('.//BsWfs:BsWfsElement', namespaces=root.nsmap):
        timestamp = member.find('.//BsWfs:Time', namespaces=root.nsmap).text
        parameter = member.find('.//BsWfs:ParameterName', namespaces=root.nsmap).text
        value = member.find('.//BsWfs:ParameterValue', namespaces=root.nsmap).text
        data.append({'Timestamp': timestamp, 'Parameter': parameter, 'Value': value})

    # Convert list of dictionaries to DataFrame
    df = pd.DataFrame(data)
    
    try:
        df['Value'] = pd.to_numeric(df['Value'], errors='coerce')
        df_pivot = df.pivot(index='Timestamp', columns='Parameter', values='Value').reset_index()
    except Exception as e:
        print(f"DataFrame operation failed with FMI data: {e}")
        sys.exit(1)

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
    
    # If end_date is not provided, use start_date as end_date
    if end_date is None:
        end_date = start_date

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

    # Make the request
    response = requests.get(base_url, params=params)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch data: {response.text}")

    # Parse the XML response
    root = etree.fromstring(response.content)
    data = []
    for member in root.findall('.//BsWfs:BsWfsElement', namespaces=root.nsmap):
        timestamp = member.find('.//BsWfs:Time', namespaces=root.nsmap).text
        parameter = member.find('.//BsWfs:ParameterName', namespaces=root.nsmap).text
        value = member.find('.//BsWfs:ParameterValue', namespaces=root.nsmap).text
        data.append({'Timestamp': timestamp, 'Parameter': parameter, 'Value': value})

    # Convert list of dictionaries to DataFrame
    df = pd.DataFrame(data)
    df['Value'] = pd.to_numeric(df['Value'], errors='coerce')
    df_pivot = df.pivot(index='Timestamp', columns='Parameter', values='Value').reset_index()
    return df_pivot

def clean_up_df_after_merge(df):
    """
    This function removes duplicate columns resulting from a merge operation,
    and fills the NaN values in the original columns with the values from the
    duplicated columns. Assumes duplicated columns have suffixes '_x' and '_y',
    with '_y' being the most recent values to retain.
    """
    # Identify duplicated columns by their suffixes
    cols_to_remove = []
    for col in df.columns:
        if col.endswith('_x'):
            original_col = col[:-2]  # Remove the suffix to get the original column name
            duplicate_col = original_col + '_y'
            
            # Check if the duplicate column exists
            if duplicate_col in df.columns:
                # Fill NaN values in the original column with values from the duplicate
                df[original_col] = df[col].fillna(df[duplicate_col])
                
                # Mark the duplicate column for removal
                cols_to_remove.append(duplicate_col)
                
            # Also mark the original '_x' column for removal as it's now redundant
            cols_to_remove.append(col)
    
    # Drop the marked columns
    df.drop(columns=cols_to_remove, inplace=True)
    
    return df

# TODO: Combine this with the other update function, they are almost identical
def update_wind_speed(df):
    """
    Updates the input DataFrame with wind speed forecast and historical data for specified locations.

    This function fetches wind speed forecasts up to 120 hours into the future and historical wind speed data from the past 7 days for each location specified in the input DataFrame. The locations are identified by 'fmisid' codes in the column names prefixed with 'ws_'. The function then interpolates missing values in both forecast and historical data, combines them while handling overlaps, and updates the original DataFrame with the combined wind speed data.

    Parameters:
    - df (pd.DataFrame): The input DataFrame containing a 'Timestamp' column and one or more wind speed columns named with the pattern 'ws_{fmisid}', where '{fmisid}' is the location code.

    Returns:
    - pd.DataFrame: The updated DataFrame with combined forecast and historical wind speed data for each specified location. The wind speed data is merged into the original DataFrame based on the 'Timestamp' column, which is also made timezone-aware (UTC) if not already.

    The function ensures that the 'Timestamp' column in the input DataFrame and the index of the combined forecast and historical data are aligned and timezone-aware (UTC). It also removes potential duplicates after combining the forecast and historical data. After updating the wind speed data, the function performs a clean-up to handle any issues arising from the merge operation.
    """
    # Define the current date for fetching forecasts
    current_date = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
    
    # 7 days earlier:
    history_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    
    # 120 hours later:
    end_date = (datetime.now(pytz.UTC) + timedelta(hours=120)).strftime("%Y-%m-%d")
    
    print("* Fetching wind speed forecast and historical data between", history_date, "and", end_date)
    
    for col in [c for c in df.columns if c.startswith('ws_')]:
        fmisid = int(col.split('_')[1])
        # Fetch forecast data
        forecast_df = get_forecast(fmisid, current_date, ['windspeedms'], end_date=end_date)
        # Fetch historical data for the past 7 days
        history_df = get_history(fmisid, history_date, ['WS_PT1H_AVG'], end_date=end_date)       
        
        # Rename columns to match the input DataFrame's namespace
        forecast_df.rename(columns={'windspeedms': col}, inplace=True)
        history_df.rename(columns={'WS_PT1H_AVG': col}, inplace=True)
        
        # Interpolate missing values in the forecast and history
        forecast_df[col] = forecast_df[col].interpolate(method='linear')
        history_df[col] = history_df[col].interpolate(method='linear')

        # Combine forecast and history with overlap handling
        combined_df = pd.concat([forecast_df.set_index('Timestamp'), history_df.set_index('Timestamp')]).sort_index()
        # Remove potential duplicates after combining
        combined_df = combined_df[~combined_df.index.duplicated(keep='first')]

        # Ensure the 'Timestamp' column in df and the index of combined_df are timezone-aware and aligned
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], utc=True)
        combined_df.index = pd.to_datetime(combined_df.index, utc=True).unique()

        # Update the original DataFrame with the combined data
        df = pd.merge(df, combined_df[[col]], left_on='Timestamp', right_index=True, how='left')
        
        # Merged data frame contains the old NaN column and the new column with the same name → remove the old one
        df = clean_up_df_after_merge(df)
        
    return df

# TODO: Combine this with the other update function, they are almost identical
def update_temperature(df):
    """
    Updates the input DataFrame with temperature forecast and historical data for specified locations.

    This function fetches temperature forecasts up to 120 hours into the future and historical temperature data from the past 7 days for each location specified in the input DataFrame. The locations are identified by 'fmisid' codes in the column names prefixed with 't_'. The function then interpolates missing values in both forecast and historical data, combines them while handling overlaps, and updates the original DataFrame with the combined temperature data.

    Parameters:
    - df (pd.DataFrame): The input DataFrame containing a 'Timestamp' column and one or more temperature columns named with the pattern 't_{fmisid}', where '{fmisid}' is the location code.

    Returns:
    - pd.DataFrame: The updated DataFrame with combined forecast and historical temperature data for each specified location. The temperature data is merged into the original DataFrame based on the 'Timestamp' column, which is also made timezone-aware (UTC) if not already.

    The function ensures that the 'Timestamp' column in the input DataFrame and the index of the combined forecast and historical data are aligned and timezone-aware (UTC). It also removes potential duplicates after combining the forecast and historical data. After updating the temperature data, the function performs a clean-up to handle any issues arising from the merge operation.
    """
    # Define the current date and end date for fetching forecasts and historical data
    current_date = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
    history_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (datetime.now(pytz.UTC) + timedelta(hours=120)).strftime("%Y-%m-%d")  # 120 hours later for forecasts

    print("* Fetching temperature forecast and historical data between", history_date, "and", end_date)

    for col in [c for c in df.columns if c.startswith('t_')]:
        fmisid = int(col.split('_')[1])
        
        # Fetch forecast data with updated end_date parameter
        forecast_df = get_forecast(fmisid, current_date, ['temperature'], end_date=end_date)
        # Fetch historical data with updated end_date parameter
        history_df = get_history(fmisid, history_date, ['TA_PT1H_AVG'], end_date=end_date)
        
        # Rename columns to match the input DataFrame's namespace
        forecast_df.rename(columns={'temperature': col}, inplace=True)
        history_df.rename(columns={'TA_PT1H_AVG': col}, inplace=True)
        
        # Interpolate missing values in the forecast and history
        forecast_df[col] = forecast_df[col].interpolate(method='linear')
        history_df[col] = history_df[col].interpolate(method='linear')

        # Combine forecast and history with overlap handling
        combined_df = pd.concat([forecast_df.set_index('Timestamp'), history_df.set_index('Timestamp')]).sort_index()
        # Remove potential duplicates after combining
        combined_df = combined_df[~combined_df.index.duplicated(keep='first')]

        # Ensure the 'Timestamp' column in df and the index of combined_df are timezone-aware and aligned
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], utc=True)
        combined_df.index = pd.to_datetime(combined_df.index, utc=True).unique()

        # Update the original DataFrame with the combined data
        df = pd.merge(df, combined_df[[col]], left_on='Timestamp', right_index=True, how='left')
        
        # Optionally, you can include the clean-up function here if necessary
        df = clean_up_df_after_merge(df)

    return df

# Main function for testing the FMI API functions
if __name__ == "__main__":

    # Comparing hourly forecast, same-day-history and ability to fetch data from way past

    # Get forecast for a specific day and place
    date = datetime.today().strftime('%Y-%m-%d')
    fmisid = 101846 # Kemi Ajos
    parameters_forecast = ['temperature', 'windspeedms']
    forecast = get_forecast(fmisid, date, parameters_forecast)
    print("Forecast:")
    print(forecast)

    # Get history for the same day, do they correlate?
    parameters_history = ['TA_PT1H_AVG', 'WS_PT1H_AVG']
    history = get_history(fmisid, date, parameters_history)
    print("\nHistory:")
    print(history)

    # Get history from way past
    date = "2023-01-01"
    history = get_history(fmisid, date, parameters_history)
    print("\nFrom way past:")
    print(history)