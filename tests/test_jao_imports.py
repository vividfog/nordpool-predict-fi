from datetime import datetime, timezone
from unittest.mock import mock_open

import pandas as pd
import pytest

from util import jao_imports


def test_calculate_capacity_sums_forward_fills_zero_totals():
    ts0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    ts1 = datetime(2025, 1, 1, 1, 0, tzinfo=timezone.utc)
    records = []
    for ts, values in [(ts0, [100, 200, 300]), (ts1, [0, 0, 0])]:
        for border, value in zip(["SE1_FI", "SE3_FI", "EE_FI"], values):
            records.append(
                {"dateTimeUtc": ts, "border": border, "CapacityMW": value}
            )
    df = pd.DataFrame(records)

    result = jao_imports.calculate_capacity_sums(df.copy())

    # First row total = 600, second should forward fill the previous non-zero value
    assert list(result["TotalCapacityMW"]) == [600, 600]
    assert list(result["SE1_FI"]) == [100, 0]
    assert list(result["SE3_FI"]) == [200, 0]
    assert list(result["EE_FI"]) == [300, 0]


def test_update_import_capacity_merges_borders(monkeypatch):
    base = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    fake_fetch_df = pd.DataFrame(
        {
            "dateTimeUtc": [
                base,
                base,
                base,
                base + pd.Timedelta(hours=1),
                base + pd.Timedelta(hours=1),
                base + pd.Timedelta(hours=1),
            ],
            "border": ["SE1_FI", "SE3_FI", "EE_FI"] * 2,
            "CapacityMW": [100, 200, 300, 120, 240, 360],
        }
    )

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
            return current if tz is None else current.astimezone(tz)

    monkeypatch.setattr(jao_imports, "fetch_transfer_capacity_data", lambda start, end: fake_fetch_df)
    monkeypatch.setattr(jao_imports, "datetime", FixedDatetime)

    real_open = open
    m_open = mock_open()

    def selective_open(path, mode="r", *args, **kwargs):
        if path == "deploy/import_capacity_daily_average.json":
            return m_open(path, mode, *args, **kwargs)
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(jao_imports, "open", selective_open, raising=False)

    df = pd.DataFrame(
        {
            "timestamp": [base, base + pd.Timedelta(hours=1)],
            "dummy": [1, 2],
            "ImportCapacityMW": [0, 0],
        }
    )

    result = jao_imports.update_import_capacity(df.copy(), write_daily_average=True)

    assert list(result["ImportCapacityMW"]) == [600, 720]
    assert list(result["SE1_FI"]) == [100, 120]
    assert list(result["SE3_FI"]) == [200, 240]
    assert list(result["EE_FI"]) == [300, 360]

    # ensure original dummy column preserved and JSON file attempted to write
    assert "dummy" in result.columns
    m_open.assert_called_once()


def test_update_import_capacity_skips_daily_average_export(monkeypatch):
    base = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    fake_fetch_df = pd.DataFrame(
        {
            "dateTimeUtc": [
                base,
                base,
                base,
            ],
            "border": ["SE1_FI", "SE3_FI", "EE_FI"],
            "CapacityMW": [100, 200, 300],
        }
    )

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
            return current if tz is None else current.astimezone(tz)

    monkeypatch.setattr(jao_imports, "fetch_transfer_capacity_data", lambda start, end: fake_fetch_df)
    monkeypatch.setattr(jao_imports, "datetime", FixedDatetime)

    real_open = open
    m_open = mock_open()

    def selective_open(path, mode="r", *args, **kwargs):
        if path == "deploy/import_capacity_daily_average.json":
            return m_open(path, mode, *args, **kwargs)
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(jao_imports, "open", selective_open, raising=False)

    df = pd.DataFrame(
        {
            "timestamp": [base],
            "dummy": [1],
            "ImportCapacityMW": [0],
        }
    )

    result = jao_imports.update_import_capacity(df.copy())

    assert list(result["ImportCapacityMW"]) == [600]
    assert "dummy" in result.columns
    m_open.assert_not_called()
