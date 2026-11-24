# Notices and data attribution

GridPulse's source code is licensed under the MIT License (see `LICENSE`). The data it reads and
the data it publishes come from the sources below, under their own terms. This file collects the
attribution each of them requires.

## Independent Electricity System Operator (IESO)

Hourly demand actuals (`PUB_Demand`) are from the IESO public reports site,
https://reports-public.ieso.ca/public/.

> © Independent Electricity System Operator (IESO). Information reproduced and used under the
> limited licence in the IESO Terms of Use, https://www.ieso.ca/en/Terms-of-Use. The IESO does not
> endorse GridPulse and is not responsible for any use made of its information.

Only short excerpts (test fixtures of 7 days or less) are
committed to this repository; bulk IESO files are not redistributed. GridPulse's forecasts and
any value derived from IESO data are GridPulse's own estimates, not IESO data.

## Open-Meteo

Weather forecasts (Historical Forecast API, Forecast API and Previous Runs API, model
`gfs_seamless`) are from Open-Meteo. The Previous Runs API (what the model forecast one and two
days before each hour) is the main training input of the forecast model.

> Weather data by Open-Meteo.com (https://open-meteo.com/), licensed under the Creative Commons
> Attribution 4.0 International licence (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/).
> GridPulse stores and transforms the data (per-city hourly columns, derived weather features).

GridPulse uses the free, non-commercial Open-Meteo API.

## Prior work: GridCast

Part of the code is ported from GridCast, an earlier personal project of Hamza ZIOUINE
(https://github.com/hamzaziouine/gridcast), an Ontario day-ahead demand forecast on a different
stack (no Azure, no Fabric). Ported, then adapted (database layers removed, 5 cities instead
of 6):

- `src/gridpulse/ieso.py` (IESO `PUB_Demand` parsing) and `src/gridpulse/openmeteo.py`
  (Open-Meteo parsing and request pacing);
- `src/gridpulse/timeutil.py` (fixed UTC-5 hour-ending time model);
- `src/gridpulse/calendar_features.py` and the city list in `src/gridpulse/config.py`;
- the LightGBM parameters in `src/gridpulse/forecast.py` and the degree-hour base temperature;
- tests `tests/unit/test_ieso.py`, `test_openmeteo.py`, `test_timeutil.py`,
  `test_calendar_baselines.py`, and the fixtures marked "via GridCast" in `tests/fixtures/README.md`.

New in GridPulse: every Azure and Fabric part (pipelines, Lakehouse medallion layers, Spark
notebooks, Key Vault, SQL source, policies, roles), the real-time path, pseudonymisation, and the
lead-matched training on Previous Runs weather.
