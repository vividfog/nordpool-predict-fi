"""
** This script needs to run at the project root folder for the util.fmi import to work. Sorry. **

Fetch historical weather data for a specified date range and set of Finnish Meteorological Institute (FMI) station IDs (FMISIDs).
Outputs SQL UPDATE statements for the prediction table to stdout.

Usage:
    The script is executed from the command line, requiring three positional arguments:
    1. start_date: The start date of the desired date range in 'YYYY-MM-DD' format.
    2. end_date: The end date of the desired date range in 'YYYY-MM-DD' format.
    3. fmisids: A comma-separated list of FMISIDs for which the historical weather data is to be fetched.

    Example command:
    python fmi_fetch_history.py 2023-01-01 2024-02-29 "101673,101256,101846,101805,101267,101786,101118,100968,101065,101339" > updates.sql
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
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d') + timedelta(days=1)
    fmisids = [int(fmisid.strip()) for fmisid in args.fmisids.split(',')]
    missing_data = []

    # Start transaction
    print("BEGIN TRANSACTION;")
    
    # Process each date in the range
    current_date = start_date
    while current_date < end_date:
        date_str = current_date.strftime('%Y-%m-%d')

        for fmisid in fmisids:
            print(f"-- Processing date {date_str} for FMISID {fmisid}")
            day_data = get_history(fmisid, date_str, ['TA_PT1H_AVG', 'WS_PT1H_AVG'])
            # print (day_data)
            
            for _, row in day_data.iterrows():
                # Format timestamp to match SQLite format exactly: YYYY-MM-DDTHH:MM:SS+00:00
                timestamp = pd.to_datetime(row['Timestamp']).strftime('%Y-%m-%dT%H:%M:%S+00:00')
                
                if pd.isna(row['TA_PT1H_AVG']):
                    missing_data.append(f"Missing TA_PT1H_AVG for FMISID {fmisid} at {timestamp}")
                    print(f"UPDATE prediction SET t_{fmisid} = NULL WHERE timestamp = '{timestamp}';")
                else:
                    print(f"UPDATE prediction SET t_{fmisid} = {row['TA_PT1H_AVG']:.1f} "
                          f"WHERE timestamp = '{timestamp}';")
                if pd.isna(row['WS_PT1H_AVG']):
                    missing_data.append(f"Missing WS_PT1H_AVG for FMISID {fmisid} at {timestamp}")
                    print(f"UPDATE prediction SET ws_{fmisid} = NULL WHERE timestamp = '{timestamp}';")
                else:
                    print(f"UPDATE prediction SET ws_{fmisid} = {row['WS_PT1H_AVG']:.1f} "
                          f"WHERE timestamp = '{timestamp}';")
            
            time.sleep(0.2)

        current_date += timedelta(days=1)

    # End transaction
    print("COMMIT;")
    if missing_data:
        print("-- Missing data details:")
        for entry in missing_data:
            print(f"-- {entry}")
        print(f"-- Total missing entries: {len(missing_data)}")

if __name__ == "__main__":
    main()