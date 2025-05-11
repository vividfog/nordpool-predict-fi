-- archive_schema.sql

BEGIN TRANSACTION;

-- 1. Each snapshot run
CREATE TABLE IF NOT EXISTS prediction_runs (
  run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  run_datetime  TEXT    NOT NULL              -- ISO8601 UTC when snapshot was taken
);

-- 2. All forecasts + actuals for each run
CREATE TABLE IF NOT EXISTS archived_predictions (
  archive_id            INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id                INTEGER NOT NULL,
  timestamp             TEXT    NOT NULL,     -- ISO8601 UTC of the forecast hour
                                              /* normalized via normalize_timestamp */
  PricePredict_cpkWh    REAL    NOT NULL,
  Price_cpkWh           REAL,                 -- NULL until actual arrives
  WindPowerCapacityMW   REAL,
  NuclearPowerMW        REAL,
  ImportCapacityMW      REAL,
  WindPowerMW           REAL,
  holiday               INTEGER,
  sum_irradiance        REAL,
  mean_irradiance       REAL,
  std_irradiance        REAL,
  min_irradiance        REAL,
  max_irradiance        REAL,
  SE1_FI                INTEGER,
  SE3_FI                INTEGER,
  EE_FI                 INTEGER,
  -- Weather station wind speed columns
  ws_101256             REAL,
  ws_101267             REAL,
  ws_101673             REAL,
  ws_101846             REAL,
  ws_101784             REAL,
  ws_101661             REAL,
  ws_101783             REAL,
  ws_101464             REAL,
  ws_101481             REAL,
  ws_101785             REAL,
  ws_101794             REAL,
  ws_101660             REAL,
  ws_101268             REAL,
  ws_101485             REAL,
  ws_101462             REAL,
  ws_101061             REAL,
  ws_101840             REAL,
  ws_100932             REAL,
  ws_100908             REAL,
  ws_101851             REAL,
  -- Weather station temperature columns
  t_101784              REAL,
  t_101661              REAL,
  t_101783              REAL,
  t_101464              REAL,
  t_101481              REAL,
  t_101785              REAL,
  t_101794              REAL,
  t_101660              REAL,
  t_101268              REAL,
  t_101485              REAL,
  t_101462              REAL,
  t_101061              REAL,
  t_101840              REAL,
  t_100932              REAL,
  t_100908              REAL,
  t_101846              REAL,
  t_101256              REAL,
  t_101673              REAL,
  t_101267              REAL,
  t_101851              REAL,
  -- EU wind speed columns
  eu_ws_EE01            REAL,
  eu_ws_EE02            REAL,
  eu_ws_DK01            REAL,
  eu_ws_DK02            REAL,
  eu_ws_DE01            REAL,
  eu_ws_DE02            REAL,
  eu_ws_SE01            REAL,
  eu_ws_SE02            REAL,
  eu_ws_SE03            REAL,
  FOREIGN KEY(run_id) REFERENCES prediction_runs(run_id),
  UNIQUE(run_id, timestamp)
);

COMMIT;
