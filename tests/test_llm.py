import importlib
import json
import os
import inspect

import pandas as pd
import pytz
import pytest

os.environ.setdefault("LLM_API_BASE", "https://example.invalid/v1")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_MODEL", "test-model")
os.environ.setdefault("LLM_DISPLAY_NAME", "Test Model")

from util import llm


def valid_article():
    table = "\n".join(
        [
            "Ennuste on päivitetty lauantaina klo 12:09.",
            "| | keskihinta | min - max | tuulivoima | lämpötila |",
            "|:--|:--:|:--:|:--:|:--:|",
            *[f"| **päivä {day}** | 4,0 | 1,0 - 7,0 | 1000 - 2000 | 10,0 |" for day in range(1, 8)],
        ]
    )
    return table + "\n\n" + ("Ennustejakson hintakehitys pysyy maltillisena. " * 12)


def test_optional_env_treats_missing_and_blank_as_none(monkeypatch):
    monkeypatch.delenv("OPTIONAL_TEST_VALUE", raising=False)
    assert llm._optional_env("OPTIONAL_TEST_VALUE") is None

    monkeypatch.setenv("OPTIONAL_TEST_VALUE", "  \t")
    assert llm._optional_env("OPTIONAL_TEST_VALUE") is None

    monkeypatch.setenv("OPTIONAL_TEST_VALUE", "  configured value  ")
    assert llm._optional_env("OPTIONAL_TEST_VALUE") == "configured value"


def test_llm_settings_parse_configured_values(monkeypatch):
    with monkeypatch.context() as env:
        env.setenv("LLM_MAX_TOKENS", " 8192 ")
        env.setenv("LLM_TEMPERATURE", " 0.25 ")
        env.setenv("LLM_EXTRA_BODY", ' {"reasoning_effort": "low"} ')
        env.setenv("LLM_MAX_RETRIES", " 3 ")
        env.setenv("LLM_MAX_OUTPUT_CHARS", " 4096 ")
        importlib.reload(llm)

        assert llm.LLM_MAX_TOKENS == 8192
        assert llm.LLM_TEMPERATURE == 0.25
        assert llm.LLM_EXTRA_BODY == {"reasoning_effort": "low"}
        assert llm.LLM_MAX_RETRIES == 3
        assert llm.LLM_MAX_OUTPUT_CHARS == 4096

    importlib.reload(llm)


def test_llm_settings_use_defaults_for_blank_values(monkeypatch):
    with monkeypatch.context() as env:
        env.setenv("LLM_MAX_TOKENS", "")
        env.setenv("LLM_TEMPERATURE", "")
        env.setenv("LLM_EXTRA_BODY", "")
        env.setenv("LLM_MAX_RETRIES", "")
        env.setenv("LLM_MAX_OUTPUT_CHARS", "")
        importlib.reload(llm)

        assert llm.LLM_MAX_TOKENS == 16384
        assert llm.LLM_TEMPERATURE is None
        assert llm.LLM_EXTRA_BODY is None
        assert llm.LLM_MAX_RETRIES == 0
        assert llm.LLM_MAX_OUTPUT_CHARS == 8192

    importlib.reload(llm)


@pytest.mark.parametrize(
    ("extra_body", "error"),
    [
        ("{broken", json.JSONDecodeError),
        ('["reasoning_effort", "low"]', ValueError),
        ("null", ValueError),
    ],
)
def test_llm_extra_body_rejects_invalid_json_objects(monkeypatch, extra_body, error):
    with monkeypatch.context() as env:
        env.setenv("LLM_EXTRA_BODY", extra_body)
        with pytest.raises(error):
            importlib.reload(llm)

    importlib.reload(llm)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LLM_MAX_TOKENS", "abc"),
        ("LLM_MAX_TOKENS", "0"),
        ("LLM_TEMPERATURE", "nan"),
        ("LLM_TEMPERATURE", "3.5"),
        ("LLM_MAX_RETRIES", "-1"),
        ("LLM_MAX_OUTPUT_CHARS", "0"),
    ],
)
def test_llm_settings_reject_invalid_values(monkeypatch, name, value):
    with monkeypatch.context() as env:
        env.setenv(name, value)
        with pytest.raises(ValueError):
            importlib.reload(llm)

    importlib.reload(llm)


def test_build_request_params_omits_max_tokens_for_gpt5(monkeypatch):
    messages = [{"role": "user", "content": "test"}]
    monkeypatch.setattr(llm, "LLM_MODEL", "gpt-5.4")
    monkeypatch.setattr(llm, "LLM_TEMPERATURE", None)
    monkeypatch.setattr(llm, "LLM_EXTRA_BODY", None)

    request = llm._build_request_params(messages)

    assert "max_tokens" not in request
    assert request["model"] == "gpt-5.4"


def test_build_request_params_uses_defaults_and_omits_optional_values(monkeypatch):
    messages = [{"role": "user", "content": "test"}]
    monkeypatch.setattr(llm, "LLM_MAX_TOKENS", 16384)
    monkeypatch.setattr(llm, "LLM_TEMPERATURE", None)
    monkeypatch.setattr(llm, "LLM_EXTRA_BODY", None)

    assert llm._build_request_params(messages) == {
        "model": llm.LLM_MODEL,
        "messages": messages,
        "stream": False,
        "max_tokens": 16384,
    }


def test_build_request_params_passes_nano_config_unchanged(monkeypatch):
    messages = [{"role": "user", "content": "test"}]
    extra_body = {"reasoning_effort": "low"}
    monkeypatch.setattr(llm, "LLM_MAX_TOKENS", 8192)
    monkeypatch.setattr(llm, "LLM_TEMPERATURE", None)
    monkeypatch.setattr(llm, "LLM_EXTRA_BODY", extra_body)

    request = llm._build_request_params(messages)

    assert request["max_tokens"] == 8192
    assert "temperature" not in request
    assert request["extra_body"] is extra_body


def test_build_request_params_includes_configured_temperature(monkeypatch):
    monkeypatch.setattr(llm, "LLM_TEMPERATURE", 0.25)
    monkeypatch.setattr(llm, "LLM_EXTRA_BODY", None)

    request = llm._build_request_params([])

    assert request["temperature"] == 0.25


@pytest.mark.parametrize("stage", ["narration", "ingress", "translation"])
@pytest.mark.parametrize("content", [None, "", "  \n\t"])
def test_require_content_rejects_missing_content(stage, content):
    with pytest.raises(RuntimeError, match=stage):
        llm._require_content(content, stage)


@pytest.mark.parametrize("stage", ["narration", "ingress", "translation"])
def test_require_content_rejects_oversized_output(stage):
    with pytest.raises(RuntimeError, match=stage):
        llm._require_content("x" * (llm.LLM_MAX_OUTPUT_CHARS + 1), stage)


def test_require_content_accepts_complete_stage_outputs_unchanged():
    narration = valid_article()
    ingress = (
        "*Sähköennuste lupaa edullista jaksoa, mutta tuulivoiman heikkeneminen "
        "nostaa hintoja yksittäisinä päivinä.*"
    )
    translation = valid_article().replace("Ennuste", "Forecast")

    assert llm._require_content(narration, "narration") is narration
    assert llm._require_content(ingress, "ingress") is ingress
    assert llm._require_content(translation, "translation") is translation


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


def test_narration_instructions_use_display_name_in_signature():
    instructions = llm.format_narration_instructions()

    assert instructions.count("Test Model") == 2
    assert "test-model" not in instructions
    assert "{LLM_DISPLAY_NAME}" not in instructions


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
