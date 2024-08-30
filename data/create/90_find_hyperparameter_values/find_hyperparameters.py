"""
USAGE: python find_hyperparameters.py path_to_your_dump.csv

This script takes in a csv file containing a dataset and applies GridSearchCV using RandomForestRegressor.
It then outputs the best hyperparameters for the model based on the data.

The script requires a path to a dump.csv file as a command-line argument.

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
data_path = sys.argv[1]  # Use the provided command-line argument for the data path
data = pd.read_csv(data_path)

# Preprocess the dataset
data['timestamp'] = pd.to_datetime(data['timestamp'], utc=True)
data['MonthNumber'] = data['timestamp'].dt.month
data['WeekdayNumber'] = data['timestamp'].dt.weekday
data['HourNumber'] = data['timestamp'].dt.hour

# Outlier removal using the IQR method
Q1 = data['Price_cpkWh'].quantile(0.25)
Q3 = data['Price_cpkWh'].quantile(0.75)
IQR = Q3 - Q1

# Adjust the multiplier if necessary, e.g., 2.5 as in `train.py`
min_threshold = Q1 - 2.5 * IQR
max_threshold = Q3 + 2.5 * IQR
data_filtered = data[(data['Price_cpkWh'] >= min_threshold) & (data['Price_cpkWh'] <= max_threshold)]

# Drop irrelevant columns after filtering
data_filtered.drop(columns=['WindPowerCapacityMW', 'PricePredict_cpkWh', 'timestamp'], inplace=True)

# Select features and target variable
features = [
    'MonthNumber', 'WeekdayNumber', 'HourNumber', 
    'ws_101256', 'ws_101267', 'ws_101673', 'ws_101846', 
    't_101118', 't_101339', 't_101786', 't_100968', 
    'NuclearPowerMW', 'ImportCapacityMW'
]

X = data_filtered[features]
y = data_filtered['Price_cpkWh']

# Split the data into training and testing sets (80/20 split)
X_train, X_test, y_train, y_test = train_test_split(
    X, 
    y, 
    test_size=0.2, 
    random_state=42
    )

# Define a grid of hyperparameters for tuning
# param_grid = {
#     'n_estimators': [400, 500, 600],
#     'max_depth': [30, 35, 40, None],
#     'min_samples_split': [2, 3],
#     'min_samples_leaf': [1, 2],
#     'max_features': [0.4, 0.5, 0.6],
#     'bootstrap': [False],
#     'criterion': ['squared_error', 'absolute_error']
# }

# Searching from higher values too
param_grid = {
    'n_estimators': [600, 700, 800],  # Increase beyond 600 to explore further improvements
    'max_depth': [40, 45, None],      # Expand to deeper trees, including unrestricted depth
    'min_samples_split': [2, 3],      # Keep the most promising lower values
    'min_samples_leaf': [1, 2],       # Continue focusing on low values
    'max_features': [0.45, 0.5, 0.55],# Fine-tune around the promising 0.5 value
    'bootstrap': [False],             # Continue with no bootstrapping as it performed better
    'criterion': ['squared_error', 'absolute_error']  # Test both MSE and MAE criteria
}

# Initialize and perform the grid search on the training set
grid_search = GridSearchCV(
    RandomForestRegressor(random_state=42), 
    param_grid, 
    cv=7,
    scoring={'MAE': 'neg_mean_absolute_error', 'MSE': 'neg_mean_squared_error', 'RMSE': rmse_scorer, 'R2': 'r2'},
    refit='MAE', 
    return_train_score=True, 
    verbose=3, 
    n_jobs=-1
)

grid_search.fit(X_train, y_train)

# After completion, output the best parameters and their corresponding scores
print("Best parameters:", grid_search.best_params_)
best_index = grid_search.best_index_
print("Best MAE (validation):", -grid_search.cv_results_['mean_test_MAE'][best_index])
print("Best MSE (validation):", -grid_search.cv_results_['mean_test_MSE'][best_index])
print("Best RMSE (validation):", -grid_search.cv_results_['mean_test_RMSE'][best_index])
print("Best R^2 (validation):", grid_search.cv_results_['mean_test_R2'][best_index])

# Optionally, evaluate the best model on the test set
best_model = grid_search.best_estimator_
y_pred = best_model.predict(X_test)
test_mse = mean_squared_error(y_test, y_pred)
test_rmse = rmse(y_test, y_pred)
test_r2 = r2_score(y_test, y_pred)

print("Test MSE:", test_mse)
print("Test RMSE:", test_rmse)
print("Test R^2:", test_r2)
