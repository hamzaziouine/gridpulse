"""IESO PUB_Demand (source S1): file naming, version selection and CSV parsing.

Ported from GridCast `ingest/ieso_demand.py` (the database/versioning layer is not needed here:
in GridPulse the bronze layer keeps the raw file and silver overwrites by date partition).

Source facts:
- `PUB_Demand_YYYY.csv` per year; each revision is also posted as `PUB_Demand_YYYY_vNNN.csv`, and
  the unsuffixed name is the latest version.
- A few junk lines starting with `\\`, then `Date,Hour,Market Demand,Ontario Demand`.
- Hours are hour-ending 1..24 in EST (fixed UTC-5, see timeutil).
- Known gap: 2025-05-01 HE1 is missing (Market Renewal go-live). Gaps are kept as gaps; the
  silver data-quality step reports them.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime

import pandas as pd

from gridpulse.timeutil import EST, he_to_utc

BASE_URL = "https://reports-public.ieso.ca/public/Demand/"
HEADER = ["Date", "Hour", "Market Demand", "Ontario Demand"]

_NAME_RE = re.compile(r"^PUB_Demand(?:_(\d{4}))?(?:_v(\d+))?\.csv$")
_CREATED_RE = re.compile(r"Created at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_HREF_RE = re.compile(r'href="([^"?/]+)"')


class EmptyFeedError(ValueError):
    """A source file parsed to zero data rows."""


def list_directory(html: str) -> list[str]:
    """File names linked from an IESO reports-public directory listing."""
    return sorted(set(_HREF_RE.findall(html)))


def parse_file_name(name: str) -> tuple[int | None, str | None]:
    """`PUB_Demand_2026_v295.csv` -> (2026, 'v295'); `PUB_Demand.csv` -> (None, None)."""
    m = _NAME_RE.match(name)
    if not m:
        raise ValueError(f"not a PUB_Demand file name: {name!r}")
    year = int(m.group(1)) if m.group(1) else None
    version = f"v{int(m.group(2)):03d}" if m.group(2) else None
    return year, version


def latest_files_by_year(listing: Iterable[str]) -> dict[int, str]:
    """Newest file per year from a directory listing: the highest `_vNNN`, else the plain name."""
    best: dict[int, tuple[int, str]] = {}
    for name in listing:
        try:
            year, version = parse_file_name(name)
        except ValueError:
            continue
        if year is None:
            continue
        rank = int(version[1:]) if version else -1
        if year not in best or rank > best[year][0]:
            best[year] = (rank, name)
    return {y: n for y, (_, n) in sorted(best.items())}


def parse_created_at(body: str) -> datetime | None:
    """The `\\Created at` header line (EST wall time) as a UTC instant, if present."""
    m = _CREATED_RE.search(body[:500])
    if not m:
        return None
    local = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=EST)
    return local.astimezone(UTC)


def parse_pub_demand(body: str) -> pd.DataFrame:
    """Parse a PUB_Demand CSV body.

    Returns one row per (Date, Hour) with columns local_date, hour_ending, market_demand_mw,
    ontario_demand_mw, target_time (UTC interval start). Junk `\\` lines before the header are
    skipped whatever their number; gaps are kept as gaps.
    """
    lines = body.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith("Date,Hour"))
    except StopIteration as exc:
        raise EmptyFeedError("PUB_Demand header line not found") from exc
    reader = csv.reader(io.StringIO("\n".join(lines[start:])))
    header = next(reader)
    if [h.strip() for h in header[:4]] != HEADER:
        raise ValueError(f"unexpected PUB_Demand header: {header!r}")
    records = []
    for row in reader:
        if not row or not row[0].strip():
            continue
        d = date.fromisoformat(row[0].strip())
        he = int(row[1])
        records.append(
            {
                "local_date": d,
                "hour_ending": he,
                "market_demand_mw": float(row[2]),
                "ontario_demand_mw": float(row[3]),
                "target_time": he_to_utc(d, he),
            }
        )
    if not records:
        raise EmptyFeedError("PUB_Demand file has 0 data rows")
    df = pd.DataFrame.from_records(records)
    if df.duplicated(["local_date", "hour_ending"]).any():
        raise ValueError("duplicate (Date, Hour) rows in PUB_Demand file")
    df["target_time"] = pd.to_datetime(df["target_time"], utc=True)
    return df
