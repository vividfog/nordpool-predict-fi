import pandas as pd

# Path to the electricity spot price data file
file_path_spot_price = './sahkotin_spot_price_vat.csv'

# Read the CSV file, ensuring timestamps are parsed correctly
df_spot_price = pd.read_csv(file_path_spot_price,
                            parse_dates=['hour'],
                            index_col='hour')

# Assuming the data is already hourly and does not require resampling
# Interpolate missing values if necessary
df_spot_price_interpolated = df_spot_price.interpolate(method='linear')

# Generate and print UPDATE statements for the Price_cpkWh column
for timestamp, row in df_spot_price_interpolated.iterrows():
    price_value = row['price']
    print(f"UPDATE prediction SET Price_cpkWh = {price_value} WHERE Timestamp = '{timestamp.isoformat()}';")
