import pandas as pd

def weekdays_get(df):

    # Ensure 'timestamp' is in datetime format
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # Update 'month', 'hour', 'day_of_week'
    df['month'] = df['timestamp'].dt.month
    df['hour'] = df['timestamp'].dt.hour
    df['day_of_week'] = df['timestamp'].dt.dayofweek + 1  # +1 to match your requirement Monday=1

    return df