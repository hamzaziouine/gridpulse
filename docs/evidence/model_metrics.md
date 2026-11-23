# Forecast model metrics (local run)

Generated 2026-11-23 01:06 UTC by `scripts/model_report.py` from the
gold tables written by `fabric/nb_forecast.Notebook` when run on a laptop through
`scripts/run_local.py` (local Spark 3.5, real IESO and Open-Meteo data 2019 to 2026).
**Tested locally only**: the same notebook has not run in Fabric yet.

MLflow run `456340525b064a7f85b28bada02d0085` (local file store `mlruns/`), registered model `gridpulse_lgbm` version 1.

## Setup

- Target: Ontario demand (MW) for each hour of EST day T, issued on T-1 at 08:15 EST.
  Demand features use only days up to T-2 (what IESO has published at that time).
- Model: LightGBM, L1 objective, 45 features (calendar, population-weighted weather and
  the 5 city temperatures, demand lags of 48 h and more). Rounds chosen by early stopping
  on 2025.
- Baseline: seasonal naive, same hour one week earlier (known at issue time).
- MAPE = mean absolute percentage error over hours; skill = 1 - MAPE model / MAPE naive.

## Results

| Evaluation | Period | Hours | Model MAPE % | Naive MAPE % | Model MAE (MW) | Skill vs naive % |
|---|---|---|---|---|---|---|
| Holdout: one model trained on 2019-2025, frozen | 2026-01-01 to 2026-11-05 | 7,411 | 2.70 | 6.84 | 458 | 60.5 |
| Backtest: retrained every month on the data known then | 2025-01-01 to 2026-11-05 | 16,169 | 2.45 | 6.95 | 416 | 64.8 |

Success criterion 6 of the proposal (beat seasonal-naive MAPE by at least 30 %) is met
in both evaluations, on historical data.

## Backtest by month

| Month | Model MAPE % | Naive MAPE % | Peak-hour APE % | Skill % | Hours |
|---|---|---|---|---|---|
| 2025-01 | 2.56 | 7.08 | 3.68 | 63.8 | 744 |
| 2025-02 | 1.59 | 4.05 | 1.71 | 60.7 | 672 |
| 2025-03 | 2.43 | 6.70 | 3.09 | 63.7 | 744 |
| 2025-04 | 2.29 | 6.02 | 2.42 | 62.0 | 720 |
| 2025-05 | 2.01 | 3.86 | 2.82 | 47.9 | 742 |
| 2025-06 | 3.18 | 9.08 | 4.56 | 65.0 | 720 |
| 2025-07 | 3.50 | 12.87 | 4.82 | 72.8 | 744 |
| 2025-08 | 2.40 | 14.51 | 3.37 | 83.5 | 744 |
| 2025-09 | 3.06 | 5.14 | 3.06 | 40.5 | 720 |
| 2025-10 | 1.73 | 5.53 | 1.82 | 68.7 | 744 |
| 2025-11 | 1.87 | 4.34 | 1.45 | 56.9 | 720 |
| 2025-12 | 1.96 | 4.97 | 1.98 | 60.6 | 744 |
| 2026-01 | 1.90 | 5.73 | 1.92 | 66.9 | 744 |
| 2026-02 | 1.99 | 5.60 | 2.08 | 64.5 | 672 |
| 2026-03 | 2.68 | 6.80 | 3.22 | 60.7 | 744 |
| 2026-04 | 2.43 | 6.59 | 2.75 | 63.2 | 720 |
| 2026-05 | 2.31 | 4.69 | 2.72 | 50.8 | 744 |
| 2026-06 | 2.75 | 10.35 | 3.96 | 73.4 | 720 |
| 2026-07 | 3.50 | 10.80 | 4.72 | 67.6 | 744 |
| 2026-08 | 3.09 | 7.67 | 3.05 | 59.8 | 744 |
| 2026-09 | 2.52 | 6.78 | 2.95 | 62.8 | 720 |
| 2026-10 | 2.07 | 3.94 | 1.84 | 47.3 | 744 |
| 2026-11 | 2.32 | 3.12 | 0.92 | 25.4 | 115 |

## Scored with weather of the production lead time

The tables above use Historical Forecast weather. In production the forecast for day T
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

- Weather inputs of the tables at the top come from the Open-Meteo Historical Forecast
  API (lead of a few hours). The section above measures the effect of the longer lead
  used in production on 2024-12 to 2026-11 only, because the Previous Runs archive is
  not complete before. Live rows (`split = 'live'` in `gold_forecast`) measure the real
  error once the daily pipeline runs in Fabric.
- Hardest months in the backtest: 2026-07 (3.50 %), 2025-07 (3.50 %), 2025-06 (3.18 %).
  Summer air-conditioning load swings with temperature, so weather forecast error
  matters most then.
- The model does not know about outages, large industrial changes or market rule changes
  (for example the Market Renewal go-live on 2025-05-01).
- Monitoring needed in production: weekly MAPE of the live rows against this backtest,
  drift of the weather inputs (population stability index per feature), and retraining
  when live MAPE stays above the backtest level for several weeks.
