"""Day-ahead forecast features (DESIGN D13), built in pandas on the Spark driver.

Timeline for a target EST day T (24 hours, HE1..HE24):
- The forecast is issued on day T-1 at 08:15 EST (13:15 UTC), right after the daily pipeline.
- At that moment IESO has published PUB_Demand up to day T-2 complete (plus a provisional HE1 of
  T-1, which is not used). So every demand feature of a target hour reads only hours of EST
  days <= T-2: same-hour lags of 48 h and more on the hourly grid (T-2, T-3, T-7, T-14), the
  mean of the same hour over T-2..T-8, the statistics of day T-2 and its last hour.
  tests/unit/test_features_forecast.py proves it by changing every demand value from day T-1 on
  and checking that no feature moves.
- Weather at the target hour is a forecast: the Historical Forecast API for training and the
  backtest, the Forecast API for live scoring (nb_predict). Limitation: the historical series
  stitches the most recent model run for each hour (short lead time), so it is somewhat more
  accurate than the 1 to 2 day ahead forecast available at 08:15 EST the day before. Live error
  will be a bit higher.
- Calendar facts come from calendar_features (civil date, Ontario holidays).

The seasonal-naive baseline is the same hour one week earlier (`naive168`): it is known at issue
time. "Same hour yesterday" is not (day T-1 is not published at issue time), so it is not used.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

import numpy as np
import pandas as pd

from gridpulse.calendar_features import CALENDAR_COLUMNS, calendar_features
from gridpulse.config import CITIES, VARIABLES

FEATURE_SCHEMA_VERSION = 1
TARGET = "ontario_demand_mw"
DEMAND_LAGS_H = (48, 72, 168, 336)
WEATHER_COLUMNS = (
    *(f"{v}_w" for v in VARIABLES),
    "temperature_2m_mean",
    "hdd_w",
    "cdd_w",
    *(f"temperature_2m_{c.key}" for c in CITIES),
)
DERIVED_WEATHER = (
    "temp_w_mean24",
    "temp_w_delta3",
    "temp_w_day_max",
    "temp_w_day_min",
    "temp_w_lag48",
    "temp_w_change48",
)
DEMAND_FEATURES = (
    *(f"lag{h}" for h in DEMAND_LAGS_H),
    "sameh_mean7",
    "d2_mean",
    "d2_max",
    "d2_min",
    "last_known",
)
FEATURE_COLUMNS: tuple[str, ...] = (
    *CALENDAR_COLUMNS,
    *WEATHER_COLUMNS,
    *DERIVED_WEATHER,
    *DEMAND_FEATURES,
)
META_COLUMNS = ("target_time", "est_date", "hour_ending", "issue_date", "actual", "naive168")
EST_SHIFT = pd.Timedelta(hours=5)


def to_hourly_grid(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows keyed by `target_time` (UTC hour start) -> a gap-free hourly grid, UTC-aware index.
    Missing hours (e.g. IESO's 2025-05-01 HE1) become NaN rows."""
    t = pd.to_datetime(frame["target_time"], utc=True)
    g = frame.drop(columns=["target_time"]).set_index(t).sort_index()
    g = g[~g.index.duplicated(keep="last")]
    full = pd.date_range(g.index.min(), g.index.max(), freq="h", tz="UTC")
    return g.reindex(full)


def build_features(frame: pd.DataFrame, target_days: Iterable[date] | None = None) -> pd.DataFrame:
    """One row per target hour: META_COLUMNS + FEATURE_COLUMNS.

    `frame`: target_time, ontario_demand_mw (NaN where unknown, e.g. the future), and the weather
    columns of silver_demand_weather_hourly for every hour (history and forecast). Rows are kept
    for `target_days` if given, else for every hour that has its longest lag (336 h).
    """
    g = to_hourly_grid(frame)
    idx = g.index
    local = idx - EST_SHIFT  # EST wall clock, as naive-equivalent UTC-5
    est = pd.Series(local.date, index=idx)
    he = pd.Series(local.hour + 1, index=idx)
    y = g[TARGET].astype("float64")

    out = pd.DataFrame(index=idx)
    out["target_time"] = idx
    out["est_date"] = est.values
    out["hour_ending"] = he.values
    out["issue_date"] = (est - timedelta(days=1)).values
    out["actual"] = y.values

    for h in DEMAND_LAGS_H:
        out[f"lag{h}"] = y.shift(h).values
    out["naive168"] = out["lag168"]
    same_hour = pd.concat([y.shift(24 * k) for k in range(2, 9)], axis=1)  # days T-2 .. T-8
    out["sameh_mean7"] = same_hour.mean(axis=1).values
    daily = y.groupby(est.values).agg(["mean", "max", "min"])
    d2 = (est - timedelta(days=2)).values
    out["d2_mean"] = daily["mean"].reindex(d2).to_numpy()
    out["d2_max"] = daily["max"].reindex(d2).to_numpy()
    out["d2_min"] = daily["min"].reindex(d2).to_numpy()
    # Last hour of day T-2 (HE24) = target hour minus (HE + 24) hours.
    out["last_known"] = y.reindex(idx - pd.to_timedelta(he.values + 24, unit="h")).to_numpy()

    for col in WEATHER_COLUMNS:
        out[col] = g[col].astype("float64").values if col in g else np.nan
    tw = g["temperature_2m_w"].astype("float64")
    out["temp_w_mean24"] = tw.rolling(24, min_periods=24).mean().values
    out["temp_w_delta3"] = (tw - tw.shift(3)).values
    out["temp_w_day_max"] = tw.groupby(est.values).transform("max").values
    out["temp_w_day_min"] = tw.groupby(est.values).transform("min").values
    out["temp_w_lag48"] = tw.shift(48).values
    out["temp_w_change48"] = (tw - tw.shift(48)).values

    cal = calendar_features(pd.DatetimeIndex(idx))
    for col in CALENDAR_COLUMNS:
        out[col] = cal[col].to_numpy()

    if target_days is not None:
        keep = out["est_date"].isin(set(target_days))
    else:
        keep = out["lag336"].notna()
    res = out.loc[keep, [*META_COLUMNS, *FEATURE_COLUMNS]].reset_index(drop=True)
    return res


def has_weather(features: pd.DataFrame) -> pd.Series:
    return features["temperature_2m_w"].notna()


def live_frame(
    history: pd.DataFrame, forecast_weather: pd.DataFrame | None, target_day: date
) -> tuple[pd.DataFrame, str]:
    """Hourly frame for scoring `target_day` in production (nb_predict).

    `history`: silver_demand_weather_hourly rows (demand known up to T-2, weather from the
    Historical Forecast API). `forecast_weather`: silver_weather_forecast_ontario rows
    (valid_time + weather columns) from today's Forecast API file, or None. Forecast weather wins
    for every hour it covers from the start of day T-1 and fills earlier hours that have no
    historical weather yet; the target day's hours get NaN demand.
    Returns the frame and the weather source of the target day.
    """
    day_start = pd.Timestamp(target_day).tz_localize("UTC") + EST_SHIFT  # HE1 of T, in UTC
    hours = pd.date_range(day_start - pd.Timedelta(days=16), day_start + pd.Timedelta(hours=23),
                          freq="h", tz="UTC")  # fmt: skip
    hist = history.copy()
    hist["target_time"] = pd.to_datetime(hist["target_time"], utc=True)
    frame = hist.set_index("target_time").reindex(hours)
    frame.index.name = "target_time"
    source = "historical_forecast"
    if forecast_weather is not None and len(forecast_weather):
        fw = forecast_weather.copy()
        fw["valid_time"] = pd.to_datetime(fw["valid_time"], utc=True)
        fw = fw.set_index("valid_time").sort_index()
        fw = fw[~fw.index.duplicated(keep="last")]
        # The history file of the daily pipeline ends at yesterday 23:00Z while day T-1 starts at
        # 05:00Z today: the forecast file also fills any earlier hour the history does not have
        # (HE20..HE24 of day T-2, read by temp_w_lag48 of target hours HE20..HE24).
        in_frame = fw.index[fw.index.isin(hours)]
        no_history = frame.index[frame["temperature_2m_w"].isna()]
        from_t1 = in_frame >= day_start - pd.Timedelta(hours=24)
        use = in_frame[from_t1 | in_frame.isin(no_history)]
        cols = [c for c in WEATHER_COLUMNS if c in fw.columns]
        frame.loc[use, cols] = fw.loc[use, cols].to_numpy()
        target_hours = hours[hours >= day_start]
        if fw.index.isin(target_hours).sum() == len(target_hours):
            source = "forecast_api"
    target_mask = frame.index >= day_start
    frame.loc[target_mask, TARGET] = np.nan
    if frame.loc[target_mask, "temperature_2m_w"].isna().any():
        raise ValueError(f"no weather for every hour of {target_day}: cannot score")
    return frame.reset_index(), source
