# Forecast model metrics (local run)

Generated 2026-11-22 19:05 UTC by `scripts/model_report.py` from the
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

## Limitations

- Weather inputs come from the Open-Meteo Historical Forecast API, which keeps the most
  recent model run for each hour (lead time of a few hours). In production the input is
  the forecast available at 08:15 EST the day before, about 16 to 39 hours ahead of the
  target hours, which is less accurate, so live error
  will be higher than the table above. Live rows (`split = 'live'` in `gold_forecast`)
  measure that once the daily pipeline runs in Fabric.
- Hardest months in the backtest: 2026-07 (3.50 %), 2025-07 (3.50 %), 2025-06 (3.18 %).
  Summer air-conditioning load swings with temperature, so weather forecast error
  matters most then.
- The model does not know about outages, large industrial changes or market rule changes
  (for example the Market Renewal go-live on 2025-05-01).
- Monitoring needed in production: weekly MAPE of the live rows against this backtest,
  drift of the weather inputs (population stability index per feature), and retraining
  when live MAPE stays above the backtest level for several weeks.
