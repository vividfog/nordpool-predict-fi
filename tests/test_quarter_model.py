"""
Tests for the 15-min price model: grid helpers, features, storage, data layer, training.
"""
import numpy as np
import pandas as pd
import pytest
import requests_mock

from util import features_pricing as pricing
from util import quarter_data, quarter_grid, sahkotin, sql, train_xgb_15min
from util.fmi import get_observations_10min


def _ts(start, periods, freq):
    return pd.date_range(start, periods=periods, freq=freq, tz="UTC")


# region grid
class TestUpsampleHourly:
    def test_interpolates_continuous_and_holds_step_columns(self):
        df = pd.DataFrame(
            {
                "timestamp": _ts("2026-01-05T10:00", 2, "h"),
                "WindPowerMW": [1000.0, 2000.0],
                "Price_cpkWh": [5.0, 9.0],
                "HydroSWE_median": [1.0, 2.0],
            }
        )
        out = quarter_grid.upsample_hourly(df)

        assert len(out) == 8
        assert list(out["WindPowerMW"][:4]) == [1000.0, 1250.0, 1500.0, 1750.0]
        assert list(out["Price_cpkWh"][:4]) == [5.0] * 4
        assert list(out["HydroSWE_median"][:4]) == [1.0] * 4
        # Last hour has no successor: held
        assert list(out["WindPowerMW"][4:]) == [2000.0] * 4

    def test_does_not_bridge_missing_hours(self):
        df = pd.DataFrame({"timestamp": _ts("2026-01-05T10:00", 3, "h"), "t_1": [0.0, 4.0, 8.0]}).drop(index=1)
        out = quarter_grid.upsample_hourly(df).set_index("timestamp")["t_1"]

        assert list(out.iloc[:4]) == [0.0] * 4
        assert out.loc["2026-01-05T11:15Z":"2026-01-05T11:45Z"].isna().all()
        assert out.loc["2026-01-05T12:00Z"] == 8.0

    def test_drops_non_numeric(self):
        df = pd.DataFrame({"timestamp": _ts("2026-01-05", 1, "h"), "label": ["x"], "v": [1.0]})

        assert "label" not in quarter_grid.upsample_hourly(df).columns


class TestToQuarters:
    def test_averages_finer_samples(self):
        df = pd.DataFrame({"timestamp": _ts("2026-01-05T10:00", 10, "3min"), "v": np.arange(10.0)})
        out = quarter_grid.to_quarters(df, ["v"])

        assert list(out["timestamp"]) == list(_ts("2026-01-05T10:00", 2, "15min"))
        assert list(out["v"]) == [2.0, 7.0]

    def test_quarter_samples_pass_through(self):
        df = pd.DataFrame({"timestamp": _ts("2026-01-05T10:00", 3, "15min"), "v": [1.0, 2.0, 3.0]})

        assert list(quarter_grid.to_quarters(df, ["v"])["v"]) == [1.0, 2.0, 3.0]

    def test_coarser_samples_step_or_interpolate(self):
        df = pd.DataFrame({"timestamp": _ts("2026-01-05T10:00", 2, "h"), "v": [0.0, 4.0]})

        assert list(quarter_grid.to_quarters(df, ["v"], how="step")["v"][:4]) == [0.0] * 4
        assert list(quarter_grid.to_quarters(df, ["v"])["v"][:4]) == [0.0, 1.0, 2.0, 3.0]

    def test_empty_input(self):
        assert quarter_grid.to_quarters(pd.DataFrame(), ["v"]).empty


class TestOverlay:
    def test_native_values_win_where_present(self):
        base = pd.DataFrame({"timestamp": _ts("2026-01-05", 3, "15min"), "v": [1.0, 1.0, 1.0], "w": [0.0] * 3})
        fine = pd.DataFrame({"timestamp": _ts("2026-01-05T00:15", 3, "15min"), "v": [5.0, np.nan, 7.0]})
        out = quarter_grid.overlay(base, fine)

        assert list(out["v"]) == [1.0, 5.0, 1.0]
        assert len(out) == 3
        assert list(out["w"]) == [0.0] * 3

    def test_combine_fine_later_frames_win_and_union_rows(self):
        a = pd.DataFrame({"timestamp": _ts("2026-01-05", 2, "15min"), "v": [1.0, 2.0]})
        b = pd.DataFrame({"timestamp": _ts("2026-01-05T00:15", 2, "15min"), "v": [9.0, 3.0], "w": [1.0, 1.0]})
        out = quarter_grid.combine_fine(a, b, None)

        assert list(out["v"]) == [1.0, 9.0, 3.0]
        assert out["w"].isna().tolist() == [True, False, False]
# endregion grid


# region features
class TestQuarterFeatures:
    def test_calendar_in_helsinki_time(self):
        df = pd.DataFrame({"timestamp": _ts("2026-01-05T21:45", 2, "15min")})
        out = pricing.add_time_quarter(df)

        # 21:45 UTC = 23:45 EET Monday, 22:00 UTC = 00:00 Tuesday
        assert list(out["quarter_of_day"]) == [95, 0]
        assert list(out["qidx"]) == [3, 0]
        assert list(out["day_of_week"]) == [1, 2]

    def test_mtu15_flag_switches_at_go_live(self):
        df = pd.DataFrame({"timestamp": [quarter_grid.QUARTER_START - pd.Timedelta(minutes=15), quarter_grid.QUARTER_START]})

        assert list(pricing.add_time_quarter(df)["mtu15"]) == [0, 1]

    def test_ramps_use_timestamps_not_row_offsets(self):
        ts = _ts("2026-01-05T10:00", 12, "15min")
        df = pd.DataFrame({"timestamp": ts, "WindPowerMW": np.arange(12.0) * 10})
        out = pricing.add_ramps(df.copy())

        assert out["WindPowerMW_ramp"].iloc[4] == pytest.approx(80.0)  # (t+1h) - (t-1h)
        assert np.isnan(out["WindPowerMW_ramp"].iloc[0])
        assert out["NuclearPowerMW_ramp"].isna().all()

    def test_cols_quarter_replaces_hour_terms(self):
        cols = pricing.cols_quarter(["ws_1"], ["t_1"])

        assert "hour_sin" not in cols and "hour_cos" not in cols
        assert {"qidx", "mtu15", "quarter_of_day_sin", "WindPowerMW_ramp", "ws_1", "t_1"} <= set(cols)
        assert len(cols) == len(set(cols))
# endregion features


# region storage
class TestQuarterTable:
    def test_upsert_adds_columns_and_keeps_values_on_nan(self, tmp_path):
        db = str(tmp_path / "p.db")
        ts = _ts("2026-01-05T10:00", 2, "15min")

        sql.db_quarter_update(db, pd.DataFrame({"timestamp": ts, "Price_cpkWh": [1.0, 2.0]}))
        sql.db_quarter_update(db, pd.DataFrame({"timestamp": ts, "Price_cpkWh": [np.nan, 3.0], "eu_ws_EE01": [5.0, 6.0]}))
        sql.db_quarter_update(db, pd.DataFrame({"timestamp": ts[:1], "PricePredict_cpkWh": [1.5]}), ["PricePredict_cpkWh"])
        stored = sql.db_quarter_query_all(db)

        assert list(stored["Price_cpkWh"]) == [1.0, 3.0]
        assert list(stored["eu_ws_EE01"]) == [5.0, 6.0]
        assert stored["PricePredict_cpkWh"].iloc[0] == 1.5
        assert stored["timestamp"].iloc[1] == ts[1]

    def test_empty_table_query(self, tmp_path):
        stored = sql.db_quarter_query_all(str(tmp_path / "p.db"))

        assert stored.empty and "timestamp" in stored.columns

    def test_all_nan_rows_are_skipped(self, tmp_path):
        frame = pd.DataFrame({"timestamp": _ts("2026-01-05", 1, "15min"), "v": [np.nan]})

        assert sql.db_quarter_update(str(tmp_path / "p.db"), frame) == 0
# endregion storage


# region sources
class TestFetchQuarterPrices:
    def test_requests_quarter_resolution(self):
        payload = {"prices": [{"date": "2026-10-01T00:00:00.000Z", "value": 32.065},
                              {"date": "2026-10-01T00:15:00.000Z", "value": 26.167}]}
        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, json=payload)
            result = sahkotin.fetch_quarter_prices(pd.Timestamp("2026-10-01T00:00Z"), pd.Timestamp("2026-10-01T01:00Z"))
            assert "quarter" in m.last_request.qs

        assert list(result["Price_cpkWh"]) == pytest.approx([3.2065, 2.6167])

    def test_clips_to_market_go_live(self):
        with requests_mock.Mocker() as m:
            m.get(requests_mock.ANY, json={"prices": []})
            sahkotin.fetch_quarter_prices(pd.Timestamp("2025-01-01T00:00Z"), pd.Timestamp("2025-10-02T00:00Z"))
            assert m.last_request.qs["start"] == ["2025-09-30t22:00:00.000z"]

    def test_nothing_to_fetch_before_go_live(self):
        assert sahkotin.fetch_quarter_prices(pd.Timestamp("2025-01-01T00:00Z"), pd.Timestamp("2025-02-01T00:00Z")).empty


def test_fmi_10min_observations_are_chunked_to_168_hours():
    xml = (
        '<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" '
        'xmlns:BsWfs="http://xml.fmi.fi/schema/wfs/2.0">'
        "<wfs:member><BsWfs:BsWfsElement><BsWfs:Time>2026-01-05T00:00:00Z</BsWfs:Time>"
        "<BsWfs:ParameterName>t2m</BsWfs:ParameterName><BsWfs:ParameterValue>1.5</BsWfs:ParameterValue>"
        "</BsWfs:BsWfsElement></wfs:member></wfs:FeatureCollection>"
    )
    with requests_mock.Mocker() as m:
        m.get(requests_mock.ANY, text=xml)
        df = get_observations_10min(101004, pd.Timestamp("2026-01-01T00:00Z"), pd.Timestamp("2026-01-15T00:00Z"))
        assert m.call_count == 2
        assert all(r.qs["timestep"] == ["10"] for r in m.request_history)

    assert df["t2m"].iloc[0] == 1.5


class TestFetchQuarterSources:
    def _patch(self, monkeypatch, failing=()):
        ts = _ts("2026-01-05T10:00", 4, "15min")

        def frame(**cols):
            return lambda *a, **k: pd.DataFrame({"timestamp": ts, **cols})

        fakes = {
            "fetch_quarter_prices": frame(Price_cpkWh=[1.0, 2.0, 3.0, 4.0]),
            "fetch_import_capacity_quarters": frame(ImportCapacityMW=[3000.0] * 4),
            "fetch_eu_ws_quarters": frame(eu_ws_EE01=[5.0] * 4),
            "fetch_irradiance_quarters": frame(sum_irradiance=[0.0] * 4),
            "fetch_windpower_quarters": frame(WindPowerMW=[1000.0] * 4),
            "fetch_nuclear_quarters": frame(NuclearPowerMW=[4000.0] * 4),
            "fetch_station_quarters": frame(t_101004=[1.0] * 4),
        }
        for name, fake in fakes.items():
            if name in failing:
                def fake(*a, **k):
                    raise RuntimeError("down")
            monkeypatch.setattr(quarter_data, name, fake)
        return ts

    def test_merges_all_sources(self, monkeypatch):
        ts = self._patch(monkeypatch)
        out = quarter_data.fetch_quarter_sources(ts[0], ts[-1], fingrid_api_key="k", fmisids=["101004"])

        assert {"Price_cpkWh", "ImportCapacityMW", "eu_ws_EE01", "WindPowerMW", "NuclearPowerMW", "t_101004"} <= set(out.columns)
        assert len(out) == 4

    def test_failing_source_is_skipped(self, monkeypatch):
        ts = self._patch(monkeypatch, failing=("fetch_windpower_quarters",))
        out = quarter_data.fetch_quarter_sources(ts[0], ts[-1], fingrid_api_key="k", fmisids=["101004"])

        assert "WindPowerMW" not in out.columns
        assert "Price_cpkWh" in out.columns

    def test_entso_e_overrides_fingrid_nuclear(self, monkeypatch):
        ts = self._patch(monkeypatch)
        entso = pd.DataFrame({"timestamp": ts[2:].tz_convert("Europe/Helsinki"), "NuclearPowerMW": [2800.0, 2800.0]})
        out = quarter_data.fetch_quarter_sources(ts[0], ts[-1], fingrid_api_key="k", fmisids=[], entso_e=entso)

        assert list(out["NuclearPowerMW"]) == [4000.0, 4000.0, 2800.0, 2800.0]


def test_build_quarter_frame_overlays_native_and_ignores_stored_predictions():
    hourly = pd.DataFrame(
        {"timestamp": _ts("2026-01-05T10:00", 2, "h"), "Price_cpkWh": [5.0, 6.0], "WindPowerMW": [1000.0, 2000.0]}
    )
    fine = pd.DataFrame(
        {
            "timestamp": _ts("2026-01-05T10:00", 4, "15min"),
            "Price_cpkWh": [4.0, 5.0, 5.0, 6.0],
            "PricePredict_cpkWh": [99.0] * 4,
        }
    )
    out = quarter_data.build_quarter_frame(hourly, fine)

    assert list(out["Price_cpkWh"][:4]) == [4.0, 5.0, 5.0, 6.0]
    assert list(out["Price_cpkWh"][4:]) == [6.0] * 4
    assert list(out["WindPowerMW"][:2]) == [1000.0, 1250.0]
    assert "PricePredict_cpkWh" not in out.columns
# endregion sources


# region train
def test_train_model_15min_learns_intra_hour_shape(monkeypatch):
    monkeypatch.setattr(train_xgb_15min, "configure_cuda", lambda params, logger=None: params)
    monkeypatch.setattr(train_xgb_15min, "PARAMS", {**train_xgb_15min.PARAMS, "n_estimators": 300, "learning_rate": 0.1})

    rng = np.random.default_rng(0)
    ts = pd.date_range(quarter_grid.QUARTER_START - pd.Timedelta(days=20), periods=96 * 40, freq="15min")
    df = pd.DataFrame({"timestamp": ts, "WindPowerMW": rng.uniform(500, 5000, len(ts))})
    df = quarter_data.add_quarter_features(df, [])
    for col in pricing.cols_quarter([], []):
        if col not in df.columns:
            df[col] = np.nan
    # Quarter prices fall within each hour after go-live, flat before
    shape = np.where(df["mtu15"] == 1, 1.5 - df["qidx"], 0.0)
    df["Price_cpkWh"] = 10 - df["WindPowerMW"] / 1000 + shape + rng.normal(0, 0.1, len(df))

    model = train_xgb_15min.train_model_15min(df, [], [])
    pred = train_xgb_15min.booster_predict(model, df[pricing.cols_quarter([], [])])

    after = df["mtu15"] == 1
    first = pred[after & (df["qidx"] == 0)].mean() - pred[after & (df["qidx"] == 3)].mean()
    before = pred[~after & (df["qidx"] == 0)].mean() - pred[~after & (df["qidx"] == 3)].mean()
    assert first == pytest.approx(3.0, abs=0.5)
    assert abs(before) < 0.5
# endregion train
