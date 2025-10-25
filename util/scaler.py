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
import pytz  # Use pytz directly
import math  # Import math for ceil

from .logger import logger

# region constants
# Constants for wind-based linear scaling for spike hours
WIND_SCALE_MAX_MW = 2000.0  # Wind power (MW) at or above which the minimum multiplier is applied
WIND_SCALE_MIN_MW = 50.0   # Wind power (MW) at which the maximum multiplier is applied
MAX_WIND_MULTIPLIER = 1.5   # Multiplier applied when wind power is at WIND_SCALE_MIN_MW
MIN_WIND_MULTIPLIER = 1.0   # Multiplier applied when wind power is at or above WIND_SCALE_MAX_MW

# Constant for price percentile threshold
DAILY_PRICE_RANK_FRACTION = 0.5  # Scale the top X% most expensive hours for their specific day (Helsinki time).
# endregion constants

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
    original_tz = df_result['timestamp'].dt.tz  # Store original timezone if exists

    # Check if required columns exist
    if 'PricePredict_cpkWh' not in df_result.columns:
        logger.error("Scaler: Missing 'PricePredict_cpkWh' column required for price scaling.")
        # Return original df with an empty scaled column if price is missing
        df_result['PricePredict_cpkWh_scaled'] = np.nan
        return df_result

    # Ensure timestamp is datetime and UTC for internal calculations
    try:
        # If timezone-naive, assume UTC. If timezone-aware, convert to UTC.
        if df_result['timestamp'].dt.tz is None:
            df_result['timestamp'] = pd.to_datetime(df_result['timestamp']).dt.tz_localize('UTC')
            logger.warning("Scaler: Input timestamp column was timezone-naive, assuming UTC.")
        else:
            df_result['timestamp'] = pd.to_datetime(df_result['timestamp']).dt.tz_convert('UTC')
    except Exception as e:
        logger.error(f"Scaler: Failed to process timestamp column: {e}. Cannot proceed with scaling.", exc_info=True)
        df_result['PricePredict_cpkWh_scaled'] = np.nan
        return df_result
    # endregion [init]

    # region [helsinki_time_filter]
    # Add Helsinki time-of-day filter (06:00-22:00)
    helsinki_tz = pytz.timezone('Europe/Helsinki')
    df_result['helsinki_hour'] = df_result['timestamp'].dt.tz_convert(helsinki_tz).dt.hour
    helsinki_time_filter = (df_result['helsinki_hour'] >= 6) & (df_result['helsinki_hour'] < 22)
    # endregion [helsinki_time_filter]

    # region [top_daily_hours]
    # Calculate Daily Top Expensive Hours (Helsinki Time) ONLY for hours within the Helsinki time window
    is_top_daily_hour_mask = pd.Series(False, index=df_result.index)  # Initialize mask
    top_hours_calculated = False
    try:
        df_result['helsinki_date'] = df_result['timestamp'].dt.tz_convert(helsinki_tz).dt.date

        # Function to identify top N hours within each daily group
        def get_top_hours_indices(group):
            # Only consider hours within the Helsinki time window (06:00-21:00)
            valid_hours = group[helsinki_time_filter.loc[group.index]]
            
            # Drop NaNs before sorting and selecting
            valid_prices = valid_hours['PricePredict_cpkWh'].dropna()
            if valid_prices.empty:
                return pd.Series(False, index=group.index)  # No valid prices, no top hours

            # Calculate total number of top hours to select
            n_hours_in_day = len(valid_prices)
            n_top_hours = math.ceil(n_hours_in_day * DAILY_PRICE_RANK_FRACTION)
            if n_top_hours == 0:
                return pd.Series(False, index=group.index)  # No hours to select
                
            # Split the selection between morning (06:00-12:00) and evening (16:00-22:00)
            morning_mask = (valid_hours['helsinki_hour'] >= 6) & (valid_hours['helsinki_hour'] < 12)
            evening_mask = (valid_hours['helsinki_hour'] >= 16) & (valid_hours['helsinki_hour'] < 22)
            
            morning_prices = valid_prices[morning_mask.loc[valid_prices.index]]
            evening_prices = valid_prices[evening_mask.loc[valid_prices.index]]
            
            # Calculate how many hours to select from each period (half from each)
            n_morning_hours = math.ceil(n_top_hours / 2)
            n_evening_hours = math.ceil(n_top_hours / 2)
            
            # Adjust if there aren't enough hours in one of the periods
            if len(morning_prices) < n_morning_hours:
                n_morning_hours = len(morning_prices)
                n_evening_hours = min(len(evening_prices), n_top_hours - n_morning_hours)
            elif len(evening_prices) < n_evening_hours:
                n_evening_hours = len(evening_prices)
                n_morning_hours = min(len(morning_prices), n_top_hours - n_evening_hours)
                
            # Get indices of the top hours from morning and evening periods
            top_morning_indices = morning_prices.nlargest(n_morning_hours).index if not morning_prices.empty else []
            top_evening_indices = evening_prices.nlargest(n_evening_hours).index if not evening_prices.empty else []
            
            # Combine the indices
            top_indices = list(top_morning_indices) + list(top_evening_indices)
            
            # Create a boolean series for the original group index
            is_top = pd.Series(False, index=group.index)
            is_top.loc[top_indices] = True
            return is_top

        # Apply the function to each group and combine results
        is_top_daily_hour_mask = df_result.groupby('helsinki_date', group_keys=False).apply(get_top_hours_indices)
        # Ensure the mask has the correct index and handles potential NaNs from grouping/applying
        is_top_daily_hour_mask = is_top_daily_hour_mask.reindex(df_result.index, fill_value=False)

        logger.info(f"Scaler: Identifying top {DAILY_PRICE_RANK_FRACTION*100:.0f}% most expensive hours per day (split between 06:00-12:00 and 16:00-22:00 Helsinki time).")
        top_hours_calculated = True

    except Exception as e:
        logger.error(f"Scaler: Could not identify top daily hours: {e}. Scaling will not be applied based on daily price rank.", exc_info=True)

    if not top_hours_calculated:
        # Fallback: disable price-based filtering if calculation failed
        is_top_daily_hour_mask = pd.Series(False, index=df_result.index)  # Ensure all False
        logger.warning("Scaler: Proceeding without daily price rank filtering.")
    # endregion [top_daily_hours]

    # region [wind_multiplier]
    # Calculate Wind Multiplier
    if 'WindPowerMW' not in df_result.columns:
        logger.warning("Scaler: Missing 'WindPowerMW' column required for wind-based scaling. Applying minimum multiplier (1.0) to all future hours (if price threshold met).")
        # Apply minimum scaling if wind data is missing
        df_result['wind_multiplier'] = MIN_WIND_MULTIPLIER
    else:
        # Calculate wind multiplier using linear interpolation
        # Ensure wind power is clipped within the scaling range before interpolation
        clipped_wind = df_result['WindPowerMW'].clip(WIND_SCALE_MIN_MW, WIND_SCALE_MAX_MW)

        # Linear interpolation formula: y = y1 + (x - x1) * (y2 - y1) / (x2 - x1)
        # Here: x = clipped_wind, x1 = WIND_SCALE_MAX_MW, y1 = MIN_WIND_MULTIPLIER, x2 = WIND_SCALE_MIN_MW, y2 = MAX_WIND_MULTIPLIER
        # Avoid division by zero if thresholds are the same
        denominator = WIND_SCALE_MIN_MW - WIND_SCALE_MAX_MW
        if denominator == 0:
            # If thresholds are the same, apply min multiplier unless wind is exactly at that threshold
            df_result['wind_multiplier'] = np.where(df_result['WindPowerMW'] <= WIND_SCALE_MIN_MW, MAX_WIND_MULTIPLIER, MIN_WIND_MULTIPLIER)
        else:
            df_result['wind_multiplier'] = MIN_WIND_MULTIPLIER + (clipped_wind - WIND_SCALE_MAX_MW) * \
                                           (MAX_WIND_MULTIPLIER - MIN_WIND_MULTIPLIER) / \
                                           denominator

        # Apply minimum multiplier directly if wind is above the max threshold
        df_result.loc[df_result['WindPowerMW'] >= WIND_SCALE_MAX_MW, 'wind_multiplier'] = MIN_WIND_MULTIPLIER
        # Apply maximum multiplier directly if wind is at or below the min threshold
        df_result.loc[df_result['WindPowerMW'] <= WIND_SCALE_MIN_MW, 'wind_multiplier'] = MAX_WIND_MULTIPLIER

        # Clip final multiplier just in case (e.g., floating point inaccuracies)
        df_result['wind_multiplier'] = df_result['wind_multiplier'].clip(MIN_WIND_MULTIPLIER, MAX_WIND_MULTIPLIER)
    # endregion [wind_multiplier]

    # region [future_hours]
    # Define 'now' rounded up to the nearest hour (UTC)
    now = pd.Timestamp.utcnow().ceil('h')  # Already UTC

    # Convert to Helsinki time to check the time threshold
    helsinki_tz = pytz.timezone('Europe/Helsinki')
    now_helsinki = now.tz_convert(helsinki_tz)
    helsinki_hour = now_helsinki.hour

    # Define the start timestamp for future hours based on Helsinki time
    if 0 <= helsinki_hour < 14:
        # Between 00:00-14:00 Helsinki time: scale from tomorrow 01:00 onwards
        # Get tomorrow's date in Helsinki time
        tomorrow_helsinki = now_helsinki + pd.Timedelta(days=1)
        tomorrow_helsinki = tomorrow_helsinki.replace(hour=1, minute=0, second=0)
        
        # Convert back to UTC for comparison
        future_start = tomorrow_helsinki.tz_convert('UTC')
        logger.info(f"Scaler: Current time in Helsinki ({now_helsinki.strftime('%H:%M')}) is before 14:00, scaling from tomorrow 01:00 onwards")
    else:
        # Between 14:00-00:00 Helsinki time: scale from day after tomorrow 01:00 onwards
        # First get tomorrow's date in Helsinki time
        tomorrow_helsinki = now_helsinki + pd.Timedelta(days=1)
        tomorrow_helsinki = tomorrow_helsinki.replace(hour=0, minute=0, second=0)
        
        # Then get day after tomorrow at 01:00 Helsinki time
        day_after_tomorrow_helsinki = tomorrow_helsinki + pd.Timedelta(days=1, hours=1)
        
        # Convert back to UTC for comparison
        future_start = day_after_tomorrow_helsinki.tz_convert('UTC')
        logger.info(f"Scaler: Current time in Helsinki ({now_helsinki.strftime('%H:%M')}) is after 14:00, scaling from day after tomorrow 01:00 onwards")

    # Create a mask for future hours based on the conditional start time
    future_hours_mask = df_result['timestamp'] >= future_start
    # endregion [future_hours]

    # region [apply]
    # Initialize scaled price with NaN
    df_result['PricePredict_cpkWh_scaled'] = np.nan

    # Define the mask for rows where scaling should actually be applied
    # (Future hours with valid price AND is a top daily hour AND a multiplier > 1.0)
    # Note: Helsinki time filter (06:00-22:00) is already applied when calculating top daily hours
    valid_price_mask = df_result['PricePredict_cpkWh'].notna()
    multiplier_above_min_mask = df_result['wind_multiplier'] > MIN_WIND_MULTIPLIER

    # is_top_daily_hour_mask already includes the Helsinki time filter, so we don't need helsinki_time_filter here
    apply_scaling_mask = future_hours_mask & valid_price_mask & is_top_daily_hour_mask & multiplier_above_min_mask

    # Apply the wind multiplier ONLY to rows matching the mask
    df_result.loc[apply_scaling_mask, 'PricePredict_cpkWh_scaled'] = \
        df_result.loc[apply_scaling_mask, 'PricePredict_cpkWh'] * df_result.loc[apply_scaling_mask, 'wind_multiplier']

    # Round scaled prices to 2 decimal places (only affects non-NaN values)
    df_result['PricePredict_cpkWh_scaled'] = df_result['PricePredict_cpkWh_scaled'].round(2)
    # endregion [apply]

    # region [logging]
    # Log some statistics about the scaling applied to future hours
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
            if top_hours_calculated:
                logger.info(f"  Price Threshold: Top {DAILY_PRICE_RANK_FRACTION*100:.0f}% most expensive hours per day (Helsinki Time)")
            else:
                logger.info("  Price Threshold: Daily price rank filtering disabled.")
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
    columns_to_drop = ['wind_multiplier', 'helsinki_date', 'helsinki_hour']  # Removed 'daily_price_threshold'
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
