"""Naive baselines for the 24 h-ahead forecast (DESIGN D13, success criterion: beat them).

GridPulse issues one forecast per EST day for the next 24 hours, using demand known up to the
issue time. A simple hourly series in, a forecast per target hour out:
- seasonal_naive_168: demand one week earlier (target - 168 h).
- seasonal_naive_24: demand one day earlier (target - 24 h).
Both need only the hourly series, so they run unchanged in a Fabric notebook.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BASELINES: dict[str, int] = {"seasonal_naive_168": 168, "seasonal_naive_24": 24}


def seasonal_naive(demand: pd.Series, targets: pd.DatetimeIndex, lag_hours: int) -> pd.Series:
    """Value of `demand` (UTC-indexed hourly series) at each target - lag. NaN when missing."""
    src = targets - pd.Timedelta(hours=lag_hours)
    return pd.Series(demand.reindex(src).to_numpy(), index=targets, name=f"lag{lag_hours}")


def mape(actual: pd.Series, forecast: pd.Series) -> float:
    """Mean absolute percentage error in %, over rows where both are present."""
    a, f = actual.to_numpy(float), forecast.to_numpy(float)
    ok = ~(np.isnan(a) | np.isnan(f)) & (a != 0)
    return float(np.mean(np.abs((a[ok] - f[ok]) / a[ok])) * 100)


def mae(actual: pd.Series, forecast: pd.Series) -> float:
    a, f = actual.to_numpy(float), forecast.to_numpy(float)
    ok = ~(np.isnan(a) | np.isnan(f))
    return float(np.mean(np.abs(a[ok] - f[ok])))
