"""Lead-matched weather: honest day-ahead backtest (review finding 3) and, since 2026-11-23,
the default training input of nb_forecast (`matched_training_features`).

Training and the standard backtest use the Open-Meteo Historical Forecast API, which keeps the
newest model run for each hour (lead of a few hours). In production nb_predict scores day T with
the forecast fetched on T-1 at 13:15 UTC: the newest GFS run then is the 06 UTC run, so the
target hours (05:00Z on T to 04:00Z on T+1) are 23 to 46 hours after that run.

The Previous Runs API gives, for every valid hour, the value forecast about one day earlier
(`_previous_day1`, run 24 to 30 h before) and about two days earlier (`_previous_day2`, 48 to
54 h). Policies for the weather of the target day:
- `day1`: every target hour from day 1 (a little optimistic for the late hours);
- `matched`: HE1..HE17 from day 1 and HE18..HE24 from day 2, the nearer of the two to the
  23 to 46 h of production (crossover at 39 h, valid 20:00Z on T, HE16 ends at 21:00Z);
- `day2`: every target hour from day 2 (pessimistic, longer lead than production).

Hours of day T-1 and earlier keep the historical weather, as in `features.live_frame` where the
forecast fetched on T-1 covers T-1 with a lead of at most 16 h and day T-2 comes from history.
`lead_features` reproduces the features `live_frame` + `build_features` would give, without
rebuilding a frame per target day.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from gridpulse import openmeteo as om
from gridpulse.config import CITIES, VARIABLES
from gridpulse.features import EST_SHIFT, WEATHER_COLUMNS, build_features

BASE_TEMP_C = 18.0  # same as medallion.silver
POLICIES = ("day1", "matched", "day2")
MATCHED_LAST_DAY1_HE = 17  # HE1..HE17 from day 1, HE18..HE24 from day 2


def ontario_weather(city_wide: pd.DataFrame) -> pd.DataFrame:
    """Wide city frame (`valid_time`, `<variable>_<city>`) -> the Ontario columns silver builds:
    population-weighted `<variable>_w`, `temperature_2m_mean`, `hdd_w`, `cdd_w` and the five city
    temperatures. An aggregate is NaN unless all five cities have the value (callers fall back to
    the historical weather for that column)."""
    out = pd.DataFrame({"valid_time": pd.to_datetime(city_wide["valid_time"], utc=True)})
    weights = np.array([c.weight for c in CITIES])
    for v in VARIABLES:
        block = city_wide[[f"{v}_{c.key}" for c in CITIES]].to_numpy(dtype="float64")
        agg = block @ weights / weights.sum()
        agg[np.isnan(block).any(axis=1)] = np.nan
        out[f"{v}_w"] = agg
    temps = city_wide[[f"temperature_2m_{c.key}" for c in CITIES]].to_numpy(dtype="float64")
    out["temperature_2m_mean"] = temps.mean(axis=1)
    out["hdd_w"] = np.maximum(0.0, BASE_TEMP_C - out["temperature_2m_w"])
    out["cdd_w"] = np.maximum(0.0, out["temperature_2m_w"] - BASE_TEMP_C)
    out.loc[out["temperature_2m_w"].isna(), ["hdd_w", "cdd_w"]] = np.nan
    for c in CITIES:
        out[f"temperature_2m_{c.key}"] = city_wide[f"temperature_2m_{c.key}"].astype("float64")
    return out


def load_prevruns(folder: Path, day: int) -> pd.DataFrame:
    """Monthly JSON files of scripts/pull_openmeteo_prevruns.py -> Ontario weather of one lead."""
    files = sorted(folder.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no Previous Runs files in {folder}")
    parts = [
        om.parse_response(json.loads(f.read_text(encoding="utf-8")), f"_previous_day{day}")
        for f in files
    ]
    wide = pd.concat(parts, ignore_index=True).drop_duplicates("valid_time", keep="last")
    return ontario_weather(wide.sort_values("valid_time").reset_index(drop=True))


def lead_weather(
    hist: pd.DataFrame, day1: pd.DataFrame, day2: pd.DataFrame, policy: str
) -> tuple[pd.DataFrame, pd.Series]:
    """Copy of `hist` (silver_demand_weather_hourly rows) whose weather columns hold the chosen
    lead for EVERY hour (column by column; NaN lead values keep the historical value).

    Returns the frame and a boolean Series (same index) telling whether all weather columns of
    the hour came from the Previous Runs data."""
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}")
    out = hist.copy()
    t = pd.to_datetime(out["target_time"], utc=True)
    he = ((t - EST_SHIFT).dt.hour + 1).to_numpy()
    cols = [c for c in WEATHER_COLUMNS if c in out.columns]
    d1 = day1.set_index("valid_time").reindex(t)[cols].to_numpy()
    d2 = day2.set_index("valid_time").reindex(t)[cols].to_numpy()
    if policy == "day1":
        lead = d1
    elif policy == "day2":
        lead = d2
    else:
        lead = np.where((he <= MATCHED_LAST_DAY1_HE)[:, None], d1, d2)
    old = out[cols].to_numpy(dtype="float64")
    out[cols] = np.where(np.isnan(lead), old, lead)
    complete = pd.Series(~np.isnan(lead).any(axis=1), index=out.index)
    return out, complete


def lead_features(hist: pd.DataFrame, lead: pd.DataFrame) -> pd.DataFrame:
    """Features of every target hour as nb_predict would build them in production: weather of
    day T from `lead`, weather of T-1 and earlier from `hist`.

    `hist` and `lead` are frames for build_features with the same rows (lead = lead_weather(...)).
    Only the features that read weather of other days need care: the 24 h mean and the 3 h
    change look back into T-1, the 48 h lag reads T-2."""
    fh = build_features(hist)
    fl = build_features(lead)
    if not fh["target_time"].equals(fl["target_time"]):  # pragma: no cover - same input rows
        raise ValueError("feature rows differ between the two frames")
    out = fl.copy()
    est = pd.Series(fh["est_date"].to_numpy())

    def hourly(frame: pd.DataFrame) -> pd.Series:
        g = frame.assign(target_time=pd.to_datetime(frame["target_time"], utc=True))
        g = g.set_index("target_time").sort_index()["temperature_2m_w"].astype("float64")
        full = pd.date_range(g.index.min(), g.index.max(), freq="h", tz="UTC")
        return g[~g.index.duplicated(keep="last")].reindex(full)

    th, tl = hourly(hist), hourly(lead)
    grid_est = pd.Series((th.index - EST_SHIFT).date, index=th.index)
    cum_h = th.groupby(grid_est.values).cumsum()
    cum_l = tl.groupby(grid_est.values).cumsum()
    # sum over t-23..t = (hours of day T up to t, lead) + (the rest, from T-1, historical)
    roll_h = th.rolling(24, min_periods=24).sum()
    mean24 = (cum_l + roll_h - cum_h) / 24
    he = pd.Series(np.asarray(fh["hour_ending"]), index=out.index)
    rows = pd.DatetimeIndex(pd.to_datetime(fh["target_time"], utc=True))
    out["temp_w_mean24"] = mean24.reindex(rows).to_numpy()
    lag3 = np.where(
        he > 3, tl.shift(3).reindex(rows).to_numpy(), th.shift(3).reindex(rows).to_numpy()
    )
    out["temp_w_delta3"] = out["temperature_2m_w"].to_numpy() - lag3
    out["temp_w_lag48"] = fh["temp_w_lag48"].to_numpy()
    out["temp_w_change48"] = out["temperature_2m_w"].to_numpy() - out["temp_w_lag48"].to_numpy()
    out["est_date"] = est.to_numpy()
    return out


def split_leads(prev: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """silver_weather_prevruns_ontario rows (`valid_time`, `lead_days`, weather columns) ->
    (day1, day2) frames for `lead_weather`, one row per UTC hour, tz-aware valid_time."""
    out = []
    for d in (1, 2):
        part = prev[prev["lead_days"] == d].copy()
        part["valid_time"] = pd.to_datetime(part["valid_time"], utc=True)
        part = part.sort_values("valid_time").drop_duplicates("valid_time", keep="last")
        cols = ["valid_time", *(c for c in WEATHER_COLUMNS if c in part.columns)]
        out.append(part[cols].reset_index(drop=True))
    return out[0], out[1]


def matched_training_features(
    hist: pd.DataFrame, prev: pd.DataFrame, policy: str = "matched"
) -> tuple[pd.DataFrame, dict]:
    """Production training input: features of every hour as nb_predict builds them live, with
    the weather of day T at the lead the daily forecast really has (`policy`, default matched:
    HE1..HE17 forecast 1 day ahead, HE18..HE24 2 days ahead).

    Fallback: column by column, an hour without a complete Previous Runs value keeps the
    historical (short-lead) weather. With the gfs_seamless coverage that means: before
    2024-01-19 every variable is historical except temperature (pulled from 2024-01, so also
    historical before that), 2024-01-19 to 2024-12-06 snowfall is historical, after that every
    variable has the matched lead. Without any Previous Runs row the result equals
    `build_features(hist)` (up to float rounding of the 24 h mean).

    Returns the features and a small coverage summary for logging."""
    d1, d2 = split_leads(prev)
    lead, complete = lead_weather(hist, d1, d2, policy)
    feats = lead_features(hist, lead)
    est = (pd.to_datetime(hist["target_time"], utc=True) - EST_SHIFT).dt.date
    full_days = complete.groupby(est.to_numpy()).agg(["all", "size"])
    full = full_days.index[full_days["all"] & (full_days["size"] == 24)]
    info = {
        "policy": policy,
        "hours_full_lead": int(complete.sum()),
        "hours_total": int(len(complete)),
        "first_full_lead_day": str(min(full)) if len(full) else "",
        "last_full_lead_day": str(max(full)) if len(full) else "",
    }
    return feats, info
