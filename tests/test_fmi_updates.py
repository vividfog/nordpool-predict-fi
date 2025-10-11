from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from util import fmi


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
