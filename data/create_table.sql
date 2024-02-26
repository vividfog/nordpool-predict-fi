CREATE TABLE prediction (
    timestamp TIMESTAMP PRIMARY KEY,
    "Price [c/kWh]" FLOAT,
    "Temp [°C]" FLOAT,
    "Wind [m/s]" FLOAT,
    "Wind Power [MWh]" FLOAT,
    "Wind Power Capacity [MWh]" FLOAT,
    "PricePredict [c/kWh]" FLOAT,
    "NuclearPowerMW" FLOAT
);