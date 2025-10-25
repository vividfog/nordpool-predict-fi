import os
import json
import pandas as pd
from zipfile import BadZipFile
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from entsoe import EntsoePandasClient
from entsoe.entsoe import EntsoeRawClient
from entsoe.exceptions import NoMatchingDataError
from entsoe.parsers import parse_unavailabilities
from .logger import logger

# Total nuclear capacity in Finland is 4372 MW (2 x 890 MW, 1 x 1600 MW and 2 x 496 MW)
TOTAL_CAPACITY = 4372

# Define a threshold for a "long outage" which can be considered an anomaly (such as 6 months of zero production) 
LONG_OUTAGE_THRESHOLD = 6 * 30 * 24  # hours

def entso_e_nuclear(entso_e_api_key, DEBUG=False):
    try:
        logger.info("ENTSO-E: Fetching nuclear downtime messages...")
        client = EntsoePandasClient(api_key=entso_e_api_key)

        logger.debug(f"→ ENTSO-E: Total nuclear capacity: {TOTAL_CAPACITY} MW")

        # Define the time window for data retrieval
        start_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        end_time = start_time + timedelta(days=8)

        # Convert to Helsinki timezone for accurate regional data
        start = pd.Timestamp(start_time).tz_convert('Europe/Helsinki')
        end = pd.Timestamp(end_time).tz_convert('Europe/Helsinki')

        logger.debug(f"→ ENTSO-E: Fetching data from {start} to {end}")

        country_code = 'FI'

        def _empty_unavailability_frame():
            tz = 'Europe/Helsinki'
            return pd.DataFrame({
                'start': pd.Series(pd.DatetimeIndex([], tz=tz)),
                'end': pd.Series(pd.DatetimeIndex([], tz=tz)),
                'avail_qty': pd.Series(dtype='float64'),
                'nominal_power': pd.Series(dtype='float64'),
                'production_resource_name': pd.Series(dtype='object'),
                'plant_type': pd.Series(dtype='object'),
                'businesstype': pd.Series(dtype='object'),
                'docstatus': pd.Series(dtype='object'),
                'resolution': pd.Series(dtype='object'),
            })

        raw_client = EntsoeRawClient(api_key=entso_e_api_key)
        helsinki_tz = 'Europe/Helsinki'

        def _parse_unavailability_bytes(content: bytes, doctype: str):
            try:
                df = parse_unavailabilities(content, doctype)
            except BadZipFile:
                return _empty_unavailability_frame()

            df = df.tz_convert(helsinki_tz)
            df['start'] = df['start'].apply(lambda x: x.tz_convert(helsinki_tz))
            df['end'] = df['end'].apply(lambda x: x.tz_convert(helsinki_tz))
            df = df[(df['start'] < end) | (df['end'] > start)]
            return df

        def _fallback_generation():
            content = raw_client.query_unavailability_of_generation_units(country_code, start, end)
            return _parse_unavailability_bytes(content, "A80")

        def _fallback_production():
            content = raw_client.query_unavailability_of_production_units(country_code, start, end)
            return _parse_unavailability_bytes(content, "A77")

        def _safe_query(description, query_callable, fallback_callable):
            try:
                return query_callable()
            except BadZipFile:
                logger.info(f"ENTSO-E: {description} response looked like acknowledgement – retrying with raw client")
                return fallback_callable()
            except NoMatchingDataError:
                logger.info(f"ENTSO-E: {description} returned acknowledgement/no data – offset exhausted")
                return _empty_unavailability_frame()

        try:
            unavailable_generation = _safe_query(
                "Generation unavailability",
                lambda: client.query_unavailability_of_generation_units(country_code, start=start, end=end),
                _fallback_generation
            )
        except Exception as e:
            raise ConnectionError(f"Failed to fetch unavailability of generation units: {e}")

        logger.debug(f"→ ENTSO-E: Unavailability of generation units, RAW data:\n{unavailable_generation}")

        # print("RAW unavailable_generation:")
        # print(unavailable_generation.to_string())

        # Filter for relevant outage types
        outage_types = ['Planned maintenance', 'Unplanned outage']

        # Filter data for nuclear plant outages
        olkiluoto_outages = unavailable_generation[unavailable_generation['plant_type'] == 'Nuclear']
        olkiluoto_outages = olkiluoto_outages[olkiluoto_outages['businesstype'].isin(outage_types)]
        olkiluoto_outages = olkiluoto_outages[olkiluoto_outages['docstatus'] != 'Cancelled']
        olkiluoto_outages = olkiluoto_outages[olkiluoto_outages['resolution'] == 'PT60M']
        olkiluoto_outages = olkiluoto_outages[['start', 'end', 'avail_qty', 'nominal_power', 'production_resource_name']]

        logger.debug(f"→ ENTSO-E: Unavailability of generation units:\n{olkiluoto_outages}")

        unavailable_production = _empty_unavailability_frame()  # Initialize to an empty DataFrame
        try:
            # Query unavailability of production units
            unavailable_production_candidate = _safe_query(
                "Production unavailability",
                lambda: client.query_unavailability_of_production_units(country_code, start, end),
                _fallback_production
            )
            if not unavailable_production_candidate.empty:
                unavailable_production = unavailable_production_candidate
        except Exception as e:
            logger.info(f"[WARNING] ENTSO-E update: {e} - Loviisa production data not available, continuing with Olkiluoto only")

        if not unavailable_production.empty:  # Process only if production data is available
            if DEBUG:
                logger.info(f"ENTSO-E: Unavailability of production units, RAW data:\n{unavailable_production}")
            
            # print("RAW unavailable_production:")
            # print(unavailable_production.to_string())
            # Filter data for nuclear plant outages
            loviisa_outages = unavailable_production[unavailable_production['plant_type'] == 'Nuclear']
            loviisa_outages = loviisa_outages[loviisa_outages['businesstype'].isin(outage_types)]
            loviisa_outages = loviisa_outages[loviisa_outages['docstatus'] != 'Cancelled']
            loviisa_outages = loviisa_outages[loviisa_outages['resolution'] == 'PT60M']
            loviisa_outages = loviisa_outages[['start', 'end', 'avail_qty', 'nominal_power', 'production_resource_name']]

        else:
            loviisa_outages = pd.DataFrame()

        if DEBUG and not loviisa_outages.empty:
            logger.info(f"ENTSO-E: Unavailability of production units:\n{loviisa_outages}")

        # Combine outages from both plants
        combined_outages = pd.concat([olkiluoto_outages, loviisa_outages], axis=0)
        combined_outages["nominal_power"] = pd.to_numeric(combined_outages["nominal_power"])
        combined_outages["avail_qty"] = pd.to_numeric(combined_outages["avail_qty"])

        combined_outages = combined_outages.reset_index(drop=True)

        logger.debug(f"→ ENTSO-E: Combined unavailability of nuclear power plants (incl. history):\n{combined_outages}")

        current_time = datetime.now(timezone.utc)
        future_outages = combined_outages[combined_outages['end'] > current_time].copy()

        # Calculate outage length in hours
        future_outages.loc[:, 'outage_length_hours'] = (future_outages['end'] - future_outages['start']).dt.total_seconds() / 3600

        for _, row in future_outages.iterrows():
            # Check for anomalies in outage duration
            if row['outage_length_hours'] > LONG_OUTAGE_THRESHOLD:
                if row['avail_qty'] == 0:
                    logger.warning(f"Outage for {row['production_resource_name']} is longer than 6 months with zero production. Human in the loop required. Returning None.")
                    return None
                else:
                    logger.info(f"[WARNING] Anomaly detected: Outage for {row['production_resource_name']} is longer than 6 months ({row['outage_length_hours']} hours). Expected?")

        # Calculate availability as a percentage of nominal power
        future_outages['availability'] = (future_outages['avail_qty'] / future_outages['nominal_power'])
        future_outages.drop(columns=['outage_length_hours'], inplace=True)

        logger.info(f"ENTSO-E: Nuclear unavailability (future/ongoing only):\n{future_outages}")

        # Convert future outages data to JSON format
        future_outages_json = future_outages.to_json(orient='records', date_format='iso')

        combined_data = {
            "nuclear_outages": json.loads(future_outages_json),
        }

        # Save the JSON data to a file
        with open('deploy/nuclear_outages.json', 'w') as f:
            json.dump(combined_data, f, indent=4)

        logger.info("ENTSO-E: Future nuclear outages saved to deploy/nuclear_outages.json")
            
        # Calculate unavailable capacity
        unavailable_capacity = combined_outages.assign(unavailable_qty=(combined_outages['nominal_power'] - combined_outages['avail_qty']))
        unavailable_capacity['start'] = pd.to_datetime(unavailable_capacity['start'])
        unavailable_capacity['end'] = pd.to_datetime(unavailable_capacity['end'])

        # Initialize a forecast DataFrame with the total capacity
        date_range = pd.date_range(start=start, end=end, freq='h')
        nuclear_forecast = pd.DataFrame(index=date_range, columns=["available_capacity"])
        nuclear_forecast['available_capacity'] = TOTAL_CAPACITY

        logger.debug("→ ENTSO-E: Forecast dataset initialized with baseline capacity:\n", nuclear_forecast)

        # Adjust the forecast based on unavailable capacity
        for _, row in unavailable_capacity.iterrows():
            mask = (nuclear_forecast.index >= row['start']) & (nuclear_forecast.index < row['end'])
            nuclear_forecast.loc[mask, 'available_capacity'] -= row['unavailable_qty']
            
        nuclear_forecast.reset_index(inplace=True)
        
        logger.debug(f"→ ENTSO-E: Forecast dataset with adjusted capacity:\n{nuclear_forecast}")

        # Rename columns for clarity
        nuclear_forecast.rename(columns={'index': 'timestamp', 'available_capacity': 'NuclearPowerMW'}, inplace=True)

        # Calculate average, max, and min capacity
        avg_capacity = round(nuclear_forecast['NuclearPowerMW'].mean())
        max_capacity = round(nuclear_forecast['NuclearPowerMW'].max())
        min_capacity = round(nuclear_forecast['NuclearPowerMW'].min())

        logger.info(f"ENTSO-E: Avg: {avg_capacity}, max: {max_capacity}, min: {min_capacity} MW")
                
        return nuclear_forecast

    except Exception as e:
        logger.warning(f"ENTSO-E update: {e} - returning None")
        return None

def main():
    # Load environment variables from a local .env file
    load_dotenv(dotenv_path='.env.local')

    # Retrieve the ENTSO-E API key from environment variables
    entso_e_api_key = os.getenv('ENTSO_E_API_KEY')

    if not entso_e_api_key:
        logger.info("ENTSO_E_API_KEY not found in .env.local file.")
        return

    # Fetch and print nuclear forecast data
    nuclear_forecast_data = entso_e_nuclear(entso_e_api_key, DEBUG=True)
    if isinstance(nuclear_forecast_data, pd.DataFrame):
        logger.info(nuclear_forecast_data.to_string())
    else:
        logger.info(nuclear_forecast_data)

if __name__ == "__main__":
    main()
