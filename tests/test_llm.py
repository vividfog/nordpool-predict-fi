import os
import inspect

import pandas as pd
import pytz

os.environ.setdefault("LLM_API_BASE", "https://example.invalid/v1")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_MODEL", "test-model")

from util import llm


def make_daily_df(start, published_flags):
    helsinki_tz = pytz.timezone("Europe/Helsinki")
    rows = []
    for index, published in enumerate(published_flags):
        timestamp = helsinki_tz.localize(pd.Timestamp(start) + pd.Timedelta(days=index))
        rows.append(
            {
                "timestamp": timestamp,
                "PricePredict_cpkWh_min": round(1.0 + index, 1),
                "PricePredict_cpkWh_max": round(5.0 + index, 1),
                "PricePredict_cpkWh_mean": round(3.0 + index, 1),
            }
        )
    return pd.DataFrame(rows)


def test_build_narration_prompt_includes_forecast_window_context():
    df_daily = make_daily_df("2026-03-07 00:00:00", [True, False, False])

    prompt = llm.build_narration_prompt(df_daily, pd.DataFrame(), pytz.timezone("Europe/Helsinki"))

    first_weekday = llm._format_weekday_name(df_daily.iloc[0]["timestamp"])
    last_weekday = llm._format_weekday_name(df_daily.iloc[-1]["timestamp"])

    assert "Tämä aineisto kuvaa ennustejaksoa, ei välttämättä kalenteriviikkoa." in prompt
    assert "Nyt on " in prompt
    assert " klo " in prompt
    assert f"Ensimmäinen aineiston päivä on {first_weekday}." in prompt
    assert f"Viimeinen aineiston päivä on {last_weekday}." in prompt
    assert "<tulevien_päivien_tilanne>" not in prompt


def test_build_narration_prompt_has_no_extra_xml_preamble():
    df_daily = make_daily_df("2026-03-06 00:00:00", [False, False, False])

    prompt = llm.build_narration_prompt(df_daily, pd.DataFrame(), pytz.timezone("Europe/Helsinki"))

    assert "on jo julkaistu" not in prompt
    assert "ovat vielä ennustetta" not in prompt
    assert "päivä on vielä tulevaisuudessa" not in prompt
    assert "<nykyhetki>" not in prompt
    assert "<seuraava_tuleva_päivä" not in prompt


def test_build_narration_prompt_keeps_original_plaintext_preamble_shape():
    df_daily = make_daily_df("2026-03-08 00:00:00", [True, False])

    prompt = llm.build_narration_prompt(df_daily, pd.DataFrame(), pytz.timezone("Europe/Helsinki"))

    lines = [line for line in prompt.splitlines() if line]
    assert lines[0] == "<data>"
    assert lines[1].startswith("  Nyt on ")
    assert lines[2].startswith("  Olet osa Sähkövatkain")


def test_narration_prompt_uses_forecast_period_wording():
    assert "Onko ennustejakso tasainen vai onko suuria eroja päivien välillä?" in llm.narration_prompt
    assert "Kirjoita yleiskuvaus ennustejakson hintakehityksestä, futuurissa." in llm.narration_prompt
    assert "Ennustejakson edullisimmat ja kalleimmat ajankohdat ovat kiinnostavia tietoja" in llm.narration_prompt
    assert "Suosi viikonpäivien nimiä, kun kuvaat tulevien päivien kehitystä." in llm.narration_prompt


def test_format_spike_risk_block_uses_shared_hourly_mask():
    helsinki_tz = pytz.timezone("Europe/Helsinki")
    timestamps = pd.date_range("2026-05-04", periods=48, freq="h", tz=helsinki_tz)
    prices = [1.0] * 48
    prices[24 + 8] = 10.0
    prices[24 + 9] = 10.6
    prices[24 + 20] = 17.0
    prices[24 + 21] = 15.7
    wind = [2000.0] * 24 + [700.0] * 24

    df_intraday = pd.DataFrame(
        {
            "timestamp": timestamps,
            "PricePredict_cpkWh": prices,
            "WindPowerMW": wind,
        }
    )
    df_daily = pd.DataFrame(
        {
            "timestamp": [
                helsinki_tz.localize(pd.Timestamp("2026-05-04")),
                helsinki_tz.localize(pd.Timestamp("2026-05-05")),
            ]
        },
        index=["maanantai", "tiistai"],
    )

    block = llm.format_spike_risk_block(
        df_daily,
        df_intraday,
        helsinki_tz,
        now=pd.Timestamp("2026-05-03 10:00", tz=helsinki_tz),
    )

    assert block.count("<hintapiikkiriskit>") == 1
    assert "maanantai: ei" in block
    assert "tiistai: klo 19–21" in block


def test_llm_generate_no_longer_adds_scattered_spike_notes():
    source = inspect.getsource(llm.llm_generate)

    assert "TÄRKEÄÄ MAINITA" not in source
    assert "HUOM: Riski hintapiikeille" not in source
    assert "älä puhu hintapiikeistä" not in source


def test_narration_prompt_references_structured_spike_block():
    assert "<hintapiikkiriskit>" in llm.narration_prompt
    assert "Saat mainita hintapiikkiriskin vain päiville" in llm.narration_prompt
    assert "Älä päättele hintapiikkiriskiä itse" in llm.narration_prompt
