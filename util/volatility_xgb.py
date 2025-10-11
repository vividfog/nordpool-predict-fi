"""
Trains and applies an XGBoost model to predict the likelihood of daily price volatility.

This module defines functions to:
1. Train an XGBoost Classifier (`train_volatility_model`) to identify days 
   that are likely to experience high price variance based on daily aggregated 
   features (nuclear power, import capacity, wind power, solar irradiance, holidays).
   Volatility is defined based on a percentile threshold of daily price variance.
2. Predict the volatility likelihood (`predict_daily_volatility`) for each day 
   in a given DataFrame and add it as a new column ('volatile_likelihood').

The predicted 'volatile_likelihood' is used as an input feature for the main 
price prediction model (`train_xgb.py`) to potentially enhance its predictions, 
even though it is not currently used for direct scaling of the predicted prices.
"""

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, accuracy_score, confusion_matrix, classification_report
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier
from rich import print
from .logger import logger
from .xgb_utils import configure_cuda

# Percentage threshold for labeling volatile days
VOLATILE_THRESHOLD_PERCENTILE = 80
# Small constant to avoid division by zero in feature calculation
EPSILON = 1e-6

def train_volatility_model(df):
    """
    Train an XGBoost model to predict the likelihood of price volatility.
    
    Args:
        df: DataFrame with historical price data
        
    Returns:
        A trained model that can predict volatility likelihood
    """
    logger.info(f"Training a volatility prediction model using XGBoost")
    
    # Create a copy of the DataFrame to avoid modifying the original
    df_vol = df.copy()

    # Reset the index
    df_vol.reset_index(inplace=True)
    
    # Process timestamp
    df_vol['timestamp'] = pd.to_datetime(df_vol['timestamp'])
    df_vol['date'] = df_vol['timestamp'].dt.date
    
    # Step 1: Create the volatility label (top volatile days based on price variance)
    # Group by date and calculate the variance of prices for each day
    daily_volatility = df_vol.groupby('date')['Price_cpkWh'].var().reset_index()
    daily_volatility.columns = ['date', 'price_variance']
    
    # Identify the threshold for the topmost volatile days
    volatility_threshold = daily_volatility['price_variance'].quantile(VOLATILE_THRESHOLD_PERCENTILE / 100.0)
    daily_volatility['volatile'] = (daily_volatility['price_variance'] >= volatility_threshold).astype(int)
    
    logger.info(f"Volatility threshold (top {VOLATILE_THRESHOLD_PERCENTILE}% variance): {volatility_threshold:.4f} (c/kWh)²")
    logger.info(f"Total days: {len(daily_volatility)}, Volatile days: {daily_volatility['volatile'].sum()} ({daily_volatility['volatile'].mean()*100:.1f}%)")
    
    # Step 2: Prepare features for the daily model
    # These are features known before the day starts
    # First, calculate daily aggregates
    daily_features = df_vol.groupby('date').agg({
        'NuclearPowerMW': ['mean', 'var'],
        'ImportCapacityMW': ['mean', 'var'],
        'WindPowerMW': ['mean', 'var'],
        'sum_irradiance': ['mean', 'var'],
        'holiday': 'max',  # If any hour is a holiday, the day is a holiday
    }).reset_index()
    
    # Flatten the MultiIndex columns but preserve the 'date' column name
    new_columns = []
    for col in daily_features.columns:
        if isinstance(col, tuple):
            # Check if it's the index column which contains 'date'
            if col[0] == 'date' or (isinstance(col[0], str) and 'date' in col[0].lower()):
                new_columns.append('date')
            else:
                new_columns.append('_'.join(col).strip())
        else:
            new_columns.append(col)
    
    daily_features.columns = new_columns
    
    # Create wind interaction feature: wind variability relative to stable power sources
    try:
        # Calculate stable power sources sum (nuclear + import capacity + solar proxy)
        stable_power_sum = (
            daily_features['NuclearPowerMW_mean'] + 
            daily_features['ImportCapacityMW_mean'] + 
            daily_features['sum_irradiance_mean'] + 
            EPSILON  # Add small constant to avoid division by zero
        )
        # Wind impact is high when wind variance is high and stable power is low
        daily_features['wind_impact_factor'] = daily_features['WindPowerMW_var'] / stable_power_sum
        # Handle any potential infinity values
        daily_features['wind_impact_factor'] = daily_features['wind_impact_factor'].replace([np.inf, -np.inf], np.nan)
        # Fill NaN with median to avoid issues later
        daily_features['wind_impact_factor'] = daily_features['wind_impact_factor'].fillna(daily_features['wind_impact_factor'].median())
        logger.info("Created wind_impact_factor feature capturing wind variability relative to stable power sources")
    except Exception as e:
        logger.warning(f"Could not create wind_impact_factor: {e}")
        daily_features['wind_impact_factor'] = 0
    
    # Merge the volatility label with features
    daily_data = pd.merge(daily_features, daily_volatility[['date', 'volatile']], on='date')
    
    # Choose features for the model (avoid using any price information)
    X_features = ['NuclearPowerMW_mean', 'NuclearPowerMW_var',
                'ImportCapacityMW_mean', 'ImportCapacityMW_var',
                'WindPowerMW_mean', 'WindPowerMW_var',
                'holiday_max', 'sum_irradiance_mean', 'sum_irradiance_var',
                'wind_impact_factor']
    
    # Remove any features with too many NaN values
    X_data = daily_data[X_features].copy()
    missing_pct = X_data.isnull().mean()
    valid_features = missing_pct[missing_pct < 0.1].index.tolist()
    
    if len(valid_features) < len(X_features):
        logger.warning(f"Removed {len(X_features) - len(valid_features)} features due to >10% missing values")
        X_features = valid_features
    
    # Get the final feature set
    X_data = daily_data[X_features].copy()
    y_data = daily_data['volatile'].values
    
    # Fill any remaining NAs with median values
    X_data = X_data.fillna(X_data.median())
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X_data, y_data, test_size=0.2, random_state=42, stratify=y_data
    )
    
    logger.info(f"Training data shape: {X_train.shape}")
    logger.info(f"Volatility model feature columns: {', '.join(X_features)}")
    
    # Standardize features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Calculate scale_pos_weight for class imbalance
    neg_count = np.sum(y_train == 0)
    pos_count = np.sum(y_train == 1)
    scale_pos_weight_val = neg_count / pos_count if pos_count > 0 else 1
    logger.info(f"Calculated scale_pos_weight for XGBoost: {scale_pos_weight_val:.2f}")
    
    # Build XGBoost classifier model
    model_params = configure_cuda(
        {
            'objective': 'binary:logistic',  # Output logistic probabilities
            'eval_metric': 'logloss',        # Evaluation metric
            'scale_pos_weight': scale_pos_weight_val,  # Handle class imbalance
            'n_estimators': 200,             # Number of trees
            'learning_rate': 0.05,           # Learning rate
            'max_depth': 4,                  # Max depth of trees
            'random_state': 42,
            'n_jobs': -1                     # Use all available cores
        },
        logger,
    )
    model = XGBClassifier(**model_params)
    
    # Train the model
    model.fit(X_train_scaled, y_train)
    
    # Evaluate model performance on test set
    y_proba = model.predict_proba(X_test_scaled)[:, 1]  # Get probability of class 1
    y_pred = model.predict(X_test_scaled)
    
    # Calculate metrics
    auc = roc_auc_score(y_test, y_proba)
    accuracy = accuracy_score(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred)
    
    logger.info(f"Volatility model evaluation (XGBoost):")
    logger.info(f"  ROC AUC: {auc:.4f}")
    logger.info(f"  Accuracy: {accuracy:.4f}")
    logger.info(f"  Confusion Matrix:\n{cm}")
    logger.info(f"Classification Report:\n{classification_report(y_test, y_pred)}")
    
    # Create a prediction function that encapsulates the trained model and preprocessing
    def predict_volatility(daily_features):
        """
        Predict volatility likelihood for new data
        
        Args:
            daily_features: DataFrame with the same features used during training
            
        Returns:
            Array of probabilities indicating likelihood of volatility
        """
        features_copy = daily_features.copy()
        
        # Calculate wind impact factor if needed
        if 'wind_impact_factor' in X_features and 'wind_impact_factor' not in features_copy.columns:
            try:
                stable_power_sum = (
                    features_copy['NuclearPowerMW_mean'] + 
                    features_copy['ImportCapacityMW_mean'] + 
                    features_copy['sum_irradiance_mean'] + 
                    EPSILON
                )
                features_copy['wind_impact_factor'] = features_copy['WindPowerMW_var'] / stable_power_sum
                features_copy['wind_impact_factor'] = features_copy['wind_impact_factor'].replace([np.inf, -np.inf], np.nan)
            except Exception:
                features_copy['wind_impact_factor'] = 0  # Safe default
        
        # Ensure the new data has all required features
        missing_cols = set(X_features) - set(features_copy.columns)
        if missing_cols:
            logger.warning(f"Missing columns in prediction data: {missing_cols}")
            for col in missing_cols:
                features_copy[col] = 0  # Use a safe default
        
        # Select and order features correctly
        X_new = features_copy[X_features].copy()
        
        # Fill missing values with median from training data
        X_new = X_new.fillna(X_data.median())
        
        # Scale the features
        X_new_scaled = scaler.transform(X_new)
        
        # Get probabilities for class 1 (volatile)
        probabilities = model.predict_proba(X_new_scaled)[:, 1]
        
        return probabilities
    
    # Return the prediction function
    return predict_volatility

def predict_daily_volatility(df, model):
    """
    Predict daily volatility likelihood for the DataFrame.
    
    Args:
        df: DataFrame with hourly data
        model: The trained volatility model function
        
    Returns:
        DataFrame with an added volatile_likelihood column
    """
    # Create a copy to avoid modifying the original
    df_result = df.copy()

    # Reset the index of df_full
    df_result.reset_index(inplace=True)
    
    # Extract date from timestamp
    df_result['date'] = pd.to_datetime(df_result['timestamp']).dt.date
    
    # Aggregate daily features - matching the reduced feature set
    daily_features = df_result.groupby('date').agg({
        'NuclearPowerMW': ['mean', 'var'],
        'ImportCapacityMW': ['mean', 'var'],
        'WindPowerMW': ['mean', 'var'],
        'holiday': 'max',
        'sum_irradiance': ['mean', 'var'],
    }).reset_index()
    
    # Flatten the MultiIndex columns but preserve the 'date' column name
    new_columns = []
    for col in daily_features.columns:
        if isinstance(col, tuple):
            # Check if it's the index column which contains 'date'
            if col[0] == 'date' or (isinstance(col[0], str) and 'date' in col[0].lower()):
                new_columns.append('date')
            else:
                new_columns.append('_'.join(col).strip())
        else:
            new_columns.append(col)
    
    daily_features.columns = new_columns
    
    # Get volatility predictions
    volatility_probs = model(daily_features)
    daily_features['volatile_likelihood'] = volatility_probs
    
    # Log the volatility predictions for future dates
    # future_dates = daily_features[pd.to_datetime(daily_features['date']) >= pd.Timestamp.today().normalize()]
    # if not future_dates.empty:
    #     logger.info("Price volatility likelihood for upcoming days:")
    #     for _, row in future_dates.iterrows():
    #         logger.info(f"  {row['date']}: {row['volatile_likelihood']:.4f}")
    
    # Map the volatility likelihood back to the hourly data
    date_to_volatility = dict(zip(daily_features['date'], daily_features['volatile_likelihood']))
    df_result['volatile_likelihood'] = df_result['date'].map(date_to_volatility)
    
    # Remove the temporary date column
    df_result = df_result.drop(columns=['date'])
    
    return df_result
