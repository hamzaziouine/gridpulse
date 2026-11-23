"""Open-Meteo Historical Forecast API (source S2): request parameters, parsing, pacing.

Ported from GridCast `ingest/openmeteo.py` (database layer removed).
- Model pinned to `gfs_seamless` (no silent model switch), all times UTC (`timezone=GMT`).
- The Historical Forecast API returns archived forecasts, not observations or a reanalysis, so
  a model trained on it sees forecast-like weather (DESIGN D3). It stitches the newest run for
  each hour, so its lead time is shorter than the day-ahead forecast used live: see the
  limitation in gridpulse.features.
- Free-tier limits: 600 calls/min, 5,000/h, 10,000/day, where one request counts
  `locations x max(1, variables/10) x max(1, days/14)` calls.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from datetime import date, timedelta
from typing import Any

import pandas as pd

from gridpulse.config import CITIES, VARIABLES

HISTORICAL_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
MODEL = "gfs_seamless"


def base_params() -> dict[str, str]:
    return {
        "latitude": ",".join(f"{c.lat}" for c in CITIES),
        "longitude": ",".join(f"{c.lon}" for c in CITIES),
        "hourly": ",".join(VARIABLES),
        "models": MODEL,
        "timezone": "GMT",
    }


def month_params(first: date, last: date) -> dict[str, str]:
    return base_params() | {"start_date": first.isoformat(), "end_date": last.isoformat()}


def request_weight(n_locations: int, n_variables: int, n_days: float) -> float:
    """Open-Meteo's fractional call count for one request."""
    return n_locations * max(1.0, n_variables / 10) * max(1.0, n_days / 14)


def parse_response(payload: Any) -> pd.DataFrame:
    """Open-Meteo JSON (one object per city, in CITIES order) -> wide frame.

    Columns: valid_time (UTC) + `<variable>_<city key>`. Missing values stay NaN.
    """
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(CITIES):
        raise ValueError(f"expected {len(CITIES)} locations, got {len(items)}")
    frame: pd.DataFrame | None = None
    for city, item in zip(CITIES, items, strict=True):
        if abs(item["latitude"] - city.lat) > 0.2 or abs(item["longitude"] - city.lon) > 0.2:
            raise ValueError(f"response order mismatch at {city.name}: {item['latitude']}")
        hourly = item["hourly"]
        missing = [v for v in VARIABLES if v not in hourly]
        if missing:
            raise ValueError(f"{city.name}: variables missing from response: {missing}")
        part = pd.DataFrame({f"{v}_{city.key}": hourly[v] for v in VARIABLES}, dtype="float64")
        part.insert(0, "valid_time", pd.to_datetime(hourly["time"], utc=True))
        frame = part if frame is None else frame.merge(part, on="valid_time", how="outer")
    if frame is None:  # pragma: no cover - CITIES is never empty
        raise ValueError("empty response")
    return frame.sort_values("valid_time").reset_index(drop=True)


def month_ranges(start: date, end: date) -> Iterator[tuple[date, date]]:
    """Calendar-month chunks [first, last] covering start..end inclusive."""
    cur = start
    while cur <= end:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield cur, min(nxt - timedelta(days=1), end)
        cur = nxt


class RateLimiter:
    """Keeps weighted calls under fixed shares of Open-Meteo's minute/hour/day limits."""

    def __init__(
        self,
        budgets: Sequence[tuple[float, float]] = ((60, 300), (3600, 2500), (86400, 5000)),
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.budgets = budgets
        self.clock = clock
        self.sleep = sleep
        self.calls: deque[tuple[float, float]] = deque()

    def acquire(self, weight: float) -> None:
        while True:
            now = self.clock()
            horizon = max(w for w, _ in self.budgets)
            while self.calls and self.calls[0][0] <= now - horizon:
                self.calls.popleft()
            wait = 0.0
            for window, budget in self.budgets:
                in_window = [(t, w) for t, w in self.calls if t > now - window]
                if sum(w for _, w in in_window) + weight > budget and in_window:
                    wait = max(wait, in_window[0][0] + window - now)
            if wait <= 0:
                self.calls.append((now, weight))
                return
            self.sleep(wait)
