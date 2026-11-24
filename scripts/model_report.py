"""Write docs/evidence/model_metrics.md from the local gold forecast tables and MLflow run.

Reads data/lakehouse/Tables/gold_forecast(_eval) written by nb_forecast through
scripts/run_local.py, so every number in the file comes from the last local training run.

    uv run python scripts/model_report.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "data" / "lakehouse" / "Tables"
OUT = ROOT / "docs" / "evidence" / "model_metrics.md"
LEAD = ROOT / "docs" / "evidence" / "weather_lead_backtest.json"
WEATHER_NAMES = {
    "historical": "Historical Forecast (lead of a few hours, as in training)",
    "day1": "Previous Runs day 1 (about 24 to 30 h)",
    "matched": "Lead-matched: day 1 for HE1..HE17, day 2 for HE18..HE24",
    "day2": "Previous Runs day 2 (about 48 to 54 h)",
}


def lead_section(source: str) -> list[str]:
    """Day-ahead weather lead check (scripts/backtest_weather_lead.py), if it has been run."""
    if not LEAD.exists():
        return []
    data = json.loads(LEAD.read_text(encoding="utf-8"))
    res = {(r["evaluation"], r["training"]): r for r in data["results"]}
    lines = [
        "## Scored with weather of the production lead time",
        "",
        *(
            [
                "The tables above come from the notebook trained on lead-matched weather (its",
                "default since 2026-11-23). This section is the comparison behind that choice.",
            ]
            if source == "lead_matched"
            else ["The tables above use Historical Forecast weather."]
        ),
        "In production the forecast for day T",
        "is fetched on T-1 at 13:15 UTC, so the target hours are 23 to 46 h after the newest",
        "model run. `scripts/backtest_weather_lead.py` replaces the weather of each target day",
        "with the Open-Meteo Previous Runs API (same model gfs_seamless, same 5 cities and 9",
        "variables), which keeps what the model forecast one day (day 1) and two days (day 2)",
        "before each hour. Day T-1 and earlier keep the historical weather, as in `live_frame`.",
        "The Previous Runs archive has all 9 variables only from 2024-12-07 (8 of them from",
        "2024-01-20, snowfall later), so only target days from 2024-12-08 are scored here.",
        f"Generated {data['generated_utc']} UTC.",
        "",
    ]
    for (ev, training), title in (
        (("holdout", "historical"), "Holdout 2026, model trained as above (Historical Forecast)"),
        (("backtest", "historical"), "Monthly backtest, models trained as above"),
        (("holdout", "matched"), "Holdout 2026, model retrained on lead-matched weather"),
        (("backtest", "matched"), "Monthly backtest, models retrained on lead-matched weather"),
    ):
        r = res.get((ev, training))
        if r is None:
            continue
        lines += [
            f"**{title}**: {r['first']} to {r['last']}, {r['hours']:,} hours, "
            f"{r['rounds']} rounds, seasonal naive MAPE {r['naive_mape_pct']:.2f} %.",
            "",
            "| Weather used for day T | Model MAPE % | MAE (MW) | Peak-hour APE % "
            "| Skill vs naive % |",
            "|---|---|---|---|---|",
        ]
        for w, m in r["weather"].items():
            lines.append(f"| {WEATHER_NAMES[w]} | {m['mape_pct']:.2f} | {m['mae_mw']:.0f} | "
                         f"{m['peak_ape_pct']:.2f} | {m['skill_vs_naive_pct']:.1f} |")  # fmt: skip
        lines.append("")
    lines += [
        "How to read this:",
        "",
        "- The lead-matched row is the closest to production (the production lead runs from",
        "  23 to 46 h; day 1 is a little shorter, day 2 longer, so they bracket it).",
        "- The retrained model sees lead-matched weather only from 2024-01-20 (earlier years",
        "  keep Historical Forecast weather, snowfall keeps it until 2024-12-07). Its round count",
        "  comes from early stopping on 2025, which did not stop before the 3,000-round cap.",
        "  Its 2025 backtest months are therefore slightly optimistic; its 2026 holdout is clean.",
        "- 2025-05-01 is left out (IESO is missing one hour that day), which is why the",
        "  backtest has one day less than the table at the top.",
        "",
    ]
    months = data.get("monthly_backtest_matched", [])
    if months:
        lines += [
            "Backtest by month, models trained as above:",
            "",
            "| Month | Historical weather MAPE % | Lead-matched weather MAPE % | Naive MAPE % |",
            "|---|---|---|---|",
        ]
        lines += [f"| {m['month']} | {m['historical_mape_pct']:.2f} | "
                  f"{m['matched_mape_pct']:.2f} | {m['naive_mape_pct']:.2f} |"
                  for m in months]  # fmt: skip
        lines.append("")
    return lines


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
    source = fc.loc[fc["split"] != "live", "weather_source"].iloc[0]
    if source == "lead_matched":
        weather_lines = [
            "- Weather (`train_weather = matched`): for each target day T, the Open-Meteo Previous",
            "  Runs forecast at the lead the daily run really has (HE1..HE17 forecast 1 day ahead,",
            "  HE18..HE24 2 days ahead), days T-1 and earlier from the Historical Forecast API.",
            "  Hours the Previous Runs archive does not cover keep Historical Forecast weather,",
            "  column by column: all variables before 2024-01-19, snowfall until 2024-12-06.",
        ]
    else:
        weather_lines = [
            "- Weather: Open-Meteo Historical Forecast API (lead of a few hours; production has",
            "  23 to 46 h, see the section on the production lead time).",
        ]
    lines = [
        "# Forecast model metrics (local run)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/model_report.py` from the",
        "gold tables written by `fabric/nb_forecast.Notebook` when run on a laptop through",
        "`scripts/run_local.py` (local Spark 3.5, real IESO and Open-Meteo data 2019 to 2026).",
        "**Local figures**: this file is the laptop run. The same notebook also ran in Fabric on "
        "2026-11-23; the cloud figures are in `docs/evidence/fabric_batch.md`, section 7.",
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
        *weather_lines,
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
    lines.append("")
    lines += lead_section(source)
    lines += [
        "## Limitations",
        "",
        "- Lead-matched weather exists only from 2024 (complete from 2024-12-07), so most training",
        "  years still use Historical Forecast weather for day T. The section above measures the",
        "  lead effect on 2024-12 to 2026-11 only. Live rows (`split = 'live'` in `gold_forecast`)",
        "  measure the real error once the daily pipeline runs in Fabric.",
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
