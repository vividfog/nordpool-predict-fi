import datetime
import requests
import json
import locale
import pandas as pd
import os
import pytz
from openai import OpenAI
from .sql import db_query

import pytz

def narrate_prediction(timestamp):
    """Fetch prediction data from the database and narrate it using an LLM."""
  
    # Create a DataFrame with timestamps for the next 5 days    
    df = pd.DataFrame({'Timestamp': pd.date_range(timestamp, timestamp + datetime.timedelta(days=5), freq='h')})
    # print(df)

    # Fetch data from the database
    df_result = db_query('data/prediction.db', df)

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
    # print(df_result)

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

    prompt = (f"// Tänään on {weekday_today.lower()} {date_today} ja ennusteet lähipäiville ovat seuraavat. Ole tarkkana että käytät näitä numeroita oikein:\n\n")

    for date, row in df.iterrows():
        prompt += (f"{date.strftime('%A %d.%m.%Y')}: Pörssisähkön hinta min {row[('PricePredict_cpkWh', 'min')]:.0f} ¢/kWh, max {row[('PricePredict_cpkWh', 'max')]:.0f} ¢/kWh, keskihinta {row[('PricePredict_cpkWh', 'mean')]:.0f} ¢/kWh.\n\n")
      
    prompt += """
// Kirjoita viihdyttävä ja rikasta suomen kieltä käyttävä UUTISARTIKKELI viihteellisen aikakauslehden kolumniin näiden tietojen pohjalta. Aloita kuvailemalla sähkön hinnan kehitystä lähipäiville, ja kommentoi sitten lähipäiviä kokonaisuutena. Tavoitepituus on noin 140-160 sanaa.
// Tiedoksi itsellesi: alle 7 ¢ on halpa hinta, 10 senttiä on kohtuullinen hinta ja yli 15-20 senttiä on lukijoille kallis hinta. Mutta kun viittaat hintoihin, kirjoita niistä numeroilla eikä adjektiiveilla.
// Älä mainitse päivämääriä, koska viikonpäivät riittävät. 
// Vältä turhaa toistoa ja älä anna mitään neuvoja! Tehtäväsi on puhua vain hinnoista! Ole perinpohjainen. 
// Käytä Markdown-muotoilua tekstin rakenteen tuottamiseksi. **Vahvenna** viikonpäivät, kuten '**maanantai**' tai '**torstaina**', mutta vain kun mainitset ne ensi kertaa.
// Koska tämä on ennustus, puhu aina tulevassa aikamuodossa!
// Nyt voit kirjoittaa valmiin tekstin. Kiitos!
"""
    
    # To view the output in English, add the following to the prompt:
    # prompt += "\nFor the English readers, please write your final response in English. Thank you!"
    
    # print(prompt)
    
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "system",
                "content": f"{prompt}"
            },
        ],
        temperature=0.3,
        max_tokens=1024,
        stream=False,
    )

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