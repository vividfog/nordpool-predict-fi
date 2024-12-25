"""
dataframes.py

This module provides functions for manipulating and updating pandas DataFrames.

Functions:
- update_df_from_df(df1, df2): Updates `df1` with values from `df2` based on matching 'timestamp' and common columns.
"""

import pandas as pd
from rich import print

def update_df_from_df(df1, df2):
    # Ensure df1's 'timestamp' column is in the correct format and UTC
    df1['timestamp'] = pd.to_datetime(df1['timestamp'], utc=True)
    
    # Dynamically identify the timestamp column in df2, we've seen both uppercase and lowercase
    timestamp_col_df2 = 'timestamp' if 'timestamp' in df2.columns else 'timestamp'
    
    # Convert df2's timestamp column to datetime and to UTC
    df2[timestamp_col_df2] = pd.to_datetime(df2[timestamp_col_df2], utc=True)
    
    # Standardize column names for the operation
    df2.rename(columns={timestamp_col_df2: 'timestamp'}, inplace=True)
    
    # Find the common column to update, excluding 'timestamp'
    common_cols = set(df1.columns).intersection(set(df2.columns)) - {'timestamp'}
    if not common_cols:
        print("No common columns to update.")
        return df1
    common_col = common_cols.pop()

    # Iterate through DF2 and update DF1 based on matching Timestamps and the common column
    for index, row in df2.iterrows():
        df1.loc[df1['timestamp'] == row['timestamp'], common_col] = row[common_col]

    return df1