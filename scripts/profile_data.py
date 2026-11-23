"""Profile the raw IESO and Open-Meteo files -> docs/data_profile.md (report section 3 evidence).

uv run python scripts/profile_data.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from gridpulse import ieso, openmeteo
from gridpulse.config import CITIES, VARIABLES

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DST_DAYS = ["2025-03-09", "2025-11-02", "2026-03-08", "2026-11-01"]


def ieso_section() -> list[str]:
    out = ["## S1 IESO PUB_Demand (hourly, EST hour-ending)", ""]
    out += ["| File | Rows | First date | Last date | Missing hours | Created at (UTC) |"]
    out += ["|---|---|---|---|---|---|"]
    frames = []
    for f in sorted((RAW / "ieso").glob("PUB_Demand_*.csv")):
        body = f.read_text(encoding="utf-8")
        df = ieso.parse_pub_demand(body)
        full = pd.date_range(df["target_time"].min(), df["target_time"].max(), freq="h")
        missing = full.difference(pd.DatetimeIndex(df["target_time"]))
        created = ieso.parse_created_at(body)
        out.append(
            f"| `{f.name}` | {len(df):,} | {df['local_date'].min()} | {df['local_date'].max()} |"
            f" {len(missing)} {[str(m) for m in missing[:3]] if len(missing) else ''} |"
            f" {created:%Y-%m-%d %H:%M} |"
        )
        frames.append(df)
    allf = pd.concat(frames, ignore_index=True)
    od = allf["ontario_demand_mw"]
    out += [
        "",
        f"- Total rows: **{len(allf):,}**; duplicated target_time across files:"
        f" {int(allf['target_time'].duplicated().sum())}.",
        f"- Ontario Demand MW: min {od.min():,.0f}, median {od.median():,.0f}, max {od.max():,.0f};"
        f" zero or negative values: {int((od <= 0).sum())}.",
        "- DST days (EST has no DST, so each must have exactly 24 rows): "
        + ", ".join(
            f"{d}: {int((allf['local_date'] == pd.Timestamp(d).date()).sum())}" for d in DST_DAYS
        )
        + ".",
        "",
    ]
    return out


def openmeteo_section() -> list[str]:
    files = sorted((RAW / "openmeteo").glob("*.json"))
    if not files:
        return ["## S2 Open-Meteo", "", "No files yet.", ""]
    frames = [openmeteo.parse_response(json.loads(f.read_text(encoding="utf-8"))) for f in files]
    w = pd.concat(frames, ignore_index=True)
    out = ["## S2 Open-Meteo Historical Forecast (gfs_seamless, UTC, 5 cities)", ""]
    out += [
        f"- Files: {len(files)} months ({files[0].stem} .. {files[-1].stem});"
        f" hours: **{len(w):,}**; first {w['valid_time'].min()}, last {w['valid_time'].max()}.",
        f"- Duplicated hours: {int(w['valid_time'].duplicated().sum())}.",
        f"- Cities: {', '.join(f'{c.name} ({c.weight})' for c in CITIES)}.",
        "",
        "| Variable | Null cells (all cities) | Null % |",
        "|---|---|---|",
    ]
    for v in VARIABLES:
        cols = [f"{v}_{c.key}" for c in CITIES]
        n = int(w[cols].isna().sum().sum())
        out.append(f"| `{v}` | {n:,} | {100 * n / (len(w) * len(cols)):.3f} |")
    out.append("")
    return out


def main() -> None:
    lines = [
        "# Raw data profile",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/profile_data.py`"
        " from the local raw files (not committed: IESO licence).",
        "",
        *ieso_section(),
        *openmeteo_section(),
    ]
    (ROOT / "docs" / "data_profile.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
