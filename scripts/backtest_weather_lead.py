"""Honest day-ahead evaluation: score the model with weather of the lead it gets in production.

Review finding 3 (2026-11-22): the standard holdout and backtest use Historical Forecast weather
(lead of a few hours) while nb_predict uses a forecast 23 to 46 h after its model run. This
script rebuilds the features of every target day with Open-Meteo Previous Runs weather
(`gridpulse.weather_lead`, files from scripts/pull_openmeteo_prevruns.py) and scores:

- model A, trained exactly as nb_forecast does (Historical Forecast weather), on the holdout
  and on the monthly backtest folds, with each weather policy (historical, day1, matched, day2);
- model B, retrained with the lead-matched (`matched`) weather wherever the Previous Runs API has
  it (2024-01-20 on; snowfall only from 2024-12-07, the historical value is kept before), with
  its own early stopping on 2025.

Only target days whose 24 hours have all 9 variables for both leads are scored (2024-12-08 on),
so the holdout (2026) and the backtest folds 2025-01 to 2026-11 are fully covered.

Stages (each well under 5 minutes): `holdout`, `backtest_a`, `backtest_b`; every stage rewrites
docs/evidence/weather_lead_backtest.json from the scored rows saved so far in
data/lakehouse/weather_lead/ (git-ignored).

    uv run python scripts/backtest_weather_lead.py --stage holdout
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from gridpulse import hostguard

if __name__ == "__main__":  # commit gate before the heavy imports (pandas, LightGBM)
    hostguard.require_headroom()

import lightgbm  # noqa: E402, F401  (import before pandas/pyarrow on Windows, see bug 4)
import pandas as pd  # noqa: E402

from gridpulse import features as fx  # noqa: E402
from gridpulse import forecast as fc  # noqa: E402
from gridpulse import weather_lead as wl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SILVER = ROOT / "data" / "lakehouse" / "Tables" / "silver_demand_weather_hourly" / "data.parquet"
PREV = ROOT / "data" / "raw" / "openmeteo_prevruns"
WORK = ROOT / "data" / "lakehouse" / "weather_lead"
OUT = ROOT / "docs" / "evidence" / "weather_lead_backtest.json"
VAL_START, HOLDOUT_START, BT_START = date(2025, 1, 1), date(2026, 1, 1), date(2025, 1, 1)
WEATHER = ("historical", *wl.POLICIES)


def load() -> tuple[dict[str, pd.DataFrame], set[date]]:
    hist = pd.read_parquet(SILVER)
    hist = hist.sort_values("target_time").reset_index(drop=True)
    d1, d2 = wl.load_prevruns(PREV, 1), wl.load_prevruns(PREV, 2)
    feats = {"historical": fx.build_features(hist)}
    covered: set[date] | None = None
    est = (pd.to_datetime(hist["target_time"], utc=True) - fx.EST_SHIFT).dt.date
    for p in wl.POLICIES:
        lead, complete = wl.lead_weather(hist, d1, d2, p)
        feats[p] = wl.lead_features(hist, lead)
        days = complete.groupby(est).agg(["all", "size"])
        ok = set(days.index[days["all"] & (days["size"] == 24)])
        covered = ok if covered is None else covered & ok
    if covered is None:  # pragma: no cover - POLICIES is never empty
        raise RuntimeError("no policy")
    print(f"feature rows {len(feats['historical']):,}; days with full lead weather: "
          f"{len(covered)} ({min(covered)} .. {max(covered)})", flush=True)  # fmt: skip
    return feats, covered


def score(model, feats: dict[str, pd.DataFrame], mask: pd.Series, **tags) -> pd.DataFrame:
    base = feats["historical"].loc[mask, list(fx.META_COLUMNS)].reset_index(drop=True)
    for w in WEATHER:
        base[f"fc_{w}"] = fc.predict(model, feats[w].loc[mask].reset_index(drop=True))
    return base.assign(**tags)


def usable_mask(feats: dict[str, pd.DataFrame], key: str) -> pd.Series:
    return fc.usable(feats[key])


def stage_holdout(feats, covered) -> pd.DataFrame:
    scorable = usable_mask(feats, "historical") & usable_mask(feats, "matched")  # same hours
    parts = []
    for training in ("historical", "matched"):
        f = feats[training]
        ok = usable_mask(feats, training)
        d = f["est_date"]
        tr = f[ok & (d <= VAL_START - timedelta(days=2))]
        va = f[ok & (d >= VAL_START) & (d < HOLDOUT_START)]
        _, rounds = fc.train(tr, tr["actual"], valid=(va, va["actual"]))
        refit = f[ok & (d <= HOLDOUT_START - timedelta(days=2))]
        model, _ = fc.train(refit, refit["actual"], rounds=rounds)
        mask = scorable & (d >= HOLDOUT_START) & d.isin(covered)
        parts.append(score(model, feats, mask, evaluation="holdout", training=training,
                           rounds=rounds, fold=pd.NaT))  # fmt: skip
        print(f"holdout, model trained on {training} weather: {rounds} rounds", flush=True)
    return pd.concat(parts, ignore_index=True)


def stage_backtest(feats, covered, training: str, rounds: int) -> pd.DataFrame:
    f = feats[training]
    ok = usable_mask(feats, training)
    d = f["est_date"]
    scorable = usable_mask(feats, "historical") & usable_mask(feats, "matched")
    parts = []
    for m in fc.month_starts(BT_START, d[ok].max()):
        fold = fc.Fold(m)
        tr = f[ok & (d <= fold.train_until)]
        mask = scorable & (d >= fold.month_start) & (d <= fold.month_end) & d.isin(covered)
        if not mask.any():
            continue
        model, _ = fc.train(tr, tr["actual"], rounds=rounds)
        parts.append(score(model, feats, mask, evaluation="backtest", training=training,
                           rounds=rounds, fold=pd.Timestamp(m)))  # fmt: skip
        print(f"fold {m:%Y-%m} ({training}) done", flush=True)
    return pd.concat(parts, ignore_index=True)


def metrics(rows: pd.DataFrame, col: str) -> dict[str, float]:
    return fc.error_metrics(rows["actual"], rows[col])


def summarise() -> dict:
    files = sorted(WORK.glob("*.parquet"))
    rows = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    out: dict = {
        "generated_utc": f"{datetime.now(UTC):%Y-%m-%d %H:%M}",
        "source": "Open-Meteo Previous Runs API, model gfs_seamless, 5 cities, 9 variables",
        "matched_policy": "HE1..HE17 previous_day1, HE18..HE24 previous_day2",
        "results": [],
        "monthly_backtest_matched": [],
    }
    for (ev, training), part in rows.groupby(["evaluation", "training"]):
        naive = metrics(part, "naive168")
        rec = {"evaluation": ev, "training": training, "rounds": int(part["rounds"].iloc[0]),
               "first": str(part["est_date"].min()), "last": str(part["est_date"].max()),
               "hours": int(naive["n_hours"]), "naive_mape_pct": round(naive["mape_pct"], 3),
               "weather": {}}  # fmt: skip
        for w in WEATHER:
            m = metrics(part, f"fc_{w}")
            rec["weather"][w] = {
                "mape_pct": round(m["mape_pct"], 3),
                "mae_mw": round(m["mae_mw"], 1),
                "peak_ape_pct": round(fc.peak_ape(part, f"fc_{w}"), 3),
                "skill_vs_naive_pct": round(fc.skill_pct(m["mape_pct"], naive["mape_pct"]), 1),
            }
        out["results"].append(rec)
        if ev == "backtest" and training == "historical":
            for fold, fp in part.groupby("fold"):
                nv = metrics(fp, "naive168")["mape_pct"]
                out["monthly_backtest_matched"].append({
                    "month": f"{fold:%Y-%m}",
                    "historical_mape_pct": round(metrics(fp, "fc_historical")["mape_pct"], 3),
                    "matched_mape_pct": round(metrics(fp, "fc_matched")["mape_pct"], 3),
                    "naive_mape_pct": round(nv, 3),
                })  # fmt: skip
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("holdout", "backtest_a", "backtest_b", "summary"),
                    required=True)  # fmt: skip
    a = ap.parse_args()
    t0 = time.time()
    WORK.mkdir(parents=True, exist_ok=True)
    if a.stage != "summary":
        dog = hostguard.CommitWatchdog()  # stops this process above 28 GB
        dog.start()
        feats, covered = load()
        if a.stage == "holdout":
            res = stage_holdout(feats, covered)
        else:
            hold = pd.read_parquet(WORK / "holdout.parquet")
            training = "historical" if a.stage == "backtest_a" else "matched"
            rounds = int(hold.loc[hold["training"] == training, "rounds"].iloc[0])
            res = stage_backtest(feats, covered, training, rounds)
        res.to_parquet(WORK / f"{a.stage}.parquet", index=False)
        dog.stop()
    s = summarise()
    for r in s["results"]:
        ws = ", ".join(f"{w} {v['mape_pct']:.2f} %" for w, v in r["weather"].items())
        print(f"{r['evaluation']} / trained on {r['training']} ({r['first']}..{r['last']}, "
              f"{r['hours']} h): naive {r['naive_mape_pct']:.2f} % | {ws}")  # fmt: skip
    print(f"elapsed {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
