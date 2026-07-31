import json
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from util.archive import (
    ARCHIVE_SCHEMA_VERSION,
    backup_archive_database,
    compute_error,
    get_predictions,
    insert_snapshot,
    is_true_prediction,
    migrate_archive_database,
)


def _snapshot():
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2026-07-01T00:00:00Z", periods=2, freq="15min"
            ),
            "PricePredict_cpkWh": [4.0, 4.5],
            "Price_cpkWh": [3.5, None],
            "WindPowerMW": [2000.0, 2100.0],
            "new_model_feature": [1.0, 2.0],
        }
    )


def _create_prediction_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE prediction (
                timestamp TEXT PRIMARY KEY,
                PricePredict_cpkWh REAL,
                Price_cpkWh REAL,
                WindPowerMW REAL,
                hydro_reservoir_percent REAL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO prediction VALUES (?, ?, ?, ?, ?)
            """,
            ("2026-07-01T00:00:00+00:00", 4.0, 3.25, 2000.0, 62.0),
        )


def _create_legacy_archive(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE prediction_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_datetime TEXT NOT NULL
            );
            CREATE TABLE archived_predictions (
                archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                PricePredict_cpkWh REAL NOT NULL,
                Price_cpkWh REAL,
                UNIQUE(run_id, timestamp)
            );
            INSERT INTO prediction_runs (run_datetime)
            VALUES ('2026-06-30T10:00:00+00:00');
            INSERT INTO archived_predictions
                (run_id, timestamp, PricePredict_cpkWh, Price_cpkWh)
            VALUES (1, '2026-07-01T00:00:00+00:00', 4.0, NULL);
            """
        )


def test_insert_snapshot_extends_schema_and_records_manifest(tmp_path):
    archive_path = tmp_path / "archive.db"

    run_id = insert_snapshot(archive_path, _snapshot())

    assert run_id == 1
    with sqlite3.connect(archive_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(archived_predictions)")
        }
        assert "new_model_feature" in columns
        assert conn.execute("SELECT COUNT(*) FROM archived_predictions").fetchone()[0] == 2
        run = conn.execute(
            "SELECT schema_version, columns_json FROM prediction_runs"
        ).fetchone()
        assert run[0] == ARCHIVE_SCHEMA_VERSION
        assert json.loads(run[1]) == list(_snapshot().columns)
        actual = conn.execute(
            "SELECT Price_cpkWh, source FROM actual_prices"
        ).fetchone()
        assert actual == (3.5, "snapshot")


def test_insert_snapshot_rejects_duplicate_timestamps_atomically(tmp_path):
    archive_path = tmp_path / "archive.db"
    frame = _snapshot()
    frame.loc[1, "timestamp"] = frame.loc[0, "timestamp"]

    assert insert_snapshot(archive_path, frame) is None
    assert not archive_path.exists()


def test_insert_snapshot_rejects_unsupported_columns_without_dropping_them(tmp_path):
    archive_path = tmp_path / "archive.db"
    frame = _snapshot()
    frame["unsupported"] = [["nested"], ["values"]]

    assert insert_snapshot(archive_path, frame) is None
    assert not archive_path.exists()


def test_migration_is_idempotent_and_backfills_canonical_actuals(tmp_path):
    archive_path = tmp_path / "archive.db"
    prediction_path = tmp_path / "prediction.db"
    _create_legacy_archive(archive_path)
    _create_prediction_db(prediction_path)

    dry_run = migrate_archive_database(archive_path, prediction_path, dry_run=True)
    assert dry_run["rows_before"] == 1
    assert "hydro_reservoir_percent" in dry_run["missing_columns"]
    with sqlite3.connect(archive_path) as conn:
        assert "actual_prices" not in {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    first = migrate_archive_database(archive_path, prediction_path)
    second = migrate_archive_database(archive_path, prediction_path)

    assert first["rows_before"] == first["rows_after"] == 1
    assert "hydro_reservoir_percent" in first["added_columns"]
    assert second["added_columns"] == []
    assert second["rows_before"] == second["rows_after"] == 1
    with sqlite3.connect(archive_path) as conn:
        canonical = conn.execute(
            "SELECT Price_cpkWh, source FROM actual_prices"
        ).fetchone()
        legacy = conn.execute(
            "SELECT Price_cpkWh, hydro_reservoir_percent FROM archived_predictions"
        ).fetchone()
        assert canonical == (3.25, "prediction.db")
        assert legacy == (3.25, None)


def test_archive_queries_prefer_canonical_actual_price(tmp_path):
    archive_path = tmp_path / "archive.db"
    prediction_path = tmp_path / "prediction.db"
    _create_legacy_archive(archive_path)
    _create_prediction_db(prediction_path)
    migrate_archive_database(archive_path, prediction_path)
    with sqlite3.connect(archive_path) as conn:
        conn.execute("UPDATE archived_predictions SET Price_cpkWh = 99.0")

    timestamps = pd.DataFrame(
        {"timestamp": [pd.Timestamp("2026-07-01T00:00:00Z")]}
    )
    predictions = get_predictions(archive_path, timestamps)
    ranges = pd.DataFrame(
        {
            "start": [pd.Timestamp("2026-07-01T00:00:00Z")],
            "end": [pd.Timestamp("2026-07-01T00:00:00Z")],
        }
    )
    errors = compute_error(archive_path, ranges)

    assert predictions.iloc[0]["Price_cpkWh"] == 3.25
    assert errors.iloc[0]["mae"] == 0.75


def test_backup_archive_database_uses_sqlite_backup(tmp_path):
    archive_path = tmp_path / "archive.db"
    backup_path = tmp_path / "archive.backup.db"
    assert insert_snapshot(archive_path, _snapshot()) == 1

    result = backup_archive_database(archive_path, backup_path)

    assert result == backup_path
    with sqlite3.connect(backup_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM archived_predictions").fetchone()[0] == 2


def test_source_database_sync_updates_existing_snapshot_actual(tmp_path):
    archive_path = tmp_path / "archive.db"
    prediction_path = tmp_path / "prediction.db"
    _create_prediction_db(prediction_path)
    frame = _snapshot()
    frame["Price_cpkWh"] = None

    assert insert_snapshot(archive_path, frame, source_db_path=prediction_path) == 1

    with sqlite3.connect(archive_path) as conn:
        assert conn.execute(
            "SELECT Price_cpkWh FROM actual_prices WHERE timestamp = ?",
            ("2026-07-01T00:00:00+00:00",),
        ).fetchone()[0] == 3.25
        assert conn.execute(
            "SELECT Price_cpkWh FROM archived_predictions WHERE timestamp = ?",
            ("2026-07-01T00:00:00+00:00",),
        ).fetchone()[0] == 3.25


def test_run_timestamp_is_utc_aware(tmp_path):
    archive_path = tmp_path / "archive.db"
    assert insert_snapshot(archive_path, _snapshot()) == 1
    with sqlite3.connect(archive_path) as conn:
        value = conn.execute("SELECT run_datetime FROM prediction_runs").fetchone()[0]

    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def test_true_prediction_uses_local_delivery_date_and_publication_time():
    run_before_publication = "2026-07-01T10:59:00+00:00"  # 13:59 Helsinki
    run_after_publication = "2026-07-01T11:00:00+00:00"   # 14:00 Helsinki

    assert is_true_prediction(run_before_publication, "2026-07-01T20:45:00+00:00") is False
    assert is_true_prediction(run_before_publication, "2026-07-01T21:00:00+00:00") is True
    assert is_true_prediction(run_after_publication, "2026-07-02T20:45:00+00:00") is False
    assert is_true_prediction(run_after_publication, "2026-07-02T21:00:00+00:00") is True


def test_true_prediction_handles_dst_transition_as_local_calendar_date():
    run_after_publication = "2026-10-24T11:30:00+00:00"  # 14:30 Helsinki

    assert is_true_prediction(run_after_publication, "2026-10-25T21:45:00+00:00") is False
    assert is_true_prediction(run_after_publication, "2026-10-25T22:00:00+00:00") is True
