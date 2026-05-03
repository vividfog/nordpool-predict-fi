"""
Scales predicted electricity prices based on wind power forecasts.

This module applies a scaling multiplier to predicted electricity prices during
peak hours, if wind power generation is expected to be low. The scaling is 
applied selectively to the most expensive hours of the day (based on price rank)
and only when wind power falls below configurable thresholds.

Lower wind power results in higher price multipliers, allowing the system to
anticipate potential price spikes when renewable generation is limited.
"""

import pandas as pd
import numpy as np
import os
import json

from .logger import logger
from .spike_risk import (
    DAILY_PRICE_RANK_FRACTION,
    SPIKE_RISK_COLUMNS,
    WIND_SCALE_MAX_MW,
    compute_spike_risk_hours,
)

# region scaling
def scale_predicted_prices(df, deploy=False, deploy_folder_path=None):
    """
    Scale predicted electricity prices for FUTURE hours based on hourly wind power,
    but ONLY if the original predicted price for that hour is within the top X%
    most expensive hours for that specific day (defined by Helsinki timezone).

    A linear multiplier between MIN_WIND_MULTIPLIER and MAX_WIND_MULTIPLIER is applied,
    inversely proportional to the wind power between WIND_SCALE_MAX_MW and WIND_SCALE_MIN_MW.

    Hours not meeting the criteria (past hours, lower daily price rank, high wind) will have NaN in the scaled column.

    Optionally saves scaled future predictions to a JSON file.

    Args:
        df: DataFrame with hourly data including timestamp (assumed UTC or timezone-naive UTC),
            PricePredict_cpkWh, and WindPowerMW.
        deploy (bool): If True, save scaled future predictions to deploy folder.
        deploy_folder_path (str): Path to the deploy folder (required if deploy is True).

    Returns:
        DataFrame with scaled predicted prices in a new 'PricePredict_cpkWh_scaled' column.
        The original timezone of the input df is preserved.
    """
    # region [init]
    # Create a copy to avoid modifying the original
    df_result = df.copy()
    original_tz = df_result['timestamp'].dt.tz if pd.api.types.is_datetime64_any_dtype(df_result['timestamp']) else None

    # Check if required columns exist
    if 'PricePredict_cpkWh' not in df_result.columns:
        logger.error("Scaler: Missing 'PricePredict_cpkWh' column required for price scaling.")
        # Return original df with an empty scaled column if price is missing
        df_result['PricePredict_cpkWh_scaled'] = np.nan
        return df_result

    df_result = compute_spike_risk_hours(df_result)
    # endregion [init]

    # region [apply]
    # Initialize scaled price with NaN
    df_result['PricePredict_cpkWh_scaled'] = np.nan

    apply_scaling_mask = df_result['is_spike_risk_hour']
    valid_price_mask = df_result['PricePredict_cpkWh'].notna()

    # Apply the wind multiplier ONLY to rows matching the mask
    df_result.loc[apply_scaling_mask, 'PricePredict_cpkWh_scaled'] = \
        df_result.loc[apply_scaling_mask, 'PricePredict_cpkWh'] * df_result.loc[apply_scaling_mask, 'wind_multiplier']

    # Round scaled prices to 2 decimal places (only affects non-NaN values)
    df_result['PricePredict_cpkWh_scaled'] = df_result['PricePredict_cpkWh_scaled'].round(2)
    # endregion [apply]

    # region [logging]
    # Log some statistics about the scaling applied to future hours
    future_hours_mask = df_result['is_future_hour']
    if future_hours_mask.any():
        # Consider only future hours with valid original prices for stats
        valid_future_mask = future_hours_mask & valid_price_mask
        if valid_future_mask.any():
            # Count how many hours met all scaling criteria
            scaled_hours_count = apply_scaling_mask.sum()

            original_future = df_result.loc[valid_future_mask, 'PricePredict_cpkWh']
            # Scaled stats should only consider hours where scaling was actually applied
            scaled_future = df_result.loc[apply_scaling_mask, 'PricePredict_cpkWh_scaled']
            applied_multipliers = df_result.loc[apply_scaling_mask, 'wind_multiplier']

            # Use .dropna() before calculating stats to avoid warnings/errors if all are NaN
            original_min = original_future.dropna().min()
            original_max = original_future.dropna().max()
            original_mean = original_future.dropna().mean()

            logger.info(f"Scaler: Evaluated {valid_future_mask.sum()} future hours with valid prices.")
            logger.info(f"  Price Threshold: Top {DAILY_PRICE_RANK_FRACTION*100:.0f}% most expensive hours per day (Helsinki Time)")
            logger.info(f"  Wind Threshold for Scaling: < {WIND_SCALE_MAX_MW:.0f} MW")
            logger.info(f"  Hours meeting ALL scaling criteria: {scaled_hours_count}")

            if scaled_hours_count > 0 and not scaled_future.dropna().empty:
                scaled_min = scaled_future.dropna().min()
                scaled_max = scaled_future.dropna().max()
                scaled_mean = scaled_future.dropna().mean()
                avg_multiplier = applied_multipliers.dropna().mean()
                min_multiplier = applied_multipliers.dropna().min()
                max_multiplier = applied_multipliers.dropna().max()

                logger.info(f"  Applied Multiplier Range (on scaled hours): {min_multiplier:.2f}x - {max_multiplier:.2f}x, Mean: {avg_multiplier:.2f}x")
                logger.info("Scaler: Price impact on hours meeting scaling criteria:")
                if pd.notna(original_min):
                    logger.info(f"  Original Range (all future): {original_min:.2f} - {original_max:.2f} c/kWh, Mean: {original_mean:.2f} c/kWh")
                else:
                    logger.info("  Original Range (all future): N/A (no valid prices)")
                logger.info(f"  Scaled Range (scaled hours only):   {scaled_min:.2f} - {scaled_max:.2f} c/kWh, Mean: {scaled_mean:.2f} c/kWh")
            else:
                logger.info("  No hours met all criteria for scaling or no valid scaled prices.")
        else:
            logger.info("Scaler: No future hours with valid prices found to evaluate for scaling.")
    else:
        logger.info("Scaler: No future hours found to evaluate for scaling.")
    # endregion [logging]

    # region [deploy]
    # Save scaled predictions if deploy flag is set
    if deploy:
        if deploy_folder_path is None:
            logger.error("Scaler: deploy_folder_path is required when deploy=True, cannot save scaled predictions.")
        else:
            try:
                # Define 'now' rounded up to the nearest hour (UTC) - Redefine for safety
                now_deploy = pd.Timestamp.utcnow().ceil('h')

                # Filter for future hours AGAIN using the UTC timestamp
                df_future_scaled = df_result[df_result['timestamp'] >= now_deploy].copy()

                if not df_future_scaled.empty:
                    # Select and format data: timestamp (ms), scaled price
                    # Use the 'PricePredict_cpkWh_scaled' column which now contains scaled/original prices
                    # Note: Hours not scaled will have NaN here, which becomes null in JSON
                    scaled_output = df_future_scaled[['timestamp', 'PricePredict_cpkWh_scaled']].copy()

                    # Ensure the epoch timestamp is timezone-aware (UTC)
                    epoch = pd.Timestamp("1970-01-01", tz='UTC')  # Explicit UTC
                    scaled_output['timestamp'] = scaled_output['timestamp'].apply(
                        lambda x: int((x - epoch) // pd.Timedelta('1ms')) if pd.notna(x) else None  # x is already UTC
                    )

                    # Rename column for clarity in JSON if desired (optional)
                    # scaled_output.rename(columns={'PricePredict_cpkWh_scaled': 'price'}, inplace=True)

                    # Convert to list of lists format
                    json_data_list = scaled_output.values.tolist()

                    # Define file path
                    json_filename = 'prediction_scaled.json'
                    json_path = os.path.join(deploy_folder_path, json_filename)

                    # Write JSON file
                    # Convert any remaining NaN/None price values to null in JSON
                    json_data_list = [[item if not pd.isna(item) else None for item in row] for row in json_data_list]
                    with open(json_path, 'w') as f:
                        json.dump(json_data_list, f, ensure_ascii=False)
                    logger.info(f"Scaler: Saved scaled future predictions to '{json_path}'")
                else:
                    logger.info("Scaler: No future hours found to save scaled predictions.")

            except Exception as e:
                logger.error(f"Scaler: Failed to save scaled predictions: {e}", exc_info=True)
    # endregion [deploy]

    # region [cleanup]
    # Drop intermediate columns before returning
    columns_to_drop = SPIKE_RISK_COLUMNS
    existing_cols_to_drop = [col for col in columns_to_drop if col in df_result.columns]
    if existing_cols_to_drop:
        df_result = df_result.drop(columns=existing_cols_to_drop)

    # Restore original timezone if it existed
    if original_tz is not None:
        try:
            # Only convert if the current timezone is indeed UTC
            if df_result['timestamp'].dt.tz == pd.Timestamp(0, tz='UTC').tz:
                df_result['timestamp'] = df_result['timestamp'].dt.tz_convert(original_tz)
        except Exception as e:
            logger.warning(f"Scaler: Could not restore original timezone ({original_tz}): {e}")
    else:
        # If original was naive, convert back to naive (assuming current is UTC)
        if df_result['timestamp'].dt.tz == pd.Timestamp(0, tz='UTC').tz:
            df_result['timestamp'] = df_result['timestamp'].dt.tz_localize(None)

    return df_result
# endregion scaling
