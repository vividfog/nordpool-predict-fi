import importlib.util
import sqlite3
from pathlib import Path
from typing import Callable, Dict
import random

import pandas as pd


def load_manage_module():
    project_root = Path(__file__).resolve().parents[1]
    module_path = project_root / "data/create/10_weather_fetch_history/manage_fmi_station.py"
    spec = importlib.util.spec_from_file_location("manage_fmi_station", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


manage = load_manage_module()


def build_fake_fetch(data_map: Dict[int, pd.DataFrame]) -> Callable:
    def fake_fetch(fmisid: int, start_date: str, parameters, end_date: str = None):
        start_ts = pd.Timestamp(start_date).tz_localize("UTC")
        end_ts = pd.Timestamp(end_date or start_date).tz_localize("UTC") + pd.Timedelta(
            hours=23, minutes=59
        )
        df = data_map.get(fmisid)
        if df is None or df.empty:
            return pd.DataFrame(columns=["timestamp", *parameters])
        mask = (df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)
        subset = df.loc[mask].copy()
        if subset.empty:
            return pd.DataFrame(columns=["timestamp", *parameters])
        subset["timestamp"] = subset["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return subset[["timestamp", *parameters]].reset_index(drop=True)

    return fake_fetch


def create_prediction_db(tmp_path: Path, timestamps: pd.DatetimeIndex) -> Path:
    db_path = tmp_path / "prediction.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE prediction (timestamp TEXT PRIMARY KEY)")
    conn.executemany(
        "INSERT INTO prediction (timestamp) VALUES (?)",
        [(ts.isoformat(),) for ts in timestamps],
    )
    conn.commit()
    conn.close()
    return db_path


def fetch_prediction_values(db_path: Path, fmisid: int):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        f'SELECT t_{fmisid}, ws_{fmisid} FROM prediction ORDER BY timestamp'
    ).fetchall()
    conn.close()
    return rows


def test_prepare_plan_adds_columns_and_applies_updates(tmp_path):
    fmisid = 123456
    timestamps = pd.date_range("2025-01-01T00:00:00Z", periods=3, freq="h")
    db_path = create_prediction_db(tmp_path, timestamps)
    history = pd.DataFrame(
        {
            "timestamp": timestamps,
            "TA_PT1H_AVG": [1.0, 2.0, 3.0],
            "WS_PT1H_AVG": [4.0, 5.0, 6.0],
        }
    )
    manager = manage.StationBackfillManager(
        db_path,
        fetch_fn=build_fake_fetch({fmisid: history}),
        chunk_days=3,
    )
    plan = manager.prepare_plan(
        fmisid=fmisid,
        start=timestamps[0],
        end=timestamps[-1],
        ensure_columns=True,
    )

    assert plan.columns_added == {f"t_{fmisid}", f"ws_{fmisid}"}
    assert plan.has_updates()
    assert len(plan.updates) == 3
    assert plan.filled_counts[f"t_{fmisid}"] == 3
    assert plan.filled_counts[f"ws_{fmisid}"] == 3

    manager.apply_plan(plan)
    rows = fetch_prediction_values(db_path, fmisid)
    assert rows == [(1.0, 4.0), (2.0, 5.0), (3.0, 6.0)]


def test_prepare_plan_without_schema_warns(tmp_path):
    fmisid = 654321
    timestamps = pd.date_range("2025-02-01T00:00:00Z", periods=2, freq="h")
    db_path = create_prediction_db(tmp_path, timestamps)
    history = pd.DataFrame(
        {
            "timestamp": timestamps,
            "TA_PT1H_AVG": [7.0, 8.0],
            "WS_PT1H_AVG": [9.0, 10.0],
        }
    )

    manager = manage.StationBackfillManager(
        db_path,
        fetch_fn=build_fake_fetch({fmisid: history}),
        chunk_days=2,
    )
    plan = manager.prepare_plan(
        fmisid=fmisid,
        start=timestamps[0],
        end=timestamps[-1],
        ensure_columns=False,
    )

    assert plan.columns_added == set()
    assert plan.missing_before[f"t_{fmisid}"] == len(timestamps)
    assert plan.missing_before[f"ws_{fmisid}"] == len(timestamps)
    assert any("Schema is missing columns" in warning for warning in plan.warnings)


def test_apply_plan_respects_dry_run(tmp_path):
    fmisid = 777000
    timestamps = pd.date_range("2025-03-01T00:00:00Z", periods=1, freq="h")
    db_path = create_prediction_db(tmp_path, timestamps)
    history = pd.DataFrame(
        {
            "timestamp": timestamps,
            "TA_PT1H_AVG": [11.0],
            "WS_PT1H_AVG": [12.0],
        }
    )
    manager = manage.StationBackfillManager(
        db_path,
        fetch_fn=build_fake_fetch({fmisid: history}),
        chunk_days=1,
    )
    plan = manager.prepare_plan(
        fmisid=fmisid,
        start=timestamps[0],
        end=timestamps[-1],
        ensure_columns=True,
    )

    manager.apply_plan(plan, dry_run=True)
    rows = fetch_prediction_values(db_path, fmisid)
    assert rows == [(None, None)]


def test_prepare_plan_clips_future_end(tmp_path):
    fmisid = 888888
    start = pd.Timestamp("2025-10-09T00:00:00Z")
    requested_end = pd.Timestamp("2025-10-12T23:00:00Z")
    now = pd.Timestamp("2025-10-10T12:00:00Z")
    timestamps = pd.date_range(start, now, freq="h")
    db_path = create_prediction_db(tmp_path, timestamps)

    calls = []

    def fake_fetch(fmisid_arg: int, start_date: str, parameters, end_date: str = None):
        calls.append((start_date, end_date))
        history_index = pd.date_range(start, now, freq="h")
        df = pd.DataFrame(
            {
                "timestamp": history_index,
                "TA_PT1H_AVG": [1.0] * len(history_index),
                "WS_PT1H_AVG": [2.0] * len(history_index),
            }
        )
        mask = (df["timestamp"] >= pd.Timestamp(start_date).tz_localize("UTC")) & (
            df["timestamp"] <= pd.Timestamp(end_date).tz_localize("UTC")
            + pd.Timedelta(hours=23, minutes=59)
        )
        subset = df.loc[mask].copy()
        if subset.empty:
            return pd.DataFrame(columns=["timestamp", *parameters])
        subset["timestamp"] = subset["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return subset[["timestamp", *parameters]].reset_index(drop=True)

    manager = manage.StationBackfillManager(
        db_path,
        fetch_fn=fake_fetch,
        chunk_days=3,
        now_provider=lambda: now,
    )

    plan = manager.prepare_plan(
        fmisid=fmisid,
        start=start,
        end=requested_end,
        ensure_columns=True,
    )

    assert plan.range_end == now
    assert any("Clipped requested end" in warning for warning in plan.warnings)
    for _, end_date in calls:
        assert end_date is not None
        assert pd.Timestamp(end_date).tz_localize("UTC") <= now.normalize()


def test_determine_history_bounds_clamps_to_now(tmp_path):
    timestamps = pd.date_range("2025-10-01T00:00:00Z", periods=10, freq="h")
    db_path = create_prediction_db(tmp_path, timestamps)
    future_row = pd.Timestamp("2025-10-20T00:00:00Z")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO prediction (timestamp) VALUES (?)",
        (future_row.isoformat(),),
    )
    conn.commit()
    conn.close()

    now = pd.Timestamp("2025-10-05T12:00:00Z")
    earliest, latest = manage.determine_history_bounds(db_path, now)
    assert earliest == timestamps[0]
    assert latest == now.floor("h")


def test_sample_windows_within_range():
    earliest = pd.Timestamp("2025-01-01T00:00:00Z")
    latest = pd.Timestamp("2025-01-31T00:00:00Z")
    rng = random.Random(42)
    windows = manage.sample_windows(
        earliest,
        latest,
        pd.Timedelta(days=3),
        samples=5,
        rng=rng,
    )
    assert len(windows) == 5
    for start, end in windows:
        assert earliest <= start < end <= latest
        assert (end - start) == pd.Timedelta(days=3)
