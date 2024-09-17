# Nordpool FI Spot Price Prediction

**This is a Python app that predicts electricity prices for the Nordpool FI market. It fetches a 5-day weather forecast and more, and uses them to predict future Nordpool FI electricity prices, using a set of fine-tuned XGBoost models. Works with Random Forest, Gradient Boost, potentially other .joblib type models too.**

Live version: https://sahkovatkain.web.app

If you need the predictions, you'll find them in the [deploy](deploy) folder. See [below](#home-assistant-chart) for Home Assistant instructions. Alternatively, download [index.html](deploy/index.html) from this repository, save it, and open it locally to see the current prediction.

This repository contains all the code and much of the data to re-train the required 2 models, generate predictions, express a quantitative model analysis and plot the results.

[TOC]

<img src="data/home_assistant_sample_plot.png" alt="Predictions shown inside Home Assistant using ApexCharts" style="zoom:50%;" />

## Background

The repository began as a personal [Autogen](https://github.com/microsoft/autogen) + LLM pair programming evaluation/trial/learning/hobby, written over some weekends. 

All of the code is curated by an actual person, but there may be some AI commentary left in the code. The repository remains an evaluation tool for testing new LLMs and their coding capabilities in ML projects. If the output is useful for price prediction, that is definitely a bonus, but this is primarily a playground for tracking the evolution of AI pair programming and what can be done with it.

## Updates

**Aug 31, 2024:** After hyperparameter optimization [experiments](data/create/91_model_experiments/) measuring Random Forest, XGBoost, Gradient Boosting, and Light GBM, we're currently running XGBoost by default.

**Sep 17, 2024:** Added a wind power model training and tuning [routine](https://github.com/vividfog/nordpool-predict-fi/tree/main/data/create/91_model_experiments) for wind power preditions. It generates a .joblib file required by `utils/fingrid_windpower.py`. The updated `--predict` routine now consults this model. The same folder has a script for price prediction model tuning with [Optuna](https://github.com/optuna/optuna). Wind power prediction is now an optional extra chart for Home Assistant users, see below.

[Continue.dev](https://github.com/continuedev/continue) was and remains the tool of choice for AI pair programming. The choice of LLMs is a range of locally running and commercial models, typically the latest available and currently under evaluation.

## Usage

Clone the repository, `pip install -r requirements` in a dedicated Python environment.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The repo uses environment variables for configuration. These can be set in a file called `.env.local`. Check  `.env.local.template` [and the comments](.env.local.template) on what the variables are. Most of the defaults should be OK.

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

See the `data/create` folders for a set of DB initialization scripts if you need them. You may need to fetch some of the data sets from their original sources. The CSV and SQL database dumps are updated from time to time.

### How to use

First make sure you've installed the requirements from requirements.txt. The main script is one flow with multiple optional stops, and you can choose one or many of them in almost any combination.

Examples:

- Start with: `python nordpool_predict_fi.py --train --predict` to create a set of price predictions for 7 days into the past and 5 days into the future with no commit back to database. Training happens in-memory and the model file is not saved. This should take a minute or few on a modern CPU. Even a Raspberry Pi is fine for predicitons, if model development and tuning is first done elsewhere.

- Longer pipeline: Train a new model, show eval stats for it, update a price forecast data frame with it, narrate the forecast, commit it to your SQLite database and deploy the json/md outputs with that data: `python nordpool_predict_fi.py --train --predict --narrate --commit --deploy`.

  There is plenty of STDOUT info, it's a good idea to read it to see what's going on.

- You'll find `prediction.json` in your `deploy` folder. This file contains the prediction for the coming days. The first number of each pair is milliseconds since epoch, the second number is predicted price as cents per kWh with tax. See [how to use this data in your apps](https://github.com/vividfog/nordpool-predict-fi?tab=readme-ov-file#how-to-use-the-data-in-your-apps). The data format is made for eCharts and Apex Charts, for web and Home Assistant.

- The `--predict --commit --deploy` chain creates and rotates snapshot JSON files of daily predictions for a week. This data can be used to visualize, how the predictions change over time.

- Open `index.html` from the `deploy` folder locally in your browser to see what you did; also see what's changed in the data and deploy folders.

## How does the model work?

Surprisingly for many, this model (or problem) is **not** a time series prediction. Price now doesn't tell much about price in 2 hours before or after, and the intraday spikes frequently seen in Nordpool charts do seem quite unpredictable, quite literally flowing in the wind more than anything. The price can vary with a 1000x magnitude within the same year. 

While outliers are normal and the one-hour spikes are OK to miss, we target to have the correct number of digits in our prediction, whether the realized price is 0.1 cents, 1 cent, 10 cents or 100 cents, by recognizing the patterns in the data.

This is the current training data set:

- 20 [FMI weather stations](https://www.ilmatieteenlaitos.fi/havaintoasemat?filterKey=groups&filterQuery=sää) to report and forecast **wind speed**, a predictor for wind power. From this, we train our own wind power prediction, which the the main price prediction model then uses as a feature. 
- 20 weather stations to report and forecast **temperature**, a predictor for consumption due to heating. If it's cold in these urban centers, electricity consumption tends to go up.
- **Nuclear power** production data: Planned or unplanned maintenance break can offset a large amount of supply that wind power then needs to replace. The model can use ENTSO-E messages to deduce near-future nuclear capacity, and failing that, falls back to the last known realized value from Fingrid.
- **Day of the week** (Sunday vs. Monday) and time of the day** (3 AM vs. 7 PM), used as cyclical features via their sin/cos values. Month, day-of-month and year are not used for training, as one year can be very different from another.
- **Import capacity**: The total available import capacity from Sweden and Estonia: SE1, SE3 and EE, in megawatts. When there's shortage in transfer capacity due to maintenance or other reasons, Finland can't import cheap energy from abroad, which tends to inflate prices. (Adding export capacity is under consideration.)
- **Time stamps (year/month)** are stripped off from the training data, and the weekday/hour values are used as cyclical sin/cos values. Data analysis shows the training data has negligible autocorrelation (temporal patterns) after these operations.

### Hidden patterns in weather/price data

As code, the price information is learned from, or is a function of, patterns and correlations between the above factors, as learned by the model.

> **Example scenarios to illustrate the correlations:**
>
> - Early Spring Morning: 3°C at 5 AM with 2 m/s wind speed - Expected Price: 6 to 10 cents/kWh due to moderate heating demand and low wind energy contribution.
> - Chilly Fall Evening: 8°C at 6 PM with 1 m/s wind speed - Expected Price: 5 to 8 cents/kWh, increased demand for heating with minimal wind energy supply.
> - Cold Winter Night: -12°C at 2 AM with 4 m/s wind speed - Expected Price: 12 to 18 cents/kWh due to high heating demand, partially offset by moderate wind generation.
> - Mild Spring Afternoon: 16°C at 3 PM with 5 m/s wind speed - Expected Price: 3 to 5 cents/kWh, a balance of mild demand and good wind supply.
> - Cool Autumn Midnight: 6°C at 11 PM with 6 m/s wind speed - Expected Price: 1 to 3 cents/kWh, low demand and high wind energy generation.
> - All these will vary a lot, if a transmission lines is not available, or if a nuclear plant is not in production, etc.

## How long will this repository/data be updated?

**This is a hobby project, there is no guarantee to keep the code or data up to date in the long haul. That's why all the code is free and public.** All the data is free and public too, but the Nordpool spot data used by this repo can't be used for commercial purposes. 

Feel free to fork the project and make it your own, or submit a pull request. We plan to keep this code working as a hobby project, until there's a new and more exciting hobby project.

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

Below one of those, you could add [deploy/npf_windpower.yaml](deploy/npf_windpower.yaml) for wind power predictions using the same scale.

# Adding a new data source

The current process of adding a new data source to the model is somewhat manual. Here's the gist of it.

**The main requirement is that you need to be able to predict the future of your own input variable. Your predictor function needs to return a data frame with 7 days of data to the past, and 5 days of data to the future, using the best APIs, assumptions (or sub-model) it can work with.**

The predictor function receives a data frame, and returns it with new column(s) added for the same 12 day window. This chain gets repeated until it is given to a model, with hyperparameters pre-set and optimized for the current feature list.

> **An example of a new column candidate: SolarPowerMW,** which reports and predicts something useful about solar power production. Either directly, or indirectly.
>
> You could find a data source that expresses UV radiation, hourly, for Finland, for 2023-2024 and can also predict it for the next 5 days. Such data source would work well for our purposes, as UV radiation likely goes hand in hand with solar power production.
>
> For more predictive "resolution", you could pass a set of these measurements and each one becomes a column in the main database and prediction data frame. Much like the 20+20 wind+temperature measurements already are.

## 1. Prepare new data to learn from

You need to update the database to have a complete time series of your new training variable, so that you can refer to it during training.

1. Ensure you have the latest predictions.db from this repo to have baseline data in the `data` folder:

   ```shell
   git pull
   ```

3. Open `data/dump.csv` and `dump.sql` to understand the structure of the DB as it is now. Your task is to add a new column and populate it with data. Ensure completeness for every hourly timestamp, avoiding NaN/NULL values.

4. Let's say your new column is called `SolarPowerMW`, you need to add that to the SQLite3 prediction.db schema.

   ```sqlite
   ALTER TABLE prediction ADD COLUMN SolarPowerMW FLOAT;
   ```

5. Convert the new column in your CSV to a set of SQL update statements that set or update the values for that column for every time stamp. Now you have a baseline prediction.db to work with.

   > You can find an archive of such scripts from in the `data/create` folders. 

   Then review and commit those updates to the database, for example:

   ```shell
   sqlite3 data/prediction.db < my_update_statements.sql
   ```
   
6. Verify that your new column is now part of the database:

   ```shell
   python nordpool_predict_fi.py --dump > my_new_column.csv
   ```

## 2. Find new hyperparameters for the model

1. Review how database columns are included in the `util/train` module(s) before being passed to the training function. There may be more than one, but only one is imported and in use.
2. Training, cross-validation and hyperparameter tuning scripts can be customized from `data/create/91*` folder. Use those to learn which model type and which parameters produce the best results, and how your new column ranks in feature importance.

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
   [288 rows x 27 columns]
   ```

   If you added a new column too, we'd have 28 columns instead of 27.

   If all goes well, you're ready to test.

## 4. Test your new model and function

You've already verified earlier that the results are better than without this new/updated column, so we don't need to test that again.

1. Commit a new set of predictions to the database and deploy them to the JSON files in the deploy folder:

   ```shell
   python nordpool_predict_fi.py --train --predict --commit --narrate --deploy
   ```

   This would perform the following steps:

   * Trains a model with all of the data in the DB (sans test slice), leaves the model in memory
   * Uses the a of functions (one being yours) to forward-fill all input data feature columns required for price prediction, using sub-models, APIs and extrapolation as applicable
   * Finally forward-fills the price prediction column too, with the main model
   * Commits the updated data frame back to SQLite
   * Uses an OpenAI model to narrate the next 5 days into text
   * Deploys the prediction and wind power JSON files to "deploy" folder for use

2. Now you can test the JSON files with the index.html page, or with Home Assistant, or your preferred method. See how you like the results.

3. After confirming improvements with the new or updated column, please thoroughly test your model using the provided methods and submit a pull request.

Good luck!

If you run into trouble or have a suggestion on how to make this process easier, more modular, or more shareable, please write to the issue board.

## License

This project is licensed under the MIT License. It is a hobby and it's free, but a shoutout would be nice if you use the code in public.