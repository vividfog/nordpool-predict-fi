import sys
import os
import json
import math
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

def spike_price_risk(df):
    """Calculate the risk of price spikes for each day."""
    df['Price_Range'] = df['PricePredict_cpkWh_max'] - df['PricePredict_cpkWh_min']
    df['Price_StdDev'] = df['PricePredict_cpkWh_mean'].rolling(window=2).std().fillna(0)

    df['Spike_Risk'] = 0

    # Price or range thresholds
    df.loc[df['PricePredict_cpkWh_max'] > 15, 'Spike_Risk'] += 2
    df.loc[df['Price_Range'] > 10, 'Spike_Risk'] += 1
    df.loc[df['Price_StdDev'] > 4, 'Spike_Risk'] += 1

    # Wind thresholds
    df.loc[df['WindPowerMW_min'] < 1000, 'Spike_Risk'] += 1
    df.loc[df['WindPowerMW_mean'] < 2500, 'Spike_Risk'] += 1
    df.loc[df['WindPowerMW_mean'] > 3000, 'Spike_Risk'] -= 1  # Less likely to spike if wind is strong

    # Temperature thresholds
    df.loc[df['Avg_Temperature_mean'] < -5, 'Spike_Risk'] += 1
    df.loc[df['Avg_Temperature_mean'] > 15, 'Spike_Risk'] -= 1

    return df

def narrate_prediction():
    """Fetch prediction data from the database and narrate it using an LLM."""
    helsinki_tz = pytz.timezone('Europe/Helsinki')
    now_hel = datetime.datetime.now(helsinki_tz)

    # Calculate tomorrow's date, midnight
    tomorrow_date = now_hel.date() + datetime.timedelta(days=1)
    tomorrow_start = helsinki_tz.localize(datetime.datetime.combine(tomorrow_date, datetime.time(0, 0)))

    # Create a DataFrame with timestamps for the next 7 days (hourly)
    df = pd.DataFrame({
        'timestamp': pd.date_range(
            start=tomorrow_start,
            periods=7 * 24,
            freq='H',
            tz=helsinki_tz
        )
    })

    # Fetch data from the database
    from .sql import db_query
    try:
        df_result = db_query('data/prediction.db', df)
    except Exception as e:
        print(f"Database query failed for OpenAI narration: {e}")
        sys.exit(1)

    # Keep needed columns
    temperature_ids = os.getenv('FMISID_T', "").split(',')
    temperature_columns = [f't_{temp_id}' for temp_id in temperature_ids]
    cols_needed = ['timestamp', 'PricePredict_cpkWh', 'WindPowerMW', 'holiday'] + temperature_columns
    df_result = df_result[cols_needed].dropna()

    # Convert timestamp to Helsinki time
    df_result['timestamp'] = pd.to_datetime(df_result['timestamp'], utc=True).dt.tz_convert(helsinki_tz)
    
    # Add 'date' column for grouping
    df_result['date'] = df_result['timestamp'].dt.date

    # Compute average temperature
    df_result['Avg_Temperature'] = df_result[temperature_columns].mean(axis=1)
    df_result['holiday'] = df_result['holiday'].astype(int)

    # Prepare daily DataFrame
    df_daily = df_result.groupby(df_result['timestamp'].dt.floor('D')).agg({
        'PricePredict_cpkWh': ['min', 'max', 'mean'],
        'WindPowerMW': ['min', 'max', 'mean'],
        'Avg_Temperature': 'mean',
        'holiday': 'any'
    })
    df_daily.columns = [f"{col[0]}_{col[1]}" for col in df_daily.columns.values]
    df_daily.reset_index(inplace=True)
    df_daily.rename(columns={'timestamp_': 'timestamp'}, inplace=True)

    df_daily = df_daily.rename(columns={
        'PricePredict_cpkWh_min': 'PricePredict_cpkWh_min',
        'PricePredict_cpkWh_max': 'PricePredict_cpkWh_max',
        'PricePredict_cpkWh_mean': 'PricePredict_cpkWh_mean',
        'WindPowerMW_min': 'WindPowerMW_min',
        'WindPowerMW_max': 'WindPowerMW_max',
        'WindPowerMW_mean': 'WindPowerMW_mean',
        'Avg_Temperature_mean': 'Avg_Temperature_mean',
        'holiday_any': 'holiday_any'
    })

    # Apply spike risk logic to daily
    df_daily = spike_price_risk(df_daily)

    # Round columns
    df_daily['PricePredict_cpkWh_min'] = df_daily['PricePredict_cpkWh_min'].round(1)
    df_daily['PricePredict_cpkWh_max'] = df_daily['PricePredict_cpkWh_max'].round(1)
    df_daily['PricePredict_cpkWh_mean'] = df_daily['PricePredict_cpkWh_mean'].round(1)

    df_daily['WindPowerMW_min'] = df_daily['WindPowerMW_min'].round().astype(int)
    df_daily['WindPowerMW_max'] = df_daily['WindPowerMW_max'].round().astype(int)
    df_daily['WindPowerMW_mean'] = df_daily['WindPowerMW_mean'].round().astype(int)
    df_daily['Avg_Temperature_mean'] = df_daily['Avg_Temperature_mean'].round(1)

    df_daily['weekday'] = df_daily['timestamp'].dt.strftime('%A')
    df_daily.set_index('weekday', inplace=True)

    # Include daily average wind
    df_daily['WindPowerMW_avg'] = df_daily['WindPowerMW_mean']

    # Intraday DataFrame can remain in hourly format
    # Round columns to match daily's style
    df_result['PricePredict_cpkWh'] = df_result['PricePredict_cpkWh'].round(1)
    df_result['WindPowerMW'] = df_result['WindPowerMW'].round().astype(int)
    df_result['Avg_Temperature'] = df_result['Avg_Temperature'].round(1)

    # Send both dataframes to GPT
    narrative = send_to_gpt(df_daily, df_result, helsinki_tz)
    return narrative

def send_to_gpt(df_daily, df_intraday, helsinki_tz):
    # Load nuclear outage data
    try:
        with open('deploy/nuclear_outages.json', 'r') as file:
            NUCLEAR_OUTAGE_DATA = json.load(file).get('nuclear_outages', [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"! [WARNING] Loading nuclear outage data failed: {e}. Narration will be incomplete.")
        NUCLEAR_OUTAGE_DATA = []

    # client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"),
                    base_url="https://api.deepseek.com/v1")

    today = datetime.date.today()
    weekday_today = today.strftime("%A")
    date_today = f"{int(today.strftime('%d'))}. {today.strftime('%B').lower()}ta {today.strftime('%Y')}"
    time_now = datetime.datetime.now().strftime("%H:%M")

    # Build the prompt
    prompt = "<data>\n"
    prompt += f"  Nordpool-sähköpörssin verolliset Suomen markkinan hintaennusteet lähipäiville ovat seuraavat (viimeksi päivitetty: {weekday_today.lower()}na klo {time_now}).\n"

    prompt += f"  <tuntikohtainen_ennuste>\n"
    for date_value, group_df in df_intraday.groupby('date', sort=False):
        # Pick the weekday name (e.g. 'Maanantai') from the first row in this group
        weekday_name = group_df['timestamp'].dt.strftime('%A').iloc[0]
        weekday_name = weekday_name.lower()
        
        prompt += f"    <päivä viikonpäivä='{weekday_name}'>\n"
        compact_data = []
        
        # Identify the top-priced hour
        top_hour_row = group_df.loc[group_df['PricePredict_cpkWh'].idxmax()]
        top_hour_time = top_hour_row['timestamp'].strftime('%H:%M')
        
        for _, hour_row in group_df.iterrows():
            time_str = hour_row['timestamp'].strftime('%H:%M')
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

    # Daily rows
    for weekday, row in df_daily.iterrows():
        weekday = weekday.lower()
        prompt += f"\n  **{weekday}**\n"
        if row['holiday_any']:
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
            row['timestamp'].date() == tomorrow_date
            and now_hel.hour >= 14
        )

        if not skip_spike_for_tomorrow:
            # Spike risk note
            if row['Spike_Risk'] >= 3:
                risk_upper_boundary = int(math.ceil(row['PricePredict_cpkWh_mean'] * 3.5 / 10.0) * 10)
                risk_lower_boundary = int(math.ceil(row['PricePredict_cpkWh_mean'] * 2 / 10.0) * 10)
                if risk_upper_boundary != risk_lower_boundary:
                    prompt += f"  - TÄRKEÄÄ MAINITA: Korkea riski hintapiikeille yllä ennustettuun verrattuna {weekday}na, jopa {risk_lower_boundary}-{risk_upper_boundary} ¢ yksittäisinä tunteina.\n"
                else:
                    prompt += f"  - TÄRKEÄÄ MAINITA: Korkea riski hintapiikeille yllä ennustettuun verrattuna {weekday}na, jopa {risk_upper_boundary} ¢ yksittäisinä tunteina.\n"
            elif row['Spike_Risk'] >= 1:
                risk_upper_boundary = int(math.ceil(row['PricePredict_cpkWh_mean'] * 2 / 10.0) * 10)
                prompt += f"  - HUOM: Riski hintapiikeille yllä ennustettuun verrattuna {weekday}na, jopa {risk_upper_boundary} ¢ yksittäisinä tunteina.\n"
            else:
                prompt += f"  - Hintapiikkien riski tälle päivälle on niin pieni, että älä puhu hintapiikeistä artikkelissa ollenkaan, kun puhut {weekday}sta.\n\n"

    # Add nuclear outages if any
    if NUCLEAR_OUTAGE_DATA:
        nuclear_outage_section = "\n**Ydinvoimalat**\n"
        section_empty = True

        for outage in NUCLEAR_OUTAGE_DATA:
            start_date_utc = pd.to_datetime(outage['start'])
            end_date_utc = pd.to_datetime(outage['end'])

            start_date_hel = start_date_utc.tz_convert(helsinki_tz)
            end_date_hel = end_date_utc.tz_convert(helsinki_tz)

            if start_date_hel.date() <= today <= end_date_hel.date():
                availability = outage.get('availability', 1) * 100
                if availability < 70:
                    section_empty = False
                    nominal_power = outage.get('nominal_power')
                    avail_qty = outage.get('avail_qty')
                    resource_name = outage.get('production_resource_name', 'Tuntematon voimala')
                    start_date_str = start_date_hel.strftime('%A %Y-%m-%d %H:%M')
                    end_date_str = end_date_hel.strftime('%A %Y-%m-%d %H:%M')
                    nuclear_outage_section += (
                        f"- {resource_name}: Nimellisteho {nominal_power} MW, "
                        f"käytettävissä oleva teho {avail_qty} MW, "
                        f"käytettävyys-% {availability:.1f}. Alkaa - loppuu: "
                        f"{start_date_str} - {end_date_str}. Päättymisaika on ennuste.\n"
                    )

        if not section_empty:
            prompt += nuclear_outage_section

    prompt += "</data>\n"

    prompt += f"""
<ohjeet>
  # 1. Miten pörssisähkön hinta muodostuu

  Olet sähkömarkkinoiden asiantuntija ja kirjoitat kohta uutisartikkelin hintaennusteista lähipäiville. Seuraa näitä ohjeita tarkasti.

  ## 1.1. Tutki seuraavia tekijöitä ja mieti, miten ne vaikuttavat sähkön hintaan
  - Onko viikko tasainen vai onko suuria eroja päivien välillä? Erot voivat koskea hintaa, tuulivoimaa tai lämpötilaa.
  - Onko tuulivoimaa eri päivinä paljon, vähän vai normaalisti? Erottuuko jokin päivä matalammalla keskituotannolla?
  - Onko jonkin päivän sisällä tuulivoimaa minimissään poikkeuksellisen vähän? Onko samana päivänä myös korkea maksimihinta?
  - Onko lämpötila erityisen korkea tai matala tulevina päivinä? Erottuuko jokin päivä erityisesti?
  - Onko tiedoissa jonkin päivän kohdalla maininta pyhäpäivästä? Miten se vaikuttaa hintaan?
  - Jos jonkin päivän keskihinta tai maksimihinta on muita selvästi korkeampi, mikä voisi selittää sitä? Onko syynä tuulivoima, lämpötila vai jokin muu/tuntematon tekijä?

  ## 1.2. Sähkönkäyttäjien yleinen hintaherkkyys (keskihinta)
  - Edullinen keskihinta: alle 4-5 senttiä/kilowattitunti.
  - Normaalia keskihintaa ei tarvitse selittää.
  - Kallis keskihinta: 9-10 ¢ tai yli.
  - Hyvin kallis keskihinta: 15-20 senttiä tai enemmän.
  - Minimihinnat voivat joskus olla negatiivisia, tavallisesti yöllä. Mainitse ne, jos niitä on.

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

  ## 1.6. Piikkihintojen riski yksittäisille tunneille
  - Yli 15 c/kWh ennustettu maksimihinta ja selvästi alle 1000 MW tuulivoiman min voi olla riski: todellinen maksimihinta voi olla selvästi korkeampi kuin ennuste. Tällöin yksittäisten tuntien maksimihinnat voivat olla selvästi korkeampia ennustettuun maksimihintaan nähden. Tarkista tuntikohtainen ennuste.
  - Saat puhua hintapiikeistä vain, jos <data> mainitsee niistä, yksittäisten päivin kohdalla. Älä spekuloi, jos riskiä ei erikseen ole tietyn päivän kohdalla mainittu. Normaalisti viittaat maksimihintaan.
  - Jos hintapiikkejä ei ole <data>:ssa mainittu, riskiä ei kyseisen päivän kohdalla silloin ole, eikä hintapiikeistä ole tarpeen puhua kyseisen päivän kohdalla ollenkaan. Älä siis koskaan käytä esimerkiksi tällaista lausetta, koska se on tarpeeton: "Muina päivinä hintapiikkien riski on pieni."
  - Koska huippuhintojen ajankohtaa on vaikea ennustaa täsmälleen oikein, käytä artikkelissa 2 tunnin aikahaarukkaa, jossa huippu on keskellä. Esimerkiksi: Jos huippuhinta tuntikohtaisessa ennusteessa olisi <data>:n mukaan klo 13, tällöin käyttäisit aikahaarukkaa klo 12-14.

  ## 1.7. Muita ohjeita
  - Älä lisää omia kommenttejasi, arvioita tai mielipiteitä. Älä käytä ilmauksia kuten 'mikä ei aiheuta erityistä lämmitystarvetta' tai 'riittävän korkea'.
  - Tarkista numerot huolellisesti ja varmista, että kaikki tiedot ja vertailut ovat oikein.
  - Tuulivoimasta voit puhua, jos on hyvin tyyntä tai tuulista ja se vaikuttaa hintaan. Muuten älä mainitse tuulivoimaa.
  - Älä puhu lämpötilasta mitään, ellei keskilämpötila ole alle -5 °C.
  - Sanoja 'halpa', 'kohtuullinen', 'kallis' tai 'hyvin kallis' saa käyttää vain yleiskuvauksessa, ei yksittäisten päivien kohdalla.
  - Jos päivän maksimihinta on korkea, sellaista päivää ei voi kutsua 'halvaksi', vaikka minimihinta olisi lähellä nollaa. Keskihinta ratkaisee.
  - Pyhäpäivät ovat harvinaisia. Jos <data> ei sisällä pyhäpäiviä, älä silloin puhu pyhäpäivistä ollenkaan. Jos yksittäinen päivä kuitenkin on pyhäpäivä, se on mainittava.
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

  Mainitse taulukon yläpuolella leipätekstinä, koska ennuste on päivitetty, mukaan viikonpäivä ja kellonaika.

  Sitten näytä taulukko:

  | <pv>  | keski-<br>hinta<br>¢/kWh | min - max<br>¢/kWh | tuulivoima<br>min - max<br>MW | keski-<br>lämpötila<br>°C |
  |:-------------|:----------------:|:----------------:|:-------------:|:-------------:|

  jossa "<pv>" tarkoittaa viikonpäivää ja "ka" tarkoittaa kyseisen viikonpäivän odotettua keskihintaa. Lihavoi viikonpäivät taulukossa seuraavasti: esim. **maananatai**, **tiistai**, **keskiviikko**, **torstai**, **perjantai**, **lauantai**, **sunnuntai**.

  Tasaa sarakkeet kuten esimerkissä ja käytä dataa/desimaaleja/kokonaislukuja kuten <data>:ssa. 

  Otsikkorivillä jätä "<pv>" tyhjäksi: "". Riveillä näkyvät viikonpäivät tekevät käyttäjälle selväksi, minkä päivän tietoja taulukossa käsitellään.

  ## 3. Kirjoita yleiskuvaus viikon hintakehityksestä, futuurissa.

  - Tavoitepituus on vähintään 2, max 5 sujuvaa lyhyttä tekstikappaletta, kaikki yhteensä noin 300 sanaa.
  - Mainitse eniten erottuva päivä ja sen keski- ja maksimihinta, mutta vain jos korkeita maksimihintoja on. Tai voit sanoa, että päivät ovat keskenään hyvin samankaltaisia, jos näin on.
  - Viikon edullisimmat ja kalleimmat ajankohdat ovat kiinnostavia tietoja, varsinkin jos hinta vaihtelee paljon.
  - Älä kommentoi tuulivoimaa/keskilämpötilaa, jos se on keskimäärin normaalilla tasolla eikä vaikuta hintaan ylös- tai alaspäin.
  - Kuvaile hintakehitystä neutraalisti ja informatiivisesti.
  - Voit luoda vaihtelua käyttämällä tuntikohtaista ennustetta: Voit mainita muutaman yksittäisen tunnin, jos ne korostuvat jonkin päivän sisällä. Tai voit viitata ajankohtaan päivän sisällä.
  - Mahdolliset hintapiikit sijoittuvat tyypillisesti aamun (noin klo 8) tai illan (noin klo 18) tunneille. Tarkista mahdollisten hintapiikkien ajankohdat tuntikohtaisesta ennusteesta, ja riskit päiväkohtaisesta datasta.
  - Muotoile **viikonpäivät** lihavoinnilla: esim. **maananatai**, **tiistai**, **keskiviikko**, **torstai**, **perjantai**, **lauantai**, **sunnuntai** — mutta vain silloin kun mainitset ne tekstikappaleessa ensimmäisen kerran. Samaa päivää ei lihavoida kahdesti samassa tekstikappaleessa, koska se olisi toistoa.

  # Muista vielä nämä

  - Ole mahdollisimman tarkka ja informatiivinen, mutta älä anna neuvoja tai keksi tarinoita tai trendejä, joita ei datassa ole.
  - Desimaaliluvut: käytä pilkkua, ei pistettä. Toista desimaali- ja kokonaisluvut täsmälleen niin kuin ne on annettu.
  - Kirjoita koko teksti futuurissa, passiivimuodossa.
  - Jos ja vain jos tuulivoima on hyvin matalalla tai hyvin korkealla tasolla, silloin voit mainita hintavaikutuksen annettujen ohjeiden mukaisesti.
  - Keskity vain poikkeuksellisiin tilanteisiin, jotka vaikuttavat hintaan. Älä mainitse normaaleja olosuhteita.
  - Koska kyse on ennusteesta, toteutuvat hinnat voivat vielä muuttua ennusteesta, varsinkin jos tuuliennuste muuttuu. Puhu hintaennusteesta, hintaodotuksista jne käyttäen synonyymejä, kun viittaat hintoihin.
  - Älä koskaan kirjoita, että 'poikkeamia ei ole' tai 'ei ilmene hintaa selittäviä poikkeamia'. Jos poikkeamia ei ole, jätä tämä mainitsematta. Kirjoita vain poikkeuksista, jotka vaikuttavat hintaan.
  - Älä koskaan spekuloi ydinvoiman mahdollisella hintavaikutuksella. Kerro vain, että huoltokatko voi vaikuttaa ennusteen tarkkuuteen ja raportoi annetut tiedot sellaisenaan, kuten yllä on ohjeistettu.
  - TÄRKEÄÄ: Suomessa viikko alkaa maanantaista ja päättyy sunnuntaihin. Muista tämä, jos puhut viikonlopun päivistä tai viittaat viikon alkuun.

  Lue ohjeet vielä kerran, jotta olet varma että muistat ne. Nyt voit kirjoittaa valmiin tekstin. Älä kirjoita mitään muuta kuin valmis teksti. Kiitos!
</ohjeet>
"""

    print(prompt)

    messages = [{"role": "user", "content": prompt}]

    try:
        response = client.chat.completions.create(
            # model="gpt-4o",
            model="deepseek-chat", # DeepSeek-V3
            messages=messages,
            temperature=0.7,
            max_tokens=1536,
            stream=False,
        )
    except Exception as e:
        print(f"OpenAI API call failed: {e}")
        sys.exit(1)

    # Save to narration.json
    narration_json = {"content": response.choices[0].message.content}
    with open('deploy/narration.json', 'w', encoding='utf-8') as file:
        json.dump(narration_json, file, indent=2, ensure_ascii=False)

    return response.choices[0].message.content

if __name__ == "__main__":
    print("This is not meant to be executed directly.")
    exit()
