# filename: train_and_save_model.py
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import pandas as pd
import joblib  # Import joblib for model persistence

# Load the preprocessed dataset
df = pd.read_csv("preprocessed_electricity_prices_dataset.csv")

# Define the features and target variable
X = df[['Temp [°C]', 'Wind [m/s]', 'hour', 'day_of_week', 'month']]
y = df['Price [c/kWh]']

# Split the dataset into training and testing sets (80% train, 20% test)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Initialize the Random Forest Regressor
rf = RandomForestRegressor(n_estimators=150, max_depth=15, min_samples_split=4, min_samples_leaf=2, max_features='sqrt', random_state=42)

# Train the model
rf.fit(X_train, y_train)

# Save the trained model to a file
joblib.dump(rf, 'electricity_price_rf_model.joblib')

# No need to perform predictions here, as the model evaluation will be done using the loaded model in the second script
