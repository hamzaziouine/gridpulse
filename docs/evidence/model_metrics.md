# Forecast model metrics (local run)

Generated 2026-11-23 01:51 UTC by `scripts/model_report.py` from the
gold tables written by `fabric/nb_forecast.Notebook` when run on a laptop through
`scripts/run_local.py` (local Spark 3.5, real IESO and Open-Meteo data 2019 to 2026).
**Tested locally only**: the same notebook has not run in Fabric yet.

MLflow run `078e123504194c85b17c4ecd0f901311` (local file store `mlruns/`), registered model `gridpulse_lgbm` version 2.

## Setup

- Target: Ontario demand (MW) for each hour of EST day T, issued on T-1 at 08:15 EST.
  Demand features use only days up to T-2 (what IESO has published at that time).
- Model: LightGBM, L1 objective, 45 features (calendar, population-weighted weather and
  the 5 city temperatures, demand lags of 48 h and more). Rounds chosen by early stopping
  on 2025.
- Weather (`train_weather = matched`): for each target day T, the Open-Meteo Previous
  Runs forecast at the lead the daily run really has (HE1..HE17 forecast 1 day ahead,
  HE18..HE24 2 days ahead), days T-1 and earlier from the Historical Forecast API.
  Hours the Previous Runs archive does not cover keep Historical Forecast weather,
  column by column: all variables before 2024-01-19, snowfall until 2024-12-06.
- Baseline: seasonal naive, same hour one week earlier (known at issue time).
- MAPE = mean absolute percentage error over hours; skill = 1 - MAPE model / MAPE naive.

## Results

| Evaluation | Period | Hours | Model MAPE % | Naive MAPE % | Model MAE (MW) | Skill vs naive % |
|---|---|---|---|---|---|---|
| Holdout: one model trained on 2019-2025, frozen | 2026-01-01 to 2026-11-06 | 7,417 | 2.90 | 6.84 | 493 | 57.6 |
| Backtest: retrained every month on the data known then | 2025-01-01 to 2026-11-06 | 16,175 | 2.56 | 6.95 | 435 | 63.1 |

Success criterion 6 of the proposal (beat seasonal-naive MAPE by at least 30 %) is met
in both evaluations, on historical data.

## Backtest by month

| Month | Model MAPE % | Naive MAPE % | Peak-hour APE % | Skill % | Hours |
|---|---|---|---|---|---|
| 2025-01 | 2.29 | 7.08 | 2.82 | 67.6 | 744 |
| 2025-02 | 1.90 | 4.05 | 1.92 | 53.2 | 672 |
| 2025-03 | 2.48 | 6.70 | 3.01 | 63.0 | 744 |
| 2025-04 | 2.45 | 6.02 | 2.74 | 59.3 | 720 |
| 2025-05 | 1.95 | 3.86 | 2.32 | 49.4 | 742 |
| 2025-06 | 3.40 | 9.08 | 4.73 | 62.6 | 720 |
| 2025-07 | 3.54 | 12.87 | 4.55 | 72.5 | 744 |
| 2025-08 | 2.37 | 14.51 | 3.25 | 83.6 | 744 |
| 2025-09 | 3.17 | 5.14 | 3.63 | 38.3 | 720 |
| 2025-10 | 1.69 | 5.53 | 1.30 | 69.5 | 744 |
| 2025-11 | 1.79 | 4.34 | 1.46 | 58.7 | 720 |
| 2025-12 | 2.11 | 4.97 | 2.08 | 57.5 | 744 |
| 2026-01 | 2.01 | 5.73 | 1.93 | 65.0 | 744 |
| 2026-02 | 2.14 | 5.60 | 1.78 | 61.8 | 672 |
| 2026-03 | 2.60 | 6.80 | 3.03 | 61.8 | 744 |
| 2026-04 | 2.72 | 6.59 | 2.64 | 58.7 | 720 |
| 2026-05 | 2.47 | 4.69 | 3.22 | 47.3 | 744 |
| 2026-06 | 3.07 | 10.35 | 4.88 | 70.3 | 720 |
| 2026-07 | 3.85 | 10.80 | 4.69 | 64.4 | 744 |
| 2026-08 | 3.42 | 7.67 | 3.68 | 55.4 | 744 |
| 2026-09 | 2.94 | 6.78 | 3.32 | 56.6 | 720 |
| 2026-10 | 2.05 | 3.94 | 2.06 | 47.8 | 744 |
| 2026-11 | 2.09 | 3.13 | 1.03 | 33.1 | 121 |

## Scored with weather of the production lead time

The tables above come from the notebook trained on lead-matched weather (its
default since 2026-11-23). This section is the comparison behind that choice.
In production the forecast for day T
is fetched on T-1 at 13:15 UTC, so the target hours are 23 to 46 h after the newest
model run. `scripts/backtest_weather_lead.py` replaces the weather of each target day
with the Open-Meteo Previous Runs API (same model gfs_seamless, same 5 cities and 9
variables), which keeps what the model forecast one day (day 1) and two days (day 2)
before each hour. Day T-1 and earlier keep the historical weather, as in `live_frame`.
The Previous Runs archive has all 9 variables only from 2024-12-07 (8 of them from
2024-01-20, snowfall later), so only target days from 2024-12-08 are scored here.
Generated 2026-11-23 01:05 UTC.

**Holdout 2026, model trained as above (Historical Forecast)**: 2026-01-01 to 2026-11-05, 7,411 hours, 936 rounds, seasonal naive MAPE 6.84 %.

| Weather used for day T | Model MAPE % | MAE (MW) | Peak-hour APE % | Skill vs naive % |
|---|---|---|---|---|
| Historical Forecast (lead of a few hours, as in training) | 2.70 | 458 | 3.02 | 60.5 |
| Previous Runs day 1 (about 24 to 30 h) | 2.97 | 505 | 3.29 | 56.6 |
| Lead-matched: day 1 for HE1..HE17, day 2 for HE18..HE24 | 3.07 | 523 | 3.48 | 55.2 |
| Previous Runs day 2 (about 48 to 54 h) | 3.19 | 546 | 3.63 | 53.3 |

**Monthly backtest, models trained as above**: 2025-01-01 to 2026-11-05, 16,145 hours, 936 rounds, seasonal naive MAPE 6.96 %.

| Weather used for day T | Model MAPE % | MAE (MW) | Peak-hour APE % | Skill vs naive % |
|---|---|---|---|---|
| Historical Forecast (lead of a few hours, as in training) | 2.45 | 416 | 2.90 | 64.8 |
| Previous Runs day 1 (about 24 to 30 h) | 2.63 | 444 | 2.93 | 62.3 |
| Lead-matched: day 1 for HE1..HE17, day 2 for HE18..HE24 | 2.74 | 465 | 3.15 | 60.7 |
| Previous Runs day 2 (about 48 to 54 h) | 2.92 | 498 | 3.30 | 58.1 |

**Holdout 2026, model retrained on lead-matched weather**: 2026-01-01 to 2026-11-05, 7,411 hours, 2998 rounds, seasonal naive MAPE 6.84 %.

| Weather used for day T | Model MAPE % | MAE (MW) | Peak-hour APE % | Skill vs naive % |
|---|---|---|---|---|
| Historical Forecast (lead of a few hours, as in training) | 2.83 | 481 | 3.16 | 58.6 |
| Previous Runs day 1 (about 24 to 30 h) | 2.85 | 484 | 3.20 | 58.4 |
| Lead-matched: day 1 for HE1..HE17, day 2 for HE18..HE24 | 2.88 | 489 | 3.30 | 58.0 |
| Previous Runs day 2 (about 48 to 54 h) | 3.04 | 520 | 3.48 | 55.5 |

**Monthly backtest, models retrained on lead-matched weather**: 2025-01-01 to 2026-11-05, 16,145 hours, 2998 rounds, seasonal naive MAPE 6.96 %.

| Weather used for day T | Model MAPE % | MAE (MW) | Peak-hour APE % | Skill vs naive % |
|---|---|---|---|---|
| Historical Forecast (lead of a few hours, as in training) | 2.57 | 436 | 2.94 | 63.0 |
| Previous Runs day 1 (about 24 to 30 h) | 2.53 | 428 | 2.81 | 63.6 |
| Lead-matched: day 1 for HE1..HE17, day 2 for HE18..HE24 | 2.57 | 436 | 2.93 | 63.1 |
| Previous Runs day 2 (about 48 to 54 h) | 2.79 | 476 | 3.15 | 59.9 |

How to read this:

- The lead-matched row is the closest to production (the production lead runs from
  23 to 46 h; day 1 is a little shorter, day 2 longer, so they bracket it).
- The retrained model sees lead-matched weather only from 2024-01-20 (earlier years
  keep Historical Forecast weather, snowfall keeps it until 2024-12-07). Its round count
  comes from early stopping on 2025, which did not stop before the 3,000-round cap.
  Its 2025 backtest months are therefore slightly optimistic; its 2026 holdout is clean.
- 2025-05-01 is left out (IESO is missing one hour that day), which is why the
  backtest has one day less than the table at the top.

Backtest by month, models trained as above:

| Month | Historical weather MAPE % | Lead-matched weather MAPE % | Naive MAPE % |
|---|---|---|---|
| 2025-01 | 2.56 | 2.31 | 7.08 |
| 2025-02 | 1.59 | 1.82 | 4.05 |
| 2025-03 | 2.43 | 2.57 | 6.70 |
| 2025-04 | 2.29 | 2.48 | 6.03 |
| 2025-05 | 2.00 | 2.09 | 3.92 |
| 2025-06 | 3.18 | 3.70 | 9.08 |
| 2025-07 | 3.50 | 4.14 | 12.88 |
| 2025-08 | 2.40 | 2.71 | 14.51 |
| 2025-09 | 3.06 | 3.47 | 5.14 |
| 2025-10 | 1.73 | 1.85 | 5.53 |
| 2025-11 | 1.87 | 1.79 | 4.34 |
| 2025-12 | 1.96 | 2.18 | 4.97 |
| 2026-01 | 1.90 | 2.12 | 5.73 |
| 2026-02 | 1.99 | 2.35 | 5.60 |
| 2026-03 | 2.67 | 2.70 | 6.80 |
| 2026-04 | 2.43 | 2.66 | 6.59 |
| 2026-05 | 2.31 | 2.71 | 4.69 |
| 2026-06 | 2.75 | 3.40 | 10.35 |
| 2026-07 | 3.50 | 4.10 | 10.80 |
| 2026-08 | 3.08 | 3.68 | 7.67 |
| 2026-09 | 2.52 | 3.24 | 6.78 |
| 2026-10 | 2.07 | 2.15 | 3.94 |
| 2026-11 | 2.32 | 2.00 | 3.12 |

## Limitations

- Lead-matched weather exists only from 2024 (complete from 2024-12-07), so most training
  years still use Historical Forecast weather for day T. The section above measures the
  lead effect on 2024-12 to 2026-11 only. Live rows (`split = 'live'` in `gold_forecast`)
  measure the real error once the daily pipeline runs in Fabric.
- Hardest months in the backtest: 2026-07 (3.85 %), 2025-07 (3.54 %), 2026-08 (3.42 %).
  Summer air-conditioning load swings with temperature, so weather forecast error
  matters most then.
- The model does not know about outages, large industrial changes or market rule changes
  (for example the Market Renewal go-live on 2025-05-01).
- Monitoring needed in production: weekly MAPE of the live rows against this backtest,
  drift of the weather inputs (population stability index per feature), and retraining
  when live MAPE stays above the backtest level for several weeks.
