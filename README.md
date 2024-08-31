# Nordpool FI Spot Price Prediction

**This is a Python app that predicts electricity prices for the Nordpool FI market. It fetches a 5-day weather forecast and more, and uses them to predict future Nordpool FI electricity prices, using a trained ~~Random Forest~~ XGBoost model.**

Live version: https://sahkovatkain.web.app

If you need the predictions, you'll find them in the [deploy](deploy) folder. See [below](#home-assistant-chart) for Home Assistant instructions. Alternatively, download [index.html](deploy/index.html) from this repository, save it, and open it locally to see the current prediction.

This repository contains all the code and much of the data to re-train the model, generate predictions, express a quantitative model analysis and plot the results.

[TOC]

<img src="data/home_assistant_sample_plot.png" alt="Predictions shown inside Home Assistant using ApexCharts" style="zoom:50%;" />

## Co-authors

The original RF model was initially co-trained with [Autogen](https://github.com/microsoft/autogen). Language models were used a lot during coding, but a real human has re-written most of the code and comments by hand, including this README. Originally the project was a personal Autogen + AI pair programming evaluation/trial and a hobby project written over 2 weekends, with some updates since.

In addition to Random Forest, we also tried Linear Regression, GBM and LSTM, and a Random Forest with Linear Regression scaling. Out of these, the RF model performed the best, so that's what's used here.

**Aug 31, 2024:** After grid search [experiments](data/create/91_model_experiments/rf_vs_world.py) measuring Random Forest, XGBoost, Gradient Boosting, and Light GBM, we're currently running XGBoost by default.

[Continue.dev](https://github.com/continuedev/continue) was and remains the tool of choice for AI pair programming.

## Usage

Clone the repository, `pip install -r requirements` in a new environment.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The script uses environment variables for configuration. These can be set in a file called `.env.local`. Check  `.env.local.template` [and the comments](.env.local.template) on what the variables are. Most of the defaults should be OK.

How to use:

```shell
usage: nordpool_predict_fi.py [-h] [--train] [--eval] [--training-stats] [--dump] [--plot] [--predict] [--add-history] [--narrate] [--commit] [--deploy] [--publish]

options:
  -h, --help          show this help message and exit
  --train             Train a new model candidate using the data in the database; use with --predict
  --eval              Show evaluation metrics for the current database
  --training-stats    Show training stats for candidate models in the database as a CSV
  --dump              Dump the SQLite database to CSV format
  --plot              Plot all predictions and actual prices to a PNG file in the data folder
  --predict           Generate price predictions from now onwards
  --add-history       Add all missing predictions to the database post-hoc; use with --predict
  --narrate           Narrate the predictions into text using an LLM
  --commit            Commit the results to DB and deploy folder; use with --predict, --narrate
  --deploy            Deploy the output files to the deploy folder
```

See the data/create folder for a set of DB initialization scripts if you need them. You may need to fetch some of the data sets from their original sources.

### How to run locally

First make sure you've installed the requirements from requirements.txt. The main script is one flow with multiple optional stops, and you can choose one or many of them in almost any combination.

Examples:

- Start with: `python nordpool_predict_fi.py --train --predict` to create a set of price predictions for 7 days into the past and 5 days into the future with NO commit to DB. Training happens in-memory and the model file is not saved. This should take less than a minute on a modern CPU.

- Longer end to end pipeline: Train a new model, show eval stats for it, update a price forecast data frame with it, narrate the forecast, commit it to your SQLite database and deploy the json/md outputs with that data: `python nordpool_predict_fi.py --train --predict --narrate --commit --deploy`.

  Optionally, you can do a retrospective update to the PricePredict field for the whole DB by including `--add-history` into the command line above.

  There is plenty of STDOUT info, it's a good idea to read it to see what's going on.

- You'll find `prediction.json` in your `deploy` folder. This file contains the prediction for the coming days. The first number of each pair is milliseconds since epoch, the second number is predicted price as cents per kWh with VAT 24%. See [how to use this data in your apps](https://github.com/vividfog/nordpool-predict-fi?tab=readme-ov-file#how-to-use-the-data-in-your-apps).

- The `--predict` option creates and rotates snapshot JSON files of daily predictions for a week. This data can be used to visualize, how the predictions change over time.

- Open `index.html` from the `deploy` folder locally in your browser to see what you did; also see what's changed in the data and deploy folders.

### Sample run

Here's what a no-commit trial run might look like.

```shell
python nordpool_predict_fi.py --train --predict
Training a new model candidate using the data in the database...
* FMI Weather Stations for Wind:
['ws_101673', 'ws_101256', 'ws_101846', 'ws_101267']
* FMI Weather Stations for Temperature:
['t_101786', 't_101118', 't_100968', 't_101339']
→ Data for training, a sampling:
       day_of_week  hour  NuclearPowerMW  ImportCapacityMW  ws_101673  ws_101256  ws_101846  ws_101267  t_101786  t_101118  t_100968  t_101339
6193             6     1     3560.649997            2436.0        7.7       11.3        4.9       12.5      8.30     13.10     14.70     10.50
12211            4    19     3027.955000            2739.0        5.9        1.4        7.2        3.0     12.57     18.64     16.23     17.93
3717             7    21     3986.749997            3466.0        8.7       10.8        7.3        6.4      9.10     10.20     10.40      8.00
8878             5    22     4324.489997            3461.0        5.4        4.9        5.2        3.7    -28.50    -20.70    -16.20    -28.40
8290             2    10     4399.799996            3446.0        5.8        4.4        4.7        4.9    -11.20     -9.00     -8.30    -12.20
→ Feature Importance:
         Feature  Importance
        t_101118    0.176956
        t_100968    0.145068
ImportCapacityMW    0.110822
  NuclearPowerMW    0.099665
        t_101339    0.086524
            hour    0.069084
       ws_101256    0.065383
     day_of_week    0.064194
        t_101786    0.059386
       ws_101267    0.044082
       ws_101673    0.041684
       ws_101846    0.037152
→ Durbin-Watson autocorrelation test: 1.98
→ ACF values for the first 5 lags:
  Lag 1: 1.0000
  Lag 2: 0.0088
  Lag 3: 0.0465
  Lag 4: 0.0139
  Lag 5: 0.0411
  Lag 6: -0.0218
→ Model trained:
  MAE (vs test set): 1.1321738186463985
  MSE (vs test set): 3.386582976961483
  R² (vs test set): 0.883941221390727
  MAE (vs 10x500 randoms): 0.6527679246515273
  MSE (vs 10x500 randoms): 35.001805827151195
  R² (vs 10x500 randoms): 0.6761444937432602
→ Model NOT saved to the database but remains available in memory for --prediction.
→ Training done.
Running predictions...
* Fetching wind speed forecast and historical data between 2024-08-24 and 2024-09-05
* Fetching temperature forecast and historical data between 2024-08-24 and 2024-09-05
* Fetching nuclear power production data between 2024-08-24 and 2024-09-05 and inferring missing values
* Fingrid: Fetched 3731 hours, aggregated to 187 hourly averages spanning from 2024-08-24 to 2024-08-31
→ Fingrid: Using last known nuclear power production value: 3550 MW
* Fetching import capacities between 2024-08-24 and 2024-09-05
* Fetching electricity price data between 2024-08-24 and 2024-09-05
→ Days of data coverage (should be 7 back, 5 forward for now):  12
→ Found a newly created in-memory model for predictions
                    Timestamp  PricePredict_cpkWh  ws_101256  ws_101267  ws_101673  ws_101846  t_101118  t_101339  t_101786  t_100968  NuclearPowerMW  ImportCapacityMW  Price_cpkWh
0   2024-08-24 20:00:00+00:00           -0.127842        5.5        5.8        7.7        6.2     16.31     16.04     16.69     16.09     3156.580000            2218.0      -0.1476
1   2024-08-24 21:00:00+00:00           -0.472777        5.5        5.5        6.5        5.1     15.67     15.18     16.26     15.48     3157.830000            2213.0      -0.2492
2   2024-08-24 22:00:00+00:00            0.268920        5.5        5.3        5.3        4.1     15.03     14.32     15.83     14.87     3158.110000            1880.0      -0.1922
3   2024-08-24 23:00:00+00:00            1.871971        5.6        5.0        4.1        3.1     14.39     13.46     15.39     14.26     3161.435000            1880.0      -0.2468
4   2024-08-25 00:00:00+00:00            0.043346        5.6        4.8        2.9        2.1     13.76     12.61     14.96     13.65     3160.985000            1878.0      -0.2505
5   2024-08-25 01:00:00+00:00           -0.043021        5.8        5.2        3.5        2.5     14.16     13.16     15.05     14.38     3160.960000            1878.0      -0.2170
6   2024-08-25 02:00:00+00:00           -0.124118        6.1        5.7        4.2        2.9     14.56     13.71     15.15     15.10     3159.960000            1878.0      -0.2170
7   2024-08-25 03:00:00+00:00            0.195499        6.3        6.1        4.9        3.4     14.96     14.27     15.24     15.83     3160.250000            1880.0      -0.2170
8   2024-08-25 04:00:00+00:00           -0.111654        6.6        6.6        5.5        3.8     15.36     14.82     15.33     16.55     3161.650000            1880.0      -0.1600
9   2024-08-25 05:00:00+00:00           -0.092328        6.8        7.0        6.2        4.2     15.76     15.37     15.42     17.27     3161.200000            1880.0      -0.1116
10  2024-08-25 06:00:00+00:00           -0.099133        7.0        7.5        6.8        4.6     16.16     15.92     15.51     18.00     3160.540000            1880.0      -0.1116
...
278 2024-09-05 10:00:00+00:00            1.604935        5.4        3.8        8.0        5.6     21.91     21.48     20.46     22.61     3549.733333            2193.0          NaN
279 2024-09-05 11:00:00+00:00            1.397185        5.6        3.8        8.0        5.5     23.36     22.77     21.14     23.79     3549.733333            2193.0          NaN
280 2024-09-05 12:00:00+00:00            1.276368        5.8        3.8        8.0        5.5     24.81     24.06     21.82     24.97     3549.733333            2193.0          NaN
281 2024-09-05 13:00:00+00:00            1.773011        5.8        4.0        8.2        5.3     23.83     22.98     21.50     24.01     3549.733333            2193.0          NaN
282 2024-09-05 14:00:00+00:00            1.811605        5.9        4.2        8.5        5.1     23.84     22.90     21.78     23.83     3549.733333            2193.0          NaN
283 2024-09-05 15:00:00+00:00            2.613164        5.9        4.4        8.7        4.9     22.61     21.57     21.31     22.67     3549.733333            2193.0          NaN
284 2024-09-05 16:00:00+00:00            2.142339        6.0        4.6        8.9        4.7     21.38     20.24     20.84     21.51     3549.733333            2193.0          NaN
285 2024-09-05 17:00:00+00:00            2.272456        6.0        4.8        9.2        4.5     20.15     18.91     20.37     20.34     3549.733333            2193.0          NaN
286 2024-09-05 18:00:00+00:00            1.627901        6.0        4.9        9.4        4.3     18.92     17.59     19.91     19.18     3549.733333            2193.0          NaN
287 2024-09-05 19:00:00+00:00            0.887464        6.2        5.1        9.5        4.7     17.96     16.66     19.26     18.13     3549.733333            2193.0          NaN
* Predictions NOT committed to the database (no --commit).
```

## How does the model work?

Surprisingly, this model (or problem) is **not** a time series prediction. Price now doesn't tell much about price in 2 hours before or after, and the intraday spikes frequently seen in Nordpool charts do seem quite unpredictable. According to the hypothesis, trying to follow temporal patterns would be futile, so the model does what it can to *not* use movement of time as a predictor.

Also, the price can vary with a 1000x magnitude within the same year. While outliers are normal and the one-hour spikes are OK to miss, we should have the correct number of digits in our prediction, whether the realized price is 0.1 cents, 1 cent, 10 cents or 100 cents. If we're (far) more accurate than that, that's a bonus.

Following intuition and observing past price fluctuations, outdoor temperature can account for much of the price-impacting demand and wind can explain much of the price-impacting supply, if the supply side is *otherwise* working as-usual on any given day. What if we ignore all the other variables and see what happens if we just follow the wind?

The idea here was to formalize that intuition through a data set and a model.

- A set of [FMI weather stations](https://www.ilmatieteenlaitos.fi/havaintoasemat?filterKey=groups&filterQuery=sää) near wind power clusters to measure **wind speed**, a predictor for wind power. Any wind power model is likely to use this data as well, so we skip the interim step of predicting wind power production and use a small set of its component predictors instead.
- A set near urban centers to measure **temperature**, a predictor for consumption due to heating. If it's cold in these urban centers, electricity consumption tends to go up.
- For weather observations and forecasts, we use FMI stations that are the original source of observations and not part of an interpolated figure, and therefore likely a good souce for a weather forecast too. While it's possible to get a grid prediction for a bounding box, that's effectively stacking more models into the pipeline, potentially adding not just signal but also noise.

- **Nuclear power** production data: Planned or unplanned maintenance break can offset a large amount of supply that wind power then needs to replace. The model can use ENTSO-E messages to deduce near-future nuclear capacity, and failing that, falls back to the last known realized value from Fingrid.
- Since the **day of the week** (Sunday vs. Monday) makes a difference, as does the **time of the day** (3 AM vs. 7 PM), and a **month** (January vs. July), those too were included as labels. But the day-of-the-month was not, because all it says is likely already captured by the weather, the time and the weekday. Out of these, month turned out to have negligible predictive power and the other time variables are far behind wind/temperature/production variables too. These could be removed and the forecast would still be usable.
  - **Month** has since been removed from the data, as the model should be able to infer the seasonal effects by paying attention to the temperatures. Just because it's December doesn't necessarily mean it's cold, and May of next year can be much colder than May of last year.
- **Import capacity**: The total available import capacity from Sweden and Estonia: SE1, SE3 and EE, in megawatts. When there's shortage in transfer capacity due to maintenance or other reasons, Finland can't import cheap energy from abroad, which tends to inflate prices. (Adding export capacity is under consideration.)
- Time stamps are stripped off from the training data, and the data set is shuffled before training. This is to further enforce the hypothesis to NOT use time and temporal relations as a predictor, but instead infer the price from weather and production data. Data analysis shows the training data has negligible autocorrelation (temporal patterns) after these operations.

Data schema used for training and inference is this:

```sql
CREATE TABLE prediction (
    timestamp TIMESTAMP PRIMARY KEY,
    "ws_101256" FLOAT,
    "ws_101267" FLOAT,
    "ws_101673" FLOAT,
    "ws_101846" FLOAT,
    "t_101118" FLOAT,
    "t_101339" FLOAT,
    "t_101786" FLOAT,
    "t_100968" FLOAT,
    "WindPowerCapacityMW" FLOAT,
    "NuclearPowerMW" FLOAT,
    "Price_cpkWh" FLOAT,
    "PricePredict_cpkWh" FLOAT,
    "ImportCapacityMW" FLOAT);
CREATE TABLE sqlite_sequence(name,seq);
```

The columns starting with `t_` and `ws_` are [FMSIDs](https://www.ilmatieteenlaitos.fi/havaintoasemat?filterKey=groups&filterQuery=sää) of the FMI weather stations nearest to the locations of interest. They offer both observations and forecasts that have a high correlation with each other post-hoc. As a side effect of this approach, the repository also contains [functions](util) for working with FMI history/forecast queries, Fingrid open data and ENTSO-E market messages APIs.

### Hidden patterns in weather/price data

As code, the price information is learned from, or is a function of, patterns and correlations between the above factors, as learned by the model.

> **Example scenarios to illustrate the correlations:**
>
> - Early Spring Morning: 3°C at 5 AM with 2 m/s wind speed - Expected Price: 6 to 10 cents/kWh due to moderate heating demand and low wind energy contribution.
> - Chilly Fall Evening: 8°C at 6 PM with 1 m/s wind speed - Expected Price: 5 to 8 cents/kWh, increased demand for heating with minimal wind energy supply.
> - Cold Winter Night: -12°C at 2 AM with 4 m/s wind speed - Expected Price: 12 to 18 cents/kWh due to high heating demand, partially offset by moderate wind generation.
> - Mild Spring Afternoon: 16°C at 3 PM with 5 m/s wind speed - Expected Price: 3 to 5 cents/kWh, a balance of mild demand and good wind supply.
> - Cool Autumn Midnight: 6°C at 11 PM with 6 m/s wind speed - Expected Price: 1 to 3 cents/kWh, low demand and high wind energy generation.

### What are the important predictors in this model?

According to Feature Importance analysis, as of now they are:

| Feature        | Importance | Place: measurement     |
| -------------- | ---------- | ---------------------- |
| t_101339       | 0.211      | Oulu: temperature      |
| ws_101256      | 0.182      | Kaskinen: speed        |
| t_100968       | 0.162      | Vantaa: temperature    |
| NuclearPowerMW | 0.106      | 0...4372 megawatts     |
| t_101786       | 0.067      | Pirkkala: temperature  |
| hour           | 0.063      | 0...23                 |
| ws_101673      | 0.047      | Kalajoki: wind speed   |
| day_of_week    | 0.042      | 1...7                  |
| ws_101846      | 0.041      | Kemi: wind speed       |
| t_101118       | 0.034      | Jyväskylä: temperature |
| month          | 0.027      | 1...12                 |
| ws_101267      | 0.016      | Pori: wind speed       |

### Machine Learning Models Used

This project has so far applied two methods to predict electricity prices:

1. Random Forest (previously used):
   - Combines multiple decision trees
   - Each tree uses a random subset of features and data
   - Final prediction is an average from all trees

2. XGBoost (currently used):
   - Builds decision trees sequentially
   - Each new tree corrects errors from previous ones
   - Uses gradient boosting to minimize errors
   - Employs regularization to prevent overfitting
   - Known for speed and performance on structured data

Both models can effectively learn patterns from weather and other data to predict electricity prices, each with its own strengths. Based on an extensive grid search between these two, and other methods, XGBoost looks like the best option for now. 

## How long will this repository/data be updated?

**This is a hobby project, there is no guarantee to keep the code or data up to date in the long haul. That's why all the code is free and public.** All the data is free and public too, but the Nordpool spot data used by this repo can't be used for commercial purposes. Feel free to fork the project and make it your own, or submit a pull request. I'm using these predictions myself and plan to keep this code working as a hobby project, until there's a new and more important hobby project.

# How to use the data in your apps

## Local web page

If you download [index.html](deploy/index.html) and open it locally, it will draw the latest data in a nice format at runtime using eCharts. This is the same page which can be found at https://sahkovatkain.web.app.

## Python sample script

Pending an API, there's a sample script [deploy/npf.py](deploy/npf.py) to demonstrate how to fetch [prediction.json](deploy/prediction.json), convert it into a Pandas dataframe and save it to a CSV file.

## Home Assistant

You can show the Nordpool prices with predictions on your dashboard. The code uses official Nordpool prices for today and tomorrow (when available) and fills the rest of the chart with prediction data, as seen at the top of this README.

> [!NOTE]
>
> After 14:00, the "tomorrow" prices may show up empty for a while, until Nordpool publishes tomorrow's pricing and your Home Assistant gets a note of them now being available. Feel free to propose a more intelligent logic for the chart and submit a PR.

### Requirements

- [HACS](https://hacs.xyz), Home Assistant Community Store, which you can get from the [Add-On store](https://www.home-assistant.io/addons/), or follow the [docs](https://hacs.xyz/docs/setup/download/)

- [custom:apexcharts-card](https://github.com/RomRider/apexcharts-card) (available through HACS)
- [Nordpool integration](https://github.com/custom-components/nordpool), set to EUR VAT0 prices (available through HACS)
  - Adjust the sensor names to match yours: `sensor.nordpool_kwh_fi_eur_3_10_0`
  - Remove the "124" multiplication from your code, if your sensor already produces cent values with VAT

### Add the card to your dashboard

Add the contents of [deploy/npf.yaml](deploy/npf.yaml) as a "Manual" chart to your Lovelace dashboard. An alternative [deploy/npf2.yaml](deploy/npf2.yaml) shows the Nordpool vs prediction series in a different way. Choose the visual variation you prefer.

# Adding a new data source

The current process of adding a new data source to the model is somewhat manual. Here's the gist of it.

The main requirement is that you need to be able to predict your own input variable.

- Example: If you input wind power production in MW for the past year, you need to be able to predict the values for wind power production for the next 5 days as well. Otherwise, this leads to a recursive situation where we must predict our inputs before predicting our price, which can become a complex issue.

The existing data sources either use publicly available forecast data sources (e.g. weather), infer the data from existing data (e.g. weekday), or assume the last known number is next assumed number too (e.g. nuclear power production).

- An example of a smarter *existing* column: Create a function that has the ability to fill in nuclear power production into the respective column for 5 days into the future, perhaps by reading market messages.

- An example of a *new* column: SolarPowerMW, which follows, predicts or makes assumptions about solar power production in megawatts.

In both cases, your predictor function needs to return a data frame with 7 days to the past, and 5 days to the future, using the best assumptions (or sub-model) it can work with.

## 1. Prepare new data to learn from

You need to update the database to have a complete time series of your new training variable, so that you can refer to it during training.

1. Ensure you have the latest predictions.db from this repo to have baseline data in the `data` folder:

   ```shell
   git pull
   ```

2. Dump the whole database to a baseline CSV file you can work with: 

   ```shell
   python nordpool_predict_fi.py --dump > my_baseline.csv
   ```

3. Open the CSV to understand its structure. Your task is to add a new column and populate it with data. Ensure completeness for every hourly timestamp, avoiding NaN/NULL values.

4. Let's say your new column is called `SolarPowerMW`, you need to add that to the SQLite3 prediction.db schema.

   ```sqlite
   ALTER TABLE prediction ADD COLUMN SolarPowerMW FLOAT;
   ```

5. Convert the new column in your CSV to a set of SQL update statements that set or update the values for that column for every time stamp. Now you have a baseline prediction.db to work with.

   One approach is to use (Chat)GPT-4 or one of the open-license LLMs to generate SQL update statements from the CSV. Here's how you might phrase your prompt to the model. ChatGPT has a built-in Python interpreter which can do this for a dropped CSV file:

   > Take a look at this CSV file. Read the first few lines to learn its structure. Pay attention to the SolarPowerMW column. I want you to create SQLite3 statements that update the whole database with those values, matching the timestamps you find in the CSV. Focus only on timestamp and SolarPowerMW. Use Python to create a conversion script, then run it, and I'd like to download the final .sql file with the update statements.

   Then review and commit those updates to the database, for example:

   ```shell
   sqlite3 data/prediction.db < my_update_statements.sql
   ```

6. Verify that your new column is now part of the database:

   ```shell
   python nordpool_predict_fi.py --dump > my_new_column.csv
   ```

## 2. Update the training code to include your new column

1. Review how database columns are included in the util/train module before being passed to the training function.

2. Add yours to the list(s).

3. Try the training results, pay attention to the eval results. Compare them with and without your column:

   ```shell
   python nordpool_predict_fi.py --train --predict
   ```

​   Once you're satisified with the results, you can include this new column during the predict process too. 

## 3. Create a new predictor function as a utility

1. See the source code for how the util/FMI, Fingrid and Sahkotin functions work and how the main script calls them inside the `--train` and `--predict` arguments. These are in the util folder.

2. Create a function that accepts a data frame and returns a data frame. Add this to the util folder and import it. Use it after or in between the existing function calls.

   ```python
   df = update_wind_speed(df)
   df = update_nuclear(df, fingrid_api_key=fingrid_api_key)
   df = update_spot(df)
   df = update_se3(df) # this could be your new function
   ```

   The returned data frame should be the exact same DF passed to it, but now filled with data 7 days into the past and 5 days into the future. Merging data frames and working with time stamps can be a bit tricky, but there's sample code in the FMI/Fingrid/Sahkotin functions.

   > Failing that, just return a data frame that goes 5 days to the future, with time stamps. There's a helper function in util/dataframes.py to merge the DFs in the next step, currently used for ENTSO-E. The long term plan for "where to merge" is TODO.

3. Call that function as part of the chain that builds the data frame for the predictions. Again, your function can either add a column, or edit the existing columns.

   If you need to debug: 7+5 days is 12 days, and that is 288 hours. That should be the number of rows given back by your function. For example:

   ```shell
   python nordpool_predict_fi.py --train --predict
   ...
   My_function_debug_output:
   ...
   [288 rows x 12 columns]
   ```

   If you added a new column too, we'd have 13 columns instead of 12.

   If all goes well, you're ready to test.

## 4. Test your new model and function in apps

You've already verified earlier that the results are better than without this new/updated column, so we don't need to test that again.

1. Commit a new set of predictions to the database and deploy them to the JSON files in the deploy folder:

   ```shell
   python nordpool_predict_fi.py --train --predict --commit --deploy
   ```

2. Now you can test the JSON files with the index.html page, or with Home Assistant, or your preferred method. See how you like the results.

3. After confirming improvements with the new or updated column, please thoroughly test your model using the provided methods and submit a pull request.

Good luck!

If you run into trouble or have a suggestion on how to make this process easier, more modular, or more shareable, please write to the issue board.

## License

This project is licensed under the MIT License.