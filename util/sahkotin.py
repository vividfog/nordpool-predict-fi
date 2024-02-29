import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz

def fetch_electricity_price_data(start_date, end_date):
    """
    Fetches electricity price data from sahkotin.fi for a specified date range.

    Parameters:
    - start_date (str): The start datetime in ISO format.
    - end_date (str): The end datetime in ISO format.

    Returns:
    - pd.DataFrame: A DataFrame with two columns ['Timestamp', 'Price_cpkWh'] where 'Timestamp' is the datetime and 'Price_cpkWh' is the electricity price.
    """
    api_url = "https://sahkotin.fi/prices?vat"
    params = {
        'start': start_date,
        'end': end_date
    }
    
    response = requests.get(api_url, params=params)
    print(response.url)

    if response.status_code == 200:
        data = response.json().get('prices', [])
        df = pd.DataFrame(data)
        if not df.empty:
            # Convert 'date' to datetime and ensure it's in UTC
            df['date'] = pd.to_datetime(df['date'], utc=True)
            # Make it cents per kWh instead of euros per MWh
            df['value'] = df['value'] / 10
            # Rename columns to match expected format
            df.rename(columns={'date': 'Timestamp', 'value': 'Price_cpkWh'}, inplace=True)
            return df
        else:
            print("No data returned from the API.")
            return pd.DataFrame(columns=['Timestamp', 'Price_cpkWh'])
    else:
        print(f"Failed to fetch electricity price data: {response.text}")
        return pd.DataFrame(columns=['Timestamp', 'Price_cpkWh'])


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
    - df (pd.DataFrame): The input DataFrame containing a 'Timestamp' column.

    Returns:
    - pd.DataFrame: The updated DataFrame with electricity price data.
    """
    current_date = datetime.now(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    history_date = (datetime.now(pytz.UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_date = (datetime.now(pytz.UTC) + timedelta(hours=120)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    print(f"* Fetching electricity price data between {history_date[:10]} and {end_date[:10]}")
    
    price_df = fetch_electricity_price_data(history_date, end_date)   
    
    if not price_df.empty:
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], utc=True)
        merged_df = pd.merge(df, price_df, on='Timestamp', how='left')
       
        merged_df = clean_up_df_after_merge(merged_df)
               
        return merged_df
    else:
        print("Warning: No electricity price data fetched; unable to update DataFrame.")
        return df
