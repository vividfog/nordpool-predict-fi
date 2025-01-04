import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz

# Define the UTC timezone
UTC = pytz.UTC

# Define the exact start datetime in UTC
START_DATETIME_UTC = UTC.localize(datetime(2023, 1, 1, 0, 0, 0))

# Define the end datetime as two days before the current UTC time
END_DATETIME_UTC = datetime.now(UTC) - timedelta(days=2)

# Format dates as 'YYYY-MM-DD'
START_DATE_UTC_STR = START_DATETIME_UTC.strftime("%Y-%m-%d")
END_DATE_UTC_STR = END_DATETIME_UTC.strftime("%Y-%m-%d")

def fetch_holiday_data():
    """
    Fetches Finnish holiday data from pyhäpäivä.fi and returns a DataFrame
    with UTC timestamps and corresponding holiday kind_id.
    
    Returns:
        pd.DataFrame: DataFrame with columns ['timestamp', 'holiday_fetched'].
    """
    historical_url = "https://pyhäpäivä.fi/?output=json"
    response = requests.get(historical_url)
    response.raise_for_status()
    holidays_json = response.json()

    # Initialize a dictionary to map each UTC timestamp to its kind_id
    holiday_map = {}

    for item in holidays_json:
        kind_id_int = int(item.get("kind_id", 0))  # default 0 if missing
        local_date = pd.to_datetime(item["date"])
        helsinki_tz = pytz.timezone('Europe/Helsinki')
        local_midnight = helsinki_tz.localize(local_date)

        # Build the 24-hour range for that local day
        day_hours_local = pd.date_range(
            start=local_midnight,
            periods=24,
            freq='H'
        )
        # Convert each hour to UTC
        day_hours_utc = day_hours_local.tz_convert(UTC)

        for hour_utc in day_hours_utc:
            # Only consider timestamps within the desired range
            if START_DATETIME_UTC <= hour_utc <= END_DATETIME_UTC:
                # If hour_utc not seen yet or this kind_id is "larger," store it
                if (hour_utc not in holiday_map) or (kind_id_int > holiday_map[hour_utc]):
                    holiday_map[hour_utc] = kind_id_int

    # Convert dict -> DataFrame
    holiday_list = [(ts, val) for ts, val in holiday_map.items()]
    holiday_df = pd.DataFrame(holiday_list, columns=['timestamp', 'holiday_fetched'])
    holiday_df.sort_values('timestamp', inplace=True, ignore_index=True)

    return holiday_df

def generate_sql_updates(full_hours_df, holiday_df):
    """
    Generates SQL UPDATE statements to set the 'holiday' column in the 'prediction' table.
    
    Args:
        full_hours_df (pd.DataFrame): DataFrame containing all hourly timestamps.
        holiday_df (pd.DataFrame): DataFrame containing 'timestamp' and 'holiday_fetched'.
    
    Returns:
        list: List of SQL UPDATE statements as strings.
    """
    # Merge the full hours with holiday data
    merged_df = pd.merge(
        full_hours_df,
        holiday_df,
        on='timestamp',
        how='left'
    )

    # Replace NaN in 'holiday_fetched' with 0 (non-holiday)
    merged_df['holiday_fetched'] = merged_df['holiday_fetched'].fillna(0).astype(int)

    # Generate SQL UPDATE statements
    sql_statements = []
    for _, row in merged_df.iterrows():
        timestamp = row['timestamp'].strftime('%Y-%m-%dT%H:%M:%S+00:00')
        holiday_value = row['holiday_fetched']
        
        sql = (
            f"UPDATE prediction SET "
            f"holiday = {holiday_value} "
            f"WHERE timestamp = '{timestamp}';"
        )
        sql_statements.append(sql)
    
    return sql_statements

def main():
    """
    Main function to fetch holiday data and generate SQL UPDATE statements.
    Outputs valid SQL statements encapsulated within a transaction block.
    """
    # Fetch holiday data
    holiday_df = fetch_holiday_data()

    # Create a DataFrame with all hourly timestamps in the date range
    all_hours = pd.date_range(
        start=START_DATETIME_UTC,
        end=END_DATETIME_UTC,
        freq='H',
        tz=UTC
    )
    full_hours_df = pd.DataFrame({'timestamp': all_hours})

    # Generate SQL UPDATE statements
    sql_updates = generate_sql_updates(full_hours_df, holiday_df)

    # Output SQL statements
    print("-- Begin SQL Updates")
    print("BEGIN TRANSACTION;")
    for sql in sql_updates:
        print(sql)
    print("COMMIT;")
    print("-- End SQL Updates")

    # Optionally, save to a file (uncomment if needed)
    # with open('update_holidays.sql', 'w') as file:
    #     file.write("-- Begin SQL Updates\n")
    #     file.write("BEGIN TRANSACTION;\n")
    #     for sql in sql_updates:
    #         file.write(sql + "\n")
    #     file.write("COMMIT;\n")
    #     file.write("-- End SQL Updates\n")
    # print("SQL statements saved to update_holidays.sql")

if __name__ == "__main__":
    main()
