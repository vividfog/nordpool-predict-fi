"""
Tests for util/quarter_shape.py - intra-hour shape stage of the 15-min model.
"""
import numpy as np
import pandas as pd
import pytest

from util import quarter_shape as quarter_xgb
from util.quarter_grid import QUARTER_START


def _hourly(start, values, **cols):
    ts = pd.date_range(start, periods=len(values), freq="h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "PricePredict_cpkWh": values, **cols})


def _synthetic_quarters(hours):
    """Quarter prices whose shape ramps towards the neighbouring hours (like the real market)."""
    rng = np.random.default_rng(0)
    ts = pd.date_range(QUARTER_START, periods=hours, freq="h")
    level = 5 + 4 * np.sin(np.arange(hours) * 2 * np.pi / 24) + rng.normal(0, 0.5, hours)
    prev = np.r_[level[0], level[:-1]] - level
    nxt = np.r_[level[1:], level[-1]] - level
    offsets = np.stack([0.4 * prev, 0.1 * prev, 0.1 * nxt, 0.4 * nxt], axis=1)
    offsets -= offsets.mean(axis=1, keepdims=True)
    quarters = pd.DataFrame(
        {
            "timestamp": np.repeat(ts, 4) + pd.to_timedelta(np.tile([0, 15, 30, 45], hours), unit="min"),
            "Price_cpkWh": (level[:, None] + offsets).ravel(),
        }
    )
    hourly = pd.DataFrame({"timestamp": ts, "WindPowerMW": 2000.0, "NuclearPowerMW": 4000.0})
    return hourly, quarters


class TestQuarterFrame:
    def test_expands_each_hour_to_four_quarters(self):
        frame = quarter_xgb.quarter_frame(_hourly("2026-01-05T10:00", [1.0, 2.0, 4.0]), "PricePredict_cpkWh")

        assert len(frame) == 12
        assert list(frame["qidx"][:4]) == [0, 1, 2, 3]
        assert frame["timestamp"].iloc[1] == pd.Timestamp("2026-01-05T10:15", tz="UTC")
        assert frame["timestamp"].iloc[-1] == pd.Timestamp("2026-01-05T12:45", tz="UTC")
        assert set(quarter_xgb.COLS) <= set(frame.columns)

    def test_neighbour_gradients_and_edges(self):
        frame = quarter_xgb.quarter_frame(_hourly("2026-01-05T10:00", [1.0, 2.0, 4.0]), "PricePredict_cpkWh")
        middle = frame[frame["hour"] == pd.Timestamp("2026-01-05T11:00", tz="UTC")].iloc[0]

        assert middle["prev"] == pytest.approx(-1.0)
        assert middle["next"] == pytest.approx(2.0)
        assert np.isnan(frame["prev"].iloc[0])
        assert np.isnan(frame["next"].iloc[-1])

    def test_gap_in_hours_is_not_bridged(self):
        df = _hourly("2026-01-05T10:00", [1.0, 2.0, 4.0]).drop(index=1)
        frame = quarter_xgb.quarter_frame(df, "PricePredict_cpkWh")

        assert len(frame) == 8
        assert frame["next"].isna().iloc[:4].all()

    def test_uses_helsinki_calendar(self):
        frame = quarter_xgb.quarter_frame(_hourly("2026-01-05T22:00", [1.0]), "PricePredict_cpkWh")

        # 22:00 UTC is 00:00 Tuesday in Helsinki (EET)
        assert frame["hel_hour"].iloc[0] == 0
        assert frame["dow"].iloc[0] == 1

    def test_accepts_timestamp_index(self):
        df = _hourly("2026-01-05T10:00", [1.0, 2.0]).set_index("timestamp")
        frame = quarter_xgb.quarter_frame(df, "PricePredict_cpkWh")

        assert len(frame) == 8


def test_recentre_zero_mean_per_hour():
    hour = pd.Series(np.repeat([0, 1], 4))
    shape = quarter_xgb.recentre([1, 2, 3, 4, 0, 0, 0, 8], hour)

    assert shape.groupby(hour).mean().abs().max() == pytest.approx(0.0)
    assert list(shape[:4]) == [-1.5, -0.5, 0.5, 1.5]


class TestApplyShape:
    def test_without_model_repeats_hourly_price(self):
        out = quarter_xgb.apply_shape(None, _hourly("2026-01-05T10:00", [3.0, 5.0]))

        assert list(out.columns) == ["timestamp", "PricePredict_cpkWh"]
        assert list(out["PricePredict_cpkWh"]) == [3.0] * 4 + [5.0] * 4

    def test_skips_hours_without_prediction(self):
        out = quarter_xgb.apply_shape(None, _hourly("2026-01-05T10:00", [3.0, np.nan, 5.0]))

        assert len(out) == 8


class TestTrainShapeModel:
    def test_returns_none_with_short_history(self):
        hourly, quarters = _synthetic_quarters(24 * 5)

        assert quarter_xgb.train_shape_model(hourly, quarters) is None

    def test_learns_shape_and_preserves_hourly_mean(self, monkeypatch):
        monkeypatch.setattr(quarter_xgb, "configure_cuda", lambda params, logger=None: params)
        hourly, quarters = _synthetic_quarters(24 * 70)

        model = quarter_xgb.train_shape_model(hourly, quarters)
        assert model is not None

        # Rising hours: the first quarter is cheapest, the last the most expensive
        recent = _hourly("2026-03-02T00:00", [2.0, 4.0, 6.0, 8.0, 10.0])
        out = quarter_xgb.apply_shape(model, recent)
        middle = out["PricePredict_cpkWh"].iloc[8:12].to_numpy()

        assert middle[0] < middle[3]
        assert middle.mean() == pytest.approx(6.0, abs=1e-3)
        hourly_means = out.groupby(out["timestamp"].dt.floor("h"))["PricePredict_cpkWh"].mean()
        assert hourly_means.to_numpy() == pytest.approx([2.0, 4.0, 6.0, 8.0, 10.0], abs=1e-3)

    def test_ignores_incomplete_hours(self, monkeypatch):
        monkeypatch.setattr(quarter_xgb, "configure_cuda", lambda params, logger=None: params)
        hourly, quarters = _synthetic_quarters(24 * 40)
        # Drop one quarter from every hour: nothing complete remains
        quarters = quarters.iloc[[i for i in range(len(quarters)) if i % 4 != 3]]

        assert quarter_xgb.train_shape_model(hourly, quarters) is None
