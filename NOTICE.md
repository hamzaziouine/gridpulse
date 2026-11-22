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

Weather forecasts (Historical Forecast API and Forecast API, model `gfs_seamless`) are from
Open-Meteo.

> Weather data by Open-Meteo.com (https://open-meteo.com/), licensed under the Creative Commons
> Attribution 4.0 International licence (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/).
> GridPulse stores and transforms the data (per-city hourly columns, derived weather features).

GridPulse uses the free, non-commercial Open-Meteo API.
