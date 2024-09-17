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
    # print(df)

    # Fetch data from the database
    try:
        df_result = db_query('data/prediction.db', df)
    except Exception as e:
        print(f"Database query failed for OpenAI narration: {e}")
        sys.exit(1)

    # Keep timestamp and predicted price
    df_result = df_result[['timestamp', 'PricePredict_cpkWh']]

    # Drop rows with missing values
    df_result = df_result.dropna()
    
    # Ensure the timestamp is a datetime object
    df_result['timestamp'] = pd.to_datetime(df_result['timestamp'])

    # Define the Helsinki timezone
    helsinki_tz = pytz.timezone('Europe/Helsinki')

    # Check if the timestamp is already in the desired timezone ('Europe/Helsinki')
    # If not, convert it
    if df_result['timestamp'].dt.tz is None:
        # If timestamps are naive, localize them to UTC first (assuming they are in UTC)
        df_result['timestamp'] = df_result['timestamp'].dt.tz_localize('UTC')
    # Now convert to Helsinki timezone
    df_result['timestamp'] = df_result['timestamp'].dt.tz_convert(helsinki_tz)

    # Group by date and calculate min, max, and average price
    df_result['date'] = df_result['timestamp'].dt.date
    # print(df_result)
    df_result = df_result.groupby('date').agg({'PricePredict_cpkWh': ['min', 'max', 'mean']})
    print("→ Narration stats fetched from predictions.db:\n", df_result)
    narrative = send_to_gpt(df_result)
    
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

    # Send the processed data to OpenAI's GPT model.
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    today = datetime.date.today()
    weekday_today = today.strftime("%A")
    date_today = today.strftime("%d.%m.%Y")

    prompt = (f"Tänään on {weekday_today.lower()} {date_today} ja ennusteet lähipäiville ovat seuraavat. Ole tarkkana että käytät näitä numeroita oikein:\n\n")

    for date, row in df.iterrows():
        prompt += (f"{date.strftime('%A %d.%m.%Y')}: Pörssisähkön hinta min {row[('PricePredict_cpkWh', 'min')]:.0f} ¢/kWh, max {row[('PricePredict_cpkWh', 'max')]:.0f} ¢/kWh, keskihinta {row[('PricePredict_cpkWh', 'mean')]:.0f} ¢/kWh.\n\n")
      
    prompt += """
Olet tekoäly, joka kirjoittaa  hintatiedotteen sähkönkäyttäjille.
Kirjoita viihdyttävä ja rikasta suomen kieltä käyttävä UUTISARTIKKELI saamiesi tietojen pohjalta. 
1. Aloita kuvailemalla sähkön hinnan kehitystä lähipäiville
2. Kommentoi sitten lähipäiviä kokonaisuutena. 
3. Tavoitepituus on noin 140-160 sanaa.

Sähkönkäyttäjien yleinen hintaherkkyys: 
- Sähkönkäyttäjille halpa hinta tarkoittaa alle 5 ¢. Tätä korkeampi hinta ei ole koskaan halpa.
- Kohtuullinen hinta on 5-10 senttiä. 
- Kallis hinta on yli 10 senttiä.
- Hyvin kallis hinta on 20 senttiä tai enemmän.

Muita ohjeita, joita sinun tulee ehdottomasti noudattaa:
- Älä anna mitään neuvoja! Tehtäväsi on puhua vain hinnoista! Ole perinpohjainen ja tarkka. 
- Tämä tarkoittaa, että kun viittaat hintoihin, kirjoita niistä numeroilla eikä adjektiiveilla.
- Yllä olevat hintaherkkyystiedot on annettu tiedoksi vain sinulle. Älä käytä niitä vastauksessasi.
- Älä myöskään mainitse päivämääriä, koska viikonpäivät ovat riittävä tieto.
- Jos käytät sanoja 'halpa', 'kohtuullinen', 'kallis' tai 'hyvin kallis', voit käyttää niitä vain lähipäivien yhteenvedossa.
- Käytä Markdown-muotoilua näin: **Vahvenna** viikonpäivät, kuten '**maanantai**' tai '**torstaina**', mutta vain kun mainitset ne ensi kertaa, ja vain viikonpäivät, ei muuta.
- Koska tämä on ennustus, puhu aina tulevassa aikamuodossa.

Nyt voit kirjoittaa valmiin tekstin. Älä kirjoita mitään muuta kuin valmis teksti. Kiitos!
"""
    
    # To view the output in English, add the following to the prompt:
    # prompt += "\nFor the English readers, please write your final response in English. Thank you!"
    
    # print(prompt)
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": f"{prompt}"},
            ],
            temperature=0.7,
            max_tokens=512,
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