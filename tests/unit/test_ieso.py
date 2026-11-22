"""IESO PUB_Demand parsing (ported from GridCast tests/unit/test_ieso_demand.py)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from gridpulse import ieso as d
from gridpulse.ieso import EmptyFeedError

FIXTURE = Path(__file__).parents[1] / "fixtures" / "ieso_pub_demand_sample.csv"


def test_parse_fixture_skips_junk_lines() -> None:
    df = d.parse_pub_demand(FIXTURE.read_text())
    assert len(df) == 6 * 24 + 1
    first = df.iloc[0]
    assert first["local_date"] == date(2026, 10, 17)
    assert first["hour_ending"] == 1
    assert first["target_time"] == pd.Timestamp("2026-10-17 05:00", tz="UTC")
    last = df.iloc[-1]
    assert (last["market_demand_mw"], last["ontario_demand_mw"]) == (14664.0, 14021.0)
    assert last["target_time"] == pd.Timestamp("2026-10-23 05:00", tz="UTC")


def test_parse_tolerates_the_market_renewal_gap() -> None:
    body = (
        "\\Hourly Demand Report,,,\n\\Created at 2026-01-31 07:30:13,,,\n\\For 2025,,,\n"
        "Date,Hour,Market Demand,Ontario Demand\n"
        "2025-04-30,24,15320,13795\n2025-05-01,2,13153,12352\n"
    )
    df = d.parse_pub_demand(body)
    assert list(df["hour_ending"]) == [24, 2]
    assert df["target_time"].diff().iloc[1] == pd.Timedelta(hours=2)


def test_parse_raises_on_empty_feed() -> None:
    with pytest.raises(EmptyFeedError):
        d.parse_pub_demand("\\Hourly Demand Report,,,\nDate,Hour,Market Demand,Ontario Demand\n")
    with pytest.raises(EmptyFeedError):
        d.parse_pub_demand("<html>not found</html>")


def test_parse_rejects_unexpected_header() -> None:
    with pytest.raises(ValueError, match="header"):
        d.parse_pub_demand("Date,Hour,Ontario Demand,Market Demand\n2025-01-01,1,1,2\n")


def test_parse_rejects_duplicate_hours() -> None:
    body = "Date,Hour,Market Demand,Ontario Demand\n2025-01-01,1,1,2\n2025-01-01,1,1,2\n"
    with pytest.raises(ValueError, match="duplicate"):
        d.parse_pub_demand(body)


@pytest.mark.parametrize(
    ("name", "year", "version"),
    [
        ("PUB_Demand.csv", None, None),
        ("PUB_Demand_2025.csv", 2025, None),
        ("PUB_Demand_2026_v295.csv", 2026, "v295"),
        ("PUB_Demand_2015_v1.csv", 2015, "v001"),
    ],
)
def test_parse_file_name(name: str, year: int | None, version: str | None) -> None:
    assert d.parse_file_name(name) == (year, version)


def test_latest_files_by_year_prefers_highest_version() -> None:
    listing = [
        "PUB_Demand.csv",
        "PUB_Demand_2025.csv",
        "PUB_Demand_2025_v396.csv",
        "PUB_Demand_2026.csv",
        "PUB_Demand_2026_v293.csv",
        "PUB_Demand_2026_v295.csv",
        "PUB_Demand_2026_v294.csv",
        "PUB_Demand_2024.csv",
        "other.csv",
    ]
    assert d.latest_files_by_year(listing) == {
        2024: "PUB_Demand_2024.csv",
        2025: "PUB_Demand_2025_v396.csv",
        2026: "PUB_Demand_2026_v295.csv",
    }


def test_list_directory() -> None:
    html = '<a href="?C=N">x</a><a href="PUB_Demand_2025.csv">a</a><a href="../">up</a>'
    assert d.list_directory(html) == ["PUB_Demand_2025.csv"]


def test_created_at_is_est() -> None:
    assert d.parse_created_at(FIXTURE.read_text()) == datetime(2026, 10, 23, 12, 30, 9, tzinfo=UTC)
