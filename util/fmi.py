import requests
import pandas as pd
from lxml import etree

def get_forecast(place, start_date, parameters):
    """
    Fetch weather forecast data for a specified place and date.

    Parameters:
    - place (str): The location for which to fetch the weather forecast.
    - start_date (str): The date for which to fetch the forecast, in "YYYY-MM-DD" format.
    - parameters (list of str): A list of strings representing the weather parameters to fetch.

    Returns:
    - pd.DataFrame: A pandas DataFrame with a row for each hour of the specified date and columns for each of the requested parameters.
    """
    
    base_url = "https://opendata.fmi.fi/wfs"
    common_params = {
        'service': 'WFS',
        'version': '2.0.0',
        'request': 'getFeature',
        'storedquery_id': 'fmi::forecast::edited::weather::scandinavia::point::simple',
        'place': place,
        'starttime': f"{start_date}T00:00:00Z",
        'endtime': f"{start_date}T23:00:00Z",
        'parameters': ",".join(parameters),
        'timestep': '60'  # Hourly intervals
    }
    response = requests.get(base_url, params=common_params)
    if response.status_code != 200:
        raise Exception("Failed to fetch data")
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

def get_history(place, date, parameters):
    """
    Fetch historical weather data for a specified place and date.

    Parameters:
    - place (str): The location for which to fetch the historical weather data.
    - date (str): The date for which to fetch the data, in "YYYY-MM-DD" format.
    - parameters (list of str): A list of strings representing the weather parameters to fetch.

    Returns:
    - pd.DataFrame: A pandas DataFrame with a row for each hour of the specified date and columns for each of the requested parameters.
    """
    
    # Define the start and end time for the specific day
    starttime = f"{date}T00:00:00Z"
    endtime = f"{date}T23:59:59Z"
    
    # Define the base URL and parameters for the request
    base_url = "https://opendata.fmi.fi/wfs"
    params = {
        'service': 'WFS',
        'version': '2.0.0',
        'request': 'getFeature',
        'storedquery_id': 'fmi::observations::weather::hourly::simple',
        'place': place,
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

# Example usage
date = "2024-02-28"
place = "Helsinki"

# Get forecast for a specific day
parameters_forecast = ['temperature', 'windspeedms']
forecast = get_forecast(place, date, parameters_forecast)
print("Forecast:")
print(forecast)

# Get history for a specific day
parameters_history = ['TA_PT1H_AVG', 'WS_PT1H_AVG']
history = get_history(place, date, parameters_history)
print("\nHistory:")
print(history)
