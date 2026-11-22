"""Day-ahead features (no leakage) and the LightGBM/backtest helpers, on synthetic hours."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from gridpulse import features as fx
from gridpulse import forecast as fc
from gridpulse.config import CITIES, VARIABLES


def synthetic(days: int = 60, start: str = "2025-01-01 05:00") -> pd.DataFrame:
    """Hourly frame shaped like silver_demand_weather_hourly (UTC hour starts)."""
    rng = np.random.default_rng(7)
    t = pd.date_range(start, periods=24 * days, freq="h", tz="UTC")
    hour = (t - pd.Timedelta(hours=5)).hour
    temp = -5 + 8 * np.sin(2 * np.pi * (hour - 9) / 24) + rng.normal(0, 1, len(t))
    demand = 16000 + 1500 * np.sin(2 * np.pi * (hour - 13) / 24) - 120 * temp
    f = pd.DataFrame({"target_time": t, "ontario_demand_mw": demand + rng.normal(0, 100, len(t))})
    for v in VARIABLES:
        f[f"{v}_w"] = temp if v == "temperature_2m" else rng.normal(10, 2, len(t))
    f["temperature_2m_mean"] = temp
    f["hdd_w"] = np.maximum(0, 18 - temp)
    f["cdd_w"] = np.maximum(0, temp - 18)
    for c in CITIES:
        f[f"temperature_2m_{c.key}"] = temp + rng.normal(0, 0.5, len(t))
    return f


def test_feature_columns_and_one_row_per_target_hour() -> None:
    f = fx.build_features(synthetic(), target_days=[date(2025, 2, 10)])
    assert list(f.columns) == [*fx.META_COLUMNS, *fx.FEATURE_COLUMNS]
    assert len(f) == 24 and sorted(f["hour_ending"]) == list(range(1, 25))
    assert (f["issue_date"] == date(2025, 2, 9)).all()
    assert f[list(fx.FEATURE_COLUMNS)].notna().all().all()


def test_lags_are_on_the_hourly_grid() -> None:
    raw = synthetic()
    f = fx.build_features(raw, target_days=[date(2025, 2, 10)])
    g = raw.set_index("target_time")["ontario_demand_mw"]
    row = f.iloc[0]
    t = pd.Timestamp(row["target_time"])
    assert row["lag48"] == pytest.approx(g[t - pd.Timedelta(hours=48)])
    assert row["lag168"] == pytest.approx(g[t - pd.Timedelta(hours=168)])
    assert row["naive168"] == row["lag168"]
    # HE24 of day T-2 is the last hour IESO has published at issue time
    he1_t = pd.Timestamp("2025-02-10 05:00", tz="UTC")
    assert row["last_known"] == pytest.approx(g[he1_t - pd.Timedelta(hours=25)])


def test_no_demand_published_after_issue_time_is_used() -> None:
    """Change every demand value of day T-1 and later: no feature of day T may move."""
    raw = synthetic()
    target = date(2025, 2, 10)
    base = fx.build_features(raw, target_days=[target])
    t_minus_1_start = pd.Timestamp("2025-02-09 05:00", tz="UTC")  # HE1 of T-1
    tampered = raw.copy()
    late = pd.to_datetime(tampered["target_time"], utc=True) >= t_minus_1_start
    tampered.loc[late, "ontario_demand_mw"] = 1e9
    after = fx.build_features(tampered, target_days=[target])
    cols = list(fx.FEATURE_COLUMNS)
    pd.testing.assert_frame_equal(base[cols], after[cols])
    assert (after["actual"] == 1e9).all()  # only the label changed


def test_missing_hour_becomes_nan_not_a_shift() -> None:
    raw = synthetic()
    gap = pd.Timestamp("2025-02-08 05:00", tz="UTC")
    holed = raw[pd.to_datetime(raw["target_time"], utc=True) != gap]
    f = fx.build_features(holed, target_days=[date(2025, 2, 10)])
    he1 = f[f["hour_ending"] == 1].iloc[0]
    assert np.isnan(he1["lag48"])  # the gap hour, not the hour before it
    assert not np.isnan(f[f["hour_ending"] == 2].iloc[0]["lag48"])


def test_error_metrics_and_skill() -> None:
    m = fc.error_metrics([100, 200, np.nan], [110, 180, 5])
    assert m["mape_pct"] == pytest.approx(10.0)
    assert m["mae_mw"] == pytest.approx(15.0)
    assert m["n_hours"] == 2
    assert fc.skill_pct(3.0, 6.0) == pytest.approx(50.0)


def test_peak_ape_uses_the_actual_peak_hour() -> None:
    f = pd.DataFrame({"est_date": [date(2025, 1, 1)] * 3, "actual": [10.0, 20.0, 15.0],
                      "forecast": [10.0, 18.0, 15.0]})  # fmt: skip
    assert fc.peak_ape(f, "forecast") == pytest.approx(10.0)


def test_fold_train_window_ends_two_days_before_the_month() -> None:
    f = fc.Fold(date(2026, 3, 1))
    assert f.train_until == date(2026, 2, 27)
    assert f.month_end == date(2026, 3, 31)
    assert fc.month_starts(date(2025, 11, 15), date(2026, 2, 1)) == [
        date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]  # fmt: skip


def test_train_predict_backtest_and_eval_rows() -> None:
    feats = fx.build_features(synthetic(days=90))
    ok = feats[fc.usable(feats)]
    tr = ok[ok["est_date"] < date(2025, 3, 1)]
    booster, n = fc.train(tr, tr["actual"], rounds=50)
    assert n == 50 and booster.feature_name() == list(fx.FEATURE_COLUMNS)
    scored = fc.backtest(feats, date(2025, 3, 1), rounds=50, log=lambda *_: None)
    assert scored["est_date"].min() == date(2025, 3, 1)
    s = fc.summary(scored)
    assert s["model_mape_pct"] < s["naive_mape_pct"]  # weather-driven synthetic demand
    ev = fc.monthly_eval(scored, "backtest", "run-1")
    assert set(ev["model"]) == {fc.MODEL_NAME, fc.NAIVE_NAME}
    assert ev.loc[ev["model"] == fc.NAIVE_NAME, "skill_vs_naive_pct"].isna().all()
    rows = fc.forecast_rows(scored, "backtest", "1", "run-1", "historical_forecast")
    assert len(rows) == len(scored) and rows["ape_pct"].notna().all()
    assert (rows["issue_date"] == rows["est_date"] - timedelta(days=1)).all()


def test_predict_refuses_another_feature_list() -> None:
    feats = fx.build_features(synthetic(days=30))
    booster, _ = fc.train(feats, feats["actual"], rounds=5)
    bad = feats.rename(columns={"lag48": "lag47"})
    with pytest.raises(KeyError):
        fc.predict(booster, bad)


def test_live_frame_uses_forecast_weather_and_hides_target_demand() -> None:
    hist = synthetic(days=40)
    target = date(2025, 2, 5)
    day_start = pd.Timestamp("2025-02-05 05:00", tz="UTC")
    known = pd.to_datetime(hist["target_time"], utc=True) < day_start - pd.Timedelta(hours=24)
    history = hist[known]  # demand and weather up to T-2
    fcw = hist[~known & (pd.to_datetime(hist["target_time"], utc=True) < day_start
                         + pd.Timedelta(hours=24))].rename(columns={"target_time": "valid_time"})
    fcw = fcw.drop(columns=["ontario_demand_mw"]).assign(temperature_2m_w=-30.0)
    frame, source = fx.live_frame(history, fcw, target)
    assert source == "forecast_api"
    f = fx.build_features(frame, target_days=[target])
    assert len(f) == 24 and f["actual"].isna().all()
    assert (f["temperature_2m_w"] == -30.0).all()
    assert f[[c for c in fx.FEATURE_COLUMNS if c.startswith(("lag", "d2_"))]].notna().all().all()


def test_live_frame_without_weather_for_tomorrow_refuses() -> None:
    hist = synthetic(days=40)
    day_start = pd.Timestamp("2025-02-05 05:00", tz="UTC")
    history = hist[pd.to_datetime(hist["target_time"], utc=True) < day_start]
    with pytest.raises(ValueError, match="no weather"):
        fx.live_frame(history, None, date(2025, 2, 5))
