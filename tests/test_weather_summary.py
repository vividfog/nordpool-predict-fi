import json

import pandas as pd

from util.weather_summary import (
    build_daily_weather,
    weather_symbol_condition,
    wind_power_level,
    write_daily_weather,
)


def test_maps_fmi_weather_symbols_to_ui_conditions():
    assert weather_symbol_condition(1) == "clear-day"
    assert weather_symbol_condition(2) == "partly-cloudy-day"
    assert weather_symbol_condition(32) == "rain"
    assert weather_symbol_condition(52) == "snow"
    assert weather_symbol_condition(63) == "thunderstorms-day"
    assert weather_symbol_condition(92) == "overcast-day"
    assert weather_symbol_condition(None) is None


def test_uses_agreed_wind_power_thresholds():
    assert wind_power_level(999) == "calm"
    assert wind_power_level(1000) == "weak"
    assert wind_power_level(2499) == "weak"
    assert wind_power_level(2500) == "normal"
    assert wind_power_level(3000) == "normal"
    assert wind_power_level(3001) == "strong"


def test_builds_daily_midday_condition_and_sustained_wind_summary():
    timestamps = pd.date_range("2026-07-02T21:00:00Z", periods=48, freq="h")
    frame = pd.DataFrame({
        "timestamp": timestamps,
        "WindPowerMW": [800] * 24 + [3200] * 24,
        "weather_symbol_101": [1] * 48,
        "weather_symbol_102": [2] * 48,
        "weather_symbol_103": [2] * 24 + [32] * 24,
        "weather_symbol_104": [2] * 48,
    })

    records = build_daily_weather(
        frame,
        reference_time="2026-07-03T10:00:00+03:00",
        days=2,
    )

    assert [record["condition"] for record in records] == ["partly-cloudy-day", "partly-cloudy-day"]
    assert [record["windLevel"] for record in records] == ["calm", "strong"]
    assert records[0]["timestamp"] == int(
        pd.Timestamp("2026-07-03T12:00:00+03:00").timestamp() * 1000
    )


def test_low_sustained_wind_stays_calm_despite_short_daily_peaks():
    timestamps = pd.date_range("2026-07-02T21:00:00Z", periods=24, freq="h")
    frame = pd.DataFrame({
        "timestamp": timestamps,
        "WindPowerMW": [800] * 18 + [2400] * 6,
        "weather_symbol_101": [1] * 24,
    })

    records = build_daily_weather(
        frame,
        reference_time="2026-07-03T12:00:00+03:00",
        days=1,
    )

    assert frame["WindPowerMW"].mean() > 1000
    assert records[0]["windLevel"] == "calm"


def test_write_daily_weather_serializes_frontend_contract(tmp_path):
    frame = pd.DataFrame({
        "timestamp": [pd.Timestamp("2026-07-03T09:00:00Z")],
        "WindPowerMW": [2800],
        "weather_symbol_101": [31],
    })
    output = tmp_path / "weather.json"

    records = write_daily_weather(
        frame,
        output,
        reference_time="2026-07-03T12:00:00+03:00",
        days=1,
    )

    assert json.loads(output.read_text(encoding="utf-8")) == records
    assert records[0]["condition"] == "rain"
    assert records[0]["windLevel"] == "normal"


def test_default_window_includes_today_and_seven_forecast_days():
    timestamps = pd.date_range("2026-07-02T21:00:00Z", periods=8 * 24, freq="h")
    frame = pd.DataFrame({
        "timestamp": timestamps,
        "WindPowerMW": [1500] * len(timestamps),
        "weather_symbol_101": [2] * len(timestamps),
    })

    records = build_daily_weather(
        frame,
        reference_time="2026-07-03T12:00:00+03:00",
    )

    assert len(records) == 8
    assert records[-1]["timestamp"] == int(
        pd.Timestamp("2026-07-10T12:00:00+03:00").timestamp() * 1000
    )
