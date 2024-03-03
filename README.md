# Nordpool FI Spot Price Prediction

**This is a Python app that predicts electricity prices for the Nordpool FI market. It fetches a 5-day weather forecast and more, and uses them to predict future Nordpool FI electricity prices, using a trained Random Forest model.**

Live version: https://sahkovatkain.web.app

If you need the predictions, you'll find them in the [deploy](deploy) folder. See [below](#home-assistant-chart) for Home Assistant instructions. Alternatively, download [index.html](deploy/index.html) from this repository, save it, and open it locally to see the current prediction.

This repository contains all the code and much of the data to re-train the model, generate predictions, express a quantitative model analysis and plot the results.

[TOC]

<img src="data/home_assistant_sample_plot.png" alt="Predictions shown inside Home Assistant using ApexCharts" style="zoom:50%;" />

## Model performance

TODO

## Co-authors

The original RF model was initially co-trained with [Autogen](https://github.com/microsoft/autogen). GPT-4 was used a lot during coding, but a real human has re-written most of the code and comments by hand, including this README. Originally the project was a personal Autogen + AI pair programming evaluation/trial and a hobby project written over 2 weekends.

In addition to Random Forest, we (human and AI) also tried Linear Regression, GBM and LSTM, and a Random Forest with Linear Regression scaling. Out of these, the RF model performed the best, so that's what's used here.

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
usage: nordpool_predict_fi.py [-h] [--train] [--eval] [--training-stats] [--dump] [--past-performance] [--plot] [--predict] [--add-history] [--narrate] [--commit] [--deploy] [--publish] [--github]

options:
  -h, --help          show this help message and exit
  --train             Train a new model candidate using the data in the database
  --eval              Show evaluation metrics for the current database
  --training-stats    Show training stats for candidate models in the database as a CSV
  --dump              Dump the SQLite database to CSV format
  --past-performance  Generate past performance stats for recent months
  --plot              Plot all predictions and actual prices to a PNG file in the data folder
  --predict           Generate price predictions from now onwards
  --add-history       Add all missing predictions to the database post-hoc; use with --predict
  --narrate           Narrate the predictions into text using an LLM
  --commit            Commit the results to DB and deploy folder; use with --predict, --narrate, --past-performance
  --deploy            Deploy the output files to the deploy folder but not GitHub
  --github            Push the deployed files to a GitHub repo; use with --deploy
```

See the data/create folder for a set of DB initialization scripts if you need them. You may need to fetch some of the data sets from their original sources.

### How to run locally

First make sure you've installed the requirements from requirements.txt. The main script is one flow with multiple optional stops, and you can choose one or many of them in almost any combination.

Examples:

- Start with: `python nordpool_predict_fi.py --predict` to create a set of price predictions for 7 days into the past and 5 days into the future with NO commit to DB

- Longer end to end pipeline: Train a new model, show eval stats for it, update a price forecast data frame with it, narrate the forecast, commit it to your SQLite database and deploy the json/md outputs with that data: `python nordpool_predict_fi.py --train --eval --predict --narrate --commit --deploy`

  Optionally, you can do a retrospective update to the PricePredict field for the whole DB by including `--add-history` into the command line above

  There is plenty of STDOUT info, it's a good idea to read it to see what's going on

- Open `index.html` from the `deploy` folder locally in your browser to see what you did; also see what's changed in the data and deploy folders

## How does this model work?

Surpisingly, this model (or problem) is **not** a time series prediction. Price now doesn't tell much about price in 2 hours before or after. Just look at the shape of the chart above.

Following intuition and observing past price fluctuations, outdoor temperature can hedge much of the price-impacting demand and wind can hedge much of the price-impacting supply, if the supply side is *otherwise* working as-usual on any given day. What if we ignore all the other variables and see what happens if we just follow the wind?

The idea here was to formalize that intuition through a data set and a model.

* A set of FMI weather stations near wind power clusters to measure wind speed, a predictor for wind power
* Another set near urban centers to measure wind speed, a predictor for consumption due to heating 

- Since the day of the week (Sunday vs. Monday) makes a difference, as does the time of the day (3 AM vs. 7 PM), and a month (January vs. July), those too were included as variables. But the day-of-the-month was not, because all it says is likely already captured by the weather, the time and the weekday.

- Nuclear power production data is included post-hoc and near future is inferred from last known values. Planned or unplanned maintenance break can offset a large amount of supply that wind power then needs to replace. The model reacts to these with a few hours a delay, as the drop becomes apparent in the input data.

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

The columns starting with `t_` and `ws_` are [FMSIDs](https://www.ilmatieteenlaitos.fi/havaintoasemat?filterKey=groups&filterQuery=sää) of the FMI weather stations nearest to the locations of interest. They offer both observations and forecasts that have a high correlation with each other post-hoc. As a side effect of this approach, the repository also contains [functions](util/fmi.py) for working with FMI history/forecast queries.

### Hidden patterns in weather/price data

As code, the price information is learned from, or is a function of, patterns and correlations between the above factors, as learned by the model.

> **Example scenarios to illustrate the correlations:**
>
> - Early Spring Morning: 3°C at 5 AM with 2 m/s wind speed - Expected Price: 6 to 10 cents/kWh due to moderate heating demand and low wind energy contribution.
> - Chilly Fall Evening: 8°C at 6 PM with 1 m/s wind speed - Expected Price: 5 to 8 cents/kWh, increased demand for heating with minimal wind energy supply.
> - Cold Winter Night: -12°C at 2 AM with 4 m/s wind speed - Expected Price: 12 to 18 cents/kWh due to high heating demand, partially offset by moderate wind generation.
> - Mild Spring Afternoon: 16°C at 3 PM with 5 m/s wind speed - Expected Price: 3 to 5 cents/kWh, a balance of mild demand and good wind supply.
> - Cool Autumn Midnight: 6°C at 11 PM with 6 m/s wind speed - Expected Price: 1 to 3 cents/kWh, low demand and high wind energy generation.

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
   python nordpool_predict_fi.py --train --eval
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

3. Call that function as part of the chain that builds the data frame for the predictions. Again, your function can either add a column, or edit the existing columns.

   If you need to debug: 7+5 days is 12 days, and that is 288 hours. That should be the number of rows given back by your function. For example:

   ```shell
   python nordpool_predict_fi.py --predict
   ...
   My_function_debug_output:
   ...
   [288 rows x 12 columns] # do we have +1 in the columns and 288 rows after df update by your function?
   ```

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

