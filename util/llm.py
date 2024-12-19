import sys
import os
import json
import locale
import datetime
import pandas as pd
import pytz
from dotenv import load_dotenv
from openai import OpenAI
from rich import print
from datetime import datetime as dt
from .sql import db_query

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

    # Rounding and conversion to ensure integer output for min and max
    df_grouped[('PricePredict_cpkWh', 'min')] = df_grouped[('PricePredict_cpkWh', 'min')].round().astype(int)
    df_grouped[('PricePredict_cpkWh', 'max')] = df_grouped[('PricePredict_cpkWh', 'max')].round().astype(int)

    # Keeping mean as a float rounded to 1 decimal place
    df_grouped[('PricePredict_cpkWh', 'mean')] = df_grouped[('PricePredict_cpkWh', 'mean')].round(1)

    # Ensure WindPowerMW is integer and Avg_Temperature one decimal float
    df_grouped[('WindPowerMW', 'min')] = df_grouped[('WindPowerMW', 'min')].round().astype(int)
    df_grouped[('WindPowerMW', 'max')] = df_grouped[('WindPowerMW', 'max')].round().astype(int)
    df_grouped[('WindPowerMW', 'mean')] = df_grouped[('WindPowerMW', 'mean')].round().astype(int)
    df_grouped[('Avg_Temperature', 'mean')] = df_grouped[('Avg_Temperature', 'mean')].round(1)

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

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    today = datetime.date.today()
    weekday_today = today.strftime("%A")
    date_today = today.strftime("%d. %B %Y")
    time_now = datetime.datetime.now().strftime("%H:%M")

    prompt = "<data>\n"
    prompt += f"Nyt on {weekday_today.lower()} {date_today.lower()} klo {time_now}. "
    prompt += f"Nordpool-sähköpörssin verolliset Suomen markkinan hintaennusteet lähipäiville ovat seuraavat (viimeksi päivitetty: {weekday_today.lower()}na klo {time_now}). "
    prompt += "Ole tarkkana että käytät näitä numeroita oikein ja lue ohjeet tarkasti:\n"

    # Iterate over each weekday and concatenate all relevant data
    for weekday, row in df.iterrows():
        prompt += f"\n**{weekday}**\n"
        prompt += (
            f"- Pörssisähkön hinta ¢/kWh: {int(row[('PricePredict_cpkWh', 'min')])} - "
            f"{int(row[('PricePredict_cpkWh', 'max')])}, "
            f"päivän keskihinta {row[('PricePredict_cpkWh', 'mean')]} ¢/kWh.\n"
        )
        prompt += (
            f"- Tuulivoima MW: {int(row[('WindPowerMW', 'min')])} - "
            f"{int(row[('WindPowerMW', 'max')])}, "
            f"keskimäärin {int(row[('WindPowerMW', 'mean')])} MW.\n"
        )
        prompt += f"- Päivän keskilämpötila: {row[('Avg_Temperature', 'mean')]} °C.\n"
        
    # Add a single section for nuclear outages
    if NUCLEAR_OUTAGE_DATA is not None:
        nuclear_outage_section = "\n**Ydinvoimalat**\n"
        section_empty = True  # Flag to check if any entry is added
        
        helsinki_tz = pytz.timezone('Europe/Helsinki')
        
        for outage in NUCLEAR_OUTAGE_DATA:
            start_date_utc = pd.to_datetime(outage['start'])
            end_date_utc = pd.to_datetime(outage['end'])

            start_date_hel = start_date_utc.tz_convert(helsinki_tz)
            end_date_hel = end_date_utc.tz_convert(helsinki_tz)

            # Assuming today is defined earlier in the code using dt.date.today()
            if start_date_hel.date() <= today <= end_date_hel.date():
                availability = outage['availability'] * 100  # Convert to percentage
                if availability < 70:  # Only include rows with availability below 70%
                    section_empty = False  # Mark that the section is not empty
                    nominal_power = outage['nominal_power']
                    avail_qty = outage['avail_qty']
                    resource_name = outage['production_resource_name']
                    start_date_str = start_date_hel.strftime('%A %Y-%m-%d %H:%M')  # %A for full weekday name
                    end_date_str = end_date_hel.strftime('%A %Y-%m-%d %H:%M')
                    nuclear_outage_section += (
                        f"- {resource_name}: Nimellisteho {nominal_power} MW, "
                        f"käytettävissä oleva teho {avail_qty} MW, "
                        f"käytettävyys-% {availability:.1f}. Alkaa - loppuu: "
                        f"{start_date_str} - {end_date_str}. Päättymisaika on ennuste, joka voi muuttua.\n"
                    )

        if not section_empty:
            prompt += nuclear_outage_section

    prompt += "</data>\n"

    prompt += f"""
<instructions>
# 1. Miten pörssisähkön hinta muodostuu

Olet sähkömarkkinoiden asiantuntija ja kirjoitat kohta uutisartikkelin hintaennusteista lähipäiville. Seuraa näitä ohjeita tarkasti.

## 1.1. Tutki seuraavia tekijöitä ja mieti, miten ne vaikuttavat sähkön hintaan
- Onko viikko tasainen vai onko suuria eroja päivien välillä? Erot voivat koskea hintaa, tuulivoimaa tai lämpötilaa.
- Onko tuulivoimaa eri päivinä paljon, vähän vai normaalisti? Erottuuko jokin päivä matalammalla keskituotannolla?
- Onko jonkin päivän sisällä tuulivoimaa minimissään poikkeuksellisen vähän? Osuuko samalle päivälle korkea maksimihinta?
- Onko lämpötila erityisen korkea tai matala tulevina päivinä? Erottuuko jokin päivä erityisesti?
- Jos jonkin päivän keskihinta tai maksimihinta on muita selvästi korkeampi, mikä voisi selittää sitä? Onko syynä tuulivoima, lämpötila vai jokin muu/tuntematon tekijä?

## 1.2. Sähkönkäyttäjien yleinen hintaherkkyys (keskihinta)
- Edullinen keskihinta: alle 5 senttiä/kilowattitunti.
- Normaali keskihinta: 5-8 ¢/kWh. Normaalia keskihintaa ei tarvitse selittää.
- Kallis keskihinta: 9 ¢ tai yli.
- Hyvin kallis keskihinta: 15 senttiä tai enemmän.
- Minimihinnat voivat olla negatiivisia, tavallisesti yöllä. Mainitse ne, jos niitä on.

## 1.3. Sähkön hinta ja tuulivoiman määrä
- Tyyni: Jos tuulivoimaa on keskimäärin vain alle 1000 MW, se voi nostaa sähkön keskihintaa selvästi. Tuulivoima on heikkoa.
- Heikko tuuli: alle 2500 MW keskimääräinen tuulivoima voi voi nostaa sähkön keskihintaa jonkin verran. Tuulivoima on matalalla tasolla.
- Tavanomainen tuuli: 2500-3000 MW tuulivoimalla ei ole mainittavaa hintavaikutusta, joten silloin tuulivoimaa ei tarvitse ennusteessa edes mainita.
- Voimakas tuuli: yli 3000 MW tuulivoima voi selittää matalaa sähkön hintaa. Tuulivoimaa on tarjolla paljon.
- Suuri ero päivän minimi- ja maksimihinnan välillä voi selittyä tuulivoiman tuotannon vaihteluilla.
    - Jos päivän tuulivoiman minimituotanto on alle 2000 MW ja samana päivänä maksimihinta on korkeampi kuin muina päivinä, sinun on ehdottomasti mainittava tämä yhteys ja kerrottava, että alhainen tuulivoiman minimituotanto selittää korkeamman maksimihinnan.

## 1.4. Lämpötilan vaikutus
- Kova pakkanen: alle -5 °C voi selittää korkeaa hintaa.
- Normaali talvikeli: -5 °C ... 5 °C ei välttämättä vaikuta hintaan.
- Viileä sää: 5 °C ... 15 °C ei yleensä vaikuta hintaan.
- Lämmin sää: yli 15 °C ei yleensä vaikuta hintaan.

## 1.5. Ydinvoimaloiden tuotanto
- Suomessa on viisi ydinvoimalaa: Olkiluoto 1, 2 ja 3, sekä Loviisa 1 ja 2.
- Näet listan poikkeuksellisen suurista ydinvoimaloiden tuotantovajauksista.
- Jos käyttöaste on nolla prosenttia, silloin käytä termiä huoltokatko. Muuten kyseessä on tuotantovajaus.
- Huoltokatko tai tuotantovajaus voi vaikuttaa hintaennusteen tarkkuuteen. Tämän vuoksi älä koskaan spekuloi ydinvoiman mahdollisella hintavaikutuksella, vaan raportoi tiedot sellaisenaan, ja kerro myös että opetusdataa on huoltokatkojen ajalta saatavilla rajallisesti.

## 1.7. Muita ohjeita
- Älä lisää omia kommenttejasi, arvioita tai mielipiteitä. Älä käytä ilmauksia kuten 'mikä ei aiheuta erityistä lämmitystarvetta' tai 'riittävän korkea'.
- Tarkista numerot huolellisesti ja varmista, että kaikki tiedot ja vertailut ovat oikein.
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

- Artikkelia ei tule otsikoida.

- Älä koskaan mainitse päivämääriä (kuukausi, vuosi). Käytä vain viikonpäiviä.

Artikkelin rakenne on kolmiosainen:

## 1. Jos käynnissä on ydinvoiman huoltokatkoja

- Mainitse voimala ja häiriön alkamis- ja loppumisaika kellonaikoineen.
- Mainitse että huoltokatko voi vaikuttaa ennusteen tarkkuuteen, koska opetusdataa on huoltokatkojen ajalta saatavilla rajallisesti.

Jos käynnissä ei ole ydinvoiman huoltokatkoja, jätä tämä osio kokonaan pois.

## 2. Tee taulukko. Kirjoita jokaisesta päivästä oma rivi taulukkoon.

Muista, että jos käynnissä ei ole ydinvoiman huoltokatkoja, artikkeli alkaa suoraan taulukosta.

Mainitse taulukon yläpuolella leipätekstinä, koska ennuste on päivitetty.

Sitten näytä taulukko:

| viikonpäivä  | keskihinta<br>¢/kWh | min - max<br>¢/kWh | tuulivoima<br>min - max<br>MW | keski-<br>lämpötila<br>°C |
|:-------------|:----------------:|:----------------:|:-------------:|:-------------:|

jossa "ka" tarkoittaa kyseisen viikonpäivän keskihintaa. Tasaa sarakkeet kuten esimerkissä.

Huomaa että minimi- ja maksimihinnat ovat kokonaislukuja, mutta keskihinnassa on yksi desimaali. Hinnat on kirjattu tarkoituksella juuri näin.

## 3. Kirjoita yleiskuvaus viikon hintakehityksestä, futuurissa.

- Tavoitepituus on kaksi sujuvaa tekstikappaletta, yhteensä noin 200 sanaa.
- Mainitse eniten erottuva päivä ja sen keski- ja maksimihinta, mutta vain jos korkeita maksimihintoja on. Tai voit sanoa, että päivät ovat keskenään hyvin samankaltaisia, jos näin on.
- Älä kommentoi tuulivoimaa/keskilämpötilaa, jos se on keskimäärin normaalilla tasolla eikä vaikuta hintaan ylös- tai alaspäin.
- Kuvaile hintakehitystä neutraalisti ja informatiivisesti.

# Muista vielä nämä

- Ole mahdollisimman tarkka ja informatiivinen, mutta älä anna neuvoja tai keksi tarinoita tai trendejä, joita ei datassa ole.
- Desimaaliluvut: käytä pilkkua, ei pistettä. Toista desimaali- ja kokonaisluvut täsmälleen niin kuin ne on annettu.
- Kirjoita koko teksti futuurissa.
- Jos ja vain jos tuulivoima on hyvin matalalla tai hyvin korkealla tasolla, silloin voit mainita hintavaikutuksen annettujen ohjeiden mukaisesti.
- Keskity vain poikkeuksellisiin tilanteisiin, jotka vaikuttavat hintaan. Älä mainitse normaaleja olosuhteita.
- Älä koskaan kirjoita, että 'poikkeamia ei ole' tai 'ei ilmene hintaa selittäviä poikkeamia'. Jos poikkeamia ei ole, jätä tämä mainitsematta. Kirjoita vain poikkeuksista, jotka vaikuttavat hintaan.
- Älä koskaan spekuloi ydinvoiman mahdollisella hintavaikutuksella. Kerro vain, että huoltokatko voi vaikuttaa ennusteen tarkkuuteen ja raportoi annetut tiedot sellaisenaan, kuten yllä on ohjeistettu.

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
            model="gpt-4o",
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
