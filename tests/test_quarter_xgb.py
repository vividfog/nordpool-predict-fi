"""
Tests for util/quarter_xgb.py - 15-min shape model on top of hourly predictions.
"""
import numpy as np
import pandas as pd
import pytest
import requests_mock

from util import quarter_xgb, sahkotin, sql


def _hourly(start, values, **cols):
    ts = pd.date_range(start, periods=len(values), freq="h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "PricePredict_cpkWh": values, **cols})


def _synthetic_quarters(hours):
    """Quarter prices whose shape ramps towards the neighbouring hours (like the real market)."""
    rng = np.random.default_rng(0)
    ts = pd.date_range(sahkotin.QUARTER_START, periods=hours, freq="h")
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


class TestPredictQuarterPrices:
    def test_without_model_repeats_hourly_price(self):
        out = quarter_xgb.predict_quarter_prices(None, _hourly("2026-01-05T10:00", [3.0, 5.0]))

        assert list(out.columns) == ["timestamp", "PricePredict_cpkWh"]
        assert list(out["PricePredict_cpkWh"]) == [3.0] * 4 + [5.0] * 4

    def test_skips_hours_without_prediction(self):
        out = quarter_xgb.predict_quarter_prices(None, _hourly("2026-01-05T10:00", [3.0, np.nan, 5.0]))

        assert len(out) == 8


class TestTrainQuarterModel:
    def test_returns_none_with_short_history(self):
        hourly, quarters = _synthetic_quarters(24 * 5)

        assert quarter_xgb.train_quarter_model(hourly, quarters) is None

    def test_learns_shape_and_preserves_hourly_mean(self, monkeypatch):
        monkeypatch.setattr(quarter_xgb, "configure_cuda", lambda params, logger=None: params)
        hourly, quarters = _synthetic_quarters(24 * 70)

        model = quarter_xgb.train_quarter_model(hourly, quarters)
        assert model is not None

        # Rising hours: the first quarter is cheapest, the last the most expensive
        recent = _hourly("2026-03-02T00:00", [2.0, 4.0, 6.0, 8.0, 10.0])
        out = quarter_xgb.predict_quarter_prices(model, recent)
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

        assert quarter_xgb.train_quarter_model(hourly, quarters) is None


class TestQuarterStorage:
    def test_upsert_keeps_other_column(self, tmp_path):
        db = str(tmp_path / "p.db")
        ts = pd.date_range("2026-01-05T10:00", periods=2, freq="15min", tz="UTC")

        sql.db_quarter_update(db, pd.DataFrame({"timestamp": ts, "Price_cpkWh": [1.0, 2.0]}), "Price_cpkWh")
        sql.db_quarter_update(
            db, pd.DataFrame({"timestamp": ts, "PricePredict_cpkWh": [1.5, np.nan]}), "PricePredict_cpkWh"
        )
        stored = sql.db_quarter_query_all(db)

        assert list(stored["Price_cpkWh"]) == [1.0, 2.0]
        assert stored["PricePredict_cpkWh"].iloc[0] == 1.5
        assert np.isnan(stored["PricePredict_cpkWh"].iloc[1])
        assert stored["timestamp"].iloc[1] == ts[1]

    def test_rejects_unknown_column(self, tmp_path):
        with pytest.raises(ValueError):
            sql.db_quarter_update(str(tmp_path / "p.db"), pd.DataFrame({"timestamp": [], "x": []}), "x")

    def test_load_quarter_prices_fetches_and_commits(self, tmp_path, monkeypatch):
        db = str(tmp_path / "p.db")
        ts = pd.date_range("2026-01-05T10:00", periods=4, freq="15min", tz="UTC")
        fetched = pd.DataFrame({"timestamp": ts, "Price_cpkWh": [1.0, 2.0, 3.0, 4.0]})
        calls = []

        def fake_fetch(start, end):
            calls.append(start)
            return fetched

        monkeypatch.setattr(quarter_xgb, "fetch_quarter_prices", fake_fetch)

        no_commit = quarter_xgb.load_quarter_prices(db, commit=False, now="2026-01-05T12:00Z")
        assert len(no_commit) == 4
        assert sql.db_quarter_query_all(db).empty
        assert calls[-1] == sahkotin.QUARTER_START

        quarter_xgb.load_quarter_prices(db, commit=True, now="2026-01-05T12:00Z")
        assert len(sql.db_quarter_query_all(db)) == 4

        # Incremental fetch starts two days before the last stored quarter
        quarter_xgb.load_quarter_prices(db, commit=False, now="2026-01-05T12:00Z")
        assert calls[-1] == ts[-1] - pd.Timedelta(days=2)


class TestFetchQuarterPrices:
    def test_requests_quarter_resolution(self):
        payload = {"prices": [{"date": "2026-10-01T00:00:00.000Z", "value": 32.065},
                              {"date": "2026-10-01T00:15:00.000Z", "value": 26.167}]}
        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, json=payload)
            result = sahkotin.fetch_quarter_prices(
                pd.Timestamp("2026-10-01T00:00Z"), pd.Timestamp("2026-10-01T01:00Z")
            )
            assert "quarter" in m.last_request.qs

        assert list(result["Price_cpkWh"]) == pytest.approx([3.2065, 2.6167])

    def test_clips_to_market_go_live(self):
        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, json={"prices": []})
            sahkotin.fetch_quarter_prices(pd.Timestamp("2025-01-01T00:00Z"), pd.Timestamp("2025-10-02T00:00Z"))
            assert m.last_request.qs["start"] == ["2025-09-30t22:00:00.000z"]

    def test_nothing_to_fetch_before_go_live(self):
        result = sahkotin.fetch_quarter_prices(pd.Timestamp("2025-01-01T00:00Z"), pd.Timestamp("2025-02-01T00:00Z"))

        assert result.empty
