"""Smart-meter simulator: event schema, pacing, anomaly multiplier."""

from __future__ import annotations

import importlib.util
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("simulator", ROOT / "realtime" / "simulator.py")
assert spec and spec.loader
sim = importlib.util.module_from_spec(spec)
sys.modules["simulator"] = sim
spec.loader.exec_module(sim)

SHAPE = {(m, h): 1.0 for m in range(1, 13) for h in range(24)}
M = sim.Meter("MTR-0001", 5, 100.0, "active")


def test_reading_schema() -> None:
    ev = sim.reading(M, datetime(2026, 11, 16, 15, tzinfo=UTC), SHAPE, random.Random(1))
    assert set(ev) == {"ts", "meter_id", "site_id", "kw", "voltage", "status"}
    assert ev["ts"] == "2026-11-16T15:00:00.000Z"
    assert 30 < ev["kw"] < 60  # 0.45 * 100 kW, 5 % noise


def test_anomaly_multiplies_only_its_site() -> None:
    ts = datetime(2026, 11, 16, 15, tzinfo=UTC)
    base = sim.reading(M, ts, SHAPE, random.Random(7))["kw"]
    hot = sim.reading(M, ts, SHAPE, random.Random(7), factor=3.0)["kw"]
    assert hot == pytest.approx(3 * base, rel=1e-3)
    a = sim.Anomaly(site_id=5, factor=3.0, until=10.0)
    assert a.applies(5, 9.9) and not a.applies(5, 10.0) and not a.applies(4, 1.0)


def test_maintenance_meter_reads_zero() -> None:
    m = sim.Meter("MTR-0017", 7, 50.0, "maintenance")
    ev = sim.reading(m, datetime(2026, 11, 16, 15, tzinfo=UTC), SHAPE, random.Random(1))
    assert ev["kw"] == 0.0


def test_events_paced_and_cycle_meters() -> None:
    now = [0.0]

    def sleep(s: float) -> None:
        now[0] += s

    meters = [sim.Meter(f"MTR-{i:04d}", i, 10.0, "active") for i in range(1, 4)]
    evs = list(
        sim.events(
            meters,
            SHAPE,
            rate=5,
            seconds=2,
            anomaly=None,
            rng=random.Random(0),
            clock=lambda: now[0],
            sleep=sleep,
            watch=None,
        )
    )
    assert len(evs) == 10  # 5 events/s for 2 s
    assert [e["meter_id"] for e in evs[:4]] == ["MTR-0001", "MTR-0002", "MTR-0003", "MTR-0001"]
