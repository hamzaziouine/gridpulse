"""Download Open-Meteo Previous Runs data (day-1 and day-2 lead) to data/raw/openmeteo_prevruns/.

Same 5 cities, 9 variables and model (gfs_seamless) as scripts/pull_openmeteo.py, but each value
is the forecast issued about one day (`_previous_day1`) or two days (`_previous_day2`) before
its valid hour. Used by scripts/backtest_weather_lead.py to score the model with weather of the
lead it gets in production. Coverage for all 9 variables starts in January 2024 (only
temperature_2m goes back to 2021, which is not enough for the model's inputs).

One JSON file per month (`YYYY-MM.json`), resumable like the historical pull. Network: only
previous-runs-api.open-meteo.com.

    uv run python scripts/pull_openmeteo_prevruns.py [--start 2024-01-01] [--end 2026-11-06]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from gridpulse import openmeteo as om
from gridpulse.config import CITIES, VARIABLES

OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "openmeteo_prevruns"
UA = {"User-Agent": "gridpulse student project (UIR)"}


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=5, max=120))
def get(cl: httpx.Client, params: dict[str, str]) -> object:
    r = cl.get(om.PREVRUNS_URL, params=params)
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    ap.add_argument("--end", type=date.fromisoformat, default=date(2026, 11, 6))
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    limiter = om.RateLimiter()
    n_vars = len(VARIABLES) * len(om.PREVIOUS_DAYS)
    n_req = 0
    with httpx.Client(timeout=120, headers=UA) as cl:
        for first, last in om.month_ranges(a.start, a.end):
            target = OUT / f"{first:%Y-%m}.json"
            if target.exists():
                old = json.loads(target.read_text(encoding="utf-8"))
                if old[0]["hourly"]["time"][-1].startswith(last.isoformat()):
                    continue
            n_days = (last - first).days + 1
            limiter.acquire(om.request_weight(len(CITIES), n_vars, n_days))
            payload = get(cl, om.prevruns_params(first, last))
            counts = []
            for d in om.PREVIOUS_DAYS:
                frame = om.parse_response(payload, f"_previous_day{d}")  # validates order, names
                if len(frame) != n_days * 24:
                    raise RuntimeError(f"{first:%Y-%m}: {len(frame)} hours, expected {n_days * 24}")
                full = int(frame.drop(columns="valid_time").notna().all(axis=1).sum())
                counts.append(f"day{d} complete hours={full}/{len(frame)}")
            target.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            n_req += 1
            print(f"{first:%Y-%m}: " + ", ".join(counts), flush=True)
            time.sleep(1)
    print(f"done: {n_req} requests, files={len(list(OUT.glob('*.json')))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
