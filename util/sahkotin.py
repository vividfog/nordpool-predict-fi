import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz
import sys
from rich import print

def fetch_electricity_price_data(start_date, end_date):
    """
    Fetches electricity price data from sahkotin.fi for a specified date range.

    Parameters:
    - start_date (str): The start datetime in ISO format.
    - end_date (str): The end datetime in ISO format.

    Returns:
    - pd.DataFrame: A DataFrame with two columns ['timestamp', 'Price_cpkWh'] where 'timestamp' is the datetime and 'Price_cpkWh' is the electricity price.
    """
    api_url = "https://sahkotin.fi/prices?vat"
    params = {
        'start': start_date,
        'end': end_date
    }
    
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status() 
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error occurred while fetching data from Sähkötin API: {e}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Error occurred during request to Sähkötin API: {e}")
        sys.exit(1)

    if response.status_code == 200:
        try:
            data = response.json().get('prices', [])
        except ValueError as e:  # Includes simplejson.decoder.JSONDecodeError
            print(f"Error decoding JSON from Sähkötin API response: {e}")
            sys.exit(1)
        df = pd.DataFrame(data)
        if not df.empty:
            try:
                df['date'] = pd.to_datetime(df['date'], utc=True)
                df['value'] = df['value'] / 10
                df.rename(columns={'date': 'timestamp', 'value': 'Price_cpkWh'}, inplace=True)
            except Exception as e:
                print(f"Error processing data from Sähkötin API: {e}")
                sys.exit(1)
            return df
        else:
            print("No data returned from the API.")
            return pd.DataFrame(columns=['timestamp', 'Price_cpkWh'])
    else:
        print(f"Failed to fetch electricity price data: {response.text}")
        return pd.DataFrame(columns=['timestamp', 'Price_cpkWh'])


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

def update_spot(df):
    """
    Updates the input DataFrame with electricity price data fetched from sahkotin.fi.

    Parameters:
    - df (pd.DataFrame): The input DataFrame containing a 'timestamp' column.

    Returns:
    - pd.DataFrame: The updated DataFrame with electricity price data.
    """
    current_date = datetime.now(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    history_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_date = (datetime.now(pytz.UTC) + timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    print(f"* Sähkötin: Fetching electricity price data between {history_date[:10]} and {end_date[:10]}")
    
    price_df = fetch_electricity_price_data(history_date, end_date)   
    
    if not price_df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        merged_df = pd.merge(df, price_df, on='timestamp', how='left')
       
        merged_df = clean_up_df_after_merge(merged_df)

        # Interpolate to fill NaN values in 'Price_cpkWh'
        merged_df['Price_cpkWh'] = merged_df['Price_cpkWh'].interpolate(method='cubic')

        return merged_df
    else:
        print("Warning: No electricity price data fetched; unable to update DataFrame.")
        return df

def sahkotin_tomorrow():
    tz = pytz.timezone("Europe/Helsinki")
    tomorrow = datetime.now(tz) + timedelta(days=1)
    start_dt = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = tomorrow.replace(hour=23, minute=59, second=59, microsecond=0)
    # Convert Helsinki times to UTC for the API request
    start_utc = start_dt.astimezone(pytz.UTC)
    end_utc = end_dt.astimezone(pytz.UTC)
    start_str = start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_str = end_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    df = fetch_electricity_price_data(start_str, end_str)
    if df.empty:
        return df, None, start_dt

    # Convert timestamp to Helsinki time and resample to hourly data.
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_convert(tz)
    df.set_index('timestamp', inplace=True)
    hourly_df = df.resample("h").mean()
    daily_avg = df["Price_cpkWh"].mean()
    
    return hourly_df, daily_avg, start_dt

def main():
    tz = pytz.timezone("Europe/Helsinki")
    hourly_df, daily_avg, start_dt = sahkotin_tomorrow()
    
    if hourly_df.empty:
        print("[red]No pricing data available for tomorrow.")
        return

    print(f"[bold blue]* Sähkötin: Fetched tomorrow's prices for {start_dt.strftime('%Y-%m-%d')} (Helsinki Time)")
    
    from rich.table import Table
    table = Table(title=f"Electricity Prices for {start_dt.strftime('%Y-%m-%d')} (Hourly in Helsinki Time) and Daily Average")
    table.add_column("Hour (Helsinki)", justify="center")
    table.add_column("Price cpkWh", justify="center")
    
    for timestamp, row in hourly_df.iterrows():
        hour_str = timestamp.strftime('%H:%M')
        price = row["Price_cpkWh"]
        value_str = f"{price:.2f}" if not pd.isna(price) else "N/A"
        table.add_row(hour_str, value_str)
    
    table.add_row("[bold]Daily Average[/bold]", f"[bold]{daily_avg:.2f}[/bold]")
    print(table)

if __name__ == '__main__':
    main()