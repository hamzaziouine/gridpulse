"""KQL Q2 (realtime/kql/q2_anomaly.kql) replayed in pandas on simulated meter events.

KQL cannot run locally, so `q2` below mirrors the query step by step (bin to the minute, mean
per meter, sum per site, trailing-hour mean and sample stdev, last complete minute, n >= 10,
mean + 3 sigma). `q2_old` is the first version (sum of every reading per site-minute) and shows
the review finding: the old value moves with the number of readings in a minute.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

KQL = Path(__file__).resolve().parents[2] / "realtime" / "kql" / "q2_anomaly.kql"
NOW = pd.Timestamp("2026-11-23 12:00:20", tz="UTC")
SITES = {1: 5, 5: 4}  # site_id -> number of meters
PERIOD_S = 5  # 50 meters at 10 events/s: one reading per meter every 5 s


def simulate(seed: int = 3) -> pd.DataFrame:
    """62 complete minutes plus the current partial minute, every meter every 5 s, 2 % noise."""
    rng = np.random.default_rng(seed)
    start = NOW.floor("min") - pd.Timedelta(minutes=64)
    rows = []
    for site, n in SITES.items():
        for m in range(n):
            rated = 20.0 + 5 * m + site
            ts = pd.date_range(start + pd.Timedelta(seconds=m), NOW, freq=f"{PERIOD_S}s")
            kw = rated * (1 + rng.normal(0, 0.02, len(ts)))
            rows.append(pd.DataFrame({"ts": ts, "meter_id": f"S{site}-M{m}", "site_id": site,
                                      "kw": kw}))  # fmt: skip
    return pd.concat(rows, ignore_index=True)


def _verdict(per_minute: pd.DataFrame) -> pd.DataFrame:
    last = NOW.floor("min") - pd.Timedelta(minutes=1)
    base = per_minute[per_minute["minute"] < last].groupby("site_id")["site_kw"]
    baseline = pd.DataFrame({"mean_kw": base.mean(), "sd_kw": base.std(ddof=1),
                             "n": base.count()}).reset_index()  # fmt: skip
    cur = per_minute[per_minute["minute"] == last].merge(baseline, on="site_id")
    hit = cur[(cur["n"] >= 10) & (cur["site_kw"] > cur["mean_kw"] + 3 * cur["sd_kw"])]
    return hit.assign(z=(hit["site_kw"] - hit["mean_kw"]) / hit["sd_kw"]).reset_index(drop=True)


def _window(events: pd.DataFrame) -> pd.DataFrame:
    e = events[events["ts"] > NOW - pd.Timedelta(minutes=65)]
    return e.assign(minute=e["ts"].dt.floor("min"))


def q2(events: pd.DataFrame) -> pd.DataFrame:
    """Current query: mean kW per meter and minute, summed per site."""
    per_meter = _window(events).groupby(["site_id", "meter_id", "minute"], as_index=False)["kw"]
    per_meter = per_meter.mean().rename(columns={"kw": "meter_kw"})
    per_minute = per_meter.groupby(["site_id", "minute"], as_index=False).agg(
        site_kw=("meter_kw", "sum"), meters=("meter_id", "nunique")
    )
    return _verdict(per_minute)


def q2_old(events: pd.DataFrame) -> pd.DataFrame:
    """First version: sum(kw) of every reading per site and minute."""
    per_minute = _window(events).groupby(["site_id", "minute"], as_index=False)["kw"].sum()
    return _verdict(per_minute.rename(columns={"kw": "site_kw"}))


def last_minute(events: pd.DataFrame, site: int) -> pd.Series:
    last = NOW.floor("min") - pd.Timedelta(minutes=1)
    return (events["site_id"] == site) & (events["ts"].dt.floor("min") == last)


def test_kql_file_averages_per_meter_before_summing_per_site() -> None:
    text = KQL.read_text(encoding="utf-8")
    assert "summarize meter_kw = avg(kw) by site_id, meter_id, minute = bin(ts, 1m)" in text
    assert "site_kw = sum(meter_kw)" in text
    assert "sum(kw)" not in text
    assert "mean_kw + 3 * sd_kw" in text and "n >= 10" in text


def test_steady_stream_raises_nothing() -> None:
    ev = simulate()
    assert q2(ev).empty and q2_old(ev).empty


def test_real_anomaly_is_flagged_by_both_versions() -> None:
    ev = simulate()
    ev.loc[last_minute(ev, 5), "kw"] *= 3.0  # simulator --anomaly 5 3.0
    assert list(q2(ev)["site_id"]) == [5]
    assert list(q2_old(ev)["site_id"]) == [5]


def test_duplicated_events_are_no_longer_an_anomaly() -> None:
    """At-least-once delivery: 6 readings of site 1 arrive twice in the last minute."""
    ev = simulate()
    dup = ev[last_minute(ev, 1)].head(6)
    ev = pd.concat([ev, dup], ignore_index=True)
    assert list(q2_old(ev)["site_id"]) == [1]  # old: +6 readings look like a load spike
    assert q2(ev).empty


def test_dropped_events_no_longer_hide_a_real_anomaly() -> None:
    """Site 5 really jumps 25 % in the last minute while 30 % of its events were dropped."""
    ev = simulate()
    mask = last_minute(ev, 5)
    ev.loc[mask, "kw"] *= 1.25
    idx = ev.index[mask]
    dropped = np.random.default_rng(1).choice(idx, size=int(0.3 * len(idx)), replace=False)
    ev = ev.drop(index=dropped)
    assert q2_old(ev).empty  # old: fewer readings cancel the higher load
    hit = q2(ev)
    assert list(hit["site_id"]) == [5] and int(hit["meters"].iloc[0]) == SITES[5]


def test_dropped_events_alone_raise_nothing() -> None:
    """Throttling drops 20 % of all events in random baseline minutes: no false alarm now."""
    ev = simulate()
    rng = np.random.default_rng(2)
    keep = rng.random(len(ev)) > 0.2
    last = NOW.floor("min") - pd.Timedelta(minutes=1)
    keep |= ev["ts"].dt.floor("min") == last  # the last complete minute arrived in full
    ev = ev[keep]
    assert q2(ev).empty
