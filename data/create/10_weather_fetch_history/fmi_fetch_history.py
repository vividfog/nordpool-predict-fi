"""
** This script needs to run at the project root folder for the util.fmi import to work. Sorry. **

Fetch historical weather data for a specified date range and set of Finnish Meteorological Institute (FMI) station IDs (FMISIDs), and save the data incrementally to CSV files. Each FMISID will have its own CSV file containing the weather data for the given date range. The data fetched includes hourly average temperature ('TA_PT1H_AVG') and hourly average wind speed ('WS_PT1H_AVG').

Usage:
    The script is executed from the command line, requiring three positional arguments:
    1. start_date: The start date of the desired date range in 'YYYY-MM-DD' format.
    2. end_date: The end date of the desired date range in 'YYYY-MM-DD' format.
    3. fmisids: A comma-separated list of FMISIDs for which the historical weather data is to be fetched.

    Example command:
    python fmi_fetch_history.py 2023-01-01 2024-02-29 "101673,101256,101846,101805,101267,101786,101118,100968,101065,101339"
    
    FMISDID list:
    https://www.ilmatieteenlaitos.fi/havaintoasemat?filterKey=groups&filterQuery=sää

After you have the data, you can append them to the training database.
"""

import argparse
from datetime import datetime, timedelta
import pandas as pd
from util.fmi import get_history
import time

def parse_args():
    parser = argparse.ArgumentParser(description='Fetch historical weather data for multiple FMISIDs from FMI and save to CSV incrementally.')
    parser.add_argument('start_date', type=str, help='Start date of the range (YYYY-MM-DD)')
    parser.add_argument('end_date', type=str, help='End date of the range (YYYY-MM-DD)')
    parser.add_argument('fmisids', type=str, help='Comma-separated FMISIDs for the locations')
    return parser.parse_args()

def main():
    args = parse_args()
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d') + timedelta(days=1)  # Include the end date in the range
    fmisids = [int(fmisid.strip()) for fmisid in args.fmisids.split(',')]

    # For each FMISID, fetch the historical weather data for the date range and save to CSV
    for fmisid in fmisids:
        csv_filename = f"{fmisid}.csv"
        
        # Determine if header should be written (i.e., if file is new)
        write_header = True
        
        current_date = start_date
        while current_date < end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            print(f"Fetching data for {date_str} at FMISID {fmisid}...")

            # Fetch the data for the day
            day_data = get_history(fmisid, date_str, ['TA_PT1H_AVG', 'WS_PT1H_AVG'])
            
            # Write the data for the day to CSV
            day_data.to_csv(csv_filename, mode='a', header=write_header, index=False)
            if write_header:  # Only write the header once
                write_header = False
            
            current_date += timedelta(days=1)
            time.sleep(0.2)  # Let's not spam the FMI API

        print(f"Data saved to {csv_filename}")

if __name__ == "__main__":
    main()