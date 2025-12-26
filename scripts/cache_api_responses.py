#!/usr/bin/env python3
"""
Fetch and cache API responses for integration tests.

Run this script periodically to refresh cached API responses:
    python scripts/cache_api_responses.py

The cached responses are stored in tests/fixtures/ and used by
integration tests to avoid making real HTTP calls.
"""
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"

# Dynamic date range for API requests
TODAY = datetime.now().date()
PAST_DAYS = 7
FORECAST_DAYS = 10
START_DATE = TODAY - timedelta(days=PAST_DAYS)
END_DATE = TODAY + timedelta(days=FORECAST_DAYS)


def fetch_fmi_forecast():
    """Fetch FMI weather forecast XML."""
    url = "https://opendata.fmi.fi/wfs"
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "getFeature",
        "storedquery_id": "fmi::forecast::edited::weather::scandinavia::point::simple",
        "fmisid": "101004",
        "starttime": f"{TODAY}T00:00:00Z",
        "endtime": f"{TODAY}T23:59:59Z",
        "parameters": "temperature",
        "timestep": "60",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.content


def fetch_fmi_history():
    """Fetch FMI historical data XML."""
    url = "https://opendata.fmi.fi/wfs"
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "getFeature",
        "storedquery_id": "fmi::observations::weather::hourly::simple",
        "fmisid": "101004",
        "starttime": f"{START_DATE}T00:00:00Z",
        "endtime": f"{END_DATE}T23:59:59Z",
        "parameters": "TA_PT1H_AVG",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.content


def fetch_sahkotin_prices():
    """Fetch Sähkötin electricity prices."""
    url = "https://sahkotin.fi/prices"
    params = {
        "vat": None,
        "start": f"{TODAY}T00:00:00.000Z",
        "end": f"{TODAY + timedelta(days=1)}T23:59:59.000Z",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_holidays():
    """Fetch Finnish holidays from pyhäpäivä.fi."""
    url = "https://pyhapaiva.fi/"
    params = {"output": "json"}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_openmeteo_historical():
    """Fetch Open-Meteo historical wind data."""
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": 54.2194,
        "longitude": 9.6961,
        "start_date": str(START_DATE),
        "end_date": str(TODAY),
        "hourly": "wind_speed_100m",
        "wind_speed_unit": "ms",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_openmeteo_forecast():
    """Fetch Open-Meteo forecast wind data."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 54.2194,
        "longitude": 9.6961,
        "hourly": "wind_speed_120m",
        "wind_speed_unit": "ms",
        "past_days": PAST_DAYS,
        "forecast_days": FORECAST_DAYS,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    print("Fetching and caching API responses...")
    print(f"Output directory: {FIXTURES_DIR}")
    print()

    # FMI
    print("Fetching FMI forecast...")
    with open(FIXTURES_DIR / "fmi" / "forecast_temperature.xml", "w") as f:
        f.write(fetch_fmi_forecast().decode("utf-8"))
    print("  -> tests/fixtures/fmi/forecast_temperature.xml")

    print("Fetching FMI history...")
    with open(FIXTURES_DIR / "fmi" / "history_temperature.xml", "w") as f:
        f.write(fetch_fmi_history().decode("utf-8"))
    print("  -> tests/fixtures/fmi/history_temperature.xml")

    # Sähkötin
    print("Fetching Sähkötin prices...")
    data = fetch_sahkotin_prices()
    with open(FIXTURES_DIR / "sahkotin" / "prices.json", "w") as f:
        json.dump(data, f, indent=2)
    print("  -> tests/fixtures/sahkotin/prices.json")

    # Holidays
    print("Fetching Finnish holidays...")
    data = fetch_holidays()
    with open(FIXTURES_DIR / "holidays" / "finnish_holidays.json", "w") as f:
        json.dump(data, f, indent=2)
    print("  -> tests/fixtures/holidays/finnish_holidays.json")

    # Open-Meteo
    print("Fetching Open-Meteo historical...")
    data = fetch_openmeteo_historical()
    with open(FIXTURES_DIR / "openmeteo" / "eu_wind_historical.json", "w") as f:
        json.dump(data, f, indent=2)
    print("  -> tests/fixtures/openmeteo/eu_wind_historical.json")

    print("Fetching Open-Meteo forecast...")
    data = fetch_openmeteo_forecast()
    with open(FIXTURES_DIR / "openmeteo" / "eu_wind_forecast.json", "w") as f:
        json.dump(data, f, indent=2)
    print("  -> tests/fixtures/openmeteo/eu_wind_forecast.json")

    print("\nDone! All cached responses refreshed.")


if __name__ == "__main__":
    main()
