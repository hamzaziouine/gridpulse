"""Calendar features (ported from GridCast) and the naive baselines."""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from gridpulse import baselines as b
from gridpulse import calendar_features as cal


def ts(*args: int) -> pd.Timestamp:
    return pd.Timestamp(datetime(*args, tzinfo=UTC))  # type: ignore[misc]


@pytest.mark.parametrize(
    ("d", "hid"),
    [(date(2027, 2, 15), 2), (date(2026, 8, 3), 6), (date(2026, 12, 25), 9), (date(2026, 8, 4), 0)],
)
def test_holidays(d: date, hid: int) -> None:
    assert cal.holiday_id(d) == hid


def test_calendar_civil_date_at_edt_boundary() -> None:
    # Civic Holiday 2026-08-03 (EDT): civil 00:00-01:00 = 04:00Z = HE24 of EST date 2026-08-02.
    f = cal.calendar_features(pd.DatetimeIndex([ts(2026, 8, 3, 4), ts(2026, 8, 3, 3)]))
    assert list(f["is_holiday"]) == [1.0, 0.0]
    assert list(f["hour_est"]) == [23.0, 22.0]
    assert list(f["civil_hour"]) == [0.0, 23.0]


def test_long_weekend_bridge_and_xmas() -> None:
    assert cal.is_long_weekend(date(2026, 8, 1))
    assert not cal.is_long_weekend(date(2026, 8, 8))
    assert cal.is_bridge_day(date(2027, 7, 2))
    f = cal.calendar_features(pd.DatetimeIndex([ts(2026, 12, 24, 17), ts(2027, 1, 3, 17)]))
    assert list(f["xmas_period"]) == [1.0, 0.0]
    assert cal.days_to_next_holiday(date(2026, 12, 20)) == 5


def test_seasonal_naive_and_metrics() -> None:
    idx = pd.date_range("2026-01-01", periods=24 * 10, freq="h", tz="UTC")
    demand = pd.Series(np.arange(len(idx), dtype=float) + 1000, index=idx)
    targets = idx[-24:]
    f168 = b.seasonal_naive(demand, targets, 168)
    assert (demand[targets].to_numpy() - f168.to_numpy() == 168).all()
    early = b.seasonal_naive(demand, idx[:2], 24)
    assert early.isna().all()  # no history before the series starts
    assert b.mae(demand[targets], f168) == pytest.approx(168)
    assert b.mape(pd.Series([100.0, 200.0]), pd.Series([110.0, np.nan])) == pytest.approx(10.0)
