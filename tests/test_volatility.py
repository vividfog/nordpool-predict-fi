from datetime import datetime, timezone

import numpy as np
import pandas as pd

from util.volatility_xgb import predict_daily_volatility


def test_predict_daily_volatility_groups_and_maps():
    timestamps = [
        datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc),
    ]

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "NuclearPowerMW": [1000, 1100, 1200, 1300],
            "ImportCapacityMW": [2000, 2100, 2200, 2300],
            "WindPowerMW": [500, 800, 600, 900],
            "holiday": [0, 0, 1, 1],
            "sum_irradiance": [10, 12, 15, 18],
        }
    )

    recorded = {}

    def fake_model(daily_features: pd.DataFrame):
        # capture the prepared feature frame for assertions
        recorded["columns"] = list(daily_features.columns)
        recorded["data"] = daily_features.copy()
        return np.array([0.1, 0.9])

    result = predict_daily_volatility(df.copy(), fake_model)

    assert "volatile_likelihood" in result.columns

    # Map should apply per day
    expected = {
        datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc).date(): 0.1,
        datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc).date(): 0.9,
    }
    assert list(result["volatile_likelihood"]) == [expected[t.date()] for t in result["timestamp"]]

    # Daily aggregation should include mean/var columns for key signals
    assert "NuclearPowerMW_mean" in recorded["columns"]
    assert "NuclearPowerMW_var" in recorded["columns"]
    assert "holiday_max" in recorded["columns"]
