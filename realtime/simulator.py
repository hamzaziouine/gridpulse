"""S4: smart-meter simulator -> Fabric Eventstream (custom endpoint, Event Hubs protocol).

Each of the 50 meters (data/reference/meters.csv) emits one JSON reading per cycle:
    {"ts", "meter_id", "site_id", "kw", "voltage", "status"}
kW follows the real Ontario demand shape (realtime/shape_profile.csv: mean demand by EST hour and
month from IESO 2019-2025, normalised to mean 1), scaled to each meter's rated_kw, plus noise.

Anomaly injection (the KQL Q2 / Activator demo): `--anomaly SITE_ID FACTOR SECONDS` multiplies a
site's readings from the start, or drop a file realtime/anomaly.json
    {"site_id": 5, "factor": 3.0, "seconds": 120}
while the simulator runs (it is read once, then renamed to anomaly.done.json).

Connection: `--conn-str` (Eventstream custom endpoint connection string incl. EntityPath), or
`--kv-url` + `--kv-secret` to read it from Key Vault with DefaultAzureCredential (DESIGN D16).

    uv run python realtime/simulator.py --dry-run --rate 5 --seconds 10
    uv run python realtime/simulator.py --kv-url https://kv-hz2611-cdda.vault.azure.net \
        --kv-secret es-meters-conn --rate 10
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EST = timezone(timedelta(hours=-5), "EST")
NOMINAL_V = 240.0


@dataclass(frozen=True)
class Meter:
    meter_id: str
    site_id: int
    rated_kw: float
    status: str


@dataclass
class Anomaly:
    site_id: int
    factor: float
    until: float  # monotonic deadline

    def applies(self, site_id: int, now: float) -> bool:
        return site_id == self.site_id and now < self.until


def load_meters(path: Path = ROOT / "data" / "reference" / "meters.csv") -> list[Meter]:
    with path.open(encoding="utf-8") as f:
        return [
            Meter(r["meter_id"], int(r["site_id"]), float(r["rated_kw"]), r["status"])
            for r in csv.DictReader(f)
        ]


def load_shape(path: Path = HERE / "shape_profile.csv") -> dict[tuple[int, int], float]:
    with path.open(encoding="utf-8") as f:
        rows = csv.DictReader(f)
        return {(int(r["month"]), int(r["hour_est"])): float(r["factor"]) for r in rows}


def reading(
    meter: Meter,
    ts: datetime,
    shape: dict[tuple[int, int], float],
    rng: random.Random,
    factor: float = 1.0,
) -> dict[str, object]:
    est = ts.astimezone(EST)
    base = 0.45 * meter.rated_kw * shape[(est.month, est.hour)]
    kw = max(0.0, base * rng.gauss(1.0, 0.05) * factor)
    if meter.status == "maintenance":
        kw = 0.0
    voltage = rng.gauss(NOMINAL_V, 2.0) - (6.0 if factor > 1 else 0.0)
    return {
        "ts": ts.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "meter_id": meter.meter_id,
        "site_id": meter.site_id,
        "kw": round(kw, 3),
        "voltage": round(voltage, 2),
        "status": meter.status,
    }


def events(
    meters: list[Meter],
    shape: dict[tuple[int, int], float],
    rate: float,
    seconds: float | None,
    anomaly: Anomaly | None,
    rng: random.Random,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    watch: Path | None = HERE / "anomaly.json",
) -> Iterator[dict[str, object]]:
    """Yield readings at `rate` events/s, cycling through the meters."""
    start = clock()
    n = 0
    while seconds is None or clock() - start < seconds:
        now = clock()
        if watch is not None and watch.exists():
            spec = json.loads(watch.read_text(encoding="utf-8"))
            anomaly = Anomaly(int(spec["site_id"]), float(spec["factor"]), now + spec["seconds"])
            watch.replace(watch.with_name("anomaly.done.json"))
            print(f"anomaly armed: {spec}", file=sys.stderr)
        m = meters[n % len(meters)]
        f = anomaly.factor if anomaly and anomaly.applies(m.site_id, now) else 1.0
        yield reading(m, datetime.now(UTC), shape, rng, f)
        n += 1
        delay = start + n / rate - clock()
        if delay > 0:
            sleep(delay)


def connection_string(args: argparse.Namespace) -> str:
    if args.conn_str:
        return args.conn_str
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    client = SecretClient(vault_url=args.kv_url, credential=DefaultAzureCredential())
    value = client.get_secret(args.kv_secret).value
    if not value:
        raise SystemExit(f"secret {args.kv_secret} is empty")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rate", type=float, default=10.0, help="events per second (default 10)")
    ap.add_argument("--seconds", type=float, default=None, help="stop after N seconds")
    ap.add_argument("--dry-run", action="store_true", help="print JSON lines, send nothing")
    ap.add_argument("--anomaly", nargs=3, metavar=("SITE_ID", "FACTOR", "SECONDS"))
    ap.add_argument("--conn-str")
    ap.add_argument("--kv-url")
    ap.add_argument("--kv-secret", default="es-meters-conn")
    ap.add_argument("--seed", type=int, default=2611)
    ap.add_argument("--batch", type=int, default=50, help="events per send when not dry-run")
    args = ap.parse_args(argv)

    meters, shape = load_meters(), load_shape()
    anomaly = None
    if args.anomaly:
        s, fct, sec = args.anomaly
        anomaly = Anomaly(int(s), float(fct), time.monotonic() + float(sec))
    stream = events(meters, shape, args.rate, args.seconds, anomaly, random.Random(args.seed))

    if args.dry_run:
        for ev in stream:
            print(json.dumps(ev), flush=True)
        return 0
    if not (args.conn_str or args.kv_url):
        ap.error("need --conn-str or --kv-url (or --dry-run)")

    from azure.eventhub import EventData, EventHubProducerClient

    producer = EventHubProducerClient.from_connection_string(connection_string(args))
    sent = 0
    with producer:
        batch = producer.create_batch()
        for ev in stream:
            batch.add(EventData(json.dumps(ev)))
            if len(batch) >= args.batch:
                producer.send_batch(batch)
                sent += len(batch)
                print(f"sent {sent}", file=sys.stderr, flush=True)
                batch = producer.create_batch()
        if len(batch):
            producer.send_batch(batch)
            sent += len(batch)
    print(f"done, {sent} events", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
