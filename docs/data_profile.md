# Raw data profile

Generated 2026-11-06 21:29 UTC by `scripts/profile_data.py` from the local raw files (not committed: IESO licence).

## S1 IESO PUB_Demand (hourly, EST hour-ending)

| File | Rows | First date | Last date | Missing hours | Created at (UTC) |
|---|---|---|---|---|---|
| `PUB_Demand_2019_v395.csv` | 8,760 | 2019-01-01 | 2019-12-31 | 0  | 2020-01-31 12:30 |
| `PUB_Demand_2020_v396.csv` | 8,784 | 2020-01-01 | 2020-12-31 | 0  | 2021-01-31 12:30 |
| `PUB_Demand_2021_v396.csv` | 8,760 | 2021-01-01 | 2021-12-31 | 0  | 2022-01-31 12:30 |
| `PUB_Demand_2022_v397.csv` | 8,760 | 2022-01-01 | 2022-12-31 | 0  | 2023-01-31 12:30 |
| `PUB_Demand_2023_v395.csv` | 8,760 | 2023-01-01 | 2023-12-31 | 0  | 2024-01-31 12:30 |
| `PUB_Demand_2024_v395.csv` | 8,784 | 2024-01-01 | 2024-12-31 | 0  | 2025-01-31 12:30 |
| `PUB_Demand_2025_v396.csv` | 8,759 | 2025-01-01 | 2025-12-31 | 1 ['2025-05-01 05:00:00+00:00'] | 2026-01-31 12:30 |
| `PUB_Demand_2026_v307.csv` | 7,417 | 2026-01-01 | 2026-11-06 | 0  | 2026-11-06 12:30 |

- Total rows: **68,784**; duplicated target_time across files: 0.
- Ontario Demand MW: min 9,831, median 15,628, max 25,646; zero or negative values: 0.
- DST days (EST has no DST, so each must have exactly 24 rows): 2025-03-09: 24, 2025-11-02: 24, 2026-03-08: 24, 2026-11-01: 24.

## S2 Open-Meteo Historical Forecast (gfs_seamless, UTC, 5 cities)

- Files: 95 months (2019-01 .. 2026-11); hours: **68,784**; first 2019-01-01 00:00:00+00:00, last 2026-11-05 23:00:00+00:00.
- Duplicated hours: 0.
- Cities: Toronto (0.5294), Ottawa (0.1765), London (0.1176), Windsor (0.0941), Sudbury (0.0824).

| Variable | Null cells (all cities) | Null % |
|---|---|---|
| `temperature_2m` | 0 | 0.000 |
| `apparent_temperature` | 0 | 0.000 |
| `relative_humidity_2m` | 0 | 0.000 |
| `dew_point_2m` | 0 | 0.000 |
| `wind_speed_10m` | 0 | 0.000 |
| `cloud_cover` | 0 | 0.000 |
| `shortwave_radiation` | 0 | 0.000 |
| `precipitation` | 0 | 0.000 |
| `snowfall` | 0 | 0.000 |
