import datetime
import sys
import locale
import pandas as pd
import os
import pytz
from openai import OpenAI
from .sql import db_query
from rich import print

import pytz

def narrate_prediction(timestamp):
    """Fetch prediction data from the database and narrate it using an LLM."""

    # Create a DataFrame with timestamps for the next 5 days    
    df = pd.DataFrame({'Timestamp': pd.date_range(timestamp, timestamp + datetime.timedelta(days=5), freq='h')})

    # Fetch data from the database
    try:
        df_result = db_query('data/prediction.db', df)
    except Exception as e:
        print(f"Database query failed for OpenAI narration: {e}")
        sys.exit(1)

    # Keep timestamp, predicted price, and wind power data
    df_result = df_result[['timestamp', 'PricePredict_cpkWh', 'WindPowerMW']]

    # Drop rows with missing values
    df_result = df_result.dropna()

    # Ensure the timestamp is a datetime object
    df_result['timestamp'] = pd.to_datetime(df_result['timestamp'])

    # Define the Helsinki timezone
    helsinki_tz = pytz.timezone('Europe/Helsinki')

    # Localize to UTC if naive, then convert to Helsinki timezone
    if df_result['timestamp'].dt.tz is None:
        df_result['timestamp'] = df_result['timestamp'].dt.tz_localize('UTC')
    df_result['timestamp'] = df_result['timestamp'].dt.tz_convert(helsinki_tz)

    # Convert WindPowerMW to gigawatts (GW)
    df_result['WindPowerGW'] = (df_result['WindPowerMW'] / 1000)

    # Group by date and calculate min, max, and average price, as well as the average wind power
    df_result['date'] = df_result['timestamp'].dt.date
    df_grouped = df_result.groupby('date').agg({
        'PricePredict_cpkWh': ['min', 'max', 'mean'],
        'WindPowerGW': 'mean'
    })

    # Round price values to integer
    df_grouped['PricePredict_cpkWh'] = df_grouped['PricePredict_cpkWh'].round(0).astype(int)
    
    # Round wind power values to 1 decimal
    df_grouped['WindPowerGW'] = df_grouped['WindPowerGW'].round(1)

    # Convert date index to weekday names and retain it in the DataFrame
    df_grouped.index = pd.to_datetime(df_grouped.index).strftime('%A')

    print("→ Narration stats fetched from predictions.db:\n", df_grouped)

    narrative = send_to_gpt(df_grouped)

    # Return the prediction as text
    return narrative

def send_to_gpt(df):
    """
    Send the processed data to an OpenAI's GPT model and return the narrative.
    The input prompt is in Finnish and the output is expected to be in Finnish as well.
    """
    # Attempt to set the locale to Finnish for day names
    try:
        locale.setlocale(locale.LC_TIME, 'fi_FI')
    except locale.Error:
        print("Finnish locale not available, using default.")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    today = datetime.date.today()
    weekday_today = today.strftime("%A")
    date_today = today.strftime("%d.%m.%Y")

    prompt = (f"Tänään on {weekday_today.lower()} {date_today} ja ennusteet lähipäiville ovat seuraavat. Ole tarkkana että käytät näitä numeroita oikein:\n\n")

    for weekday, row in df.iterrows():
        prompt += (
            f"{weekday}: Pörssisähkön hinta min {row[('PricePredict_cpkWh', 'min')]} ¢/kWh, max {row[('PricePredict_cpkWh', 'max')]} ¢/kWh, keskihinta {row[('PricePredict_cpkWh', 'mean')]} ¢/kWh. "
            f"Keskimääräinen tuulivoimamäärä {row[('WindPowerGW', 'mean')]} GW.\n\n"
        )
      
    prompt += """
Olet tekoäly, joka kirjoittaa hintatiedotteen sähkönkäyttäjille.

Sähkönkäyttäjien yleinen hintaherkkyys: 
- Sähkönkäyttäjille halpa hinta tarkoittaa alle 5 ¢. Tätä korkeampi hinta ei ole koskaan halpa.
- Kohtuullinen keskihinta on 5-9 senttiä. 
- Kallis keskihinta on 10 senttiä tai yli.
- Hyvin kallis keskihinta on 15 senttiä tai enemmän.

Tuulivoimasta:
- Tyyntä: Alle 1 GW tuulivoima voi nostaa sähkön hintaa selvästi.
- Kova tuuli: Yli 3 GW tuulivoima voi laskea sähkön hintaa selvästi.

Muita ohjeita, joita sinun tulee ehdottomasti noudattaa:
- Älä anna mitään neuvoja! Tehtäväsi on puhua vain hinnoista! Ole perinpohjainen ja tarkka.
- Tämä tarkoittaa, että kun viittaat hintoihin, kirjoita niistä numeroilla eikä adjektiiveilla.
- Yllä olevat hintaherkkyystiedot on annettu tiedoksi vain sinulle. Älä käytä niitä vastauksessasi.
- Älä koskaan mainitse päivämääriä (kuukausi, vuosi), koska viikonpäivät ovat riittävä tieto. Jos käytät päivämääriä (kuten 31.1.2024), vastauksesi hylätään.
- Tuulivoimasta voit puhua jos jaksolla on hyvin tyyntä tai tuulista ja se voi selittää hintoja.
- Jos käytät sanoja 'halpa', 'kohtuullinen', 'kallis' tai 'hyvin kallis', voit käyttää niitä vain yhteenvetojen yhteydessä.
- Käytä Markdown-muotoilua näin: **Vahvenna** viikonpäivät, kuten '**maanantai**' tai '**torstaina**', mutta vain kun mainitset ne ensi kertaa.
- Koska tämä on ennustus, puhu aina tulevassa aikamuodossa eli futuurissa.
- Vältä lauseenvastikkeita: kirjoita yksi lause kerrallaan.

Kirjoita tiivis, viihdyttävä, rikasta suomen kieltä käyttävä UUTISARTIKKELI saamiesi tietojen pohjalta.

1. Alusta artikkeli yleiskuvauksella viikon hintakehityksestä. Mainitse, jos jokin päivä erottuu erityisesti. Käytä tässä adjektiiveja. Voit kertoa tuulivoiman trendeistä.

2. Kirjoita jokaisesta päivästä oma kappale keskittyen kyseisen päivän minimaalisuuteen ja maksimaalisuuteen hintaan numeroina. Vältä adjektiiveja. Älä mainitse tuulivoimaa tässä.

3. Päätä artikkeli yhteenvetoon, jossa arvioit viikon hintakehityksen ja kommentoit trendejä tai poikkeamia. Tässä osuudessa adjektiivien käyttö on sallittua.

Älä käytä hinnoissa desimaaleja. Käytä kokonaislukuja.

Tuulivoimassa voit käyttää desimaaleja.

Tavoitepituus on noin 200-300 sanaa.

Nyt voit kirjoittaa valmiin tekstin. Älä kirjoita mitään muuta kuin valmis teksti. Kiitos!
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": f"{prompt}"},
            ],
            temperature=0.3,
            max_tokens=1024,
            stream=False,
        )
    except Exception as e:
        print(f"OpenAI API call failed: {e}")
        sys.exit(1)

    return response.choices[0].message.content


def test_llm():
    # This is to test that the function works as expected   
    # Fetch the data from the beginning of today
    now = datetime.datetime.now(pytz.utc).replace(minute=0, second=0, microsecond=0)
    narration = narrate_prediction(now)
    print(narration)
    return narration

if __name__ == "__main__":
    print("This is not meant to be executed directly.")
    exit()