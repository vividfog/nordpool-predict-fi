import datetime
import sys
import locale
import pandas as pd
import os
import pytz
from openai import OpenAI
from .sql import db_query
from rich import print
from dotenv import load_dotenv

load_dotenv('.env.local')

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

    # Keep timestamp, predicted price, wind power data, and temperature data
    temperature_ids = os.getenv('FMISID_T').split(',')
    temperature_columns = [f't_{temp_id}' for temp_id in temperature_ids]
    df_result = df_result[['timestamp', 'PricePredict_cpkWh', 'WindPowerMW'] + temperature_columns]

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

    # Calculate average temperature
    df_result['Avg_Temperature'] = df_result[temperature_columns].mean(axis=1)

    # Group by date and calculate min, max, and average price, as well as the average wind power and temperature
    df_result['date'] = df_result['timestamp'].dt.date
    df_grouped = df_result.groupby('date').agg({
        'PricePredict_cpkWh': ['min', 'max', 'mean'],
        'WindPowerGW': 'mean',
        'Avg_Temperature': 'mean'
    })

    # Round price values to integer
    df_grouped['PricePredict_cpkWh'] = df_grouped['PricePredict_cpkWh'].round(0).astype(int)
    
    # Round wind power and temperature values to 1 decimal
    df_grouped['WindPowerGW'] = df_grouped['WindPowerGW'].round(1)
    df_grouped['Avg_Temperature'] = df_grouped['Avg_Temperature'].round(1)

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
            f"{weekday}: Pörssisähkön hinta: min {row[('PricePredict_cpkWh', 'min')]} ¢/kWh, max {row[('PricePredict_cpkWh', 'max')]} ¢/kWh, keskihinta {row[('PricePredict_cpkWh', 'mean')]} ¢/kWh. "
            f"Tuulivoima: keskiarvo {row[('WindPowerGW', 'mean')]} GW. "
            f"Päivän keskilämpötila: {row[('Avg_Temperature', 'mean')]} °C.\n---\n"
        )


    prompt += """
Olet tekoäly, joka kirjoittaa hintatiedotteen sähkönkäyttäjille.

Sähkönkäyttäjien yleinen hintaherkkyys, joka koskee **keskihintaa**:
- Sähkönkäyttäjille edullinen keskihinta tarkoittaa alle 5 ¢. Tätä korkeampi keskihinta ei ole koskaan halpa, vaikka yöllä minimihinta olisi lähellä nollaa tai jopa sen alle. Negatiiviset minimihinnat ovat mahdollisia, ja ne voi mainita, jos niitä on. Negatiivisia hintoja on tavallisesti vain yöllä.
- Normaali keskihinta on 5-9 senttiä.
- Kallis keskihinta on 10 senttiä tai yli.
- Hyvin kallis keskihinta on 15 senttiä tai enemmän.

Tuulivoimasta:
- Tyyni tai heikko tuuli: Alle 1 GW tuulivoima voi nostaa sähkön hintaa selvästi.
- Tavanomainen, riittävä tuuli: 1-3 GW tuulivoimalla ei välttämättä ole erityistä hintavaikutusta.
- Reipas tai voimakas tuuli: Yli 3 GW tuulivoima voi laskea sähkön hintaa selvästi.

Lämpötiloista:
- Kova pakkanen: Alle -10 °C voi nostaa sähkön hintaa selvästi.
- Normaali talvikeli: -10 °C - 5 °C voi nostaa sähkön hintaa vähän.
- Viileä sää: 5 °C - 15 °C ei välttämättä ole erityistä hintavaikutusta.
- Lämmin tai kuuma sää: Yli 15 °C ei välttämättä ole erityistä hintavaikutusta.

Muita ohjeita, joita sinun tulee ehdottomasti noudattaa:
- Älä anna mitään neuvoja! Tehtäväsi on puhua vain hinnoista! Ole perinpohjainen ja tarkka.
- Tämä tarkoittaa, että kun viittaat hintoihin, kirjoita niistä numeroilla eikä adjektiiveilla.
- Yllä olevat hintaherkkyystiedot on annettu tiedoksi vain sinulle. Älä käytä niitä vastauksessasi.
- Älä koskaan mainitse päivämääriä (kuukausi, vuosi), koska viikonpäivät ovat riittävä tieto. Jos käytät päivämääriä (kuten 31.1.2024), vastauksesi hylätään.
- Tuulivoimasta voit puhua jos jaksolla on hyvin tyyntä tai tuulista ja se voi selittää hintoja. Jos tuulivoimalla ei näytä olevan hintavaikutusta tällä jaksolla, sitä ei välttämättä tarvitse mainita ollenkaan.
- Lämpötilasta voit puhua jos jaksolla on erityisen kylmä pakkaspäivä joka voi nostaa lämmitystarvetta ja hintoja.
- Hyvin matala tuuli ja kova pakkanen voivat yhdessä nostaa hintoja.
- Jos käytät sanoja 'halpa', 'kohtuullinen', 'kallis' tai 'hyvin kallis', voit käyttää niitä vain yhteenvetojen yhteydessä.
- Jos päivän aikana on hyvin korkeita maksimihintoja, sellaista päivää ei voi kutsua 'halvaksi', vaikka yöllä minimihinta olisi lähellä nollaa. Keskihinta ratkaisee.
- Käytä Markdown-muotoilua näin: **Vahvenna** viikonpäivät, kuten '**maanantai**' tai '**torstaina**', mutta vain kun mainitset ne ensi kertaa.
- Koska tämä on ennustus, puhu aina tulevassa aikamuodossa eli futuurissa.
- Vältä lauseenvastikkeita: kirjoita yksi lause kerrallaan.
- Käytä saman tyyppistä kieltä kuin uutisartikkeleissa: neutraalia, informatiivista, rikasta, hyvää suomen kieltä.

Kirjoita tiivis, viihdyttävä, rikasta suomen kieltä käyttävä UUTISARTIKKELI saamiesi tietojen pohjalta. Vältä turhaa draamaa: jos poikkeamia ei ole ja päivät ovat keskenään hyvin samankaltaisia, pidä teksti toteavana ja neutraalina.

1. Alusta artikkeli yleiskuvauksella viikon hintakehityksestä, futuurissa. Mainitse, jos jokin päivä erottuu erityisesti, mutta vain jos poikkeamia edes on. Voit myös sanoa, että päivät ovat keskenään hyvin samankaltaisia, jos asia näin on. Käytä tässä adjektiiveja. Voit kertoa tuulivoiman trendeistä, jos trendejä näkyy. Pyri olemaan mahdollisimman tarkka ja informatiivinen, mutta älä anna neuvoja tai keksi tarinoita tai trendejä, joita ei ole.

2. Kirjoita jokaisesta päivästä futuurissa oma kappale keskittyen kyseisen päivän hintaan numeroina. Vältä adjektiiveja. Älä mainitse tuulivoimaa tässä.

3. Päätä artikkeli yhteenvetoon, jossa arvioit futuurissa tulevan viikon hintakehityksen ja kommentoit trendejä tai poikkeamia — jos niitä on.

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
