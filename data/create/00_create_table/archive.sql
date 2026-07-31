-- archive.sql
-- Bootstrap schema. util.archive.ensure_archive_schema extends
-- archived_predictions with every supported prediction column at runtime.

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS prediction_runs (
  run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  run_datetime   TEXT    NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  columns_json   TEXT    NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS archived_predictions (
  archive_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id              INTEGER NOT NULL,
  timestamp           TEXT    NOT NULL,
  PricePredict_cpkWh  REAL    NOT NULL,
  Price_cpkWh         REAL,
  FOREIGN KEY(run_id) REFERENCES prediction_runs(run_id),
  UNIQUE(run_id, timestamp)
);

-- Actual prices belong to timestamps, not individual forecast runs.
CREATE TABLE IF NOT EXISTS actual_prices (
  timestamp    TEXT PRIMARY KEY,
  Price_cpkWh  REAL NOT NULL,
  updated_at   TEXT NOT NULL,
  source       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS archive_schema_migrations (
  version     INTEGER PRIMARY KEY,
  applied_at  TEXT NOT NULL
);

COMMIT;
