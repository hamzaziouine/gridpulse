"""Build realtime/shape_profile.csv: mean Ontario demand by (month, EST hour), normalised to mean 1.

Uses the complete years 2019-2025 of the local IESO files. Only aggregate factors are written
(288 numbers), not IESO rows, so the file can be committed.

    uv run python scripts/build_shape_profile.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from gridpulse import ieso

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    frames = [
        ieso.parse_pub_demand(f.read_text(encoding="utf-8"))
        for f in sorted((ROOT / "data" / "raw" / "ieso").glob("PUB_Demand_20*.csv"))
        if not f.name.startswith("PUB_Demand_2026")
    ]
    df = pd.concat(frames, ignore_index=True)
    df["month"] = pd.to_datetime(df["local_date"]).dt.month
    df["hour_est"] = df["hour_ending"] - 1
    g = df.groupby(["month", "hour_est"])["ontario_demand_mw"].mean()
    out = (g / g.mean()).round(4).rename("factor").reset_index()
    out.to_csv(ROOT / "realtime" / "shape_profile.csv", index=False)
    print(f"{len(out)} rows, factor {out['factor'].min()}..{out['factor'].max()}")


if __name__ == "__main__":
    main()
