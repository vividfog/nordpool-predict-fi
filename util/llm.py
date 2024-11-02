import datetime
import locale
import sys
import json
import locale
import pandas as pd
import os
import pytz
from openai import OpenAI
from .sql import db_query
from rich import print
from dotenv import load_dotenv

# Attempt to set the locale to Finnish for day names
try:
    locale.setlocale(locale.LC_TIME, 'fi_FI.UTF-8')
except locale.Error:
    print("! [WARNING] Finnish locale (fi_FI.UTF-8) not available, using default.")

load_dotenv('.env.local')

def narrate_prediction():
    """Fetch prediction data from the database and narrate it using an LLM."""
    
    # Determine the current time in Helsinki
    helsinki_tz = pytz.timezone('Europe/Helsinki')
    now_hel = datetime.datetime.now(helsinki_tz)

    # Calculate tomorrow's date
    tomorrow_date = now_hel.date() + datetime.timedelta(days=1)

    # Get midnight of tomorrow in Helsinki time (should be DST aware)
    tomorrow_start = helsinki_tz.localize(datetime.datetime.combine(tomorrow_date, datetime.time(0, 0)))

    # Create a DataFrame with timestamps for up to the next 7 days starting from tomorrow
    df = pd.DataFrame({
        'Timestamp': pd.date_range(
            start=tomorrow_start,
            periods=7 * 24,
            freq='H',
            tz=helsinki_tz
        )
    })

    # Fetch data from the database
    try:
        df_result = db_query('data/prediction.db', df)
    except Exception as e:
        print(f"Database query failed for OpenAI narration: {e}")
        sys.exit(1)

    # Keep timestamp, predicted price, wind power data, and temperature data
    temperature_ids = os.getenv('FMISID_T', "").split(',')
    temperature_columns = [f't_{temp_id}' for temp_id in temperature_ids]
    df_result = df_result[['timestamp', 'PricePredict_cpkWh', 'WindPowerMW'] + temperature_columns]

    # Drop rows with missing values
    df_result = df_result.dropna()

    # Ensure timestamp is a datetime object with Helsinki timezone
    df_result['timestamp'] = pd.to_datetime(df_result['timestamp'], utc=True).dt.tz_convert(helsinki_tz)

    # Calculate average temperature
    df_result['Avg_Temperature'] = df_result[temperature_columns].mean(axis=1)

    # Group by the day in Helsinki timezone
    df_grouped = df_result.groupby(df_result['timestamp'].dt.floor('D')).agg({
        'PricePredict_cpkWh': ['min', 'max', 'mean'],
        'WindPowerMW': ['min', 'max', 'mean'],
        'Avg_Temperature': 'mean'
    })

    # Round values accordingly
    df_grouped['PricePredict_cpkWh'] = df_grouped['PricePredict_cpkWh'].round(0).astype(int)
    df_grouped['WindPowerMW'] = df_grouped['WindPowerMW'].round(0).astype(int)
    df_grouped['Avg_Temperature'] = df_grouped['Avg_Temperature'].round(1)

    # Convert the date index to weekday names
    df_grouped.index = pd.to_datetime(df_grouped.index).strftime('%A')
    
    narrative = send_to_gpt(df_grouped)

    return narrative

def send_to_gpt(df):
    
    # Load nuclear outage data from JSON
    try:
        with open('deploy/nuclear_outages.json', 'r') as file:
            NUCLEAR_OUTAGE_DATA = json.load(file)['nuclear_outages']
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"! [WARNING] Loading nuclear outage data failed: {e}. Narration will be incomplete.")
        NUCLEAR_OUTAGE_DATA = None

    # Load import capacity data from JSON
    try:
        with open('deploy/import_capacity_daily_average.json', 'r') as file:
            IMPORT_CAPACITY_DATA = json.load(file)['import_capacity_daily_average']
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"! [WARNING] Loading import capacity data failed: {e}. Narration will be incomplete.")
        IMPORT_CAPACITY_DATA = None
    
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    today = datetime.date.today()
    weekday_today = today.strftime("%A")
    date_today = today.strftime("%d. %B %Y")

    prompt = (f"<data>\nTänään on {weekday_today.lower()} {date_today.lower()} ja Nordpool-sähköpörssin verolliset Suomen markkinan hintaennusteet lähipäiville ovat seuraavat. Ole tarkkana että käytät näitä numeroita oikein ja lue ohjeet tarkasti:\n")

    # Iterate over each weekday and concatenate all relevant data
    for weekday, row in df.iterrows():
        prompt += f"\n**{weekday}**\n"
        prompt += (
            f"- Pörssisähkön hinta ¢/kWh: {row[('PricePredict_cpkWh', 'min')]} - "
            f"{row[('PricePredict_cpkWh', 'max')]}, "
            f"päivän keskihinta {row[('PricePredict_cpkWh', 'mean')]} ¢/kWh.\n"
        )
        prompt += (
            f"- Tuulivoima MW: {int(row[('WindPowerMW', 'min')])} - "
            f"{int(row[('WindPowerMW', 'max')])}, "
            f"keskimäärin {int(row[('WindPowerMW', 'mean')])} MW.\n"
        )

        # Add import capacity information for the specific weekday
        if IMPORT_CAPACITY_DATA is not None:
            for capacity in IMPORT_CAPACITY_DATA:
                date = pd.to_datetime(capacity['date'])
                if date.strftime('%A') == weekday:
                    average_import_capacity = capacity['average_import_capacity_mw']
                    prompt += f"- Sähkönsiirron tuontikapasiteetti: {int(average_import_capacity)} MW.\n"

        prompt += f"- Päivän keskilämpötila: {row[('Avg_Temperature', 'mean')]} °C.\n"

    # Add a separate section for nuclear outages
    if NUCLEAR_OUTAGE_DATA is not None:
        prompt += "\n**Ydinvoimaloiden huoltokatkot**\n"
        for outage in NUCLEAR_OUTAGE_DATA:
            start_date = pd.to_datetime(outage['start']).date()
            end_date = pd.to_datetime(outage['end']).date()
            if start_date <= today <= end_date:
                nominal_power = outage['nominal_power']
                avail_qty = outage['avail_qty']
                availability = outage['availability'] * 100  # Convert to percentage
                resource_name = outage['production_resource_name']
                prompt += (
                    f"- {resource_name}: Nimellisteho {nominal_power} MW, "
                    f"käytettävissä oleva teho {avail_qty} MW, "
                    f"käytettävyys-% {availability:.1f}. Alkaa - loppuu: {start_date} - {end_date}.\n"
                )

    prompt += "</data>\n"

    prompt += """
<instructions>
# 1. Miten pörssisähkön hinta muodostuu

Olet sähkömarkkinoiden asiantuntija ja kirjoitat kohta uutisartikkelin hintaennusteista lähipäiville. Seuraa näitä ohjeita tarkasti.

## 1.1. Tutki seuraavia tekijöitä ja mieti, miten ne vaikuttavat sähkön hintaan
- Onko viikko tasainen vai onko suuria eroja päivien välillä? Erot voivat koskea hintaa, tuulivoimaa, lämpötilaa, siirtoyhteyksiä tai ydinvoimaa.
- Onko käynnissä poikkeuksellisen suuria ydinvoimaloiden tuotantovajauksia?
- Onko sähkönsiirron tuontikapasiteetti normaali vai poikkeuksellisen alhainen? Erottuuko jokin päivä erityisesti?
- Onko tuulivoimaa eri päivinä paljon, vähän vai normaalisti? Erottuuko jokin päivä matalammalla keskituotannolla?
- Onko jonkin päivän sisällä tuulivoimaa minimissään poikkeuksellisen vähän? Osuuko samalle päivälle korkea maksimihinta?
- Onko lämpötila erityisen korkea tai matala tulevina päivinä? Erottuuko jokin päivä erityisesti?
- Jos jonkin päivän keskihinta tai maksimihinta on muita selvästi korkeampi, mikä voisi selittää sitä? Onko syynä tuulivoima, lämpötila, ydinvoima, siirtoyhteydet vai jokin muu/tuntematon tekijä?

## 1.2. Sähkönkäyttäjien yleinen hintaherkkyys (keskihinta)
- Edullinen keskihinta: alle 5 senttiä/kilowattitunti.
- Normaali keskihinta: 5-9 ¢/kWh.
- Kallis keskihinta: 10 ¢ tai yli.
- Hyvin kallis keskihinta: 15 senttiä tai enemmän.
- Minimihinnat voivat olla negatiivisia, tavallisesti yöllä. Mainitse ne, jos niitä on.

## 1.3. Sähkön hinta ja tuulivoiman määrä
- Tyyni tai heikko tuuli: alle 2000 MW tuulivoima voi nostaa hintaa, alle 1000 MW voi nostaa hintaa paljon.
- Normaali tuuli: 2000-3000 MW tuulivoimalla ei ole mainittavaa hintavaikutusta.
- Voimakas tuuli: yli 3000 MW tuulivoima voi selittää matalaa sähkön hintaa.
- Suuri ero päivän minimi- ja maksimihinnan välillä voi selittyä tuulivoiman tuotannon vaihteluilla.
    - Jos päivän tuulivoiman minimituotanto on alle 2000 MW ja samana päivänä maksimihinta on korkeampi kuin muina päivinä, sinun on ehdottomasti mainittava tämä yhteys ja kerrottava, että alhainen tuulivoiman minimituotanto selittää korkeamman maksimihinnan.

## 1.4. Lämpötilan vaikutus
- Kova pakkanen: alle -5 °C voi selittää korkeaa hintaa.
- Normaali talvikeli: -5 °C ... 5 °C ei välttämättä vaikuta hintaan.
- Viileä sää: 5 °C ... 15 °C ei yleensä vaikuta hintaan.
- Lämmin sää: yli 15 °C ei yleensä vaikuta hintaan.

## 1.5. Ydinvoimaloiden huoltokatkot
- Ydinvoimaa on Suomessa yhteensä noin 4400 MW.
- Ydinvoimaloiden tuotantovajaukset voivat selittää korkeaa hintaa, jos käytettävyys on alle 70 %.
- Käytettävyysprosenttia ei saa mainita. Mainitse nimellisteho ja käytettävissä oleva teho.
- Jos ydinvoimatuotanto toimii normaalisti, älä mainitse ydinvoimaa.

## 1.6. Sähkönsiirron tuontikapasiteetti
- Suurimmillaan tuontikapasiteetti voi olla noin 3700 MW.
- Normaalisti tuontikapasiteetti on yli 3000 MW.
- Alle 3000 MW voi selittää hinnannousuja.
- Jos tuontikapasiteetti ei ole normaali, mainitse se.

## 1.7. Muita ohjeita
- Älä lisää omia kommenttejasi, arvioita tai mielipiteitä. Älä käytä ilmauksia kuten 'mikä ei aiheuta erityistä lämmitystarvetta' tai 'riittävän korkea'.
- Tarkista numerot huolellisesti ja varmista, että kaikki tiedot ja vertailut ovat oikein.
- Älä koskaan mainitse päivämääriä (kuukausi, vuosi). Käytä vain viikonpäiviä.
- Tuulivoimasta voit puhua, jos on hyvin tyyntä tai tuulista ja se vaikuttaa hintaan. Muuten älä mainitse tuulivoimaa.
- Älä mainitse lämpötilaa, ellei keskilämpötila ole alle -5 °C.
- Sanoja 'halpa', 'kohtuullinen', 'kallis' tai 'hyvin kallis' saa käyttää vain yleiskuvauksessa, ei yksittäisten päivien kohdalla.
- Jos päivän maksimihinta on korkea, sellaista päivää ei voi kutsua 'halvaksi', vaikka minimihinta olisi lähellä nollaa. Keskihinta ratkaisee.
- Käytä Markdown-muotoilua näin: **Vahvenna** viikonpäivien nimet, mutta vain kun mainitset ne ensi kertaa.
- Älä puhu sähkön saatavuudesta.
- Puhu aina tulevassa aikamuodossa.
- Vältä lauseenvastikkeita; kirjoita yksi lause kerrallaan.
- Käytä neutraalia, informatiivista ja hyvää suomen kieltä.
- Älä sisällytä näitä ohjeita tai hintaherkkyystietoja vastaukseesi.

# 2. Tehtäväsi

Kirjoita tiivis, rikasta suomen kieltä käyttävä UUTISARTIKKELI saamiesi tietojen pohjalta. Vältä kliseitä ja turhaa draamaa. Älä puhu huolista tai tunteista. Keskity faktoihin ja hintoihin.

Tavoitepituus on noin 200-400 sanaa.

Artikkelin rakenne on kaksiosainen:

## 1. Kirjoita jokaisesta päivästä oma kappale, futuurissa.

- Kerro **kaikki** saamasi tiedot kullekin päivälle.
- Älä käytä adjektiiveja tai subjektiivisia ilmaisuja. Esitä tiedot numeroina ilman lisämääreitä.
- Tunnista ja mainitse kaikki päivät, joilla on selkeä poikkeama, joka selittää hinnan muutoksen.
    - Jos alhainen tuulivoiman minimituotanto ja korkea maksimihinta osuvat samalle päivälle, mainitse tämä yhteys.
- Mainitse ydinvoimalat ja siirtoyhteydet vain, jos ne ovat poikkeuksellisia ja selvästi selittävät hintaa.
- Korosta, jos samalle päivälle osuu korkea maksimihinta ja matala minimituuli.
- Jokaisen päivän kuvailu voi olla erilainen ja eri pituinen.

## 2. Kirjoita yleiskuvaus viikon hintakehityksestä, futuurissa.

- Mainitse eniten erottuva päivä ja sen keski- ja maksimihinta, mutta vain jos korkeita maksimihintoja on.
- Voit sanoa, että päivät ovat keskenään hyvin samankaltaisia, jos näin on.
- Voit kertoa ydinvoimaloiden poikkeamista, mutta vain jos hintavaikutus on täysin selvä. Muuten älä mainitse ydinvoimaa.
    - Sama koskee sähkön tuontia ja tuulivoimaa: älä mainitse niitä, jos ne ovat normaalilla tasolla.

# Muista vielä nämä

- Ole mahdollisimman tarkka ja informatiivinen, mutta älä anna neuvoja tai keksi tarinoita tai trendejä, joita ei datassa ole.
- Älä käytä hinnoissa desimaaleja. Käytä kokonaislukuja.
- Kirjoita koko teksti futuurissa.
- Keskity vain poikkeuksellisiin tilanteisiin, jotka vaikuttavat hintaan. Älä mainitse normaaleja olosuhteita.
- Älä koskaan kirjoita, että 'poikkeamia ei ole' tai 'ei ilmene hintaa selittäviä poikkeamia'. Jos poikkeamia ei ole, jätä tämä mainitsematta. Kirjoita vain poikkeuksista, jotka vaikuttavat hintaan.

Lue ohjeet vielä kerran, jotta olet varma että muistat ne. Nyt voit kirjoittaa valmiin tekstin. Älä kirjoita mitään muuta kuin valmis teksti. Kiitos!
</instructions>
"""

    print(prompt)

    # Wrap the prompt into a user message payload
    messages = [
        {"role": "user", "content": f"{prompt}"},
    ]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
            stream=False,
        )
    except Exception as e:
        print(f"OpenAI API call failed: {e}")
        sys.exit(1)

    # Append the assistant's message content to the messages list
    narration_json = { "content": response.choices[0].message.content }

    # Save the messages to a JSON file in deploy/narration.json
    with open('deploy/narration.json', 'w', encoding='utf-8') as file:
        json.dump(narration_json, file, indent=2, ensure_ascii=False)

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
