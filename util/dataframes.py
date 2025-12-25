"""
dataframes.py

This module provides functions for manipulating and updating pandas DataFrames.

Functions:
- update_df_from_df(df, updates, cols=...): Patch selected columns by timestamp.
- coalesce_merged_columns(df): Consolidates duplicate columns (e.g. *_x, *_y) produced by merge operations.
"""

import pandas as pd


def update_df_from_df(df, updates, *, cols):
    if not cols:
        raise ValueError("cols must contain at least one column")

    if "timestamp" not in df.columns:
        raise ValueError("df must contain a 'timestamp' column")

    timestamp_cols = [col for col in updates.columns if col.lower() == "timestamp"]
    if not timestamp_cols:
        raise ValueError("updates must contain a 'timestamp' column")

    updates_ts = timestamp_cols[0]

    left = df.copy()
    right = updates.copy()

    left["timestamp"] = pd.to_datetime(left["timestamp"], utc=True)
    if updates_ts != "timestamp":
        right = right.rename(columns={updates_ts: "timestamp"})
    right["timestamp"] = pd.to_datetime(right["timestamp"], utc=True)

    right = right[["timestamp"] + list(cols)].drop_duplicates(
        subset=["timestamp"], keep="last"
    )
    right = right.rename(columns={col: f"{col}_new" for col in cols})

    merged = pd.merge(left, right, on="timestamp", how="left")

    for col in cols:
        col_new = f"{col}_new"
        if col not in merged.columns:
            merged[col] = merged[col_new]
        else:
            merged[col] = merged[col_new].combine_first(merged[col])

        merged.drop(columns=[col_new], inplace=True)

    return merged


def coalesce_merged_columns(df):
    """
    Remove duplicate columns created by merge operations while preserving the most
    recent data. For columns ending with '_x'/'_y', values from '_y' take precedence
    when the original column contains NaNs.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("coalesce_merged_columns expects a pandas DataFrame")

    columns_to_drop = set()

    for col in list(df.columns):
        if not col.endswith("_x"):
            continue

        base_name = col[:-2]
        duplicate_name = f"{base_name}_y"

        df[base_name] = df[col].copy()

        if duplicate_name in df.columns:
            df[base_name] = df[base_name].where(
                df[base_name].notna(), df[duplicate_name]
            )
            columns_to_drop.add(duplicate_name)

        columns_to_drop.add(col)

    if columns_to_drop:
        df.drop(columns=list(columns_to_drop), inplace=True)

    return df
