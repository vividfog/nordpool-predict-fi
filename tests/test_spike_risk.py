import pandas as pd
import pytest
import pytz

from util.spike_risk import (
    MAX_WIND_MULTIPLIER,
    MIN_WIND_MULTIPLIER,
    WIND_SCALE_MAX_MW,
    WIND_SCALE_MIN_MW,
    compute_spike_risk_hours,
    spike_risk_future_start,
)


HELSINKI = pytz.timezone("Europe/Helsinki")


def make_hourly_day(day="2026-05-04", prices=None, wind=500):
    timestamps = pd.date_range(day, periods=24, freq="h", tz=HELSINKI)
    if prices is None:
        prices = [1.0] * 24
    if not isinstance(wind, list):
        wind = [wind] * 24
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "PricePredict_cpkWh": prices,
            "WindPowerMW": wind,
        }
    )


def test_wind_multiplier_interpolates_and_clips():
    midpoint_wind = (WIND_SCALE_MAX_MW + WIND_SCALE_MIN_MW) / 2
    df = make_hourly_day(
        prices=[10.0] * 24,
        wind=[WIND_SCALE_MAX_MW, midpoint_wind, WIND_SCALE_MIN_MW] + [2000.0] * 21,
    )

    result = compute_spike_risk_hours(
        df,
        now=pd.Timestamp("2026-05-03 10:00", tz=HELSINKI),
        helsinki_tz=HELSINKI,
    )

    assert result.loc[0, "wind_multiplier"] == pytest.approx(MIN_WIND_MULTIPLIER)
    assert result.loc[1, "wind_multiplier"] == pytest.approx(
        (MIN_WIND_MULTIPLIER + MAX_WIND_MULTIPLIER) / 2
    )
    assert result.loc[2, "wind_multiplier"] == pytest.approx(MAX_WIND_MULTIPLIER)


def test_top_daily_hours_are_split_between_morning_and_evening():
    prices = [1.0] * 24
    prices[8] = 20.0
    prices[9] = 19.0
    prices[10] = 18.0
    prices[19] = 30.0
    prices[20] = 29.0
    prices[21] = 28.0
    df = make_hourly_day(prices=prices, wind=500)

    result = compute_spike_risk_hours(
        df,
        now=pd.Timestamp("2026-05-03 10:00", tz=HELSINKI),
        helsinki_tz=HELSINKI,
    )

    flagged_hours = result.loc[result["is_spike_risk_hour"], "helsinki_hour"].tolist()
    assert flagged_hours == [8, 9, 19, 20]


def test_helsinki_hour_filter_excludes_night_and_22():
    prices = [1.0] * 24
    prices[5] = 100.0
    prices[6] = 18.0
    prices[8] = 20.0
    prices[16] = 28.0
    prices[19] = 30.0
    prices[22] = 99.0
    df = make_hourly_day(prices=prices, wind=500)

    result = compute_spike_risk_hours(
        df,
        now=pd.Timestamp("2026-05-03 10:00", tz=HELSINKI),
        helsinki_tz=HELSINKI,
    )

    assert not result.loc[result["helsinki_hour"].isin([5, 22]), "is_top_daily_price_hour"].any()
    assert set(result.loc[result["is_top_daily_price_hour"], "helsinki_hour"]) == {6, 8, 16, 19}


def test_future_cutoff_changes_after_14_helsinki_time():
    before_cutoff = spike_risk_future_start(
        now=pd.Timestamp("2026-05-03 13:00", tz=HELSINKI),
        helsinki_tz=HELSINKI,
    ).tz_convert(HELSINKI)
    after_cutoff = spike_risk_future_start(
        now=pd.Timestamp("2026-05-03 14:30", tz=HELSINKI),
        helsinki_tz=HELSINKI,
    ).tz_convert(HELSINKI)

    assert before_cutoff == pd.Timestamp("2026-05-04 01:00", tz=HELSINKI)
    assert after_cutoff == pd.Timestamp("2026-05-05 01:00", tz=HELSINKI)


def test_low_wind_without_top_price_hour_is_not_spike_risk():
    prices = [1.0] * 24
    prices[8] = 20.0
    prices[19] = 30.0
    wind = [2000.0] * 24
    wind[12] = 500.0
    df = make_hourly_day(prices=prices, wind=wind)

    result = compute_spike_risk_hours(
        df,
        now=pd.Timestamp("2026-05-03 10:00", tz=HELSINKI),
        helsinki_tz=HELSINKI,
    )

    assert not result["is_spike_risk_hour"].any()
    assert result.loc[12, "wind_multiplier"] > MIN_WIND_MULTIPLIER
    assert not result.loc[12, "is_top_daily_price_hour"]


def test_top_price_hour_without_low_wind_is_not_spike_risk():
    prices = [1.0] * 24
    prices[8] = 20.0
    prices[19] = 30.0
    df = make_hourly_day(prices=prices, wind=WIND_SCALE_MAX_MW)

    result = compute_spike_risk_hours(
        df,
        now=pd.Timestamp("2026-05-03 10:00", tz=HELSINKI),
        helsinki_tz=HELSINKI,
    )

    assert not result["is_spike_risk_hour"].any()


def test_may_3_style_fixture_flags_only_thursday_peak_hours():
    monday = make_hourly_day("2026-05-04", prices=[1.0] * 24, wind=1500)
    thursday_prices = [1.0] * 24
    for hour, price in {8: 10.0, 9: 10.6, 20: 17.0, 21: 15.7}.items():
        thursday_prices[hour] = price
    thursday = make_hourly_day("2026-05-07", prices=thursday_prices, wind=700)
    df = pd.concat([monday, thursday], ignore_index=True)

    result = compute_spike_risk_hours(
        df,
        now=pd.Timestamp("2026-05-03 15:00", tz=HELSINKI),
        helsinki_tz=HELSINKI,
    )

    flagged = result.loc[result["is_spike_risk_hour"], ["helsinki_date", "helsinki_hour"]]
    assert flagged["helsinki_date"].unique().tolist() == [pd.Timestamp("2026-05-07").date()]
    assert flagged["helsinki_hour"].tolist() == [8, 9, 20, 21]
