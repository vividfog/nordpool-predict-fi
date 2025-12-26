from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from lxml import etree

from util import fmi


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "fmi"


def load_forecast_xml():
    """Load cached FMI forecast XML response."""
    with open(FIXTURES_DIR / "forecast_temperature.xml", "rb") as f:
        return f.read()


@pytest.mark.parametrize(
    "update_func,prefix,forecast_param,history_param,expected",
    [
        (fmi.update_wind_speed, "ws_", "windspeedms", "WS_PT1H_AVG", [5.0, 6.0]),
        (fmi.update_temperature, "t_", "temperature", "TA_PT1H_AVG", [15.0, 16.0]),
    ],
)
def test_fmi_station_updates_merge_forecast_and_history(
    monkeypatch, update_func, prefix, forecast_param, history_param, expected
):
    base_ts = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    timestamps = [base_ts, base_ts + timedelta(hours=1)]

    df = pd.DataFrame({"timestamp": timestamps, f"{prefix}101": [None, None]})

    call_log = {"forecast": [], "history": []}

    def fake_get_forecast(fmisid, start_date, parameters, end_date=None):
        assert parameters == [forecast_param]
        call_log["forecast"].append((fmisid, start_date, end_date))
        return pd.DataFrame(
            {
                "timestamp": [
                    (base_ts + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    for offset in (0, 1)
                ],
                forecast_param: expected,
            }
        )

    def fake_get_history(fmisid, start_date, parameters, end_date=None):
        assert parameters == [history_param]
        call_log["history"].append((fmisid, start_date, end_date))
        # Provide a distinct set of values to ensure forecast data is preferred where overlapping
        history_values = [expected[0] - 0.5, expected[1] - 0.5]
        return pd.DataFrame(
            {
                "timestamp": [
                    (base_ts + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    for offset in (0, 1)
                ],
                history_param: history_values,
            }
        )

    monkeypatch.setattr(fmi, "get_forecast", fake_get_forecast)
    monkeypatch.setattr(fmi, "get_history", fake_get_history)

    result = update_func(df.copy())

    column_name = f"{prefix}101"
    assert list(result[column_name]) == expected
    # Ensure merge artefacts are cleaned up
    assert not any(col.endswith(("_x", "_y")) for col in result.columns)
    # Ensure the stubbed helpers were called exactly once per station
    assert len(call_log["forecast"]) == 1
    assert len(call_log["history"]) == 1


# --- Unit tests for XML parsing ---


def test_parse_fmi_xml_temperature_values():
    """Verify XML is parsed correctly for temperature."""
    cached_xml = load_forecast_xml()
    root = etree.fromstring(cached_xml)

    # Count elements
    elements = root.findall('.//BsWfs:BsWfsElement', namespaces=root.nsmap)
    assert len(elements) == 24

    # Verify first and last values
    first = elements[0]
    timestamp = first.find('.//BsWfs:Time', namespaces=root.nsmap).text
    value = float(first.find('.//BsWfs:ParameterValue', namespaces=root.nsmap).text)
    assert timestamp == "2025-12-26T00:00:00Z"
    assert value == 2.33


def test_fmi_xml_pivot_to_wide_format():
    """Verify XML data can be pivoted to wide format."""
    cached_xml = load_forecast_xml()
    root = etree.fromstring(cached_xml)

    data = []
    for member in root.findall('.//BsWfs:BsWfsElement', namespaces=root.nsmap):
        timestamp = member.find('.//BsWfs:Time', namespaces=root.nsmap).text
        parameter = member.find('.//BsWfs:ParameterName', namespaces=root.nsmap).text
        value = member.find('.//BsWfs:ParameterValue', namespaces=root.nsmap).text
        data.append({'timestamp': timestamp, 'Parameter': parameter, 'Value': value})

    df = pd.DataFrame(data)
    df['Value'] = pd.to_numeric(df['Value'], errors='coerce')
    df_pivot = df.pivot(index='timestamp', columns='Parameter', values='Value').reset_index()

    assert "temperature" in df_pivot.columns
    assert len(df_pivot) == 24
    assert df_pivot["temperature"].iloc[0] == 2.33
    assert df_pivot["temperature"].iloc[14] == 5.65


class TestGetForecast:
    """Tests for get_forecast function."""

    def test_parses_fmi_xml_response(self, monkeypatch):
        """Verify get_forecast parses XML into correct DataFrame structure."""
        cached_xml = load_forecast_xml()

        class MockResponse:
            status_code = 200
            content = cached_xml

            def raise_for_status(self):
                pass

        monkeypatch.setattr(fmi.requests, "get", lambda *args, **kwargs: MockResponse())

        result = fmi.get_forecast(101004, "2025-12-26", ["temperature"])

        # Verify structure
        assert isinstance(result, pd.DataFrame)
        assert "timestamp" in result.columns
        assert "temperature" in result.columns
        assert len(result) == 24  # 24 hours in the fixture

        # Verify temperature values are parsed correctly
        assert result["temperature"].iloc[0] == 2.33
        assert result["temperature"].iloc[14] == 5.65  # Peak at 14:00
        assert result["temperature"].iloc[-1] == 3.41

    def test_handles_empty_response(self, monkeypatch):
        """Verify empty XML response is handled gracefully."""
        empty_xml = b'''<?xml version="1.0"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"
    xmlns:BsWfs="http://www.opengis.net/wfs/2.0">
</wfs:FeatureCollection>'''

        class MockResponse:
            status_code = 200
            content = empty_xml

            def raise_for_status(self):
                pass

        monkeypatch.setattr(fmi.requests, "get", lambda *args, **kwargs: MockResponse())

        # The function should handle this by exiting - test that it doesn't crash
        try:
            fmi.get_forecast(999999, "2025-12-26", ["temperature"])
        except SystemExit:
            pass  # Expected behavior


class TestGetHistory:
    """Tests for get_history function."""

    def test_get_history_function_exists(self):
        """Verify get_history function exists and is callable."""
        assert hasattr(fmi, "get_history")
        assert callable(fmi.get_history)


class TestUpdateFunctions:
    """Integration tests for update_wind_speed and update_temperature."""

    def test_update_functions_exist(self):
        """Verify update functions exist."""
        assert hasattr(fmi, "update_temperature")
        assert hasattr(fmi, "update_wind_speed")
        assert callable(fmi.update_temperature)
        assert callable(fmi.update_wind_speed)
