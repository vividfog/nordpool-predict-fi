import sys
import os
import json
import math
import time
import locale
import datetime
import pandas as pd
import pytz
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime as dt
from .sql import db_query
from .sahkotin import sahkotin_tomorrow
from .logger import logger
from .llm_prompts import narration_prompt

# Attempt to set the locale to Finnish for day names
try:
    locale.setlocale(locale.LC_TIME, "fi_FI.UTF-8")
except locale.Error:
    logger.warning("locale (fi_FI.UTF-8) not available, using default.")

load_dotenv(".env.local")

LLM_API_BASE = os.getenv("LLM_API_BASE", None)
LLM_API_KEY = os.getenv("LLM_API_KEY", None)
LLM_MODEL = os.getenv("LLM_MODEL", None)

if None in (LLM_API_BASE, LLM_API_KEY, LLM_MODEL):
    logger.error(
        "LLM API credentials not found in .env.local, can't narrate, will exit. See .env.template for a sample."
    )
    sys.exit(1)

logger.debug(f"LLM conf: '{LLM_API_BASE}': '{LLM_MODEL}'")

# region spike risk
def spike_price_risk(df):
    """Calculate the risk of price spikes for each day."""
    df["Price_Range"] = df["PricePredict_cpkWh_max"] - df["PricePredict_cpkWh_min"]
    df["Price_StdDev"] = df["PricePredict_cpkWh_mean"].rolling(window=2).std().fillna(0)

    df["Spike_Risk"] = 0

    # Price or range thresholds
    df.loc[df["PricePredict_cpkWh_max"] > 15, "Spike_Risk"] += 2
    df.loc[df["Price_Range"] > 10, "Spike_Risk"] += 1
    df.loc[df["Price_StdDev"] > 4, "Spike_Risk"] += 1

    # Wind thresholds
    df.loc[df["WindPowerMW_min"] < 1000, "Spike_Risk"] += 1
    df.loc[df["WindPowerMW_mean"] < 2500, "Spike_Risk"] += 1
    df.loc[
        df["WindPowerMW_mean"] > 3000, "Spike_Risk"
    ] -= 1  # Less likely to spike if wind is strong

    # Temperature thresholds
    df.loc[df["Avg_Temperature_mean"] < -5, "Spike_Risk"] += 1
    df.loc[df["Avg_Temperature_mean"] > 15, "Spike_Risk"] -= 1

    return df

# region df
def narrate_prediction(deploy=False, commit=False):
    """Fetch prediction data from the database and narrate it using an LLM."""
    helsinki_tz = pytz.timezone("Europe/Helsinki")
    now_hel = datetime.datetime.now(helsinki_tz)

    # Calculate tomorrow's date, midnight
    tomorrow_date = now_hel.date() + datetime.timedelta(days=1)
    tomorrow_start = helsinki_tz.localize(
        datetime.datetime.combine(tomorrow_date, datetime.time(0, 0))
    )

    # Create a DataFrame with timestamps for the next 7 days (hourly)
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                start=tomorrow_start, periods=7 * 24, freq="H", tz=helsinki_tz
            )
        }
    )

    try:
        df_result = db_query("data/prediction.db", df)
    except Exception as e:
        logger.info(f"Database query failed for OpenAI narration: {e}")
        raise e

    # Keep needed columns
    temperature_ids = os.getenv("FMISID_T", "").split(",")
    temperature_columns = [f"t_{temp_id}" for temp_id in temperature_ids]
    cols_needed = [
        "timestamp",
        "PricePredict_cpkWh",
        "WindPowerMW",
        "holiday",
    ] + temperature_columns
    df_result = df_result[cols_needed].dropna()

    # Convert timestamp to Helsinki time
    df_result["timestamp"] = pd.to_datetime(
        df_result["timestamp"], utc=True
    ).dt.tz_convert(helsinki_tz)

    # Add 'date' column for grouping
    df_result["date"] = df_result["timestamp"].dt.date

    # Compute average temperature
    df_result["Avg_Temperature"] = df_result[temperature_columns].mean(axis=1)
    df_result["holiday"] = df_result["holiday"].astype(int)

    # Prepare daily DataFrame
    df_daily = df_result.groupby(df_result["timestamp"].dt.floor("D")).agg(
        {
            "PricePredict_cpkWh": ["min", "max", "mean"],
            "WindPowerMW": ["min", "max", "mean"],
            "Avg_Temperature": "mean",
            "holiday": "any",
        }
    )
    df_daily.columns = [f"{col[0]}_{col[1]}" for col in df_daily.columns.values]
    df_daily.reset_index(inplace=True)
    df_daily.rename(columns={"timestamp_": "timestamp"}, inplace=True)

    df_daily = df_daily.rename(
        columns={
            "PricePredict_cpkWh_min": "PricePredict_cpkWh_min",
            "PricePredict_cpkWh_max": "PricePredict_cpkWh_max",
            "PricePredict_cpkWh_mean": "PricePredict_cpkWh_mean",
            "WindPowerMW_min": "WindPowerMW_min",
            "WindPowerMW_max": "WindPowerMW_max",
            "WindPowerMW_mean": "WindPowerMW_mean",
            "Avg_Temperature_mean": "Avg_Temperature_mean",
            "holiday_any": "holiday_any",
        }
    )

    # Apply spike risk logic to daily
    df_daily = spike_price_risk(df_daily)

    # Round columns
    df_daily["PricePredict_cpkWh_min"] = df_daily["PricePredict_cpkWh_min"].round(1)
    df_daily["PricePredict_cpkWh_max"] = df_daily["PricePredict_cpkWh_max"].round(1)
    df_daily["PricePredict_cpkWh_mean"] = df_daily["PricePredict_cpkWh_mean"].round(1)

    df_daily["WindPowerMW_min"] = df_daily["WindPowerMW_min"].round().astype(int)
    df_daily["WindPowerMW_max"] = df_daily["WindPowerMW_max"].round().astype(int)
    df_daily["WindPowerMW_mean"] = df_daily["WindPowerMW_mean"].round().astype(int)
    df_daily["Avg_Temperature_mean"] = df_daily["Avg_Temperature_mean"].round(1)

    df_daily["weekday"] = df_daily["timestamp"].dt.strftime("%A")
    df_daily.set_index("weekday", inplace=True)

    # Include daily average wind
    df_daily["WindPowerMW_avg"] = df_daily["WindPowerMW_mean"]

    # Intraday DataFrame can remain in hourly format
    # Round columns to match daily's style
    df_result["PricePredict_cpkWh"] = df_result["PricePredict_cpkWh"].round(1)
    df_result["WindPowerMW"] = df_result["WindPowerMW"].round().astype(int)
    df_result["Avg_Temperature"] = df_result["Avg_Temperature"].round(1)

    # Send both dataframes to GPT
    narrative = llm_generate(
        df_daily, df_result, helsinki_tz, deploy=deploy, commit=commit
    )

    return narrative

# region generate()
def llm_generate(df_daily, df_intraday, helsinki_tz, deploy=False, commit=False):
    # Load nuclear outage data
    try:
        with open("deploy/nuclear_outages.json", "r") as file:
            NUCLEAR_OUTAGE_DATA = json.load(file).get("nuclear_outages", [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(
            f"Loading nuclear outage data failed: {e}. Narration will be incomplete."
        )
        NUCLEAR_OUTAGE_DATA = []

    client = OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_API_BASE,
    )

    today = datetime.date.today()
    weekday_today = today.strftime("%A")
    date_today = f"{int(today.strftime('%d'))}. {today.strftime('%B').lower()}ta {today.strftime('%Y')}"
    time_now = datetime.datetime.now().strftime("%H:%M")

    # Build the prompt
    prompt = "<data>\n"
    prompt += f"  Olet osa Sähkövatkain-nimistä verkkopalvelua, joka arvioi pörssisähkön hintaa noin viikon verran eteenpäin. Nordpool-sähköpörssin verolliset Suomen markkinan hintaennusteet lähipäiville ovat seuraavat (viimeksi päivitetty: {weekday_today.lower()}na klo {time_now}).\n"

    # region _hourly
    prompt += f"  <tuntikohtainen_ennuste huom='Yksityiskohdat tiedoksi sinulle — mutta huomaathan että lopulliseen artikkeliin tulee *päiväkohtainen* ennuste, ei tuntikohtainen. Kts. alempana.'>\n"
    for date_value, group_df in df_intraday.groupby("date", sort=False):
        # Pick the weekday name (e.g. 'Maanantai') from the first row in this group
        weekday_name = group_df["timestamp"].dt.strftime("%A").iloc[0]
        weekday_name = weekday_name.lower()

        prompt += f"    <päivä viikonpäivä='{weekday_name}'>\n"
        compact_data = []

        # Identify the top-priced hour
        top_hour_row = group_df.loc[group_df["PricePredict_cpkWh"].idxmax()]
        top_hour_time = top_hour_row["timestamp"].strftime("%H:%M")

        for _, hour_row in group_df.iterrows():
            time_str = hour_row["timestamp"].strftime("%H:%M")
            price_str = f"{hour_row['PricePredict_cpkWh']} c"
            wind_power_str = f"{hour_row['WindPowerMW']} MW"

            # Add marker if this is the top-priced hour
            # if time_str == top_hour_time:
            #     compact_data.append(f"   {time_str} | {price_str} | {wind_power_str} | päivän huipputunti\n   ")
            # else:

            compact_data.append(f"   {time_str} | {price_str} | {wind_power_str}\n   ")

        prompt += "    " + " ".join(compact_data)
        prompt += "    </päivä>\n"
    prompt += f"  </tuntikohtainen_ennuste>\n"

    # We'll need the current Helsinki time for the "after 14:00 for tomorrow" check
    now_hel = datetime.datetime.now(helsinki_tz)
    tomorrow_date = (now_hel + datetime.timedelta(days=1)).date()

    # region _daily
    # Daily rows
    for weekday, row in df_daily.iterrows():
        weekday = weekday.lower()
        prompt += f"\n  **{weekday}**\n"
        if row["holiday_any"]:
            prompt += "  - Tämä on pyhäpäivä. Energian kysyntä voi olla normaalia alhaisempi, mikä saattaa pudottaa hintaa.\n"
        prompt += (
            f"  - Pörssisähkön odotettu hinta ¢/kWh: {row['PricePredict_cpkWh_min']} - "
            f"{row['PricePredict_cpkWh_max']}, "
            f"päivän odotettu keskihinta {row['PricePredict_cpkWh_mean']} ¢/kWh.\n"
        )
        prompt += (
            f"  - Tuulivoima MW: {row['WindPowerMW_min']} - "
            f"{row['WindPowerMW_max']}, "
            f"keskimäärin {row['WindPowerMW_mean']} MW.\n"
        )
        prompt += f"  - Päivän keskilämpötila: {row['Avg_Temperature_mean']} °C.\n"

        # Skip spike risk if it's tomorrow AND the current time is >=14:00
        skip_spike_for_tomorrow = (
            row["timestamp"].date() == tomorrow_date and now_hel.hour >= 14
        )

        if not skip_spike_for_tomorrow:
            # Spike risk note
            if row["Spike_Risk"] >= 3:
                risk_upper_boundary = int(
                    math.ceil(row["PricePredict_cpkWh_mean"] * 3.5 / 10.0) * 10
                )
                risk_lower_boundary = int(
                    math.ceil(row["PricePredict_cpkWh_mean"] * 2 / 10.0) * 10
                )
                if risk_upper_boundary != risk_lower_boundary:
                    prompt += f"  - TÄRKEÄÄ MAINITA: Korkea riski hintapiikeille yllä ennustettuun verrattuna {weekday}na, jopa {risk_lower_boundary}-{risk_upper_boundary} ¢ yksittäisinä tunteina.\n"
                else:
                    prompt += f"  - TÄRKEÄÄ MAINITA: Korkea riski hintapiikeille yllä ennustettuun verrattuna {weekday}na, jopa {risk_upper_boundary} ¢ yksittäisinä tunteina.\n"
            elif row["Spike_Risk"] >= 1:
                risk_upper_boundary = int(
                    math.ceil(row["PricePredict_cpkWh_mean"] * 2 / 10.0) * 10
                )
                prompt += f"  - HUOM: Riski hintapiikeille yllä ennustettuun verrattuna {weekday}na, jopa {risk_upper_boundary} ¢ yksittäisinä tunteina.\n"
            else:
                prompt += f"  - Hintapiikkien riski tälle päivälle on niin pieni, että älä puhu hintapiikeistä artikkelissa ollenkaan, kun puhut {weekday}sta.\n\n"

    # region _nuclear
    # Add nuclear outages if any
    if NUCLEAR_OUTAGE_DATA:
        nuclear_outage_section = "  **Ydinvoimalat**\n"
        section_empty = True

        for outage in NUCLEAR_OUTAGE_DATA:
            start_date_utc = pd.to_datetime(outage["start"])
            end_date_utc = pd.to_datetime(outage["end"])

            start_date_hel = start_date_utc.tz_convert(helsinki_tz)
            end_date_hel = end_date_utc.tz_convert(helsinki_tz)

            if start_date_hel.date() <= today <= end_date_hel.date():
                availability = outage.get("availability", 1) * 100
                if availability < 70:
                    section_empty = False
                    nominal_power = outage.get("nominal_power")
                    avail_qty = outage.get("avail_qty")
                    resource_name = outage.get(
                        "production_resource_name", "Tuntematon voimala"
                    )

                    # Format the dates for Finland without leading zeros
                    start_date_str = f"{int(start_date_hel.strftime('%d'))}.{int(start_date_hel.strftime('%m'))}.{start_date_hel.year} klo {start_date_hel.strftime('%H')}"
                    end_date_str = f"{int(end_date_hel.strftime('%d'))}.{int(end_date_hel.strftime('%m'))}.{end_date_hel.year} klo {end_date_hel.strftime('%H')}"

                    # Did the outage already begin?
                    start_phrase = "Alkoi" if start_date_hel < pd.Timestamp.now(helsinki_tz) else "Alkaa"

                    nuclear_outage_section += (
                        f"  - {resource_name}: Nimellisteho {nominal_power} MW, "
                        f"käytettävissä oleva teho {avail_qty} MW, "
                        f"käytettävyys-% {availability:.1f}. {start_phrase} - loppuu: "
                        f"{start_date_str} - {end_date_str}. Päättymisaika on ennuste. "
                        f"Päivämäärät ovat suomalaisessa muodossa: päivä, kuukausi, vuosi.\n"
                        f"\n"
                    )

        if not section_empty:
            prompt += nuclear_outage_section

    prompt += "</data>\n"

    prompt += narration_prompt.format(LLM_MODEL=LLM_MODEL)

    logger.info(prompt)

    messages = [{"role": "user", "content": prompt}]

    # region _llm()
    def llm_call(messages):

        # Avoid rate limits on free APIs
        time.sleep(5)

        try:
            logger.debug(
                f"llm_call(): '{LLM_API_BASE}': '{LLM_MODEL}': payload: {len(messages)} messages"
            )
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=1536,
                stream=False,
            )
            
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM API call failed: {e}", exc_info=True)
            logger.info(f"LLM API call failed: {e}")
            raise e

    # Generate a narration
    narration = llm_call(messages)
    messages.append({"role": "assistant", "content": narration})

    # region _ingress
    messages.append(
        {
            "role": "user",
            "content": "Nyt luo tälle artikkelille yhden rivin ingressi (noin 20-40 sanaa). Vältä toistoa ja pysy ylätasolla: esim. mahdollisia huoltokatkoja ei ole tarpeen toistaa ingressissä. Älä kirjoita mitään muuta kuin ingressi. Muotoile ingressi kursiivilla käyttämällä markdown-syntaksia. Kiitos!",
        }
    )

    ingress = llm_call(messages)
    
    # Strip off any quotes from around the ingress
    ingress = ingress.strip("\"'")
    
    messages.append({"role": "assistant", "content": ingress})

    # Full narration with Markdown formatting
    narration = ingress + "\n\n" + narration

    # English translation
    messages.append(
        {
            "role": "user",
            "content": "Finally, translate the entire ingress + article to English, using the same formatting as above. Do not write anything else. Thank you!",
        }
    )
    narration_en = llm_call(messages)
    messages.append({"role": "assistant", "content": narration_en})

    # region _commit
    def archive(content, filename, folders, is_json=True, indent=2):
        """Save content as JSON or markdown to specified folders."""
        for folder in folders:
            path = os.path.join(folder, filename)
            with open(path, "w", encoding="utf-8") as file:
                if is_json:
                    json.dump(content, file, indent=indent, ensure_ascii=False)
                else:
                    file.write(content + "\n")
            logger.info(f"{filename} saved to '{path}'")

    if deploy and commit:
        DEPLOY_FOLDER_PATH = os.getenv("DEPLOY_FOLDER_PATH", "deploy")
        ARCHIVE_FOLDER_PATH = os.getenv("ARCHIVE_FOLDER_PATH", "archive")

        archive_dir = os.path.join(ARCHIVE_FOLDER_PATH, dt.now().strftime('%Y-%m-%d_%H%M%S'))
        os.makedirs(archive_dir, exist_ok=True)

        folders = [DEPLOY_FOLDER_PATH, archive_dir]

        # Save the full conversation
        archive(messages, "narration_full.json", folders, is_json=True)

        # Save the Markdown narration
        archive({"content": narration}, "narration.json", folders, is_json=True)
        archive(narration, "narration.md", folders, is_json=False)
        archive(narration_en, "narration_en.md", folders, is_json=False)
    else:
        logger.info(narration)

    return narration

if __name__ == "__main__":
    logger.info(f"This is not meant to be executed directly.")
    exit()
