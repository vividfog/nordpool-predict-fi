-- Step 1: Start a transaction
BEGIN TRANSACTION;

-- Step 2: Create a new table with the constraint
CREATE TABLE prediction (
    timestamp TIMESTAMP PRIMARY KEY,
    "Price [c/kWh]" FLOAT,
    "Temp [°C]" FLOAT,
    "Wind [m/s]" FLOAT,
    "Wind Power [MWh]" FLOAT,
    "Wind Power Capacity [MWh]" FLOAT,
    "hour" INT,
    "day_of_week" INT,
    "month" INT,
    "PricePredict [c/kWh]" FLOAT
);

-- Step 6: Commit the transaction
COMMIT;
