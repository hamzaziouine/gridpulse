"""LightGBM day-ahead model, evaluation and the rolling-origin backtest (DESIGN D13).

One model for all 24 target hours (hour of day is a feature), L1 objective (median forecast,
robust to the odd spike), parameters from GridCast. Splits never let a model see a target it
predicts or any demand published after its issue time:
- holdout: train on 2019-2024, early stopping on 2025, refit on 2019-2025 with that number of
  rounds, then score 2026 with the frozen model (the "train once, deploy" view);
- backtest: one fold per month from 2025-01; each fold trains on every target day up to the
  first issue of the month (fold start minus 2 days) and scores the whole month without
  retraining (the "retrain monthly" view);
- production: refit on all complete days, registered in MLflow, used by nb_predict.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from gridpulse.features import FEATURE_COLUMNS

SEED = 20261122
PARAMS: dict[str, Any] = {
    "objective": "l1",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "seed": SEED,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 4,
    "verbosity": -1,
}
MAX_ROUNDS = 3000
EARLY_STOPPING_ROUNDS = 100
MODEL_NAME = "lightgbm"
NAIVE_NAME = "seasonal_naive_168"


def train(
    x: pd.DataFrame,
    y: pd.Series,
    valid: tuple[pd.DataFrame, pd.Series] | None = None,
    rounds: int | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[lgb.Booster, int]:
    """Fit on (x, y). With `valid`, early stopping picks the round count; else `rounds` rounds."""
    p = {**PARAMS, **(params or {})}
    dtrain = lgb.Dataset(x[list(FEATURE_COLUMNS)], label=y, free_raw_data=True)
    if valid is not None:
        dvalid = lgb.Dataset(valid[0][list(FEATURE_COLUMNS)], label=valid[1], reference=dtrain)
        booster = lgb.train(
            p,
            dtrain,
            num_boost_round=MAX_ROUNDS,
            valid_sets=[dvalid],
            callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
        )
        return booster, int(booster.best_iteration)
    n = int(rounds or MAX_ROUNDS)
    return lgb.train(p, dtrain, num_boost_round=n), n


def predict(booster: lgb.Booster, x: pd.DataFrame) -> np.ndarray:
    names = booster.feature_name()
    if names != list(FEATURE_COLUMNS):
        raise ValueError("model was trained on another feature list: refusing to score")
    return booster.predict(x[names], num_iteration=booster.best_iteration or None)


def error_metrics(actual: Iterable[float], forecast: Iterable[float]) -> dict[str, float]:
    a = np.asarray(list(actual), dtype=float)
    f = np.asarray(list(forecast), dtype=float)
    ok = ~(np.isnan(a) | np.isnan(f)) & (a != 0)
    err = f[ok] - a[ok]
    if not ok.any():
        return {"mape_pct": np.nan, "mae_mw": np.nan, "rmse_mw": np.nan, "n_hours": 0}
    return {
        "mape_pct": float(np.mean(np.abs(err / a[ok])) * 100),
        "mae_mw": float(np.mean(np.abs(err))),
        "rmse_mw": float(np.sqrt(np.mean(err**2))),
        "n_hours": int(ok.sum()),
    }


def peak_ape(frame: pd.DataFrame, forecast_col: str) -> float:
    """Mean absolute % error at each EST day's actual peak hour."""
    f = frame.dropna(subset=["actual", forecast_col])
    if f.empty:
        return float("nan")
    at_peak = f.loc[f.groupby("est_date")["actual"].idxmax()]
    return float((abs(at_peak[forecast_col] - at_peak["actual"]) / at_peak["actual"]).mean() * 100)


def skill_pct(model_mape: float, naive_mape: float) -> float:
    return float(100 * (1 - model_mape / naive_mape)) if naive_mape else float("nan")


@dataclass(frozen=True)
class Fold:
    month_start: date

    @property
    def month_end(self) -> date:
        nxt = (self.month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return nxt - timedelta(days=1)

    @property
    def train_until(self) -> date:
        """Newest target day the fold may train on: complete at the first issue of the month."""
        return self.month_start - timedelta(days=2)


def month_starts(first: date, last: date) -> list[date]:
    out, cur = [], first.replace(day=1)
    while cur <= last:
        out.append(cur)
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def usable(features: pd.DataFrame) -> pd.Series:
    """Rows a model can learn from or be scored on: actual known, weather present."""
    return features["actual"].notna() & features["temperature_2m_w"].notna()


def backtest(
    features: pd.DataFrame, first_month: date, rounds: int, params: dict[str, Any] | None = None,
    log: Any = print,
) -> pd.DataFrame:  # fmt: skip
    """Rolling-origin monthly backtest. Returns scored rows with a `fold` column."""
    ok = features[usable(features)]
    last = ok["est_date"].max()
    parts = []
    for m in month_starts(first_month, last):
        fold = Fold(m)
        tr = ok[ok["est_date"] <= fold.train_until]
        te = ok[(ok["est_date"] >= fold.month_start) & (ok["est_date"] <= fold.month_end)]
        if te.empty:
            continue
        booster, _ = train(tr, tr["actual"], rounds=rounds, params=params)
        scored = te[["target_time", "est_date", "hour_ending", "issue_date", "actual", "naive168"]]
        scored = scored.assign(forecast=predict(booster, te), fold=m)
        parts.append(scored)
        met = error_metrics(scored["actual"], scored["forecast"])
        nai = error_metrics(scored["actual"], scored["naive168"])
        log(f"fold {m:%Y-%m}: train {len(tr):,} rows to {fold.train_until}, test {len(te):,} | "
            f"MAPE {met['mape_pct']:.2f} % vs naive {nai['mape_pct']:.2f} %")  # fmt: skip
    return pd.concat(parts, ignore_index=True)


def monthly_eval(scored: pd.DataFrame, split: str, run_id: str) -> pd.DataFrame:
    """gold_forecast_eval rows: per month, the model and the seasonal-naive baseline."""
    rows = []
    s = scored.assign(month_start=pd.to_datetime(scored["est_date"]).dt.to_period("M"))
    for period, part in s.groupby("month_start"):
        m = period.start_time.date()
        mod = error_metrics(part["actual"], part["forecast"])
        nai = error_metrics(part["actual"], part["naive168"])
        for name, met, col in ((MODEL_NAME, mod, "forecast"), (NAIVE_NAME, nai, "naive168")):
            rows.append({
                "month_start": m,
                "date_key": m.year * 10000 + m.month * 100 + 1,
                "split": split,
                "model": name,
                **met,
                "peak_ape_pct": peak_ape(part, col),
                "skill_vs_naive_pct": skill_pct(mod["mape_pct"], nai["mape_pct"])
                if name == MODEL_NAME else np.nan,
                "run_id": run_id,
            })  # fmt: skip
    out = pd.DataFrame(rows)
    out["n_hours"] = out["n_hours"].astype("int32")
    out["date_key"] = out["date_key"].astype("int32")
    return out


def forecast_rows(
    scored: pd.DataFrame, split: str, model_version: str, run_id: str, weather_source: str
) -> pd.DataFrame:
    """gold_forecast rows from scored features (columns: target_time .. forecast)."""
    out = pd.DataFrame({
        "target_time": pd.to_datetime(scored["target_time"], utc=True),
        "est_date": scored["est_date"].to_numpy(),
        "hour_ending": scored["hour_ending"].astype("int32").to_numpy(),
        "issue_date": scored["issue_date"].to_numpy(),
    })  # fmt: skip
    out["date_key"] = [d.year * 10000 + d.month * 100 + d.day for d in out["est_date"]]
    out["date_key"] = out["date_key"].astype("int32")
    out["split"] = split
    out["model_name"] = MODEL_NAME
    out["model_version"] = model_version
    out["run_id"] = run_id
    out["forecast_mw"] = scored["forecast"].astype(float).round(1).to_numpy()
    out["naive168_mw"] = scored["naive168"].astype(float).to_numpy()
    out["actual_mw"] = scored["actual"].astype(float).to_numpy()
    out["abs_error_mw"] = (out["forecast_mw"] - out["actual_mw"]).abs()
    out["ape_pct"] = out["abs_error_mw"] / out["actual_mw"] * 100
    out["weather_source"] = weather_source
    return out


def summary(scored: pd.DataFrame) -> dict[str, float]:
    mod = error_metrics(scored["actual"], scored["forecast"])
    nai = error_metrics(scored["actual"], scored["naive168"])
    return {
        **{f"model_{k}": v for k, v in mod.items()},
        **{f"naive_{k}": v for k, v in nai.items()},
        "model_peak_ape_pct": peak_ape(scored, "forecast"),
        "naive_peak_ape_pct": peak_ape(scored, "naive168"),
        "skill_vs_naive_pct": skill_pct(mod["mape_pct"], nai["mape_pct"]),
    }
