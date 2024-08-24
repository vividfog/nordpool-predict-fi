import os
from dotenv import load_dotenv
import pandas as pd
from datetime import datetime, timedelta, timezone
from entsoe import EntsoePandasClient
import pandas as pd
from rich import print

"""
Fetch nuclear production forecast data for Finland for next 5 days.

Forecast is based on known maximum production based on all 5 nuclear plants (OL1, OL2, OL3 and Loviisa 1 and 2), minus the planned maintenance reduction of available capacity. Forecast is based on market messages available from ENTSO-E

    Parameters:
    - API Key for ENTSO-E access
    Returns:
    - pd.DataFrame: A pandas DataFrame with a row for each hour of the specified date range and column for forecasted Nuclear production
    """

def entso_e_nuclear(entso_e_api_key, DEBUG=False):
    print("* ENTSO-E: Fetching nuclear downtime messages...")  
    client = EntsoePandasClient(api_key=entso_e_api_key)

    # Total nuclear capacity in Finland is 4372 MW (2 x 890 MW, 1 x 1600 MW and 2 x 496 MW)
    total_capacity = 4372 # TODO: Get from .env.local instead

    if DEBUG:
        print(f"→ ENTSO-E: Total nuclear capacity: {total_capacity} MW")

    start_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)  # Round to the next full hour
    end_time = start_time + timedelta(days=6)  # 5+1 to fill the data frame (TODO: these should match without this hack)

    start = pd.Timestamp(start_time).tz_convert('Europe/Helsinki')
    end = pd.Timestamp(end_time).tz_convert('Europe/Helsinki')

    if DEBUG:
        print(f"→ ENTSO-E: Fetching data from {start} to {end}")

    country_code = 'FI'  # Finland

    try:
        # "Unavailability of generation units" from Entso-E includes Olkiluoto units
        unavailable_generation = client.query_unavailability_of_generation_units(country_code, start=start, end=end, docstatus=None, periodstartupdate=None, periodendupdate=None)
    except Exception as e:
        raise ConnectionError(f"Failed to fetch unavailability of generation units: {e}")

    if DEBUG:
        print("→ ENTSO-E: Unavailability of generation units, RAW data:\n", unavailable_generation)

    unavailable_nuclear1 = unavailable_generation[unavailable_generation['plant_type'] == 'Nuclear'] 
    unavailable_nuclear1 = unavailable_nuclear1[unavailable_nuclear1['businesstype'] == 'Planned maintenance'] 
    unavailable_nuclear1 = unavailable_nuclear1[unavailable_nuclear1['resolution'] == 'PT60M'] 
    unavailable_nuclear1 = unavailable_nuclear1[['start', 'end','avail_qty','nominal_power', 'production_resource_name']]

    if DEBUG:
        print("→ ENTSO-E: Unavailability of generation units:\n", unavailable_nuclear1)

    # "Unavailability of production plants" from Entso-E includes Loviisa units
    unavailable_production = client.query_unavailability_of_production_units(country_code, start, end, docstatus=None, periodstartupdate=None, periodendupdate=None)

    # Debug print    
    if DEBUG:
        print("→ ENTSO-E: Unavailability of production units, RAW data:\n", unavailable_production)
    
    unavailable_nuclear2 = unavailable_production[unavailable_production['plant_type'] == 'Nuclear'] 
    unavailable_nuclear2 = unavailable_nuclear2[unavailable_nuclear2['businesstype'] == 'Planned maintenance']
    unavailable_nuclear2 = unavailable_nuclear2[unavailable_nuclear2['resolution'] == 'PT60M'] 
    unavailable_nuclear2 = unavailable_nuclear2[['start', 'end','avail_qty','nominal_power', 'production_resource_name']]

    if DEBUG:
        print("→ ENTSO-E: Unavailability of production units:\n", unavailable_nuclear2)

    # Combine datasets
    unavailable_nuclear = pd.concat([unavailable_nuclear1, unavailable_nuclear2], axis=0)
    unavailable_nuclear["nominal_power"] = pd.to_numeric(unavailable_nuclear["nominal_power"])
    unavailable_nuclear["avail_qty"] = pd.to_numeric(unavailable_nuclear["avail_qty"])

    # Drop "created_doc_time" column
    unavailable_nuclear = unavailable_nuclear.reset_index(drop=True)

    if DEBUG:
        print("→ ENTSO-E: Combined unavailability of nuclear power plants:\n", unavailable_nuclear)

    # Calculate unavailable capacity for each unavailability entry
    unavailable_nuclear_capacity = unavailable_nuclear.assign(unavailable_qty = (unavailable_nuclear['nominal_power'] - unavailable_nuclear['avail_qty']))
    unavailable_nuclear_capacity['start'] = pd.to_datetime(unavailable_nuclear_capacity['start'])
    unavailable_nuclear_capacity['end'] = pd.to_datetime(unavailable_nuclear_capacity['end'])

    # Initialize forecast dataset with baseline capacity when all capacity is available
    date_range = pd.date_range(start=start, end=end, freq='h')
    nuclear_forecast = pd.DataFrame(index=date_range, columns=["available_capacity"])
    nuclear_forecast['available_capacity'] = total_capacity

    # Debug print    
    if DEBUG:
        print("→ ENTSO-E: Forecast dataset initialized with baseline capacity:\n", nuclear_forecast)

    # Adjust available capacity based on unavailability entries
    for _, row in unavailable_nuclear_capacity.iterrows():
        mask = (nuclear_forecast.index >= row['start']) & (nuclear_forecast.index < row['end'])
        nuclear_forecast.loc[mask, 'available_capacity'] -= row['unavailable_qty']
        
    nuclear_forecast.reset_index(inplace=True)
    
    if DEBUG:
        print("→ ENTSO-E: Forecast dataset with adjusted capacity:\n", nuclear_forecast)

    # Let's go back to the host program naming conventions
    nuclear_forecast.rename(columns={'index': 'timestamp', 'available_capacity': 'NuclearPowerMW'}, inplace=True)
    nuclear_forecast.rename(columns={'index': 'Timestamp'}, inplace=True)

    avg_capacity = round(nuclear_forecast['NuclearPowerMW'].mean())
    max_capacity = round(nuclear_forecast['NuclearPowerMW'].max())
    min_capacity = round(nuclear_forecast['NuclearPowerMW'].min())

    print(f"→ ENTSO-E: Avg: {avg_capacity}, max: {max_capacity}, min: {min_capacity} MW")
            
    return nuclear_forecast

def main():
    
    # Test the function
    # Run from the root folder of the project: python util/nuclear_forecast.py
    
    # Load environment variables from .env.local file
    load_dotenv(dotenv_path='.env.local')

    # Retrieve the ENTSO_E_API_KEY from environment variables
    entso_e_api_key = os.getenv('ENTSO_E_API_KEY')

    if not entso_e_api_key:
        print("ENTSO_E_API_KEY not found in .env.local file.")
        return

    try:
        # Fetch nuclear power forecast data
        nuclear_forecast_data = entso_e_nuclear(entso_e_api_key, DEBUG=True)
        
        # Display the fetched data
        print(nuclear_forecast_data)
    except Exception as e:
        # Handle any errors that occur during the data fetching process
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()