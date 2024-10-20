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
    locale.setlocale(locale.LC_TIME, 'fi_FI.UTF-8')  # Use 'fi_FI.UTF-8' for Unix-like systems
except locale.Error:
    print("! [WARNING] Finnish locale (fi_FI.UTF-8) not available, using default.")

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

    # Calculate average temperature
    df_result['Avg_Temperature'] = df_result[temperature_columns].mean(axis=1)

    # Group by date and calculate min, max, and average price, as well as the average wind power and temperature
    df_result['date'] = df_result['timestamp'].dt.date
    df_grouped = df_result.groupby('date').agg({
        'PricePredict_cpkWh': ['min', 'max', 'mean'],
        'WindPowerMW': 'mean',
        'Avg_Temperature': 'mean'
    })

    # Round price values to integer
    df_grouped['PricePredict_cpkWh'] = df_grouped['PricePredict_cpkWh'].round(0).astype(int)
    
    # Round temperature values to 1 decimal
    df_grouped['Avg_Temperature'] = df_grouped['Avg_Temperature'].round(1)

    # Convert date index to weekday names and retain it in the DataFrame
    df_grouped.index = pd.to_datetime(df_grouped.index).strftime('%A')

    # print("→ Narration stats fetched from predictions.db:\n", df_grouped)

    # TODO: Collecting data, creating a prompt, sending it to GPT should each be done in dedicated functions (right now gathering happens both here and in send_to_gpt)
    narrative = send_to_gpt(df_grouped)

    # Return the prediction as text
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
            f"- Pörssisähkön hinta: min {row[('PricePredict_cpkWh', 'min')]} ¢/kWh, "
            f"max {row[('PricePredict_cpkWh', 'max')]} ¢/kWh, "
            f"keskihinta {row[('PricePredict_cpkWh', 'mean')]} ¢/kWh.\n"
        )
        prompt += f"- Tuulivoima: keskiarvo {int(row[('WindPowerMW', 'mean')])} MW.\n"

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
# Ohjeita

Olet sähkömarkkinoiden asiantuntija ja kirjoitat uutisartikkelin hintaennusteista lähipäiville. Käytä dataa ja ohjeita apunasi.

## Tutki ensin seuraavia tekijöitä ja mieti, miten ne vaikuttavat sähkön hintaan
- Onko viikko keskimäärin tasainen, vai onko suuria eroja tiettyjen päivien välillä? Erot voivat koskea hintaa, tuulivoimaa, lämpötilaa, siirtoyhteyksiä tai ydinvoimaa.
- Onko käynnissä poikkeuksellisen suuria ydinvoimaloiden tuotantovajauksia vai ei?
- Onko sähkönsiirron tuontikapasiteetti normaali vai poikkeuksellisen alhainen? Erottuuko jokin päivä erityisesti, vai ei?
- Onko tuulivoimaa eri päivinä paljon, vähän vai normaalisti? Erottuuko jokin päivä erityisesti, vai ei?
- Onko lämpötila erityisen korkea tai matala tulevina päivinä? Erottuuko jokin päivä erityisesti, vai ei?
- Jos jonkin päivän keskihinta on muita korkeampi, mikä voisi selittää sitä? Onko syynä tuulivoima, lämpötila, ydinvoima, siirtoyhteydet vai jokin muu/tuntematon tekijä?

## Sähkönkäyttäjien yleinen hintaherkkyys, joka koskee **keskihintaa**
- Sähkönkäyttäjille edullinen keskihinta tarkoittaa alle 5 ¢. Tätä korkeampi keskihinta ei ole koskaan halpa, vaikka yöllä minimihinta olisi lähellä nollaa tai jopa sen alle. Negatiiviset minimihinnat ovat mahdollisia, ja ne voi mainita, jos niitä on. Negatiivisia hintoja on tavallisesti vain yöllä.
- Normaali keskihinta on 5-9 senttiä.
- Kallis keskihinta on 10 senttiä tai yli.
- Hyvin kallis keskihinta on 15 senttiä tai enemmän.

## Tuulivoimasta
- Tyyni tai heikko tuuli: Alle 1000 MW tuulivoima usein johtaa korkeaan sähkön hintaan.
- Tavanomainen, riittävä tuuli: 1000-3000 MW tuulivoimalla ei välttämättä ole erityistä hintavaikutusta.
- Reipas tai voimakas tuuli: Yli 3000 MW tuulivoima voi laskea sähkön hintaa selvästi.

## Lämpötiloista
- Kova pakkanen: Alle -5 °C ja varsinkin alle -10 °C voi selittää sähkön korkeaa hintaa, koska (kovalla) pakkasella lämmitysenergiaa kuluu paljon.
- Normaali talvikeli: -5 °C ... 5 °C voi nostaa sähkön hintaa vähän, mutta kyseessä on silti normaali talvikeli, eikä se välttämättä vaikuta hintaan.
- Viileä sää: 5 °C ... 15 °C ei välttämättä ole erityistä hintavaikutusta.
- Lämmin tai kuuma sää: Yli 15 °C ei välttämättä ole erityistä hintavaikutusta.

## Ydinvoimaloiden huoltokatkoista
- Ydinvoimaa on Suomessa yhteensä noin 4400 MW.
- Olkiluoto 3 on Suomen suurin yksittäinen sähköntuotantolaitos. Sen teho voi normaalitilanteessakin olla noin 1200 MW, koska sitä ei aina ajeta täydellä teholla.
- Ydinvoimaloiden tuotantovajaukset, tuotantorajoitukset tai huollot voivat selittää sähkön korkeaa hintaa, jos niitä on käynnissä useita yhtä aikaa tai jos käytettävissä oleva teho isossa tuotantolaitoksessa on normaalia alhaisempi.
- Käytettävyysprosentti ei ole tuttu konsepti kuluttajille, joten sitä ei saa mainita. Käytettävissä oleva teho ja nimellisteho ovat hyödyllisempiä tietoja.
- Jos ydinvoimatuotanto toimii lähestulkoon normaalisti, älä puhu ydinvoimasta vastauksessasi ollenkaan. Unohda ydinvoima, jos se ei ole merkittävästi poikkeuksellista.
- Voit puhua ydinvoimasta vain jos niillä on poikkeuksellisen suuri tuotantovajaus, käytettävyys alle 70 %. Tällöin mainitse aina myös laitosyksikön nimellisteho ja käytettävyysprosentti.

## Sähkönsiirron tuontikapasiteetista
- Sähkönsiirron tuontikapasiteetti Ruotsista ja Virosta voi nostaa sähkön hintaa, jos kapasiteetti poikkeuksellisen alhainen.
- Suurimmillaan tuontikapasiteetti voi olla noin 3700 MW.
- Normaalitilanteessa tuontikapasiteetti on yli 3000 MW. Tällöin tuontienergia voi tasata hintapiikkejä.
- Alle 3000 MW voi selittää päivittäisiä hinnannousuja. Alle 2000 MW voi selittää hinnannousuja paljon, jos samaan aikaan tuulivoima ei riitä paikkaamaan kulutusta.
- Jos yhden tai useamman päivän kapasiteetti ei ole normaali, mainitse se vastauksessasi.

## Muita ohjeita, joita sinun tulee ehdottomasti noudattaa
- Älä anna mitään neuvoja! Tehtäväsi on puhua vain hinnoista! Ole perinpohjainen ja tarkka.
- Tämä tarkoittaa, että kun viittaat hintoihin, kirjoita niistä numeroilla eikä adjektiiveilla.
- Yllä olevat hintaherkkyystiedot on annettu tiedoksi vain sinulle. Älä käytä niitä vastauksessasi.
- Älä koskaan mainitse päivämääriä (kuukausi, vuosi), koska viikonpäivät ovat riittävä tieto. Jos käytät päivämääriä (kuten 31.1.2024), vastauksesi hylätään.
- Tuulivoimasta voit puhua jos jaksolla on hyvin tyyntä tai tuulista ja se voi selittää hintoja. Jos tuulivoimalla ei näytä olevan hintavaikutusta tällä jaksolla, sitä ei välttämättä tarvitse mainita ollenkaan.
- Lämpötilasta voit puhua jos jaksolla on erityisen kylmä pakkaspäivä joka voi nostaa lämmitystarvetta ja selittää hintoja.
- Hyvin matala tuuli ja kova pakkanen voivat yhdessä selittää hinnannousuja.
- Jos käytät sanoja 'halpa', 'kohtuullinen', 'kallis' tai 'hyvin kallis', voit käyttää niitä vain yhteenvetojen yhteydessä.
- Jos päivän aikana on hyvin korkeita maksimihintoja, sellaista päivää ei voi kutsua 'halvaksi', vaikka yöllä minimihinta olisi lähellä nollaa. Keskihinta ratkaisee.
- Käytä Markdown-muotoilua näin: **Vahvenna** viikonpäivien nimet (maanantai, tiistai, keskiviikko, torstai, perjantai, lauantai, sunnuntai), mutta vain kun mainitset ne ensi kertaa.
- Data ei kerro mitään sähkön saatavuudesta. Älä koskaan puhu sähkön saatavuudesta, vaan ainoastaan hinnoista.
- Koska tämä on ennuste, puhu aina **tulevassa aikamuodossa** eli futuurissa.
- Vältä lauseenvastikkeita: kirjoita yksi lause kerrallaan.
- Käytä saman tyyppistä kieltä kuin uutisartikkeleissa: neutraalia, informatiivista, rikasta, hyvää suomen kieltä.

# Tehtäväsi

Kirjoita tiivis, rikasta suomen kieltä käyttävä UUTISARTIKKELI saamiesi tietojen pohjalta. Vältä kliseitä ja turhaa draamaa: jos hintaa selittäviä poikkeamia ei ole ja päivät ovat keskenään hyvin samankaltaisia, pidä teksti toteavana ja neutraalina. Älä puhu huolista tai tunteista. Keskity faktoihin ja hintoihin.

1. Alusta artikkeli yleiskuvauksella viikon hintakehityksestä, futuurissa. Mainitse eniten erottuva päivä ja sen keski- ja maksimihinta, mutta vain jos korkeita hintoja on. Voit myös sanoa, että päivät ovat keskenään hyvin samankaltaisia, jos asia näin on. Käytä tässä adjektiiveja. Voit kertoa tuulivoiman trendeistä, jos trendejä näkyy. Voit kertoa ydinvoimaloiden poikkeamista, mutta vain jos hintavaikutus on täysin selvä. Muuten älä mainitse ydinvoimaa. Sama koskee sähkön tuontia: normaalia siirtokapasiteettia ei tarvise kommentoida. Pyri olemaan mahdollisimman tarkka ja informatiivinen, mutta älä anna neuvoja tai keksi tarinoita tai trendejä, joita ei datassa ole.

2. Kirjoita jokaisesta päivästä futuurissa oma kappale keskittyen kyseisen päivän numeroihin. Vältä adjektiiveja. Onko yhden tai useamman päivän kohdalla selkeä hintaa selittävä poikkeama, josta on syytä mainita? Älä kerro päivän hintakehityksestä enempää kuin yhden lauseen verran. Jokaisen päivän kuvailu voi olla rakenteeltaan erilainen.

3. Yhteenveto.

Älä käytä hinnoissa desimaaleja. Käytä kokonaislukuja.

Tavoitepituus on noin 200-300 sanaa.

Nyt voit kirjoittaa valmiin tekstin. Älä kirjoita mitään muuta kuin valmis teksti. Kiitos!
</instructions>"""

    print(prompt)

    # Wrap the prompt into a user message payload
    messages = [
        {"role": "user", "content": f"{prompt}"},
    ]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
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
