"""Weather stations and variables (proposal section 3, source S2), in one place.

GridCast used 6 cities; the GridPulse proposal names 5, so Thunder Bay is dropped and the
population weights are renormalised to sum to 1. Column names of the wide weather frame are
`<variable>_<city key>`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    location_id: int
    name: str
    key: str
    lat: float
    lon: float
    weight: float


_RAW: tuple[tuple[int, str, str, float, float, float], ...] = (
    (1, "Toronto", "toronto", 43.65, -79.38, 0.45),
    (2, "Ottawa", "ottawa", 45.42, -75.70, 0.15),
    (3, "London", "london", 42.98, -81.25, 0.10),
    (4, "Windsor", "windsor", 42.30, -83.02, 0.08),
    (5, "Sudbury", "sudbury", 46.49, -80.99, 0.07),
)
_TOTAL = sum(r[5] for r in _RAW)
CITIES: tuple[City, ...] = tuple(
    City(i, n, k, la, lo, round(w / _TOTAL, 4)) for i, n, k, la, lo, w in _RAW
)

VARIABLES: tuple[str, ...] = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "dew_point_2m",
    "wind_speed_10m",
    "cloud_cover",
    "shortwave_radiation",
    "precipitation",
    "snowfall",
)
WEATHER_COLUMNS: tuple[str, ...] = tuple(f"{v}_{c.key}" for c in CITIES for v in VARIABLES)

# Data window (DESIGN D13: train 2019-2024, validate 2025, test 2026)
FIRST_YEAR = 2019
