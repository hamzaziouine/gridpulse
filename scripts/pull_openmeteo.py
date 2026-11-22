"""L4: download Open-Meteo Historical Forecast data month by month to data/raw/openmeteo/.

5 cities, 9 hourly variables, model gfs_seamless, UTC, from 2019-01-01 to yesterday (UTC).
One JSON file per month (`YYYY-MM.json`). Resumable: complete months already on disk are skipped;
the current (partial) month is always re-fetched. Paced by RateLimiter plus a 1 s pause.

    uv run python scripts/pull_openmeteo.py [--start 2019-01-01] [--end YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from gridpulse import openmeteo as om
from gridpulse.config import CITIES, VARIABLES

OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "openmeteo"
UA = {"User-Agent": "gridpulse student project (UIR)"}


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=5, max=120))
def get(cl: httpx.Client, params: dict[str, str]) -> object:
    r = cl.get(om.HISTORICAL_URL, params=params)
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=date(2019, 1, 1))
    ap.add_argument("--end", type=date.fromisoformat, default=None)
    a = ap.parse_args()
    end = a.end or (datetime.now(UTC).date() - timedelta(days=1))
    OUT.mkdir(parents=True, exist_ok=True)
    limiter = om.RateLimiter()
    n_req = 0
    with httpx.Client(timeout=120, headers=UA) as cl:
        for first, last in om.month_ranges(a.start, end):
            target = OUT / f"{first:%Y-%m}.json"
            month_complete = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(
                days=1
            ) == last
            if target.exists() and month_complete:
                continue
            n_days = (last - first).days + 1
            limiter.acquire(om.request_weight(len(CITIES), len(VARIABLES), n_days))
            payload = get(cl, om.month_params(first, last))
            frame = om.parse_response(payload)  # validates order, variables, count
            if len(frame) != n_days * 24:
                raise RuntimeError(f"{first:%Y-%m}: {len(frame)} hours, expected {n_days * 24}")
            target.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            n_req += 1
            nulls = int(frame.isna().sum().sum())
            print(f"{first:%Y-%m}: hours={len(frame)} nulls={nulls}", flush=True)
            time.sleep(1)
    print(f"done: {n_req} requests, files={len(list(OUT.glob('*.json')))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
