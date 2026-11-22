# GridPulse data dictionary

Every field of the four sources (S1 to S4) and of every bronze, silver and gold table, with type,
unit, meaning, sensitivity class and lineage.

Status (2026-11-22): this file describes the code in this repository (`src/gridpulse/`,
`fabric/nb_*.Notebook/`, `sql/`, `realtime/`). The tables were produced and checked by a local run
(`scripts/run_local.py`) only. Nothing has been built in Fabric yet. Row counts below come from that
local run or from `docs/data_profile.md`; in Fabric the history tables will be a little larger
because the data is refreshed daily.

Contents:

1. Conventions (time model, calendar, cities and weights, naming, types, sensitivity classes)
2. Sources: S1 IESO, S2 Open-Meteo, S3 Azure SQL, S4 simulator and the Eventhouse table
3. Bronze tables
4. Silver tables, including `silver_dq_results` and its 17 checks
5. Gold dimensions
6. Gold facts and analytical tables
7. Forecast tables (`gold_forecast`, `gold_forecast_eval`)
8. Lineage overview
9. Where personal data is and is not

---

## 1. Conventions

### 1.1 Time model

IESO publishes demand in market time: Eastern Standard Time, a fixed UTC-5 offset all year, with no
daylight saving. Each hour is labelled by its END (hour-ending, HE 1 to 24). GridPulse converts
every IESO hour to the UTC instant at the START of the interval and never uses the America/Toronto
zone for IESO data (DESIGN D9, `src/gridpulse/timeutil.py`, `medallion/common.py`).

| Term | Meaning |
|---|---|
| Hour-ending (HE) | IESO hour label. HE1 is 00:00 to 01:00 EST, HE24 is 23:00 to 24:00 EST of the same EST date. |
| EST | Fixed UTC-5, all year. |
| `target_time` | UTC timestamp of the start of the hour. HE h of EST date D maps to D 05:00 UTC + (h - 1) hours, so HE1 is D 05:00Z and HE24 is D+1 04:00Z. Computed with integer arithmetic, independent of the Spark session time zone. |
| `est_date` | The EST date that contains a UTC instant (UTC time minus 5 hours, date part). For demand rows it equals the IESO `Date`. |
| `date_key` | `est_date` as an integer `yyyymmdd` (for example 20260115). Joins the facts to `gold_dim_date`. Monthly tables carry the key of the first day of the month. |
| `hour_est` | HE minus 1: the EST clock hour at the start of the interval (0 to 23). |
| `valid_time` | Open-Meteo hour label, in UTC (the API is called with `timezone=GMT`). Weather is joined to demand on `valid_time = target_time`. |
| Civil time | Toronto wall clock (EST in winter, EDT in summer). Used in exactly one place: the calendar features of the forecast model (`calendar_features.py`), where holidays and weekdays are taken from the civil date of the target hour. Never used to store or join data. |
| Summer reading | While Toronto is on EDT (March to November) the wall clock is one hour ahead of EST. HE18 in July is 17:00 to 18:00 EST, which is 18:00 to 19:00 on a Toronto clock. Report pages show EST hours. |
| `run_date` | The date a notebook run is for (notebook parameter; default: today in UTC). |
| Stored timestamps | All timestamps are UTC instants (every notebook sets `spark.sql.session.timeZone = UTC`). Power BI shows them without a zone: read them as UTC. |

Daylight-saving days have exactly 24 IESO rows (checked in `docs/data_profile.md` for
2025-03-09, 2025-11-02, 2026-03-08 and 2026-11-01), which confirms the fixed-offset model.

### 1.2 Calendar rules (`gold_dim_date`, `src/gridpulse/dims.py`)

| Rule | Definition |
|---|---|
| Season | By month: Winter = December, January, February; Spring = March to May; Summer = June to August; Fall = September to November. December belongs to the Winter of its own calendar year row. `season_order`: Winter 1, Spring 2, Summer 3, Fall 4. |
| Holidays | `holidays.country_holidays("CA", subdiv="ON")` (public category) plus the Civic Holiday (first Monday of August). Ten named holidays with stable ids: New Year's Day 1, Family Day 2, Good Friday 3, Victoria Day 4, Canada Day 5, Civic Holiday 6, Labour Day 7, Thanksgiving Day 8, Christmas Day 9, Boxing Day 10. An observed day takes the id of the holiday it stands in for. Any other public holiday the package returns gets id 99: it counts as a holiday but has no `holiday_name`. Easter Monday and Remembrance Day are not used. |
| Business day | Monday to Friday and not a holiday. |
| On-peak hour | North American 5x16 convention: HE 8 to HE 23 (07:00 to 23:00 EST) on a business day. All other hours are off-peak. |

### 1.3 Weather cities and population weights (`src/gridpulse/config.py`)

Open-Meteo is queried at five Ontario cities. The raw population weights come from GridCast, which
also used Thunder Bay; GridPulse drops Thunder Bay and divides the remaining weights by their sum
(0.85), rounded to 4 decimals.

| city_id | City | city_key | Latitude | Longitude | Raw weight | Weight used |
|---|---|---|---|---|---|---|
| 1 | Toronto | toronto | 43.65 | -79.38 | 0.45 | 0.5294 |
| 2 | Ottawa | ottawa | 45.42 | -75.70 | 0.15 | 0.1765 |
| 3 | London | london | 42.98 | -81.25 | 0.10 | 0.1176 |
| 4 | Windsor | windsor | 42.30 | -83.02 | 0.08 | 0.0941 |
| 5 | Sudbury | sudbury | 46.49 | -80.99 | 0.07 | 0.0824 |

Ontario aggregate of a variable for one hour: `<variable>_w = sum(value_city * weight_city) /
sum(weight_city)` over the cities present that hour. Dividing by the weights present means one
missing city does not bias the value; the `cities_per_hour` quality check reports the gap.

Degree hours, base 18 °C: `hdd_w = max(0, 18 - temperature_2m_w)` and
`cdd_w = max(0, temperature_2m_w - 18)`, in °C for one hour. Daily tables average them over the
day (degree days); monthly tables sum the hourly values and divide by 24 (degree days of the month).

### 1.4 Naming

| Scope | Convention | Examples |
|---|---|---|
| Lakehouse tables | Layer prefix in one Lakehouse (`lh_gridpulse`, DESIGN D6) | `bronze_ieso_demand`, `silver_demand_hourly`, `gold_demand_daily` |
| Dimensions | `gold_dim_` | `gold_dim_date`, `gold_dim_city`, `gold_dim_site`, `gold_dim_meter` |
| Fabric items | Type prefix (DESIGN D22) | `ws_gridpulse` (workspace), `lh_gridpulse` (Lakehouse), `pl_daily_ingest` (pipeline), `nb_bronze`, `nb_silver`, `nb_gold`, `nb_forecast`, `nb_predict` (notebooks), `es_meters` (Eventstream), `eh_gridpulse` (Eventhouse), `rtd_gridpulse` (Real-Time Dashboard), `act_abnormal_demand` (Activator), `sm_gridpulse` (semantic model), `rpt_gridpulse` (report) |
| Azure resources | `<type>-hz2611-<name>` | `rg-hz2611-cdda`, `kv-hz2611-cdda`, `sqldb-hz2611-gridpulse` |
| Column suffixes | Unit or role | `_mw` megawatts, `_gwh` gigawatt-hours, `_kw` kilowatts, `_c` °C, `_pct` percent (0 to 100), `_kmh` km/h, `_wm2` W/m², `_mm` millimetres, `_cm` centimetres, `_w` population-weighted Ontario value (silver), `_key` join key, `is_` boolean |

### 1.5 Types

Types are the Spark SQL / Delta types the notebooks write: `int` (32-bit), `bigint` (64-bit),
`double`, `string`, `date`, `timestamp` (UTC instant), `boolean`, `decimal(p,s)`. Power BI maps
`int` and `bigint` to Whole number, `double` to Decimal number, `date` and `timestamp` to Date/time.
Counts (`count(*)`) are `bigint`. `gold_dim_date` is built in pandas and its integer columns are
cast to `int` in `nb_gold`, so its `date_key` has exactly the type of the facts' `date_key`.

### 1.6 Sensitivity classes

| Class | What it covers | Where it may live |
|---|---|---|
| Public | IESO demand (IESO licence: attribution, no bulk redistribution of raw files), Open-Meteo weather (CC BY 4.0), everything derived from them (aggregates, forecasts), calendar, city coordinates | Any layer, the report, the public repo (except raw IESO files, see `NOTICE.md`) |
| Internal | Meter readings, site and meter reference data, `customer_hash`, customer segment and city, operational metadata (data-quality results, run ids) | Azure SQL, bronze, silver, gold, Eventhouse; not in the public repo except the synthetic reference CSVs |
| Confidential PII | `customers.full_name`, `email`, `phone`, `street_address`, `postal_code` | Azure SQL `dbo.customers` and `bronze_customers` only |

The S3 data is fully synthetic (Faker, seed 2611, `example.com` emails, 555-01xx phone numbers), but
it is classified and handled as if it were real.

---

## 2. Sources

### 2.1 S1: IESO `PUB_Demand` CSV

Hourly Ontario demand from `https://reports-public.ieso.ca/public/Demand/`. One file per year,
`PUB_Demand_YYYY.csv`; each revision is also posted as `PUB_Demand_YYYY_vNNN.csv` and the unsuffixed
name is the latest version. The pipeline lands files in `Files/bronze/ieso/` of `lh_gridpulse`;
locally they are in `data/raw/ieso/` (git-ignored, IESO licence).

File layout: a few header lines that start with a backslash (title, `\Created at YYYY-MM-DD
HH:MM:SS` in EST, `\For YYYY`), then the column header `Date,Hour,Market Demand,Ontario Demand`,
then one row per hour. Volume (`docs/data_profile.md`): 8 yearly files, 2019-01-01 to 2026-11-06,
68,784 rows; Ontario Demand from 9,831 to 25,646 MW (median 15,628); one hour never published,
2025-05-01 HE1 (05:00 UTC), at the IESO Market Renewal go-live.

| Field | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `Date` | string `yyyy-MM-dd` | EST date | Market date of the hour | Public | `bronze_ieso_demand.local_date` |
| `Hour` | integer 1 to 24 | hour-ending | Hour label, HE1 = 00:00 to 01:00 EST | Public | `bronze_ieso_demand.hour_ending` |
| `Market Demand` | number | MW (hourly average) | Total energy supplied through the IESO-administered market, which includes exports | Public | `bronze_ieso_demand.market_demand_mw` |
| `Ontario Demand` | number | MW (hourly average) | Demand inside Ontario (market demand without exports). The quantity GridPulse analyses and forecasts | Public | `bronze_ieso_demand.ontario_demand_mw` |
| `\Created at` header line | text | EST wall time | When IESO generated the file; used to pick the newest version of an hour | Public | `bronze_ieso_demand.file_created_at` (converted to UTC) |
| File name | text | | Year and optional version `_vNNN` | Public | `source_file`, `source_year`, `file_version` |

### 2.2 S2: Open-Meteo weather JSON

Two endpoints, same request shape (`src/gridpulse/openmeteo.py`):

- Historical Forecast API (`historical-forecast-api.open-meteo.com/v1/forecast`): the forecasts as
  they were issued at the time, so the model never trains on weather it would not have had
  (DESIGN D3). One file per calendar month, `Files/bronze/openmeteo/YYYY-MM.json`. Profile: 95
  months (2019-01 to 2026-11), 68,784 hours, no null cells.
- Forecast API: the coming days, one file per run date, `Files/bronze/openmeteo_forecast/YYYY-MM-DD.json`.
  Used by the daily scoring notebook for the live forecast.

Request parameters: `latitude` and `longitude` (the five cities of section 1.3, in that order),
`hourly` (the nine variables below), `models=gfs_seamless` (pinned, no silent model switch),
`timezone=GMT`, `start_date`, `end_date`.

Response: a JSON array with one object per city. Bronze reads `latitude`, `longitude`,
`hourly.time` and the nine `hourly.<variable>` arrays; the other keys (`elevation`, `timezone`,
`utc_offset_seconds`, `hourly_units`, ...) are not read.

| Field | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `latitude` | number | degrees | Latitude of the model grid point Open-Meteo snapped to (close to, not equal to, the requested city) | Public | `bronze_openmeteo_*.grid_latitude`; matched to a city within 0.2 degrees to set `city_key` |
| `longitude` | number | degrees | Longitude of the grid point | Public | `bronze_openmeteo_*.grid_longitude` |
| `hourly.time` | array of string `YYYY-MM-DDTHH:MM` | UTC | Hour label of each value | Public | `valid_time` |
| `hourly.temperature_2m` | array of number | °C | Air temperature 2 m above ground | Public | `temperature_2m` |
| `hourly.apparent_temperature` | array of number | °C | Perceived temperature (wind chill and humidity included) | Public | `apparent_temperature` |
| `hourly.relative_humidity_2m` | array of number | % | Relative humidity at 2 m | Public | `relative_humidity_2m` |
| `hourly.dew_point_2m` | array of number | °C | Dew point at 2 m | Public | `dew_point_2m` |
| `hourly.wind_speed_10m` | array of number | km/h | Wind speed 10 m above ground | Public | `wind_speed_10m` |
| `hourly.cloud_cover` | array of number | % | Total cloud cover | Public | `cloud_cover` |
| `hourly.shortwave_radiation` | array of number | W/m² | Global horizontal irradiance; Open-Meteo documents it as the mean over the preceding hour | Public | `shortwave_radiation` |
| `hourly.precipitation` | array of number | mm | Total precipitation (rain, showers, snow water equivalent); sum over the preceding hour per the Open-Meteo docs | Public | `precipitation` |
| `hourly.snowfall` | array of number | cm | Snowfall amount over the preceding hour | Public | `snowfall` |

### 2.3 S3: Azure SQL Database (`sqldb-hz2611-gridpulse`)

Operational store for reference data, schema in `sql/001_schema.sql`, synthetic seed in
`sql/002_seed.sql` and `data/reference/*.csv` (generated by `scripts/gen_reference_data.py`): 10
sites, 50 customers, 50 meters (meter n belongs to customer n). The pipeline copies the three
tables to `bronze_sites`, `bronze_customers` and `bronze_meters`. The schema adds SQL sensitivity
classifications to the PII columns (visible in the portal and to Purview).

`dbo.sites`

| Column | SQL type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `site_id` | INT, primary key | | Site identifier | Internal | `bronze_sites` -> `silver_sites` -> `gold_dim_site` |
| `site_code` | VARCHAR(16), unique | | Code `SITE-<CITY>-NN`, for example `SITE-TOR-01` | Internal | same |
| `site_name` | NVARCHAR(100) | | Fictional site name at a real city location | Internal | same |
| `city` | NVARCHAR(50) | | City of the site (Toronto, Ottawa, Mississauga, Hamilton, London, Kitchener, Windsor, Sudbury, Kingston) | Internal | same |
| `latitude` | DECIMAL(8,5), 41 to 57 | degrees | Site latitude | Internal | same (double from silver on) |
| `longitude` | DECIMAL(8,5), -96 to -74 | degrees | Site longitude | Internal | same |
| `capacity_kw` | INT, > 0 | kW | Connection capacity of the site | Internal | same |

`dbo.customers`

| Column | SQL type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `customer_id` | INT, primary key | | Customer identifier; a direct key to the PII row | Internal | `bronze_customers`; replaced by `customer_hash` in silver and never copied past bronze |
| `full_name` | NVARCHAR(100) | | Customer name. Classified `Confidential - GDPR`, Name, rank HIGH | Confidential PII | `bronze_customers` only |
| `email` | NVARCHAR(120), unique | | Email address (`example.com`). `Confidential - GDPR`, Contact Info, HIGH | Confidential PII | `bronze_customers` only; checked unique by `email_unique` |
| `phone` | VARCHAR(20) | | Phone number (`+1-416-555-01xx`). `Confidential - GDPR`, Contact Info, HIGH | Confidential PII | `bronze_customers` only |
| `street_address` | NVARCHAR(150) | | Street address. `Confidential - GDPR`, Contact Info, HIGH | Confidential PII | `bronze_customers` only |
| `city` | NVARCHAR(50) | | City of the customer (the city of the site its meter is at) | Internal | `silver_customers_pseudo.city` |
| `postal_code` | VARCHAR(7) | | Canadian postal code `A1A 1A1`, a quasi-identifier. `Confidential`, Contact Info, MEDIUM | Confidential PII | `bronze_customers` only |
| `segment` | VARCHAR(20) | | `residential`, `small_business`, `commercial` or `industrial` | Internal | `silver_customers_pseudo.segment` -> `gold_dim_meter.segment` |
| `created_at` | DATE | | Date the customer account was created | Internal | `silver_customers_pseudo.customer_since` |

`dbo.meters`

| Column | SQL type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `meter_id` | VARCHAR(12), primary key | | Meter identifier `MTR-NNNN` | Internal | `bronze_meters` -> `silver_meters` -> `gold_dim_meter`; also the `meter_id` of every S4 event |
| `site_id` | INT, FK to `sites` | | Site the meter is installed at | Internal | same; checked by `fk_site` |
| `customer_id` | INT, FK to `customers` | | Customer who owns the meter | Internal | `bronze_meters`; replaced by `customer_hash` in silver; checked by `fk_customer` |
| `install_date` | DATE | | Installation date | Internal | `silver_meters`, `gold_dim_meter` |
| `tariff` | VARCHAR(10) | | Ontario price plan: `TOU`, `ULO` or `TIERED` | Internal | same |
| `rated_kw` | INT, > 0 | kW | Rated power of the meter (10, 25, 50, 100 or 250 in the seed) | Internal | same; scales the S4 readings |
| `status` | VARCHAR(12) | | `active`, `maintenance` or `retired` (every 17th seeded meter is in maintenance) | Internal | same; checked by `status_domain` |

### 2.4 S4: smart-meter simulator events and the Eventhouse table

`realtime/simulator.py` sends one JSON event per meter reading to the Eventstream `es_meters`
(custom endpoint, Event Hubs protocol; connection string read from Key Vault), which writes to the
table `meter_readings` of the Eventhouse `eh_gridpulse`. It cycles through the 50 meters of
`data/reference/meters.csv` at `--rate` events per second (default 10, so each meter reports every
5 seconds). Not built in Fabric yet; `--dry-run` prints the events locally.

Value model: `kw = max(0, 0.45 x rated_kw x shape(month, EST hour) x N(1, 0.05) x anomaly factor)`,
where `shape` is the mean IESO demand by EST hour and month for 2019 to 2025, normalised to mean 1
(`realtime/shape_profile.csv`: columns `month`, `hour_est`, `factor`, 288 rows). Meters in
`maintenance` always send 0 kW. Voltage is `N(240, 2)` V, 6 V lower while an anomaly is active. An
anomaly multiplies one site's readings by a factor for a number of seconds (`--anomaly SITE_ID
FACTOR SECONDS`, or a `realtime/anomaly.json` file dropped while the simulator runs).

Event JSON fields:

| Field | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `ts` | string, ISO 8601 UTC with milliseconds and `Z` | UTC | Time the reading was produced | Internal | `meter_readings.ts` |
| `meter_id` | string | | Meter, `MTR-NNNN` (links to a customer through S3) | Internal | `meter_readings.meter_id` |
| `site_id` | integer | | Site of the meter | Internal | `meter_readings.site_id` |
| `kw` | number, 3 decimals | kW | Instantaneous load of the meter | Internal | `meter_readings.kw` |
| `voltage` | number, 2 decimals | V | Supply voltage, nominal 240 V | Internal | `meter_readings.voltage` |
| `status` | string | | Meter status copied from the reference data | Internal | `meter_readings.status` |

Eventhouse table `meter_readings` (`realtime/kql/00_tables.kql`; JSON ingestion mapping
`meter_readings_json`; retention 7 days, soft delete):

| Column | KQL type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `ts` | datetime | UTC | Reading time | Internal | event `$.ts` |
| `meter_id` | string | | Meter identifier | Internal | event `$.meter_id` |
| `site_id` | int | | Site identifier | Internal | event `$.site_id` |
| `kw` | real | kW | Meter load | Internal | event `$.kw` |
| `voltage` | real | V | Supply voltage | Internal | event `$.voltage` |
| `status` | string | | Meter status | Internal | event `$.status` |

Columns returned by the KQL queries (computed at query time, not stored):

| Query | Column | Type | Unit | Description |
|---|---|---|---|---|
| Q1 `q1_5min_window.kql` | `site_id`, `window` | int, datetime | | Site and start of the 5-minute tumbling window (last hour) |
| Q1 | `site_kw` | real | kW | Sum over the site's meters of each meter's mean kW in the window |
| Q1 | `site_kwh` | real | kWh | `site_kw x 5/60`, energy of the window |
| Q1 | `meters` | long | | Distinct meters that reported in the window |
| Q2 `q2_anomaly.kql` | `minute` | datetime | | Last complete minute |
| Q2 | `site_kw` | real | kW | Site load summed over that minute's readings |
| Q2 | `mean_kw`, `threshold_kw` | real | kW | Mean of the site's per-minute load over the trailing hour, and mean + 3 standard deviations |
| Q2 | `z` | real | | `(site_kw - mean_kw) / sd`. A row appears only when `site_kw > threshold_kw` and the baseline has at least 10 minutes |
| Q3 `q3_top5.kql` | `site_id`, `site_kw` | int, real | kW | Top 5 sites by summed mean meter load over the last 15 minutes |

Q2 feeds the Real-Time Dashboard `rtd_gridpulse` and the Activator `act_abnormal_demand`
(business question 4).

---

## 3. Bronze tables (`nb_bronze`, `src/gridpulse/medallion/bronze.py`)

Typed copies of the landed files with lineage columns; no business rules. A daily run replaces only
the rows of the files it re-ingested (Delta `replaceWhere` on `source_file`); a backfill
(`full_refresh = True`) rewrites the table. Reading is `FAILFAST`: a malformed row stops the run.

### `bronze_ieso_demand`

One row per CSV data row. When two versions of a year are landed, the same hour appears once per
file; silver keeps the newest.

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `local_date` | date | EST date | IESO `Date` | Public | S1 `Date` |
| `hour_ending` | int | HE 1 to 24 | IESO `Hour` | Public | S1 `Hour` |
| `market_demand_mw` | double | MW | IESO `Market Demand` | Public | S1 `Market Demand` |
| `ontario_demand_mw` | double | MW | IESO `Ontario Demand` | Public | S1 `Ontario Demand` |
| `source_file` | string | | Landed file name, for example `PUB_Demand_2025_v396.csv` | Public | file metadata |
| `source_year` | int | | Year in the file name (null for a name without a year) | Public | file name |
| `file_version` | string | | `vNNN` from the file name, null for the unsuffixed latest name | Public | file name |
| `file_created_at` | timestamp | UTC | `\Created at` header time (EST) converted to UTC | Public | S1 header line |
| `ingested_at` | timestamp | UTC | When `nb_bronze` read the file | Internal | notebook |
| `run_date` | date | | Run date of `nb_bronze` | Internal | notebook parameter |

### `bronze_openmeteo_hourly` and `bronze_openmeteo_forecast`

Same columns. `bronze_openmeteo_hourly` comes from the Historical Forecast API files,
`bronze_openmeteo_forecast` from the Forecast API files. One row per city and hour (the arrays of
each city object are exploded into rows).

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `valid_time` | timestamp | UTC | Hour label | Public | S2 `hourly.time` |
| `city_key` | string | | City matched from the grid coordinates (within 0.2 degrees); null when no city matches, which fails the `unmatched_location` check | Public | `grid_latitude`, `grid_longitude` vs `config.CITIES` |
| `temperature_2m` | double | °C | See S2 | Public | S2 |
| `apparent_temperature` | double | °C | See S2 | Public | S2 |
| `relative_humidity_2m` | double | % | See S2 | Public | S2 |
| `dew_point_2m` | double | °C | See S2 | Public | S2 |
| `wind_speed_10m` | double | km/h | See S2 | Public | S2 |
| `cloud_cover` | double | % | See S2 | Public | S2 |
| `shortwave_radiation` | double | W/m² | See S2 | Public | S2 |
| `precipitation` | double | mm | See S2 | Public | S2 |
| `snowfall` | double | cm | See S2 | Public | S2 |
| `grid_latitude` | double | degrees | Grid point latitude returned by Open-Meteo | Public | S2 `latitude` |
| `grid_longitude` | double | degrees | Grid point longitude | Public | S2 `longitude` |
| `source_file` | string | | Landed file name (`YYYY-MM.json` or `YYYY-MM-DD.json`) | Public | file metadata |
| `ingested_at` | timestamp | UTC | When `nb_bronze` read the file | Internal | notebook |
| `run_date` | date | | Run date of `nb_bronze` | Internal | notebook parameter |

### `bronze_sites`, `bronze_customers`, `bronze_meters`

Copies of the three Azure SQL tables written by the pipeline's Copy activity (locally:
`scripts/run_local.py` loads `data/reference/*.csv` with the same types, `src/gridpulse/reference.py`).
Columns and meanings are those of section 2.3, with these types: `int` for `site_id`,
`capacity_kw`, `customer_id`, `rated_kw`; `decimal(8,5)` for `latitude`, `longitude`; `date` for
`created_at`, `install_date`; `string` for the rest.

| Table | Rows (local) | Sensitivity |
|---|---|---|
| `bronze_sites` | 10 | Internal |
| `bronze_customers` | 50 | Confidential PII (`full_name`, `email`, `phone`, `street_address`, `postal_code`); the only Lakehouse table holding PII |
| `bronze_meters` | 50 | Internal (`customer_id` still present) |

---

## 4. Silver tables (`nb_silver`, `src/gridpulse/medallion/silver.py`)

Validated, typed, deduplicated and joined. Silver is recomputed from bronze on each run and is only
overwritten when no data-quality check FAILS (otherwise the last good silver stays and the
pipeline alert fires).

### `silver_demand_hourly`

One row per UTC hour. Valid bronze rows only (non-null date and demands, HE 1 to 24). When several
files hold the same hour, the file with the newest `file_created_at` wins (then the higher file
name).

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `target_time` | timestamp | UTC | Start of the hour (section 1.1) | Public | `local_date`, `hour_ending` |
| `est_date` | date | EST date | IESO date of the hour | Public | `bronze_ieso_demand.local_date` |
| `hour_ending` | int | HE 1 to 24 | IESO hour | Public | bronze |
| `ontario_demand_mw` | double | MW | Ontario demand | Public | bronze |
| `market_demand_mw` | double | MW | Market demand (includes exports) | Public | bronze |
| `source_file` | string | | File the kept row came from | Public | bronze |
| `file_created_at` | timestamp | UTC | Creation time of that file | Public | bronze |

### `silver_weather_city_hourly`

One row per (`valid_time`, `city_key`). Rows without a city are dropped; for duplicates the newest
ingestion wins.

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `valid_time` | timestamp | UTC | Hour | Public | `bronze_openmeteo_hourly` |
| `city_key` | string | | City (section 1.3) | Public | bronze |
| `temperature_2m`, `apparent_temperature`, `dew_point_2m` | double | °C | City values, see S2 | Public | bronze |
| `relative_humidity_2m`, `cloud_cover` | double | % | City values | Public | bronze |
| `wind_speed_10m` | double | km/h | City value | Public | bronze |
| `shortwave_radiation` | double | W/m² | City value | Public | bronze |
| `precipitation` | double | mm | City value | Public | bronze |
| `snowfall` | double | cm | City value | Public | bronze |
| `source_file` | string | | File the kept row came from | Public | bronze |

### `silver_weather_ontario_hourly`

One row per hour: population-weighted Ontario weather.

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `valid_time` | timestamp | UTC | Hour | Public | `silver_weather_city_hourly` |
| `temperature_2m_w` | double | °C | Weighted temperature (section 1.3) | Public | city rows x `population_weight` |
| `apparent_temperature_w` | double | °C | Weighted apparent temperature | Public | same |
| `relative_humidity_2m_w` | double | % | Weighted humidity | Public | same |
| `dew_point_2m_w` | double | °C | Weighted dew point | Public | same |
| `wind_speed_10m_w` | double | km/h | Weighted wind speed | Public | same |
| `cloud_cover_w` | double | % | Weighted cloud cover | Public | same |
| `shortwave_radiation_w` | double | W/m² | Weighted irradiance | Public | same |
| `precipitation_w` | double | mm | Weighted precipitation | Public | same |
| `snowfall_w` | double | cm | Weighted snowfall | Public | same |
| `temperature_2m_mean` | double | °C | Unweighted mean temperature of the cities present | Public | city rows |
| `n_cities` | bigint | | Cities present that hour (5 expected) | Public | city rows |
| `temperature_2m_toronto` ... `temperature_2m_sudbury` | double | °C | Temperature of each of the five cities (five columns) | Public | city rows |
| `hdd_w` | double | °C (1 hour) | Heating degree hour, `max(0, 18 - temperature_2m_w)` | Public | `temperature_2m_w` |
| `cdd_w` | double | °C (1 hour) | Cooling degree hour, `max(0, temperature_2m_w - 18)` | Public | `temperature_2m_w` |

### `silver_demand_weather_hourly`

One row per demand hour, left-joined to the Ontario weather of the same UTC hour (a demand hour is
kept even when its weather has not arrived; the `weather_coverage` check counts those). The input of
every gold demand table.

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `target_time`, `est_date`, `hour_ending`, `ontario_demand_mw`, `market_demand_mw` | as in `silver_demand_hourly` | | Demand side | Public | `silver_demand_hourly` |
| `temperature_2m_w` ... `snowfall_w` (nine columns) | double | as in `silver_weather_ontario_hourly` | Weighted weather of the same hour, null when missing | Public | `silver_weather_ontario_hourly` on `valid_time = target_time` |
| `temperature_2m_mean` | double | °C | Unweighted city mean | Public | same |
| `hdd_w`, `cdd_w` | double | °C (1 hour) | Degree hours | Public | same |
| `temperature_2m_toronto` ... `temperature_2m_sudbury` | double | °C | City temperatures | Public | same |

### `silver_weather_forecast_ontario`

Built only when `bronze_openmeteo_forecast` exists (not in the local run). Same aggregation as
`silver_weather_ontario_hourly`, applied to Forecast API files, keeping the newest issue for each
hour. Read by the daily scoring notebook (`nb_predict`).

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `valid_time` | timestamp | UTC | Forecast hour | Public | `bronze_openmeteo_forecast` |
| `issued_on` | date | | Run date in the file name `YYYY-MM-DD.json` (the issue day of the forecast) | Public | `source_file` |
| `temperature_2m_w` ... `snowfall_w`, `temperature_2m_mean`, `n_cities`, the five city temperatures, `hdd_w`, `cdd_w` | as in `silver_weather_ontario_hourly` | | Forecast values | Public | same rules |

### `silver_sites`

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `site_id` | int | | Site identifier | Internal | `bronze_sites` |
| `site_code` | string | | Trimmed code | Internal | bronze |
| `site_name` | string | | Trimmed name | Internal | bronze |
| `city` | string | | Trimmed city | Internal | bronze |
| `latitude`, `longitude` | double | degrees | Location | Internal | bronze (decimal cast to double) |
| `capacity_kw` | int | kW | Site capacity | Internal | bronze |

### `silver_meters`

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `meter_id` | string | | Trimmed meter id | Internal | `bronze_meters` |
| `site_id` | int | | Site | Internal | bronze |
| `customer_hash` | string (64 hex characters) | | `sha2(salt + ":" + customer_id, 256)`; salt read from Key Vault `kv-hz2611-cdda`, secret `customer-hash-salt`. Stable join key, not reversible without the salt | Internal | `bronze_meters.customer_id` |
| `install_date` | date | | Installation date | Internal | bronze |
| `tariff` | string | | Upper-cased tariff | Internal | bronze |
| `rated_kw` | int | kW | Rated power | Internal | bronze |
| `status` | string | | Lower-cased status | Internal | bronze |

### `silver_customers_pseudo`

Customers without PII: the five PII columns and the raw `customer_id` never reach silver
(DESIGN D18; enforced by the `pii_absent` check).

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `customer_hash` | string | | Same salted hash as in `silver_meters` | Internal | `bronze_customers.customer_id` |
| `city` | string | | Customer city | Internal | bronze |
| `segment` | string | | Lower-cased segment | Internal | bronze |
| `customer_since` | date | | Account creation date | Internal | `bronze_customers.created_at` |

### `silver_dq_results`

One row per check per run (17 checks). Written before the quality gate decides, so a failed run
leaves its evidence. A rerun for the same `run_date` replaces that date's rows.

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `run_id` | string | | UUID of the `nb_silver` run | Internal | notebook |
| `run_date` | date | | Run date | Internal | notebook parameter |
| `checked_at` | timestamp | UTC | When the checks ran | Internal | notebook |
| `layer` | string | | `silver` | Internal | notebook |
| `table_name` | string | | Table the check is about | Internal | `quality.py` |
| `check_name` | string | | Check identifier (list below) | Internal | `quality.py` |
| `status` | string | | `PASS`, `WARN` (known or expected condition) or `FAIL` (stops the run) | Internal | `quality.py` |
| `observed` | double | count or days | Measured value | Internal | `quality.py` |
| `expected` | string | | Expected value, in words | Internal | `quality.py` |
| `details` | string | | Extra context (first offending hours, percentages, column names) | Internal | `quality.py` |

The 17 checks (`src/gridpulse/medallion/quality.py`):

| # | table_name | check_name | What `observed` counts | Status rule |
|---|---|---|---|---|
| 1 | `bronze_ieso_demand` | `invalid_rows` | Rows with null date or demand, or HE outside 1 to 24 | PASS if 0, else FAIL |
| 2 | `silver_demand_hourly` | `revisions_deduplicated` | Valid bronze rows minus unique hours (rows replaced by a newer file) | Always PASS (information) |
| 3 | `silver_demand_hourly` | `unique_target_time` | Duplicate `target_time` values | PASS if 0, else FAIL |
| 4 | `silver_demand_hourly` | `demand_range` | Hours with `ontario_demand_mw` outside 5,000 to 30,000 MW | PASS if 0, else FAIL |
| 5 | `silver_demand_hourly` | `hourly_gaps` | Missing hours on the continuous hourly grid | PASS if none; WARN if all missing hours are known (2025-05-01 05:00Z); else FAIL |
| 6 | `silver_demand_hourly` | `hours_per_day_24` | EST days, except the newest, without 24 hours | PASS if none; WARN if only the known gap day; else FAIL |
| 7 | `silver_demand_hourly` | `freshness_days` | Days between `run_date` and the newest EST date | PASS if 2 or less; WARN if 4 or less; else FAIL |
| 8 | `bronze_openmeteo_hourly` | `unmatched_location` | Rows whose grid point matched no city | PASS if 0, else FAIL |
| 9 | `silver_weather_city_hourly` | `cities_per_hour` | Hours without exactly 5 cities | PASS if 0, else FAIL |
| 10 | `silver_weather_city_hourly` | `null_cells` | Null weather values (all variables and cities) | PASS if 0; WARN if 1 % of cells or less; else FAIL |
| 11 | `silver_weather_city_hourly` | `physical_ranges` | Values outside the ranges below | PASS if 0, else FAIL |
| 12 | `silver_demand_weather_hourly` | `weather_coverage` | Demand hours without weather | PASS if 0; WARN if all of them are in the newest 72 hours; else FAIL |
| 13 | `silver_meters` | `fk_site` | Meters whose `site_id` is not in sites | PASS if 0, else FAIL |
| 14 | `silver_meters` | `fk_customer` | Meters whose `customer_id` is not in customers | PASS if 0, else FAIL |
| 15 | `silver_meters` | `status_domain` | Statuses outside active, maintenance, retired | PASS if 0, else FAIL |
| 16 | `bronze_customers` | `email_unique` | Email values used more than once | PASS if 0, else FAIL |
| 17 | `silver_customers_pseudo` | `pii_absent` | PII columns found in `silver_customers_pseudo` or `silver_meters` | PASS if 0, else FAIL |

Physical ranges for check 11: `temperature_2m` -50 to 50 °C, `apparent_temperature` -60 to 60 °C,
`relative_humidity_2m` 0 to 100 %, `dew_point_2m` -60 to 40 °C, `wind_speed_10m` 0 to 200 km/h,
`cloud_cover` 0 to 100 %, `shortwave_radiation` 0 to 1,400 W/m², `precipitation` 0 to 200 mm,
`snowfall` 0 to 100 cm.

---

## 5. Gold dimensions (`nb_gold`)

Gold is recomputed from silver on every run (full overwrite) and read by the Direct Lake semantic
model `sm_gridpulse`. Gold holds no PII.

### `gold_dim_date`

One row per EST date, from the first demand date to the last demand date plus 7 days (room for the
live forecast). Built in pandas (`src/gridpulse/dims.py`), integers cast to `int` in `nb_gold`. Local run:
2,874 rows. Sensitivity: Public.

| Column | Type | Unit | Description | Lineage |
|---|---|---|---|---|
| `date_key` | int | | `yyyymmdd`, primary key of the dimension | `est_date` |
| `est_date` | date | | The date (mark-as-date-table column) | date range |
| `year` | int | | Calendar year | `est_date` |
| `quarter` | int | | 1 to 4 | `est_date` |
| `month` | int | | 1 to 12 | `est_date` |
| `month_name` | string | | `January` ... (sort by `month`) | `est_date` |
| `month_short` | string | | `Jan` ... (sort by `month`) | `est_date` |
| `month_start` | date | | First day of the month | `est_date` |
| `year_month` | string | | `YYYY-MM`, sorts correctly as text | `est_date` |
| `day_of_month` | int | | 1 to 31 | `est_date` |
| `day_of_week` | int | | 0 = Monday ... 6 = Sunday | `est_date` |
| `day_name` | string | | `Monday` ... (sort by `day_of_week`) | `est_date` |
| `day_short` | string | | `Mon` ... (sort by `day_of_week`) | `est_date` |
| `is_weekend` | boolean | | Saturday or Sunday | `day_of_week` |
| `is_holiday` | boolean | | Ontario holiday (section 1.2), observed days included | `holidays` package |
| `holiday_name` | string | | Name of one of the ten named holidays; null otherwise | `holidays` package |
| `is_business_day` | boolean | | Weekday and not a holiday | rule 1.2 |
| `season` | string | | Winter, Spring, Summer, Fall (sort by `season_order`) | `month` |
| `season_order` | int | | 1 to 4 | `season` |

### `gold_dim_city`

The five weather cities (`config.CITIES`). 5 rows. Sensitivity: Public.

| Column | Type | Unit | Description | Lineage |
|---|---|---|---|---|
| `city_id` | int | | 1 to 5 | `config.py` |
| `city_key` | string | | `toronto`, `ottawa`, `london`, `windsor`, `sudbury`; key for `gold_city_weather_daily` | `config.py` |
| `city_name` | string | | Display name | `config.py` |
| `latitude`, `longitude` | double | degrees | Requested coordinates | `config.py` |
| `population_weight` | double | fraction | Renormalised weight (section 1.3), sums to 1 | `config.py` |

### `gold_dim_site`

10 rows. Sensitivity: Internal.

| Column | Type | Unit | Description | Lineage |
|---|---|---|---|---|
| `site_id` | int | | Key | `silver_sites` |
| `site_code`, `site_name`, `city` | string | | As in silver | `silver_sites` |
| `latitude`, `longitude` | double | degrees | Location | `silver_sites` |
| `capacity_kw` | int | kW | Site capacity | `silver_sites` |
| `meter_count` | bigint | | Meters at the site (0 if none) | count of `silver_meters` |
| `rated_kw_total` | bigint | kW | Sum of the meters' `rated_kw` | `silver_meters` |
| `active_meters` | bigint | | Meters with status `active` | `silver_meters` |

### `gold_dim_meter`

50 rows. Sensitivity: Internal (pseudonymised customer key, no PII).

| Column | Type | Unit | Description | Lineage |
|---|---|---|---|---|
| `site_id` | int | | Site (relationship to `gold_dim_site`) | `silver_meters` |
| `customer_hash` | string | | Pseudonymous customer key | `silver_meters` |
| `meter_id` | string | | Meter key; same id as in `meter_readings` | `silver_meters` |
| `install_date` | date | | Installation date | `silver_meters` |
| `tariff` | string | | `TOU`, `ULO`, `TIERED` | `silver_meters` |
| `rated_kw` | int | kW | Rated power | `silver_meters` |
| `status` | string | | `active`, `maintenance`, `retired` | `silver_meters` |
| `segment` | string | | Customer segment | `silver_customers_pseudo` on `customer_hash` |
| `customer_since` | date | | Customer creation date | `silver_customers_pseudo` |
| `site_code` | string | | Denormalised from the site | `silver_sites` |
| `site_city` | string | | City of the site | `silver_sites.city` |

---

## 6. Gold facts and analytical tables

All Public (derived from IESO and Open-Meteo).

### `gold_demand_hourly`

One row per UTC hour. Local run: 68,784 rows.

| Column | Type | Unit | Description | Lineage |
|---|---|---|---|---|
| `target_time` | timestamp | UTC | Start of the hour | `silver_demand_weather_hourly` |
| `est_date` | date | | EST date | silver |
| `date_key` | int | | Key to `gold_dim_date` | `est_date` |
| `hour_ending` | int | HE 1 to 24 | IESO hour | silver |
| `hour_est` | int | 0 to 23 | EST clock hour at the start (`hour_ending - 1`) | `hour_ending` |
| `season` | string | | Season of `est_date` (copied from `gold_dim_date`) | `gold_dim_date` |
| `is_business_day` | boolean | | Business day (false if the date is missing from the dimension) | `gold_dim_date` |
| `is_onpeak` | boolean | | Business day and HE 8 to 23 | rule 1.2 |
| `ontario_demand_mw` | double | MW | Ontario demand; one row = 1 hour, so MW equals MWh for that hour | silver |
| `market_demand_mw` | double | MW | Market demand (includes exports) | silver |
| `temperature_c` | double | °C | Weighted Ontario temperature, null when weather is missing | `temperature_2m_w` |
| `apparent_temperature_c` | double | °C | Weighted apparent temperature | `apparent_temperature_w` |
| `relative_humidity_pct` | double | % | Weighted humidity | `relative_humidity_2m_w` |
| `cloud_cover_pct` | double | % | Weighted cloud cover | `cloud_cover_w` |
| `solar_radiation_wm2` | double | W/m² | Weighted irradiance | `shortwave_radiation_w` |
| `wind_speed_kmh` | double | km/h | Weighted wind speed | `wind_speed_10m_w` |
| `heating_degree_c` | double | °C (1 hour) | Heating degree hour | `hdd_w` |
| `cooling_degree_c` | double | °C (1 hour) | Cooling degree hour | `cdd_w` |

Dew point, precipitation, snowfall and the city temperatures stay in silver.

### `gold_demand_daily`

One row per EST date. Local run: 2,867 rows.

| Column | Type | Unit | Description | Lineage |
|---|---|---|---|---|
| `est_date` | date | | EST date | `gold_demand_hourly` |
| `date_key` | int | | Key to `gold_dim_date` | hourly |
| `hours` | bigint | | Hours present (24 for a complete day) | count |
| `energy_gwh` | double | GWh | Sum of hourly MW / 1000 | hourly |
| `onpeak_energy_gwh` | double | GWh | Energy of on-peak hours; null on days with no on-peak hour (weekends, holidays) | hourly |
| `peak_mw` | double | MW | Highest hour of the day | hourly |
| `peak_hour_ending` | int | HE | Hour-ending of that peak | hourly (`max_by`) |
| `min_mw` | double | MW | Lowest hour | hourly |
| `avg_mw` | double | MW | Mean hourly demand | hourly |
| `temp_mean_c`, `temp_min_c`, `temp_max_c` | double | °C | Mean, min, max of the hourly weighted temperature | hourly |
| `hdd` | double | °C day | Heating degree days (mean of hourly degree values) | hourly |
| `cdd` | double | °C day | Cooling degree days | hourly |
| `load_factor` | double | ratio 0 to 1 | `avg_mw / peak_mw` | derived |
| `is_complete_day` | boolean | | `hours = 24` (false for the newest partial day and for 2025-05-01) | derived |

### `gold_demand_monthly`

One row per EST month. Local run: 95 rows.

| Column | Type | Unit | Description | Lineage |
|---|---|---|---|---|
| `month_start` | date | | First day of the month | `gold_demand_hourly.est_date` |
| `hours` | bigint | | Hours present | count |
| `energy_gwh` | double | GWh | Energy of the month | hourly |
| `onpeak_energy_gwh` | double | GWh | On-peak energy | hourly |
| `peak_mw` | double | MW | Highest hour of the month | hourly |
| `avg_mw` | double | MW | Mean hourly demand | hourly |
| `hdd`, `cdd` | double | °C day | Degree days of the month (sum of hourly values / 24) | hourly |
| `year`, `month` | int | | Calendar year and month | `month_start` |
| `date_key` | int | | Key of `month_start` in `gold_dim_date` | `month_start` |
| `offpeak_energy_gwh` | double | GWh | `energy_gwh - onpeak_energy_gwh` | derived |
| `onpeak_share` | double | fraction 0 to 1 | `onpeak_energy_gwh / energy_gwh` | derived |
| `is_complete_month` | boolean | | Hours at least 99 % of days x 24 (the newest month is partial) | derived |
| `energy_gwh_prev_year` | double | GWh | Energy of the same month one year earlier | self join |
| `yoy_energy_pct` | double | percent (0 to 100 scale) | `100 x (energy_gwh / energy_gwh_prev_year - 1)`; null unless both months are complete | derived |

### `gold_top_peaks`

The hours at or above the 99th percentile of `ontario_demand_mw` over the whole history (top 1 %).
The threshold comes from Spark's approximate percentile. Local run: 688 rows.

| Column | Type | Unit | Description | Lineage |
|---|---|---|---|---|
| `peak_rank` | int | | 1 = highest hour of the whole history | window rank |
| `peak_rank_in_year` | int | | Rank within the EST year | window rank |
| `target_time` | timestamp | UTC | Start of the hour | `gold_demand_hourly` |
| `est_date` | date | | EST date | hourly |
| `date_key` | int | | Key to `gold_dim_date` | hourly |
| `hour_ending` | int | HE | IESO hour | hourly |
| `season` | string | | Season | hourly |
| `ontario_demand_mw` | double | MW | Demand of the hour | hourly |
| `temperature_c` | double | °C | Weighted temperature | hourly |
| `apparent_temperature_c` | double | °C | Weighted apparent temperature | hourly |
| `relative_humidity_pct` | double | % | Weighted humidity | hourly |
| `heating_degree_c`, `cooling_degree_c` | double | °C (1 hour) | Degree hours | hourly |
| `threshold_mw` | double | MW | The 99th-percentile threshold (same value on every row) | percentile |

### `gold_temp_sensitivity`

Demand profile against temperature, over the whole history: one row per 1 °C bin, season and
business-day flag. No date column, so a year filter does not apply to it. Local run: 315 rows.

| Column | Type | Unit | Description | Lineage |
|---|---|---|---|---|
| `temp_bin_c` | int | °C | `floor(temperature_c)`: the bin covers `[temp_bin_c, temp_bin_c + 1)` | `gold_demand_hourly` |
| `season` | string | | Season | hourly |
| `is_business_day` | boolean | | Business day flag | hourly |
| `hours` | bigint | | Hours in the bin | count |
| `avg_demand_mw` | double | MW | Mean demand | hourly |
| `max_demand_mw` | double | MW | Highest demand | hourly |
| `p90_demand_mw` | double | MW | Approximate 90th percentile of demand | hourly |

### `gold_sensitivity_yearly`

Least-squares slope of demand on temperature per EST year, on the heating side (hours below 15 °C)
and the cooling side (hours above 20 °C). Hours between 15 and 20 °C are left out. Local run: 8
rows (2019 to 2026).

| Column | Type | Unit | Description | Lineage |
|---|---|---|---|---|
| `year` | int | | EST year | `gold_demand_hourly` |
| `heating_mw_per_c` | double | MW per °C | `-cov(T, demand) / var(T)` on hours with T < 15 °C: MW added per degree colder (positive when demand rises as it gets colder) | hourly |
| `heating_r2` | double | 0 to 1 | Squared correlation on those hours | hourly |
| `heating_hours` | bigint | | Hours used | hourly |
| `cooling_mw_per_c` | double | MW per °C | `cov(T, demand) / var(T)` on hours with T > 20 °C: MW added per degree warmer | hourly |
| `cooling_r2` | double | 0 to 1 | Squared correlation | hourly |
| `cooling_hours` | bigint | | Hours used | hourly |

### `gold_city_weather_daily`

Daily weather per city, for the report's city slicer. One row per (EST date, city), clipped by
`nb_gold` to the dates of `gold_dim_date`. Local run: 14,330 rows.

| Column | Type | Unit | Description | Lineage |
|---|---|---|---|---|
| `est_date` | date | | EST date of `valid_time` | `silver_weather_city_hourly` |
| `city_key` | string | | City (relationship to `gold_dim_city`) | silver |
| `hours` | bigint | | Hours present (24 for a complete day) | count |
| `temp_mean_c`, `temp_min_c`, `temp_max_c` | double | °C | Daily mean, min, max temperature of the city | silver |
| `hdd`, `cdd` | double | °C day | Degree days, base 18 °C (mean of hourly values) | silver |
| `precipitation_mm` | double | mm | Daily sum | silver |
| `snowfall_cm` | double | cm | Daily sum | silver |
| `relative_humidity_pct` | double | % | Daily mean | silver |
| `date_key` | int | | Key to `gold_dim_date` | `est_date` |

Edge days: weather starts at 2019-01-01 00:00 UTC, which is 2018-12-31 19:00 EST. That partial
first EST day is dropped by `nb_gold` (it has no row in `gold_dim_date`). The newest day is usually
partial, so report visuals on this table filter `hours = 24`.

---

## 7. Forecast tables (`nb_forecast`, `nb_predict`)

Day-ahead forecast of Ontario demand. Issued on EST day D at 08:15 EST (13:15 UTC), after IESO has
posted day D-1, for the 24 hours of D+1. Model: LightGBM, tracked in MLflow. Baseline: seasonal
naive 168 h (same hour one week earlier). Success criterion 6 of the proposal: beat the seasonal
naive MAPE by at least 30 %. Sensitivity: Public (derived), except the technical ids marked
Internal.

### `gold_forecast`

One row per forecast hour and split. The `backtest` and `holdout` splits cover the same 2026 hours,
so a report must filter one split at a time.

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `target_time` | timestamp | UTC | Start of the forecast hour | Public | forecast grid |
| `est_date` | date | | EST date of the target hour (day D+1) | Public | `target_time` |
| `date_key` | int | | Key to `gold_dim_date` | Public | `est_date` |
| `hour_ending` | int | HE 1 to 24 | IESO hour of the target | Public | `target_time` |
| `issue_date` | date | | EST day the forecast was issued, `est_date` minus 1 day | Public | `est_date` |
| `split` | string | | `backtest`: monthly rolling-origin retrain over 2025-01 to 2026-10; `holdout`: one frozen model trained on 2019 to 2025, scored on 2026; `live`: daily production forecast for tomorrow | Public | notebook |
| `model_name` | string | | `lightgbm` | Public | notebook |
| `model_version` | string | | Model version used for the row | Internal | MLflow registry |
| `run_id` | string | | MLflow run id | Internal | MLflow |
| `forecast_mw` | double | MW | Forecast demand | Public | model |
| `naive168_mw` | double | MW | Actual demand at the same hour one week earlier (`target_time` - 168 h) | Public | observed IESO demand (S1) |
| `actual_mw` | double | MW | Actual Ontario demand; null for live rows until IESO publishes the hour | Public | observed IESO demand (S1) |
| `abs_error_mw` | double | MW | `abs(forecast_mw - actual_mw)`; null while `actual_mw` is null | Public | derived |
| `ape_pct` | double | percent (0 to 100 scale) | `100 x abs_error_mw / actual_mw` | Public | derived |
| `weather_source` | string | | `historical_forecast` (Open-Meteo Historical Forecast API, as-of forecasts) or `forecast_api` (Open-Meteo Forecast API, normally the live rows) | Public | silver weather tables |

### `gold_forecast_eval`

Monthly evaluation, one row per month, split and model.

| Column | Type | Unit | Description | Sensitivity | Lineage |
|---|---|---|---|---|---|
| `month_start` | date | | First day of the evaluated EST month | Public | `gold_forecast.est_date` |
| `date_key` | int | | Key of `month_start` in `gold_dim_date` | Public | `month_start` |
| `split` | string | | As in `gold_forecast` | Public | `gold_forecast` |
| `model` | string | | `lightgbm` or `seasonal_naive_168` | Public | notebook |
| `mape_pct` | double | percent (0 to 100 scale) | Mean absolute percentage error over the month's hours | Public | `gold_forecast` |
| `mae_mw` | double | MW | Mean absolute error | Public | `gold_forecast` |
| `rmse_mw` | double | MW | Root mean squared error | Public | `gold_forecast` |
| `peak_ape_pct` | double | percent (0 to 100 scale) | Mean absolute percentage error at each day's actual peak hour | Public | `gold_forecast` |
| `n_hours` | int | | Hours evaluated | Public | `gold_forecast` |
| `skill_vs_naive_pct` | double | percent (0 to 100 scale) | `100 x (1 - MAPE_model / MAPE_naive)`; only on `lightgbm` rows, null on naive rows | Public | derived |
| `run_id` | string | | MLflow run id | Internal | MLflow |

---

## 8. Lineage overview

| Source | Landing (`Files/`) | Bronze | Silver | Gold |
|---|---|---|---|---|
| S1 IESO CSV | `bronze/ieso/PUB_Demand_YYYY*.csv` | `bronze_ieso_demand` | `silver_demand_hourly` -> `silver_demand_weather_hourly` | `gold_demand_hourly` -> `gold_demand_daily`, `gold_demand_monthly`, `gold_top_peaks`, `gold_temp_sensitivity`, `gold_sensitivity_yearly`; actuals and naive in `gold_forecast` |
| S2 Historical Forecast API | `bronze/openmeteo/YYYY-MM.json` | `bronze_openmeteo_hourly` | `silver_weather_city_hourly` -> `silver_weather_ontario_hourly` -> `silver_demand_weather_hourly` | weather columns of the demand facts; `gold_city_weather_daily`; features of `gold_forecast` (backtest, holdout) |
| S2 Forecast API | `bronze/openmeteo_forecast/YYYY-MM-DD.json` | `bronze_openmeteo_forecast` | `silver_weather_forecast_ontario` | features of `gold_forecast` (live) |
| S3 Azure SQL | none (Copy activity writes tables) | `bronze_sites`, `bronze_customers`, `bronze_meters` | `silver_sites`, `silver_customers_pseudo`, `silver_meters` | `gold_dim_site`, `gold_dim_meter` |
| S4 simulator | none (Eventstream `es_meters`) | | | Eventhouse `eh_gridpulse`, table `meter_readings` (not in the Lakehouse) |
| `config.py` | | | | `gold_dim_city` |
| `holidays` package | | | | `gold_dim_date` |
| All silver checks | | | `silver_dq_results` | |

## 9. Where personal data is and is not

| Location | Holds PII? | Notes |
|---|---|---|
| Azure SQL `dbo.customers` | Yes | Column classifications in `sql/001_schema.sql`; access through Entra ID roles |
| `bronze_customers` | Yes | Only Lakehouse table with PII; needed so the copy is a faithful raw layer |
| `silver_*` | No | `customer_hash` replaces `customer_id`; `pii_absent` check fails the run if a PII column appears |
| `gold_*` | No | `gold_dim_meter` keeps `customer_hash` and `segment` only |
| Eventhouse `meter_readings` | No | `meter_id` links to a customer only through S3, hence Internal |
| `sm_gridpulse`, `rpt_gridpulse` | No | Built on gold tables and `silver_dq_results` only |

To verify once the workspace exists: whether a workspace Viewer can query Lakehouse tables through
the SQL analytics endpoint. If so, `bronze_customers` would be readable by the Analyst persona;
deny it on that table (or share only the report and semantic model instead of the workspace role).
