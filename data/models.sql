CREATE TABLE IF NOT EXISTS models (
    training_id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_timestamp DATETIME NOT NULL,
    MAE REAL NOT NULL,
    MSE REAL NOT NULL,
    R2 REAL NOT NULL,
    samples_MAE REAL NOT NULL,
    samples_MSE REAL NOT NULL,
    samples_R2 REAL NOT NULL,
    model_path TEXT NOT NULL
);
