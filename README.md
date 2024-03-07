# Nordpool FI Spot Price Prediction

**This is a Python app that predicts electricity prices for the Nordpool FI market. It fetches a 5-day weather forecast and more, and uses them to predict future Nordpool FI electricity prices, using a trained Random Forest model.**

Live version: https://sahkovatkain.web.app

If you need the predictions, you'll find them in the [deploy](deploy) folder. See [below](#home-assistant-chart) for Home Assistant instructions. Alternatively, download [index.html](deploy/index.html) from this repository, save it, and open it locally to see the current prediction.

This repository contains all the code and much of the data to re-train the model, generate predictions, express a quantitative model analysis and plot the results.

[TOC]

<img src="data/home_assistant_sample_plot.png" alt="Predictions shown inside Home Assistant using ApexCharts" style="zoom:50%;" />

## Co-authors

The original RF model was initially co-trained with [Autogen](https://github.com/microsoft/autogen). GPT-4 was used a lot during coding, but a real human has re-written most of the code and comments by hand, including this README. Originally the project was a personal Autogen + AI pair programming evaluation/trial and a hobby project written over 2 weekends.

In addition to Random Forest, we also tried Linear Regression, GBM and LSTM, and a Random Forest with Linear Regression scaling. Out of these, the RF model performed the best, so that's what's used here.

[Continue.dev](https://github.com/continuedev/continue) was the tool of choice for AI pair programming.

## Usage

Clone the repository, `pip install -r requirements` in a new environment.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The script uses environment variables for configuration. These can be set in a file called `.env.local`. Check  `.env.local.template` [and the comments](.env.local.template) on what the variables are. Most of the defaults should be OK.

How to use:

```
usage: nordpool_predict_fi.py [-h] [--train] [--eval] [--training-stats] [--dump] [--plot] [--predict] [--add-history] [--narrate] [--commit] [--deploy] [--publish] [--github]

options:
  -h, --help          show this help message and exit
  --train             Train a new model candidate using the data in the database
  --eval              Show evaluation metrics for the current database
  --training-stats    Show training stats for candidate models in the database as a CSV
  --dump              Dump the SQLite database to CSV format
  --plot              Plot all predictions and actual prices to a PNG file in the data folder
  --predict           Generate price predictions from now onwards
  --add-history       Add all missing predictions to the database post-hoc; use with --predict
  --narrate           Narrate the predictions into text using an LLM
  --commit            Commit the results to DB and deploy folder; use with --predict, --narrate
  --deploy            Deploy the output files to the deploy folder but not GitHub
  --github            Push the deployed files to a GitHub repo; use with --deploy
```

See the data/create folder for a set of DB initialization scripts if you need them. You may need to fetch some of the data sets from their original sources.

### How to run locally

First make sure you've installed the requirements from requirements.txt. The main script is one flow with multiple optional stops, and you can choose one or many of them in almost any combination.

Examples:

- Start with: `python nordpool_predict_fi.py --predict` to create a set of price predictions for 7 days into the past and 5 days into the future with NO commit to DB.

- Longer end to end pipeline: Train a new model, show eval stats for it, update a price forecast data frame with it, narrate the forecast, commit it to your SQLite database and deploy the json/md outputs with that data: `python nordpool_predict_fi.py --train --predict --narrate --commit --deploy`.

  Optionally, you can do a retrospective update to the PricePredict field for the whole DB by including `--add-history` into the command line above.

  There is plenty of STDOUT info, it's a good idea to read it to see what's going on.

- You'll find `prediction.json` in your deploy folder. This file contains the prediction for the coming days. The first number of each pair is milliseconds since epoch, the second number is predicted price as cents per kWh with VAT 24%. See [how to use this data in your apps](https://github.com/vividfog/nordpool-predict-fi?tab=readme-ov-file#how-to-use-the-data-in-your-apps).

- The `--predict` option creates and rotates snapshot JSON files of daily predictions for a week. This data can be used to visualize, how the predictions change over time.

- Open `index.html` from the `deploy` folder locally in your browser to see what you did; also see what's changed in the data and deploy folders.

### Sample run

Here's what a no-commit trial run might look like:

```
python nordpool_predict_fi.py --train --predict
[2024-03-08 00:16:18] Nordpool Predict FI
Training a new model candidate using the data in the database...
* FMI Weather Stations for Wind: ['ws_101673', 'ws_101256', 'ws_101846', 'ws_101267']
* FMI Weather Stations for Temperature: ['t_101786', 't_101118', 't_100968', 't_101339']
→ Feature Importance:
       Feature  Importance
      t_101339    0.211443
     ws_101256    0.181828
      t_100968    0.162449
NuclearPowerMW    0.106445
      t_101786    0.066850
          hour    0.062656
     ws_101673    0.047487
   day_of_week    0.042330
     ws_101846    0.040911
      t_101118    0.034386
         month    0.027271
     ws_101267    0.015943
→ Durbin-Watson autocorrelation test: 2.00
→ ACF values for the first 5 lags:
  Lag 1: 1.0000
  Lag 2: -0.0014
  Lag 3: -0.0237
  Lag 4: -0.0202
  Lag 5: -0.0028
  Lag 6: -0.0080
→ Model trained:
  MAE (vs test set): 1.7806310108575483
  MSE (vs test set): 17.125934255294478
  R² (vs test set): 0.8378969382433199
  MAE (vs 10x500 randoms): 1.1947948581029935
  MSE (vs 10x500 randoms): 10.365377264411277
  R² (vs 10x500 randoms): 0.9001239127137068
→ Model NOT saved to the database but remains available in memory for --prediction.
→ Training done.
Running predictions...
* Fetching wind speed forecast and historical data between 2024-02-29 and 2024-03-12
* Fetching temperature forecast and historical data between 2024-02-29 and 2024-03-12
* Fetching nuclear power production data between 2024-02-29 and 2024-03-12 and inferring missing values
* Fingrid: Fetched 2648 hours, aggregated to 133 hourly averages spanning from 2024-02-29 to 2024-03-05
→ Fingrid: Using last known nuclear power production value: 2764 MW
* ENTSO-E: Fetching nuclear downtime messages...
→ ENTSO-E: Avg: 2772, max: 2772, min: 2772 MW
* Fetching electricity price data between 2024-02-29 and 2024-03-12
→ Days of data coverage (should be 7 back, 5 forward for now):  12
→ Found a newly created in-memory model for predictions
                    Timestamp  PricePredict_cpkWh  ws_101256  ws_101267  ws_101673  ws_101846  t_101118  t_101339  t_101786  t_100968  NuclearPowerMW  Price_cpkWh
0   2024-03-01 00:00:00+00:00            0.268877       13.8       12.4       11.6       11.3      0.31      0.43      1.62      0.67        4228.760       0.0000
1   2024-03-01 01:00:00+00:00            0.239165       13.5       11.4       11.3       11.1      0.55      0.35      1.70      0.58        4228.825       0.0000
2   2024-03-01 02:00:00+00:00            0.338605       13.4       10.2       11.1       10.9      0.60      0.31      1.60      0.34        4229.235       0.0000
3   2024-03-01 03:00:00+00:00            0.729866       13.0       10.0       10.9       10.4      0.62      0.28      1.55      0.01        4228.350       0.0012
4   2024-03-01 04:00:00+00:00            2.111404       12.7       10.0       10.8        9.9      0.36      0.27      1.23     -0.35        4229.000       2.5370
..                        ...                 ...        ...        ...        ...        ...       ...       ...       ...       ...             ...          ...
283 2024-03-12 19:00:00+00:00           12.084022        2.2        2.1        4.7        2.1     -5.29     -7.53     -5.28     -6.27        2772.000          NaN
284 2024-03-12 20:00:00+00:00           12.363734        2.0        2.1        4.7        2.3     -5.87     -7.94     -5.59     -6.97        2772.000          NaN
285 2024-03-12 21:00:00+00:00           10.250964        1.9        2.4        4.5        2.5     -4.83     -6.69     -8.43     -4.51        2772.000          NaN
286 2024-03-12 22:00:00+00:00            8.946699        1.8        2.5        4.4        2.6     -5.52     -7.10     -8.61     -5.14        2772.000          NaN
287 2024-03-12 23:00:00+00:00            8.871415        1.6        2.5        4.3        2.8     -6.21     -7.51     -8.80     -5.77        2772.000          NaN

[288 rows x 12 columns]
* Predictions NOT committed to the database (no --commit).
```

## How does the model work?

Surprisingly, this model (or problem) is **not** a time series prediction. Price now doesn't tell much about price in 2 hours before or after, and the intraday spikes frequently seen in Nordpool charts do seem quite unpredictable. According to the hypothesis, trying to follow temporal patterns would be futile, so the model does what it can to *not* use movement of time as a predictor.

Also, the price can vary with a 1000x magnitude within the same year. While outliers are normal and the one-hour spikes are OK to miss, we should have the correct number of digits in our prediction, whether the realized price is 0.1 cents, 1 cent, 10 cents or 100 cents. If we're (far) more accurate than that, that's a bonus.

Following intuition and observing past price fluctuations, outdoor temperature can account for much of the price-impacting demand and wind can explain much of the price-impacting supply, if the supply side is *otherwise* working as-usual on any given day. What if we ignore all the other variables and see what happens if we just follow the wind?

The idea here was to formalize that intuition through a data set and a model.

* A set of [FMI weather stations](https://www.ilmatieteenlaitos.fi/havaintoasemat?filterKey=groups&filterQuery=sää) near wind power clusters to measure **wind speed**, a predictor for wind power. Any wind power model is likely to use this data as well, so we skip the interim step of predicting wind power production and use a small set of its component predictors instead.
* A set near urban centers to measure **temperature**, a predictor for consumption due to heating. If it's cold in these urban centers, electricity consumption tends to go up.
* For weather observations and forecasts, we use FMI stations that are the original source of observations and not part of an interpolated figure, and therefore likely a good souce for a weather forecast too. While it's possible to get a grid prediction for a bounding box, that's effectively stacking more models into the pipeline, potentially adding not just signal but also noise.

- **Nuclear power** production data: Planned or unplanned maintenance break can offset a large amount of supply that wind power then needs to replace. The model uses ENTSO-E messages to deduce near-future nuclear capacity, and failing that, falls back to the last known realized value from Fingrid.
- Since the **day of the week** (Sunday vs. Monday) makes a difference, as does the **time of the day** (3 AM vs. 7 PM), and a **month** (January vs. July), those too were included as labels. But the day-of-the-month was not, because all it says is likely already captured by the weather, the time and the weekday. Out of these, month turned out to have negligible predictive power and the other time variables are far behind wind/temperature/production variables too. These could be removed and the forecast would still be usable.
- Time stamps are stripped off from the training data, and the data set is shuffled before training. This is to further enforce the hypothesis to NOT use time and temporal relations as a predictor, but instead infer the price from weather and production data. Data analysis shows the training data has negligible autocorrelation (temporal patterns) after these operations.

Data schema used for training and inference is this:

```
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
    "PricePredict_cpkWh" FLOAT
);
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

### What's a Random Forest?

How can a Random Forest model learn these patterns to predict future prices based on future weather? That's a good question. We could ask GPT-4 to see what it says:

> A Random Forest model learns to predict outcomes, such as electricity prices based on weather and other conditions, through a combination of decision trees. Here's how it typically works for understanding and predicting patterns like those in your examples:
>
> 1. **Decision Trees**: At the heart of a Random Forest are decision trees. Each decision tree in the forest is built from a random subset of the data features ('Temp_dC', 'Wind_mps', 'WindPowerMW', etc.) and instances. These trees are grown to their maximum size without pruning, which makes them highly sensitive to the specific data they're trained on, capturing complex patterns including nonlinear relationships and interactions between variables.
>
> 2. **Randomness**: Two levels of randomness are introduced in a Random Forest: 
>    - **Feature Sampling**: When splitting a node, the model randomly selects a subset of the features to consider for the split. This ensures that the trees in the forest are diverse, which reduces the model's variance and helps to avoid overfitting.
>    - **Bootstrap Sampling**: Each tree is trained on a different bootstrap sample of the data (i.e., a sample drawn with replacement), which adds to the diversity among the trees.
>
> 3. **Aggregation (Bagging)**: The predictions from all the trees are aggregated (usually by averaging) to make a final prediction. This process of combining multiple models to improve the overall performance is known as bootstrap aggregating, or bagging. The aggregation reduces the variance without increasing the bias, making the model robust against overfitting and capable of capturing complex patterns in the data.
>
> 4. **Learning Correlations**: In the context of your examples, the Random Forest model would learn the intricate relationships between temperature, wind speed, time of day, and other factors with the electricity prices. Each tree in the forest would capture different aspects of these relationships based on the subset of data and features it's trained on. For instance, one tree might learn the importance of wind power capacity during high-demand periods, while another might focus on the impact of temperature during different seasons.
>
> 5. **Feature Importance**: An additional benefit of using Random Forests is that they can provide insights into the importance of each feature in predicting the outcome. In your case, this could help identify which factors (e.g., temperature, wind speed, time of day) are most influential in determining electricity prices.
>
> The Random Forest algorithm is particularly well-suited for this kind of prediction task because it can handle complex, nonlinear relationships between variables and is robust against overfitting. It achieves this by learning from the collective insights of multiple decision trees, each of which may capture different underlying patterns and correlations in the data.

That's a lot of hidden complexity that happens during the about 2 seconds it takes to re-train the model with the data. [It doesn't need a lot of code though.](util/train.py#L49)

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

- An example of a *new* column: Transmission_FI_SE3, which either predicts or makes assumptions about the transfer lines between Finland and Northern Sweden.

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

4. Let's say your new column is called `Transmission_FI_SE3`, you need to add that to the SQLite3 prediction.db schema.

   ```sqlite
   ALTER TABLE prediction ADD COLUMN Transmission_FI_SE3 FLOAT;
   ```

5. Convert the new column in your CSV to a set of SQL update statements that set or update the values for that column for every time stamp. Now you have a baseline prediction.db to work with.

   One approach is to use (Chat)GPT-4 or one of the open-license LLMs to generate SQL update statements from the CSV. Here's how you might phrase your prompt to the model. ChatGPT has a built-in Python interpreter which can do this for a dropped CSV file:

   > Take a look at this CSV file. Read the first few lines to learn its structure. Pay attention to the Transmission_FI_SE3 column. I want you to create SQLite3 statements that update the whole database with those values, matching the timestamps you find in the CSV. Focus only on timestamp and Transmission_FI_SE3. Use Python to create a conversion script, then run it, and I'd like to download the final .sql file with the update statements.

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
   python nordpool_predict_fi.py --train
   ```

​	Once you're satisified with the results, you can include this new column during the predict process too. 

## 3. Create a new predictor function as a utility

1. See the source code for how the util/FMI, Fingrid and Sahkotin functions work and how the main script calls them inside the `--train` and `--predict` arguments. These are in the util folder.

2. Create a function that accepts a data frame and returns a data frame. Add this to the util folder and import it. Use it after or in between the existing function calls.

   ```
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
   python nordpool_predict_fi.py --predict
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
   python nordpool_predict_fi.py --predict --commit --deploy
   ```

2. Now you can test the JSON files with the index.html page, or with Home Assistant, or your preferred method. See how you like the results.

3. After confirming improvements with the new or updated column, please thoroughly test your model using the provided methods and submit a pull request.

Good luck!

If you run into trouble or have a suggestion on how to make this process easier, more modular, or more shareable, please write to the issue board.

## License

This project is licensed under the MIT License.

