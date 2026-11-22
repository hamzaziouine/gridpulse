# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "{{LAKEHOUSE_ID}}",
# META       "default_lakehouse_name": "lh_gridpulse",
# META       "default_lakehouse_workspace_id": "{{WORKSPACE_ID}}"
# META     },
# META     "environment": {
# META       "environmentId": "{{ENVIRONMENT_ID}}",
# META       "workspaceId": "{{WORKSPACE_ID}}"
# META     }
# META   }
# META }

# MARKDOWN ********************

# # nb_forecast: train, evaluate and register the day-ahead model
#
# Target: Ontario demand (MW) for each hour of tomorrow, forecast at 08:15 EST today, when IESO
# has published demand up to yesterday. Baseline: the same hour one week earlier (seasonal naive).
#
# 1. **Holdout** (DESIGN D13): train 2019-2024, early stopping on 2025, refit on 2019-2025 with that
#    number of rounds, score 2026 with the frozen model.
# 2. **Backtest**: one fold per month from 2025-01, each trained on the days known at the first
#    issue of the month, scoring the whole month.
# 3. **Production model**: refit on every complete day, logged and registered with MLflow.
# 4. Predictions and monthly errors go to `gold_forecast` and `gold_forecast_eval` for Power BI.

# PARAMETERS CELL ********************

run_date = ""  # YYYY-MM-DD, empty = today (UTC)
experiment_name = "exp_gridpulse_forecast"
model_name = "gridpulse_lgbm"
validation_start = "2025-01-01"
holdout_start = "2026-01-01"
backtest_start = "2025-01-01"
register_model = True

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

import glob
import sys
from datetime import UTC, datetime, timedelta

try:
    import gridpulse
except ImportError:
    wheels = sorted(glob.glob("/lakehouse/default/Files/libs/gridpulse-*.whl"))
    if not wheels:
        raise
    sys.path.insert(0, wheels[-1])
    import gridpulse

import lightgbm  # noqa: F401  (load LightGBM's native library before pandas/pyarrow)
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import pandas as pd
from mlflow.models import infer_signature

from gridpulse import features as fx
from gridpulse import forecast as fc
from gridpulse.lakehouse import FabricStore

spark.conf.set("spark.sql.session.timeZone", "UTC")
try:
    store  # injected by scripts/run_local.py for laptop runs
except NameError:
    store = FabricStore(spark)


def as_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


RUN_DATE = as_date(run_date) if run_date else datetime.now(UTC).date()
VAL_START, HOLDOUT_START, BT_START = map(as_date, (validation_start, holdout_start, backtest_start))
REGISTER = str(register_model).lower() in ("true", "1")
print(f"gridpulse {gridpulse.__version__} | run_date {RUN_DATE} | mlflow {mlflow.__version__}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Features on the Spark driver: ~69k hours x 45 features is a few MB, LightGBM trains in seconds.
hist = store.read("silver_demand_weather_hourly").toPandas()
feats = fx.build_features(hist)
ok = feats[fc.usable(feats)]
print(f"{len(feats):,} feature rows, {len(ok):,} with actual and weather, "
      f"{ok['est_date'].min()} .. {ok['est_date'].max()}")  # fmt: skip

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 1. Holdout: early stopping on the validation year, refit, score the holdout period.
train_set = ok[ok["est_date"] <= VAL_START - timedelta(days=2)]
valid_set = ok[(ok["est_date"] >= VAL_START) & (ok["est_date"] < HOLDOUT_START)]
_, best_rounds = fc.train(train_set, train_set["actual"], valid=(valid_set, valid_set["actual"]))
refit_set = ok[ok["est_date"] <= HOLDOUT_START - timedelta(days=2)]
holdout_model, _ = fc.train(refit_set, refit_set["actual"], rounds=best_rounds)
test_set = ok[ok["est_date"] >= HOLDOUT_START]
holdout = test_set[list(fx.META_COLUMNS)].assign(forecast=fc.predict(holdout_model, test_set))
holdout_summary = fc.summary(holdout)
print(f"best rounds: {best_rounds}")
print(f"holdout {test_set['est_date'].min()} .. {test_set['est_date'].max()}: "
      f"MAPE {holdout_summary['model_mape_pct']:.2f} % vs naive "
      f"{holdout_summary['naive_mape_pct']:.2f} %, "
      f"skill {holdout_summary['skill_vs_naive_pct']:.1f} %")  # fmt: skip

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 2. Rolling-origin backtest, one fold per month, same number of rounds.
backtest = fc.backtest(feats, BT_START, rounds=best_rounds)
backtest_summary = fc.summary(backtest)
print(f"backtest {len(backtest):,} hours: MAPE {backtest_summary['model_mape_pct']:.2f} % "
      f"vs naive {backtest_summary['naive_mape_pct']:.2f} %, "
      f"skill {backtest_summary['skill_vs_naive_pct']:.1f} %")  # fmt: skip

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 3. Production model on every complete day, tracked and registered with MLflow.
prod_model, _ = fc.train(ok, ok["actual"], rounds=best_rounds)
importance = pd.DataFrame({
    "feature": prod_model.feature_name(),
    "gain": prod_model.feature_importance("gain"),
}).sort_values("gain", ascending=False)  # fmt: skip

mlflow.set_experiment(experiment_name)
with mlflow.start_run(run_name=f"train-{RUN_DATE}") as run:
    mlflow.log_params({**{f"lgbm_{k}": v for k, v in fc.PARAMS.items()},
                       "best_rounds": best_rounds,
                       "feature_schema_version": fx.FEATURE_SCHEMA_VERSION,
                       "n_features": len(fx.FEATURE_COLUMNS),
                       "train_until": str(VAL_START - timedelta(days=2)),
                       "validation": f"{VAL_START}..{HOLDOUT_START - timedelta(days=1)}",
                       "holdout": f"{HOLDOUT_START}..{test_set['est_date'].max()}",
                       "backtest_from": str(BT_START),
                       "production_rows": len(ok),
                       "production_until": str(ok["est_date"].max())})  # fmt: skip
    mlflow.log_metrics({f"holdout_{k}": v for k, v in holdout_summary.items()})
    mlflow.log_metrics({f"backtest_{k}": v for k, v in backtest_summary.items()})
    bt_eval = fc.monthly_eval(backtest, "backtest", run.info.run_id)
    for r in bt_eval[bt_eval["model"] == fc.MODEL_NAME].itertuples():
        step = r.month_start.year * 100 + r.month_start.month
        mlflow.log_metric("backtest_month_mape_pct", r.mape_pct, step=step)
    fig, ax = plt.subplots(figsize=(8, 9))
    top = importance.head(25).iloc[::-1]
    ax.barh(top["feature"], top["gain"])
    ax.set_title("LightGBM feature importance (gain), production model")
    fig.tight_layout()
    mlflow.log_figure(fig, "feature_importance.png")
    mlflow.log_text(importance.to_csv(index=False), "feature_importance.csv")
    mlflow.log_text(bt_eval.to_csv(index=False), "backtest_monthly.csv")
    x_example = ok[list(fx.FEATURE_COLUMNS)].head(24)
    info = mlflow.lightgbm.log_model(
        prod_model,
        artifact_path="model",
        signature=infer_signature(x_example, fc.predict(prod_model, x_example)),
        input_example=x_example.head(2),
        registered_model_name=model_name if REGISTER else None,
    )
    RUN_ID = run.info.run_id
MODEL_VERSION = str(getattr(info, "registered_model_version", None) or "unregistered")
print(f"MLflow run {RUN_ID}, registered {model_name} version {MODEL_VERSION}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 4. Gold tables for the "Forecast vs actual" report page.
rows = pd.concat([
    fc.forecast_rows(backtest, "backtest", MODEL_VERSION, RUN_ID, "historical_forecast"),
    fc.forecast_rows(holdout, "holdout", MODEL_VERSION, RUN_ID, "historical_forecast"),
], ignore_index=True)  # fmt: skip
evals = pd.concat([bt_eval, fc.monthly_eval(holdout, "holdout", RUN_ID)], ignore_index=True)
FORECAST_SCHEMA = (
    "target_time timestamp, est_date date, hour_ending int, issue_date date, date_key int, "
    "split string, model_name string, model_version string, run_id string, forecast_mw double, "
    "naive168_mw double, actual_mw double, abs_error_mw double, ape_pct double, "
    "weather_source string"
)
EVAL_SCHEMA = (
    "month_start date, date_key int, split string, model string, mape_pct double, "
    "mae_mw double, rmse_mw double, n_hours int, peak_ape_pct double, "
    "skill_vs_naive_pct double, run_id string"
)


def frame(pdf: pd.DataFrame, ddl: str):
    cols = [c.strip().split(" ")[0] for c in ddl.split(",")]
    return spark.createDataFrame(pdf[cols], ddl)


n1 = store.write(frame(rows, FORECAST_SCHEMA), "gold_forecast",
                 replace={"split": ["backtest", "holdout"]})  # fmt: skip
n2 = store.write(frame(evals, EVAL_SCHEMA), "gold_forecast_eval",
                 replace={"split": ["backtest", "holdout"]})  # fmt: skip
print(f"gold_forecast: {n1:,} rows, gold_forecast_eval: {n2:,} rows")
display(frame(evals, EVAL_SCHEMA).where("model = 'lightgbm'").orderBy("split", "month_start"))
