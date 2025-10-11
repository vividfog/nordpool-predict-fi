import pandas as pd
import pytest

from util.dataframes import coalesce_merged_columns


def test_coalesce_merged_columns_merges_left_and_right_values():
    df = pd.DataFrame(
        {
            "value_x": [1.0, None, 3.0],
            "value_y": [None, 2.5, 3.5],
            "other": [10, 20, 30],
        }
    )

    result = coalesce_merged_columns(df.copy())

    assert "value_x" not in result.columns
    assert "value_y" not in result.columns
    assert list(result["value"]) == [1.0, 2.5, 3.0]
    # Ensure unrelated columns remain untouched
    assert list(result["other"]) == [10, 20, 30]


def test_coalesce_merged_columns_handles_missing_right_side():
    df = pd.DataFrame(
        {
            "metric_x": [None, 5.0],
            "metric_y": [None, None],
        }
    )

    # When only *_x exists, the helper should still provide the base column
    result = coalesce_merged_columns(df.copy())

    assert "metric_x" not in result.columns
    assert "metric_y" not in result.columns
    assert "metric" in result.columns
    assert pd.isna(result.loc[0, "metric"])
    assert result.loc[1, "metric"] == 5.0
