import requests
import pandas as pd
from datetime import datetime, timedelta
from entsoe import EntsoePandasClient
import pandas as pd

"""
Fetch nuclear production forecast data for Finland for next 5 days.

Forecast is based on known maximum production based on all 5 nuclear plants (OL1, OL2, OL3 and Loviisa 1 and 2)
minus the planned maintenance reduction of available capacity.
Forecast is based on market messages available from Entso-E

    Parameters:
    - API Key for Entso-E access
    Returns:
    - pd.DataFrame: A pandas DataFrame with a row for each hour of the specified date range and column for forecasted Nuclear production
    """

def fetch_nuclear_power_forecast_data(ensto-e_api_key):
  
client = EntsoePandasClient(api_key=ensto-e_api_key)

# Total nuclear capacity in Finland is 4372 MW (2 x 890 MW, 1 x 1600 MW and 2 x 496 MW)
total_capacity = 4372

start_time = datetime.utcnow().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)  # Round to the next full hour
end_time = start_time + timedelta(days=5)

start = pd.Timestamp(pd.to_datetime(start_time), tz='Europe/Helsinki')
end = pd.Timestamp(pd.to_datetime(end_time), tz='Europe/Helsinki')

country_code = 'FI'  # Finland

# "Unavaibility of generation units" from Entso-E includes Olkiluoto units
unavailable_generation = client.query_unavailability_of_generation_units(country_code, start=start, end=end, docstatus=None, periodstartupdate=None, periodendupdate=None)
unavailable_nuclear1 = unavailable_generation[unavailable_generation['plant_type'] == 'Nuclear'] 
unavailable_nuclear1 = unavailable_nuclear1[unavailable_nuclear1['businesstype'] == 'Planned maintenance'] 
unavailable_nuclear1 = unavailable_nuclear1[unavailable_nuclear1['resolution'] == 'PT60M'] 
unavailable_nuclear1 = unavailable_nuclear1[['start', 'end','avail_qty','nominal_power', 'production_resource_name']]

# "Unavailability of production plants" from Entso-E includes Loviisa units
unavailable_production = client.query_unavailability_of_production_units(country_code, start, end, docstatus=None, periodstartupdate=None, periodendupdate=None)
unavailable_nuclear2 = unavailable_production[unavailable_production['plant_type'] == 'Nuclear'] 
unavailable_nuclear2 = unavailable_nuclear2[unavailable_nuclear2['businesstype'] == 'Planned maintenance']
unavailable_nuclear2 = unavailable_nuclear2[unavailable_nuclear2['resolution'] == 'PT60M'] 
unavailable_nuclear2 = unavailable_nuclear2[['start', 'end','avail_qty','nominal_power', 'production_resource_name']]

# Combine datasets
unavailable_nuclear = pd.concat([unavailable_nuclear1, unavailable_nuclear2], axis=0)
unavailable_nuclear["nominal_power"] = pd.to_numeric(unavailable_nuclear["nominal_power"])
unavailable_nuclear["avail_qty"] = pd.to_numeric(unavailable_nuclear["avail_qty"])

# Drop "created_doc_time" column
unavailable_nuclear = unavailable_nuclear.reset_index(drop=True)

# Calculate unavailable capacity for each unavailability entry
unavailable_nuclear_capacity = unavailable_nuclear.assign(unavailable_qty = (unavailable_nuclear['nominal_power'] - unavailable_nuclear['avail_qty']))
unavailable_nuclear_capacity['start'] = pd.to_datetime(unavailable_nuclear_capacity['start'])
unavailable_nuclear_capacity['end'] = pd.to_datetime(unavailable_nuclear_capacity['end'])

# Initialize forecast dataset with baseline capacity when all capacity is available
date_range = pd.date_range(start=start, end=end, freq='h')
nuclear_forecast = pd.DataFrame(index=date_range, columns=["available_capacity"])
nuclear_forecast['available_capacity'] = total_capacity

# Adjust available capacity based on unavailability entries
for _, row in unavailable_nuclear_capacity.iterrows():
    mask = (nuclear_forecast.index >= row['start']) & (nuclear_forecast.index < row['end'])
    nuclear_forecast.loc[mask, 'available_capacity'] -= row['unavailable_qty']
    
nuclear_forecast.reset_index(inplace=True)
nuclear_forecast.rename(columns={'index': 'timestamp'}, inplace=True)
        
return nuclear_forecast


