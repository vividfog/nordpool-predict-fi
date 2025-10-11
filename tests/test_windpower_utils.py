import pandas as pd

from util.fingrid_windpower_xgb import cols_cleanup


def test_cols_cleanup_preserves_original_order_and_adds_required_columns():
    original = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=2, freq="h"),
            "foo": [1, 2],
        }
    )

    merged = original.copy()
    merged["WindPowerMW"] = [100.0, 110.0]
    merged["WindPowerCapacityMW"] = [3000.0, 3000.0]
    merged["extra_column"] = [42, 43]

    result = cols_cleanup(original, merged)

    assert list(result.columns) == ["timestamp", "foo", "WindPowerMW", "WindPowerCapacityMW"]
    assert "extra_column" not in result.columns
