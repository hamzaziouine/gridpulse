# Test fixtures

Small excerpts of public files used by the parser tests. Each covers 7 days or less; no bulk source
file is committed (IESO licence).

| File | Source | Content |
|---|---|---|
| `ieso_pub_demand_sample.csv` | IESO `PUB_Demand_2026_v295.csv` (via GridCast) | 3 header lines, 2026-10-17 HE1 to 2026-10-22 HE24, plus the provisional 2026-10-23 HE1 |
| `lake/ieso/PUB_Demand_2025_v396.csv` | IESO `PUB_Demand_2025_v396.csv` (cut by `scripts/make_test_fixtures.py`) | original header lines, 2025-04-28 HE1 to 2025-05-03 HE24 (6 days, 143 rows: 2025-05-01 HE1 is missing in the source) |
| `lake/openmeteo/2025-04.json`, `2025-05.json` | Open-Meteo Historical Forecast API, `gfs_seamless`, 5 cities | 2025-04-28 00:00Z to 2025-05-04 04:00Z, original JSON layout, split by month |
| `lake/openmeteo_prevruns/2025-04.json`, `2025-05.json` | Open-Meteo Previous Runs API, `gfs_seamless`, 5 cities, `_previous_day1` and `_previous_day2` of the 9 variables | same window as above, cut by `scripts/make_test_fixtures.py`; contains one `cloud_cover_previous_day2` value of 101 as delivered |
| `openmeteo_historical_sample.json` | Open-Meteo Historical Forecast API, `gfs_seamless` (via GridCast, Thunder Bay removed) | 5 cities, 2018-01-01 and 2018-01-02, 9 hourly variables |

**IESO notice.** © Independent Electricity System Operator (IESO), reproduced under the limited
licence in the IESO Terms of Use (https://www.ieso.ca/en/Terms-of-Use). Unmodified apart from being
cut to a few days.

**Open-Meteo notice.** Weather data by Open-Meteo.com (https://open-meteo.com/), CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/).
