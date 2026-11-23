"""Cut the small "lake" fixture used by the Spark tests from the local raw files.

6 EST days, 2025-04-28 to 2025-05-03, chosen because they contain IESO's real missing hour
(2025-05-01 HE1). The IESO excerpt keeps the original header lines; the Open-Meteo excerpt keeps
the original JSON layout (5 city objects with hourly arrays), split by month like the real files;
the same window is cut from the Previous Runs files (data/raw/openmeteo_prevruns).
Short excerpts only (IESO licence: 7 days or less). Output: tests/fixtures/lake/.

    uv run python scripts/make_test_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "tests" / "fixtures" / "lake"
FIRST, LAST = "2025-04-28", "2025-05-03"
# Weather must cover HE24 of the last EST day: 2025-05-04 04:00Z.
WX_FIRST, WX_LAST = "2025-04-28T00:00", "2025-05-04T04:00"


def main() -> None:
    src = next((RAW / "ieso").glob("PUB_Demand_2025_v*.csv"))
    lines = src.read_text(encoding="utf-8").splitlines()
    head = [ln for ln in lines if ln.startswith("\\")] + [lines[3]]
    rows = [ln for ln in lines if ln[:10] >= FIRST and ln[:10] <= LAST and ln[:1].isdigit()]
    (OUT / "ieso").mkdir(parents=True, exist_ok=True)
    (OUT / "ieso" / src.name).write_text("\n".join(head + rows) + "\n", encoding="utf-8")
    print(f"ieso/{src.name}: {len(rows)} rows")

    for folder in ("openmeteo", "openmeteo_prevruns"):
        cut_weather(folder)


def cut_weather(folder: str) -> None:
    (OUT / folder).mkdir(parents=True, exist_ok=True)
    for month in ("2025-04", "2025-05"):
        payload = json.loads((RAW / folder / f"{month}.json").read_text(encoding="utf-8"))
        cut = []
        for item in payload:
            times = item["hourly"]["time"]
            keep = [i for i, t in enumerate(times) if WX_FIRST <= t <= WX_LAST]
            hourly = {k: [v[i] for i in keep] for k, v in item["hourly"].items()}
            cut.append({**{k: v for k, v in item.items() if k != "hourly"}, "hourly": hourly})
        (OUT / folder / f"{month}.json").write_text(
            json.dumps(cut, separators=(",", ":")), encoding="utf-8"
        )
        n = len(cut[0]["hourly"]["time"])
        print(f"{folder}/{month}.json: {n} hours x {len(cut)} cities")


if __name__ == "__main__":
    main()
