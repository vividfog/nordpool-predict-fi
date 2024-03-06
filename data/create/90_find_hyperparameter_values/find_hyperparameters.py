"""
USAGE: python find_hyperparameters.py path_to_your_data.csv

This script takes in a csv file containing a dataset and applies GridSearchCV using RandomForestRegressor.
It then outputs the best hyperparameters for the model based on the data.

The script requires a path to a csv file as a command-line argument.

Example:
    $ python find_hyperparameters.py dataset.csv

Arguments:
    path_to_your_data.csv: The path to the csv file that contains the dataset to be used.

Returns:
    The best parameters for the RandomForestRegressor model and their corresponding scores.

"""

import numpy as np
import pandas as pd
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, make_scorer, r2_score
import sys

# Define RMSE scorer for use in GridSearchCV
def rmse(y_true, y_pred):
    return np.sqrt(mean_squared_error(y_true, y_pred))

rmse_scorer = make_scorer(rmse, greater_is_better=False)

# Check if the user has provided a command-line argument
if len(sys.argv) != 2:
    print('Usage: python find_hyperparameters.py path_to_your_data.csv')
    sys.exit()

# Load the dataset
data_path = sys.argv[1]
data = pd.read_csv(data_path)

# Preprocess the dataset
data['timestamp'] = pd.to_datetime(data['timestamp'])
data['MonthNumber'] = data['timestamp'].dt.month
data['WeekdayNumber'] = data['timestamp'].dt.weekday
data['HourNumber'] = data['timestamp'].dt.hour
data.drop(columns=['WindPowerCapacityMW', 'PricePredict_cpkWh', 'timestamp'], inplace=True)
data = data.dropna()

# Select features and target variable
features = ['MonthNumber', 'WeekdayNumber', 'HourNumber', 'ws_101256', 'ws_101267', 'ws_101673', 'ws_101846', 't_101118', 't_101339', 't_101786', 't_100968']
X = data[features]
y = data['Price_cpkWh']

# Define a grid of hyperparameters for tuning
param_grid = {
    'n_estimators': [50, 100, 150, 200],
    'max_depth': [None, 10, 20, 30],
    'min_samples_split': [2, 4, 6],
    'min_samples_leaf': [1, 2, 4],
}

# Initialize and perform the grid search
grid_search = GridSearchCV(RandomForestRegressor(random_state=42), param_grid, cv=5,
                           scoring={'MAE': 'neg_mean_absolute_error', 'MSE': 'neg_mean_squared_error', 'RMSE': rmse_scorer, 'R2': 'r2'},
                           refit='MAE', return_train_score=True, verbose=3, n_jobs=1)
grid_search.fit(X, y)

# Output the best parameters and their corresponding scores
print("Best parameters:", grid_search.best_params_)
best_index = grid_search.best_index_
print("Best MAE (validation):", -grid_search.cv_results_['mean_test_MAE'][best_index])
print("Best MSE (validation):", -grid_search.cv_results_['mean_test_MSE'][best_index])
print("Best RMSE (validation):", -grid_search.cv_results_['mean_test_RMSE'][best_index])
print("Best R^2 (validation):", grid_search.cv_results_['mean_test_R2'][best_index])
