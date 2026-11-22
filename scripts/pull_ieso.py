"""L3: download the newest IESO PUB_Demand file per year (2019 .. current) to data/raw/ieso/.

Resumable: a year whose newest file name is already on disk is skipped. Raw files stay local
(gitignored): the IESO licence forbids redistributing them.

    uv run python scripts/pull_ieso.py
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from gridpulse import ieso
from gridpulse.config import FIRST_YEAR

OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "ieso"
UA = {"User-Agent": "gridpulse student project (UIR)"}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, headers=UA, follow_redirects=True) as cl:
        listing = ieso.list_directory(cl.get(ieso.BASE_URL).raise_for_status().text)
        files = {y: n for y, n in ieso.latest_files_by_year(listing).items() if y >= FIRST_YEAR}
        print(f"{len(listing)} names in listing; newest per year: {files}")
        for year, name in files.items():
            target = OUT / name
            if target.exists():
                print(f"{year}: {name} already present, skip")
                continue
            for old in OUT.glob(f"PUB_Demand_{year}*.csv"):
                old.unlink()  # an older version of the same year
            body = cl.get(ieso.BASE_URL + name).raise_for_status().text
            df = ieso.parse_pub_demand(body)  # fail loudly on a bad file
            target.write_text(body, encoding="utf-8")
            span = f"{df['local_date'].min()}..{df['local_date'].max()}"
            print(f"{year}: {name} rows={len(df)} {span}")
            time.sleep(1)
    (OUT / "_pulled_at.txt").write_text(datetime.now(UTC).isoformat() + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
