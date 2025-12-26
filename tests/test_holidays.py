"""
Tests for util/holidays.py - Finnish holiday data processing.
"""
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import pytz

from util import holidays

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "holidays"


def load_holidays_fixture():
    """Load cached Finnish holidays response."""
    with open(FIXTURES_DIR / "finnish_holidays.json") as f:
        return json.load(f)


# --- Unit tests for holiday parsing ---


def test_holiday_json_structure():
    """Verify the holiday JSON fixture has expected structure."""
    cached = load_holidays_fixture()

    assert len(cached) > 0
    holiday = cached[0]
    assert "date" in holiday
    assert "name" in holiday
    assert "kind_id" in holiday
    assert "kind" in holiday


def test_holiday_json_to_dataframe_conversion():
    """Verify holiday JSON can be converted to DataFrame."""
    cached = load_holidays_fixture()

    # Simulate the conversion logic from _fetch_holidays
    helsinki_tz = pytz.timezone('Europe/Helsinki')
    holiday_map = {}

    for item in cached:
        kind_id_int = int(item.get("kind_id", 0))
        local_date = pd.to_datetime(item["date"])
        local_midnight = helsinki_tz.localize(local_date)
        day_hours_local = pd.date_range(
            start=local_midnight,
            end=local_midnight + pd.Timedelta(hours=23),
            freq='h'
        )
        day_hours_utc = day_hours_local.tz_convert(pytz.UTC)
        for hour_utc in day_hours_utc:
            current_kind = holiday_map.get(hour_utc, -1)
            if kind_id_int > current_kind:
                holiday_map[hour_utc] = kind_id_int

    holiday_df = pd.DataFrame(list(holiday_map.items()), columns=['timestamp', 'holiday_fetched'])
    holiday_df['timestamp'] = pd.to_datetime(holiday_df['timestamp'], utc=True)
    holiday_df['holiday_fetched'] = holiday_df['holiday_fetched'].astype(int)

    # Verify structure
    assert isinstance(holiday_df, pd.DataFrame)
    assert list(holiday_df.columns) == ["timestamp", "holiday_fetched"]
    assert holiday_df["holiday_fetched"].dtype in [np.int64, int]
    assert len(holiday_df) > 0


def test_christmas_day_2024_is_holiday():
    """Verify Christmas Day 2024 is identified as a holiday."""
    cached = load_holidays_fixture()

    # Simulate the conversion logic
    helsinki_tz = pytz.timezone('Europe/Helsinki')
    holiday_map = {}

    for item in cached:
        kind_id_int = int(item.get("kind_id", 0))
        local_date = pd.to_datetime(item["date"])
        local_midnight = helsinki_tz.localize(local_date)
        day_hours_local = pd.date_range(
            start=local_midnight,
            end=local_midnight + pd.Timedelta(hours=23),
            freq='h'
        )
        day_hours_utc = day_hours_local.tz_convert(pytz.UTC)
        for hour_utc in day_hours_utc:
            current_kind = holiday_map.get(hour_utc, -1)
            if kind_id_int > current_kind:
                holiday_map[hour_utc] = kind_id_int

    # Check if Christmas Day 2024 is in the map
    christmas_utc = helsinki_tz.localize(datetime(2024, 12, 25, 12, 0, 0)).astimezone(pytz.UTC)
    assert christmas_utc in holiday_map
    assert holiday_map[christmas_utc] >= 1  # Public holiday


def test_regular_day_not_in_holiday_map():
    """Verify a regular day (not in fixture) is not a holiday."""
    cached = load_holidays_fixture()

    # Simulate the conversion logic
    helsinki_tz = pytz.timezone('Europe/Helsinki')
    holiday_map = {}

    for item in cached:
        kind_id_int = int(item.get("kind_id", 0))
        local_date = pd.to_datetime(item["date"])
        local_midnight = helsinki_tz.localize(local_date)
        day_hours_local = pd.date_range(
            start=local_midnight,
            end=local_midnight + pd.Timedelta(hours=23),
            freq='h'
        )
        day_hours_utc = day_hours_local.tz_convert(pytz.UTC)
        for hour_utc in day_hours_utc:
            current_kind = holiday_map.get(hour_utc, -1)
            if kind_id_int > current_kind:
                holiday_map[hour_utc] = kind_id_int

    # December 27, 2024 is not in the holiday fixture (only 24-26 are)
    dec27_utc = helsinki_tz.localize(datetime(2024, 12, 27, 12, 0, 0)).astimezone(pytz.UTC)
    assert dec27_utc not in holiday_map


class TestUpdateHolidays:
    """Tests for update_holidays function."""

    def test_adds_holiday_column_to_dataframe(self, monkeypatch):
        """Verify update_holidays adds holiday column."""
        cached = load_holidays_fixture()

        class MockResponse:
            status_code = 200
            _json = cached

            def json(self):
                return self._json

            def raise_for_status(self):
                pass

        monkeypatch.setattr(holidays.requests, "get", lambda *args, **kwargs: MockResponse())

        # Clear cache
        holidays._holiday_cache = None

        try:
            # Create test DataFrame around Christmas 2024
            helsinki_tz = pytz.timezone("Europe/Helsinki")
            ts = helsinki_tz.localize(datetime(2024, 12, 25, 12, 0, 0))
            df = pd.DataFrame({"timestamp": [ts]})

            result = holidays.update_holidays(df.copy())

            # Verify holiday column was added
            assert "holiday" in result.columns
            assert result["holiday"].dtype in [np.int64, int]
        finally:
            holidays._holiday_cache = None

    def test_preserves_existing_holiday_values(self, monkeypatch):
        """Verify existing non-NaN holiday values are preserved."""
        cached = load_holidays_fixture()

        class MockResponse:
            status_code = 200
            _json = cached

            def json(self):
                return self._json

            def raise_for_status(self):
                pass

        monkeypatch.setattr(holidays.requests, "get", lambda *args, **kwargs: MockResponse())

        # Clear cache
        holidays._holiday_cache = None

        try:
            # Create test DataFrame with existing holiday values
            helsinki_tz = pytz.timezone("Europe/Helsinki")
            ts1 = helsinki_tz.localize(datetime(2024, 12, 25, 12, 0, 0))  # Christmas
            ts2 = helsinki_tz.localize(datetime(2024, 12, 26, 12, 0, 0))  # Second Day of Christmas

            df = pd.DataFrame({
                "timestamp": [ts1, ts2],
                "holiday": [99.0, np.nan]  # Existing value for first row
            })

            result = holidays.update_holidays(df.copy())

            # First row should preserve existing value (99)
            assert result["holiday"].iloc[0] == 99
            # Second row should be filled from API (1 for public holiday)
            assert result["holiday"].iloc[1] >= 1
        finally:
            holidays._holiday_cache = None

    def test_handles_missing_timestamp_column(self, monkeypatch):
        """Verify error when timestamp column is missing."""
        class MockResponse:
            status_code = 200
            _json = []

            def json(self):
                return self._json

            def raise_for_status(self):
                pass

        monkeypatch.setattr(holidays.requests, "get", lambda *args, **kwargs: MockResponse())

        df = pd.DataFrame({"dummy": [1, 2, 3]})

        with pytest.raises(SystemExit):
            holidays.update_holidays(df.copy())

    def test_all_day_timestamps_covered(self, monkeypatch):
        """Verify holiday mapping covers full 24-hour period."""
        cached = load_holidays_fixture()

        class MockResponse:
            status_code = 200
            _json = cached

            def json(self):
                return self._json

            def raise_for_status(self):
                pass

        monkeypatch.setattr(holidays.requests, "get", lambda *args, **kwargs: MockResponse())

        # Clear cache
        holidays._holiday_cache = None

        try:
            # Create DataFrame spanning 24 hours of Christmas Day
            helsinki_tz = pytz.timezone("Europe/Helsinki")
            start = helsinki_tz.localize(datetime(2024, 12, 25, 0, 0, 0))
            end = helsinki_tz.localize(datetime(2024, 12, 25, 23, 0, 0))
            timestamps = pd.date_range(start=start, end=end, freq="h", tz="Europe/Helsinki")
            df = pd.DataFrame({"timestamp": timestamps})

            result = holidays.update_holidays(df.copy())

            # All 24 hours should have the same holiday value
            assert result["holiday"].nunique() == 1
            assert result["holiday"].iloc[0] >= 1
        finally:
            holidays._holiday_cache = None
