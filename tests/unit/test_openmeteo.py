"""Open-Meteo parsing and pacing (ported from GridCast tests/unit/test_openmeteo.py, 5 cities)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from gridpulse import openmeteo as om
from gridpulse.config import CITIES, WEATHER_COLUMNS

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def test_five_cities_weights_sum_to_one() -> None:
    assert [c.key for c in CITIES] == ["toronto", "ottawa", "london", "windsor", "sudbury"]
    assert sum(c.weight for c in CITIES) == pytest.approx(1.0, abs=1e-3)
    assert len(WEATHER_COLUMNS) == 45


def test_parse_historical_fixture() -> None:
    frame = om.parse_response(_load("openmeteo_historical_sample.json"))
    assert list(frame.columns) == ["valid_time", *WEATHER_COLUMNS]
    assert len(frame) == 48
    assert frame["valid_time"].iloc[0] == pd.Timestamp("2018-01-01 00:00", tz="UTC")
    assert frame["temperature_2m_toronto"].iloc[0] == pytest.approx(-16.4)
    # Accumulated variables start one hour later: only 2018-01-01T00 is null.
    accumulated = ("shortwave_radiation_", "precipitation_", "snowfall_")
    first_row_nulls = frame.columns[frame.iloc[0].isna()]
    assert all(c.startswith(accumulated) for c in first_row_nulls)
    assert not frame.iloc[1:].isna().any().any()


def test_parse_rejects_wrong_location_order() -> None:
    payload = _load("openmeteo_historical_sample.json")
    assert isinstance(payload, list)
    payload[0], payload[1] = payload[1], payload[0]
    with pytest.raises(ValueError, match="order"):
        om.parse_response(payload)


def test_parse_rejects_wrong_location_count() -> None:
    payload = _load("openmeteo_historical_sample.json")
    assert isinstance(payload, list)
    with pytest.raises(ValueError, match="expected 5"):
        om.parse_response(payload[:4])


def test_month_params() -> None:
    p = om.month_params(date(2019, 1, 1), date(2019, 1, 31))
    assert p["start_date"] == "2019-01-01" and p["end_date"] == "2019-01-31"
    assert p["models"] == "gfs_seamless" and p["timezone"] == "GMT"
    assert len(p["latitude"].split(",")) == 5


def test_month_ranges() -> None:
    assert list(om.month_ranges(date(2018, 1, 1), date(2018, 3, 10))) == [
        (date(2018, 1, 1), date(2018, 1, 31)),
        (date(2018, 2, 1), date(2018, 2, 28)),
        (date(2018, 3, 1), date(2018, 3, 10)),
    ]


def test_request_weight() -> None:
    assert om.request_weight(5, 9, 31) == pytest.approx(5 * 31 / 14)
    assert om.request_weight(5, 9, 3) == 5


def test_rate_limiter_waits_when_minute_budget_is_spent() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    limiter = om.RateLimiter(budgets=((60, 30),), clock=lambda: now[0], sleep=sleep)
    for _ in range(2):
        limiter.acquire(13.3)
    assert slept == []
    limiter.acquire(13.3)  # 39.9 > 30 within the minute
    assert slept == [60.0]
