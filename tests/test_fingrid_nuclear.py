from datetime import datetime, timedelta, timezone

import pandas as pd

from util import fingrid_nuclear


def test_update_nuclear_resamples_and_forward_fills(monkeypatch):
    base_ts = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    fetch_data = pd.DataFrame(
        {
            "startTime": [
                base_ts,
                base_ts + timedelta(minutes=30),
                base_ts + timedelta(hours=1),
            ],
            "NuclearPowerMW": [1000.0, 1010.0, 1020.0],
        }
    )

    def fake_fetch(key, start_date, end_date):
        return fetch_data

    monkeypatch.setattr(fingrid_nuclear, "fetch_nuclear_power_data", fake_fetch)

    df = pd.DataFrame(
        {
            "timestamp": [
                base_ts,
                base_ts + timedelta(hours=1),
                base_ts + timedelta(hours=2),
            ]
        }
    )

    result = fingrid_nuclear.update_nuclear(df.copy(), fingrid_api_key="dummy")

    expected = [1005.0, 1020.0, 1020.0]
    # After resampling, the hourly values should be averaged, with the final hour forward-filled
    assert list(result["NuclearPowerMW"]) == expected
    assert not any(col.endswith(("_x", "_y")) for col in result.columns)
