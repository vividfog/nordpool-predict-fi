import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import scipy.stats as stats
from pytz import timezone
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, mean_absolute_percentage_error
from .sql import db_query_all

def eval(db_path, plot=False):
    # Load the data
    data = db_query_all(db_path)

    data_clean = data.dropna(subset=['Price_cpkWh', 'PricePredict_cpkWh']).copy()

    # Localize timestamp to UTC and convert to Helsinki timezone
    data_clean['timestamp'] = pd.to_datetime(data_clean['timestamp'])
    data_clean['timestamp'] = data_clean['timestamp'].dt.tz_localize('UTC').dt.tz_convert('Europe/Helsinki')

    # Get minimum and maximum timestamp
    min_timestamp = data_clean['timestamp'].min()
    max_timestamp = data_clean['timestamp'].max()

    # Calculate evaluation metrics
    mae = mean_absolute_error(data_clean['Price_cpkWh'], data_clean['PricePredict_cpkWh'])
    mse = mean_squared_error(data_clean['Price_cpkWh'], data_clean['PricePredict_cpkWh'])
    rmse = np.sqrt(mse)
    r2 = r2_score(data_clean['Price_cpkWh'], data_clean['PricePredict_cpkWh'])
    smape = 2.0 * np.mean(np.abs(data_clean['Price_cpkWh'] - data_clean['PricePredict_cpkWh']) / (np.abs(data_clean['Price_cpkWh']) + np.abs(data_clean['PricePredict_cpkWh']))) * 100
    pearson_corr = data_clean['Price_cpkWh'].corr(data_clean['PricePredict_cpkWh'], method='pearson')
    spearman_corr = data_clean['Price_cpkWh'].corr(data_clean['PricePredict_cpkWh'], method='spearman')

    # Evaluation metrics formatted as markdown text, including units and interpretative guidance
    markdown = f"""Evaluation Metrics and Explanations (For the time period from {min_timestamp} to {max_timestamp} Helsinki Time):

- **MAE (Mean Absolute Error): {mae:.2f} cents/kWh**
  This measures the average magnitude of errors in the model's predictions, without considering their direction. In simple terms, it shows how much, on average, the model's price predictions are off from the actual prices. Ideally, we want this number to be as low as possible. A low MAE indicates that the model's predictions are generally close to the actual prices.

- **MSE (Mean Squared Error): {mse:.2f} (cents/kWh)^2**
  This squares the errors before averaging, which means it gives more weight to larger errors. This metric is useful for identifying whether the model is making any significantly large errors, though its units are squared, making it less intuitive. Lower values indicate that the model is making fewer and less severe mistakes in its predictions.

- **RMSE (Root Mean Squared Error): {rmse:.2f} cents/kWh**
  This is the square root of MSE, bringing the error units back to the same units as the prices (cents per kWh). It's useful for understanding the magnitude of error in the same units as the target variable. Like MAE, a lower RMSE indicates better fit to the data, but it gives a sense of the average size of the errors.

- **R^2 (Coefficient of Determination): {r2:.3f} (unitless)**
  This indicates how much of the variance in the actual prices is explained by the model. A score of 1 means the model perfectly predicts the prices, while a score closer to 0 means the model fails to accurately predict the prices.

- **sMAPE (Symmetric Mean Absolute Percentage Error): {smape:.1f}%**
  This provides an intuitive understanding of the average error in percentage terms. It treats overpredictions and underpredictions equally. A value closer to 0% indicates more accurate predictions.

Correlation Coefficients:
- **Pearson Correlation Coefficient: {pearson_corr:.3f} (unitless)**
  This measures the linear correlation between the actual and predicted prices. A coefficient of 1 indicates a perfect positive linear correlation, meaning the model's predictions perfectly align with the actual prices in a linear fashion.

- **Spearman Rank Correlation Coefficient: {spearman_corr:.3f} (unitless)**
  This assesses how well the relationship between the model's predictions and the actual prices can be described using a monotonic function. It does not assume a linear relationship but rather that the rankings of actual and predicted prices match.
"""

    if not plot:
        return markdown

    # Generate and display plots for visual analysis if requested
    residuals = data_clean['PricePredict_cpkWh'] - data_clean['Price_cpkWh']

    # Plotting Histogram of Residuals
    plt.figure(figsize=(10, 6))
    sns.histplot(residuals, kde=True)
    plt.title('Histogram of Residuals')
    plt.xlabel('Residuals (cents/kWh)')
    plt.ylabel('Frequency')
    plt.grid(True)
    plt.show()

    # Plotting Q-Q Plot
    plt.figure(figsize=(10, 6))
    stats.probplot(residuals, dist="norm", plot=plt)
    plt.title('Q-Q Plot of Residuals')
    plt.grid(True)
    plt.show()

    # Bland-Altman Plot
    mean_prices = (data_clean['Price_cpkWh'] + data_clean['PricePredict_cpkWh']) / 2
    diff_prices = data_clean['PricePredict_cpkWh'] - data_clean['Price_cpkWh']
    plt.figure(figsize=(10, 6))
    plt.scatter(mean_prices, diff_prices, alpha=0.5)
    plt.axhline(y=np.mean(diff_prices), color='r', linestyle='--')
    plt.axhline(y=np.mean(diff_prices) + 1.96*np.std(diff_prices), color='g', linestyle='--')
    plt.axhline(y=np.mean(diff_prices) - 1.96*np.std(diff_prices), color='g', linestyle='--')
    plt.title('Bland-Altman Plot')
    plt.xlabel('Mean Price (Actual and Predicted, cents/kWh)')
    plt.ylabel('Difference (Predicted - Actual, cents/kWh)')
    plt.grid(True)
    plt.show()

    return markdown
