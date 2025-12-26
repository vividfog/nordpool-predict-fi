from datetime import datetime, timedelta, timezone
from pathlib import Path

import json
import pandas as pd
import pytest
import requests_mock

from util import sahkotin


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sahkotin"


def load_prices_fixture():
    """Load cached Sähkötin prices response."""
    with open(FIXTURES_DIR / "prices.json") as f:
        return json.load(f)


def test_update_spot_merges_latest_prices(monkeypatch):
    base_ts = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    price_df = pd.DataFrame(
        {
            "timestamp": [
                base_ts + timedelta(hours=offset)
                for offset in range(3)
            ],
            "Price_cpkWh": [4.5, 5.0, 6.0],
        }
    )

    def fake_fetch(start, end):
        return price_df

    monkeypatch.setattr(sahkotin, "fetch_electricity_price_data", fake_fetch)

    df = pd.DataFrame({"timestamp": pd.to_datetime([base_ts + timedelta(hours=i) for i in range(3)], utc=True)})

    result = sahkotin.update_spot(df.copy())

    assert list(result["Price_cpkWh"]) == [4.5, 5.0, 6.0]
    assert not any(col.endswith(("_x", "_y")) for col in result.columns)


# --- Integration tests with cached API responses ---


class TestFetchElectricityPriceData:
    """Tests for fetch_electricity_price_data function using cached responses."""

    def test_parses_api_response_correctly(self):
        """Verify API response is parsed into expected DataFrame structure."""
        cached = load_prices_fixture()

        # Mock the requests.get call
        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, json=cached)

            result = sahkotin.fetch_electricity_price_data(
                "2025-12-26T00:00:00.000Z",
                "2025-12-27T23:59:59.000Z"
            )

        # Verify structure
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == ["timestamp", "Price_cpkWh"]
        assert len(result) == 23  # 23 hours in the fixture

        # Verify value conversion (value / 10)
        assert result["Price_cpkWh"].iloc[0] == pytest.approx(0.2093, rel=1e-3)
        assert result["Price_cpkWh"].iloc[-1] == pytest.approx(0.3627, rel=1e-3)

    def test_handles_empty_response(self):
        """Verify empty API response returns empty DataFrame with correct columns."""
        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, json={"prices": []})

            result = sahkotin.fetch_electricity_price_data(
                "2025-12-26T00:00:00.000Z",
                "2025-12-27T23:59:59.000Z"
            )

        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == ["timestamp", "Price_cpkWh"]
        assert len(result) == 0


class TestUpdateSpot:
    """Tests for update_spot function using cached responses."""

    def test_updates_dataframe_with_prices(self):
        """Verify update_spot merges prices into existing DataFrame."""
        cached = load_prices_fixture()

        # Create test DataFrame
        ts = pd.to_datetime("2025-12-26T10:00:00Z", utc=True)
        df = pd.DataFrame({"timestamp": [ts], "dummy": [42]})

        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, json=cached)

            result = sahkotin.update_spot(df.copy())

        # Verify price was merged
        assert "Price_cpkWh" in result.columns
        assert result["Price_cpkWh"].iloc[0] == pytest.approx(0.3228, rel=1e-3)
        assert "dummy" in result.columns  # Original column preserved
        assert result["dummy"].iloc[0] == 42

    def test_handles_prices_at_dataframe_boundaries(self):
        """Verify prices are handled correctly at DataFrame boundaries."""
        cached = load_prices_fixture()

        # Create DataFrame with timestamps within the price range
        ts1 = pd.to_datetime("2025-12-26T05:00:00Z", utc=True)  # Within prices
        ts2 = pd.to_datetime("2025-12-26T10:00:00Z", utc=True)  # Within prices
        ts3 = pd.to_datetime("2025-12-26T15:00:00Z", utc=True)  # Within prices
        df = pd.DataFrame({"timestamp": [ts1, ts2, ts3]})

        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, json=cached)

            result = sahkotin.update_spot(df.copy())

        # All timestamps should have prices
        assert pd.notna(result.loc[0, "Price_cpkWh"])
        assert pd.notna(result.loc[1, "Price_cpkWh"])
        assert pd.notna(result.loc[2, "Price_cpkWh"])


class TestSahkotinTomorrow:
    """Tests for sahkotin_tomorrow function using cached responses."""

    def test_tomorrow_resamples_to_hourly(self):
        """Verify tomorrow's prices are resampled to hourly."""
        cached = load_prices_fixture()

        # Filter to a single day for testing
        single_day = {"prices": [p for p in cached["prices"] if "2025-12-26" in p["date"]]}

        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, json=single_day)

            hourly_df, daily_avg, start_dt = sahkotin.sahkotin_tomorrow()

        # Should be resampled to hourly (around 23-24 entries depending on data)
        assert 22 <= len(hourly_df) <= 24
        assert daily_avg is not None
        assert start_dt is not None

    def test_daily_average_calculated_correctly(self):
        """Verify daily average is the mean of hourly prices."""
        cached = load_prices_fixture()

        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, json=cached)

            hourly_df, daily_avg, _ = sahkotin.sahkotin_tomorrow()

        expected_avg = hourly_df["Price_cpkWh"].mean()
        assert abs(daily_avg - expected_avg) < 0.001
