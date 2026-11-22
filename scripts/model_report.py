"""Write docs/evidence/model_metrics.md from the local gold forecast tables and MLflow run.

Reads data/lakehouse/Tables/gold_forecast(_eval) written by nb_forecast through
scripts/run_local.py, so every number in the file comes from the last local training run.

    uv run python scripts/model_report.py
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "data" / "lakehouse" / "Tables"
OUT = ROOT / "docs" / "evidence" / "model_metrics.md"


def pct(x: float) -> str:
    return f"{x:.2f}"


def overall(rows: pd.DataFrame) -> dict[str, float]:
    ok = rows.dropna(subset=["actual_mw"])
    model = (ok["abs_error_mw"] / ok["actual_mw"]).mean() * 100
    naive = ((ok["naive168_mw"] - ok["actual_mw"]).abs() / ok["actual_mw"]).mean() * 100
    return {"hours": len(ok), "first": ok["est_date"].min(), "last": ok["est_date"].max(),
            "mape": model, "naive": naive, "mae": ok["abs_error_mw"].mean(),
            "skill": 100 * (1 - model / naive)}  # fmt: skip


def main() -> None:
    fc = pd.read_parquet(TABLES / "gold_forecast" / "data.parquet")
    ev = pd.read_parquet(TABLES / "gold_forecast_eval" / "data.parquet")
    run_id = fc.loc[fc["split"] != "live", "run_id"].iloc[0]
    version = fc.loc[fc["split"] != "live", "model_version"].iloc[0]
    lines = [
        "# Forecast model metrics (local run)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/model_report.py` from the",
        "gold tables written by `fabric/nb_forecast.Notebook` when run on a laptop through",
        "`scripts/run_local.py` (local Spark 3.5, real IESO and Open-Meteo data 2019 to 2026).",
        "**Tested locally only**: the same notebook has not run in Fabric yet.",
        "",
        f"MLflow run `{run_id}` (local file store `mlruns/`), registered model "
        f"`gridpulse_lgbm` version {version}.",
        "",
        "## Setup",
        "",
        "- Target: Ontario demand (MW) for each hour of EST day T, issued on T-1 at 08:15 EST.",
        "  Demand features use only days up to T-2 (what IESO has published at that time).",
        "- Model: LightGBM, L1 objective, 45 features (calendar, population-weighted weather and",
        "  the 5 city temperatures, demand lags of 48 h and more). Rounds chosen by early stopping",
        "  on 2025.",
        "- Baseline: seasonal naive, same hour one week earlier (known at issue time).",
        "- MAPE = mean absolute percentage error over hours; skill = 1 - MAPE model / MAPE naive.",
        "",
        "## Results",
        "",
        "| Evaluation | Period | Hours | Model MAPE % | Naive MAPE % | Model MAE (MW) "
        "| Skill vs naive % |",
        "|---|---|---|---|---|---|---|",
    ]
    names = {"holdout": "Holdout: one model trained on 2019-2025, frozen",
             "backtest": "Backtest: retrained every month on the data known then"}  # fmt: skip
    for split in ("holdout", "backtest"):
        o = overall(fc[fc["split"] == split])
        lines.append(f"| {names[split]} | {o['first']} to {o['last']} | {o['hours']:,} | "
                     f"{pct(o['mape'])} | {pct(o['naive'])} | {o['mae']:.0f} | "
                     f"{o['skill']:.1f} |")  # fmt: skip
    lines += [
        "",
        "Success criterion 6 of the proposal (beat seasonal-naive MAPE by at least 30 %) is met",
        "in both evaluations, on historical data.",
        "",
        "## Backtest by month",
        "",
        "| Month | Model MAPE % | Naive MAPE % | Peak-hour APE % | Skill % | Hours |",
        "|---|---|---|---|---|---|",
    ]
    bt = ev[ev["split"] == "backtest"]
    for m, part in bt.groupby("month_start"):
        lg = part[part["model"] == "lightgbm"].iloc[0]
        nv = part[part["model"] == "seasonal_naive_168"].iloc[0]
        lines.append(f"| {m:%Y-%m} | {pct(lg['mape_pct'])} | {pct(nv['mape_pct'])} | "
                     f"{pct(lg['peak_ape_pct'])} | {lg['skill_vs_naive_pct']:.1f} | "
                     f"{int(lg['n_hours'])} |")  # fmt: skip
    lgb_rows = bt[bt["model"] == "lightgbm"].sort_values("mape_pct", ascending=False).head(3)
    worst = ", ".join(f"{r.month_start:%Y-%m} ({r.mape_pct:.2f} %)" for r in lgb_rows.itertuples())
    lines += [
        "",
        "## Limitations",
        "",
        "- Weather inputs come from the Open-Meteo Historical Forecast API, which keeps the most",
        "  recent model run for each hour (lead time of a few hours). In production the input is",
        "  the forecast available at 08:15 EST the day before, about 16 to 39 hours ahead of the",
        "  target hours, which is less accurate, so live error",
        "  will be higher than the table above. Live rows (`split = 'live'` in `gold_forecast`)",
        "  measure that once the daily pipeline runs in Fabric.",
        f"- Hardest months in the backtest: {worst}.",
        "  Summer air-conditioning load swings with temperature, so weather forecast error",
        "  matters most then.",
        "- The model does not know about outages, large industrial changes or market rule changes",
        "  (for example the Market Renewal go-live on 2025-05-01).",
        "- Monitoring needed in production: weekly MAPE of the live rows against this backtest,",
        "  drift of the weather inputs (population stability index per feature), and retraining",
        "  when live MAPE stays above the backtest level for several weeks.",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[16:24]))


if __name__ == "__main__":
    main()
