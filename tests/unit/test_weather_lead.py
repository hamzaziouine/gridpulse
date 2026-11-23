"""Lead-matched backtest weather (gridpulse.weather_lead, Previous Runs parsing)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from gridpulse import features as fx
from gridpulse import openmeteo as om
from gridpulse import weather_lead as wl
from gridpulse.config import CITIES, VARIABLES
from tests.unit.test_features_forecast import synthetic

COLS = [c for c in fx.WEATHER_COLUMNS]


def shifted(hist: pd.DataFrame, offset: float) -> pd.DataFrame:
    """A fake Previous Runs Ontario frame: the historical weather plus a smooth error."""
    out = hist[["target_time", *COLS]].rename(columns={"target_time": "valid_time"}).copy()
    n = len(out)
    out[COLS] = out[COLS].to_numpy() + offset * np.sin(np.arange(n) / 5.0)[:, None]
    return out


def test_parse_previous_runs_suffix_and_ontario_weights() -> None:
    times = ["2025-01-01T00:00", "2025-01-01T01:00"]
    payload = []
    for i, c in enumerate(CITIES):
        hourly = {"time": times}
        for v in VARIABLES:
            hourly[f"{v}_previous_day1"] = [float(i), float(i) + 1]
        payload.append({"latitude": c.lat, "longitude": c.lon, "hourly": hourly})
    wide = om.parse_response(payload, "_previous_day1")
    assert list(wide.columns)[1] == f"{VARIABLES[0]}_{CITIES[0].key}"
    ont = wl.ontario_weather(wide)
    w = np.array([c.weight for c in CITIES])
    expected = float(np.arange(len(CITIES)) @ w / w.sum())
    assert ont["temperature_2m_w"].iloc[0] == pytest.approx(expected)
    assert ont["temperature_2m_mean"].iloc[0] == pytest.approx(2.0)
    assert ont["hdd_w"].iloc[0] == pytest.approx(18 - expected)
    with pytest.raises(ValueError, match="missing"):
        om.parse_response(payload, "_previous_day2")


def test_ontario_weather_is_nan_when_a_city_is_missing() -> None:
    wide = pd.DataFrame({"valid_time": pd.to_datetime(["2025-01-01"], utc=True)})
    for c in CITIES:
        for v in VARIABLES:
            wide[f"{v}_{c.key}"] = 1.0
    wide.loc[0, f"snowfall_{CITIES[2].key}"] = np.nan
    ont = wl.ontario_weather(wide)
    assert np.isnan(ont["snowfall_w"].iloc[0])
    assert ont["temperature_2m_w"].iloc[0] == pytest.approx(1.0)


@pytest.mark.parametrize("policy", wl.POLICIES)
def test_lead_features_equal_what_live_scoring_would_build(policy: str) -> None:
    hist = synthetic(days=40)
    d1, d2 = shifted(hist, 2.0), shifted(hist, -3.0)
    lead, complete = wl.lead_weather(hist, d1, d2, policy)
    assert complete.all()
    got = wl.lead_features(hist, lead)
    for target in (date(2025, 1, 25), date(2025, 2, 3)):
        # Production: forecast file covers T-1 (here: the historical values, short lead) and
        # T (the lead weather); live_frame + build_features give the reference features.
        day_start = pd.Timestamp(target).tz_localize("UTC") + fx.EST_SHIFT
        t = pd.to_datetime(lead["target_time"], utc=True)
        fw = pd.concat([
            hist.loc[(t >= day_start - pd.Timedelta(hours=24)) & (t < day_start)],
            lead.loc[(t >= day_start) & (t < day_start + pd.Timedelta(hours=24))],
        ]).rename(columns={"target_time": "valid_time"})[["valid_time", *COLS]]  # fmt: skip
        frame, source = fx.live_frame(hist, fw, target)
        assert source == "forecast_api"
        ref = fx.build_features(frame, target_days=[target])
        mine = got[got["est_date"] == target].reset_index(drop=True)
        assert len(mine) == 24
        cols = list(fx.FEATURE_COLUMNS[len(fx.CALENDAR_COLUMNS) : -len(fx.DEMAND_FEATURES)])
        np.testing.assert_allclose(mine[cols].to_numpy(), ref[cols].to_numpy(), rtol=1e-9)


def test_matched_policy_switches_to_day2_after_he17_and_falls_back_on_gaps() -> None:
    hist = synthetic(days=20)
    d1, d2 = shifted(hist, 2.0), shifted(hist, -3.0)
    d2.loc[d2.index[:5], "snowfall_w"] = np.nan
    lead, complete = wl.lead_weather(hist, d1, d2, "matched")
    he = (pd.to_datetime(lead["target_time"], utc=True) - fx.EST_SHIFT).dt.hour + 1
    t = lead["temperature_2m_w"].to_numpy()
    assert np.allclose(t[he <= 17], d1["temperature_2m_w"].to_numpy()[he <= 17])
    assert np.allclose(t[he > 17], d2["temperature_2m_w"].to_numpy()[he > 17])
    gap = d2.index[:5][(he[d2.index[:5]] > 17).to_numpy()]
    assert (~complete[gap]).all()
    assert np.allclose(lead.loc[gap, "snowfall_w"], hist.loc[gap, "snowfall_w"])
    with pytest.raises(ValueError):
        wl.lead_weather(hist, d1, d2, "day3")
