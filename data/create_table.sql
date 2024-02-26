CREATE TABLE prediction (
    timestamp TIMESTAMP PRIMARY KEY,
    "Price_cpkWh" FLOAT,
    "Temp_dC" FLOAT,
    "Wind_mps" FLOAT,
    "WindPowerMW" FLOAT,
    "WindPowerCapacityMW" FLOAT,
    "PricePredict_cpkWh" FLOAT,
    "NuclearPowerMW" FLOAT
);