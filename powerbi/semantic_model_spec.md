# Semantic model `sm_gridpulse` (Direct Lake)

Status (2026-11-22): specification only. Not built in Fabric yet. Table and column names were taken
from the code (`src/gridpulse/medallion/gold.py`, `fabric/nb_gold.Notebook`) and checked against
the tables of a local run; `gold_forecast` and `gold_forecast_eval` follow the schema of
`nb_forecast` / `nb_predict`.

| Item | Value |
|---|---|
| Workspace | `ws_gridpulse` |
| Source | Lakehouse `lh_gridpulse`, Delta tables |
| Storage mode | Direct Lake |
| Built by | Hamza ZIOUINE (Data Engineer), with a Power BI individual trial (free, 60 days) |
| Used by | Report `rpt_gridpulse` (built by Omar MOUNABBIH, see `report_spec.md`) |
| Measures | `powerbi/measures.dax` |
| Field reference | `docs/data_dictionary.md` |

---

## 1. Tables in the model

Gold tables only, plus `silver_dq_results` for the data-quality page. Row counts are from the local
run of 2026-11-22; in Fabric they will be a little higher (newer data).

| Table | Role | Grain | Rows (local) |
|---|---|---|---|
| `gold_dim_date` | Dimension, date table | One EST date (history + 7 days) | 2,874 |
| `gold_dim_city` | Dimension | One weather city | 5 |
| `gold_dim_site` | Dimension | One site | 10 |
| `gold_dim_meter` | Dimension | One meter | 50 |
| `gold_demand_hourly` | Fact | One UTC hour | 68,784 |
| `gold_demand_daily` | Fact | One EST date | 2,867 |
| `gold_demand_monthly` | Fact | One EST month | 95 |
| `gold_top_peaks` | Fact | One top 1 % hour | 688 |
| `gold_city_weather_daily` | Fact | One EST date and city | 14,330 |
| `gold_forecast` | Fact | One forecast hour and split | written by `nb_forecast` / `nb_predict` |
| `gold_forecast_eval` | Fact | One month, split and model | written by `nb_forecast` / `nb_predict` |
| `gold_temp_sensitivity` | Analytical, unrelated | One 1 °C bin, season, business-day flag (whole history) | 315 |
| `gold_sensitivity_yearly` | Analytical, unrelated | One year | 8 |
| `silver_dq_results` | Operational, unrelated | One check per run | 17 per run |

Not in the model: every `bronze_*` table (raw; `bronze_customers` holds PII) and the other `silver_*`
tables (row-level working data; gold holds everything the report needs). The Analyst persona sees
data only through this model and the report, and nothing in it is personal data.

## 2. Relationships

All relationships: many-to-one, single cross-filter direction (dimension filters fact), active.

| # | From (many side) | To (one side) | Cardinality | Cross-filter |
|---|---|---|---|---|
| R1 | `gold_demand_hourly[date_key]` | `gold_dim_date[date_key]` | Many to one | Single |
| R2 | `gold_demand_daily[date_key]` | `gold_dim_date[date_key]` | Many to one | Single |
| R3 | `gold_demand_monthly[date_key]` | `gold_dim_date[date_key]` | Many to one | Single |
| R4 | `gold_top_peaks[date_key]` | `gold_dim_date[date_key]` | Many to one | Single |
| R5 | `gold_city_weather_daily[date_key]` | `gold_dim_date[date_key]` | Many to one | Single |
| R6 | `gold_city_weather_daily[city_key]` | `gold_dim_city[city_key]` | Many to one | Single |
| R7 | `gold_forecast[date_key]` | `gold_dim_date[date_key]` | Many to one | Single |
| R8 | `gold_forecast_eval[date_key]` | `gold_dim_date[date_key]` | Many to one | Single |
| R9 | `gold_dim_meter[site_id]` | `gold_dim_site[site_id]` | Many to one | Single |

Points to watch:

- R2 and R3: `date_key` is unique in `gold_demand_daily` and in `gold_demand_monthly`, so the editor
  may propose One to one with Both directions. Change it to Many to one, Single. A one-to-one
  relationship would let the fact filter the date table and, through it, every other fact.
- R3 and R8 join on the key of the first day of the month. Use only month-level attributes of
  `gold_dim_date` with these tables (`year`, `quarter`, `month`, `month_name`, `month_start`,
  `year_month`, `season`); a weekday or holiday filter would only match the 1st of the month.
- `gold_dim_date[date_key]` and the facts' `date_key` are both `int` (`nb_gold` casts the
  pandas-built dimension), so the relationships join on identical types.
- After the tables are added, open Manage relationships and delete any relationship that is not in
  the table above, in particular any fact-to-fact link on `date_key` or `target_time` created by
  auto-detection.
- Key gaps (Direct Lake shows them as a blank member of the dimension, no error):
  `nb_gold` drops the partial first weather day (2018-12-31 EST, before the first demand date), so
  `gold_city_weather_daily` has no orphan keys; city visuals still filter `hours = 24` because the
  newest day is partial. `gold_dim_date` runs to the last demand date plus 7 days, so live
  forecast rows always find their date as long as `nb_gold` ran the same day as `nb_predict`.
- "Assume referential integrity" can stay off on R5; it is not needed for Direct Lake.

### Why `gold_forecast` relates to `gold_dim_date` and not to `gold_demand_hourly`

1. Star schema: facts relate to dimensions, never to each other. A link `gold_forecast[target_time]`
   to `gold_demand_hourly[target_time]` would give `gold_dim_date` two paths to `gold_forecast`
   (directly and through the hourly fact). Power BI rejects that as ambiguous or forces one path to
   be inactive.
2. `target_time` is not unique in `gold_forecast`: the backtest and holdout splits cover the same
   2026 hours, and live rows are added every day. The live rows for tomorrow also have no hour in
   `gold_demand_hourly` yet.
3. The comparison does not need a join: `gold_forecast` already stores `actual_mw` and
   `naive168_mw` next to `forecast_mw`.
4. Through the shared `gold_dim_date`, one date slicer filters demand and forecast pages alike.
   Hour-level comparisons use `gold_forecast[hour_ending]` and `gold_forecast[target_time]` directly.

### Unrelated tables and how the measures reach them

| Table | Why no relationship | How filters reach it |
|---|---|---|
| `gold_temp_sensitivity` | Aggregated over the whole history, no date column | `Avg Demand by Temp Bin (MW)` applies the season slicer with `TREATAS` from `gold_dim_date[season]`. The year slicer cannot apply; the report says so. |
| `gold_sensitivity_yearly` | Only a `year` column, which is not a key of `gold_dim_date` | Not needed by the visuals: `Heating Slope (MW per C)` and `Cooling Slope (MW per C)` compute the same least-squares slope from `gold_demand_hourly`, so they follow every slicer. The table stays in the model as a cross-check. |
| `silver_dq_results` | Its `run_date` is a pipeline run date (UTC), not a demand date | Measures pick the latest run themselves; the DQ page has no date slicer. |
| `gold_forecast_eval` vs the split slicer | `gold_forecast_eval[split]` is a different column from `gold_forecast[split]` | `Eval Row Matches Split` reads the slicer value and is used as a visual-level filter. |

## 3. Date table

Mark `gold_dim_date` as the date table, date column `est_date`. The column meets the conditions:
Date type, one row per day, no blanks, no gaps (built with a daily range). Relationships stay on
`date_key`; marking the table keeps date functions and the date picker working with an integer key.

## 4. Sort by column

| Column | Sort by |
|---|---|
| `gold_dim_date[month_name]` | `gold_dim_date[month]` |
| `gold_dim_date[month_short]` | `gold_dim_date[month]` |
| `gold_dim_date[day_name]` | `gold_dim_date[day_of_week]` |
| `gold_dim_date[day_short]` | `gold_dim_date[day_of_week]` |
| `gold_dim_date[season]` | `gold_dim_date[season_order]` |

`year_month` (`YYYY-MM`) already sorts correctly as text.

## 5. Hidden columns

Hide these from report view (they stay usable in DAX):

| Table | Hide | Reason |
|---|---|---|
| `gold_dim_date` | `date_key`, `day_of_week`, `season_order` | Key and sort helpers |
| `gold_dim_meter` | `customer_hash`, `site_code`, `site_city` | Pseudonymous key with no reporting use; site columns come from `gold_dim_site` |
| `gold_demand_hourly` | `date_key`, `est_date`, `season`, `is_business_day` | Use the `gold_dim_date` columns so every visual filters the same way |
| `gold_demand_daily` | `date_key`, `est_date` | Same |
| `gold_demand_monthly` | `date_key`, `month_start`, `year`, `month` | Same |
| `gold_top_peaks` | `date_key` | Key; `est_date` and `season` stay visible as record details for the peak table |
| `gold_city_weather_daily` | `date_key`, `est_date`, `city_key` | Use `gold_dim_date` and `gold_dim_city` |
| `gold_forecast` | `date_key`, `run_id` | Key and technical id |
| `gold_forecast_eval` | `date_key`, `run_id` | Same |
| `silver_dq_results` | `run_id`, `layer` | Technical |
| Measures | `Eval Row Matches Split`, `Is Latest DQ Run`, `DQ Status Colour` | Helpers used in filters and conditional formatting |

## 6. Summarize by: None

Numeric columns that are labels, codes or rates must not be summed by default. Set "Summarize by"
to None on:

- `gold_dim_date`: `year`, `quarter`, `month`, `day_of_month` (and the hidden `date_key`,
  `day_of_week`, `season_order`).
- `gold_demand_hourly`: `hour_ending`, `hour_est`, `temperature_c`, `apparent_temperature_c`,
  `relative_humidity_pct`, `cloud_cover_pct`, `solar_radiation_wm2`, `wind_speed_kmh`.
- `gold_demand_daily`: `peak_hour_ending`, `load_factor`, `temp_mean_c`, `temp_min_c`,
  `temp_max_c`.
- `gold_demand_monthly`: `onpeak_share`, `yoy_energy_pct`.
- `gold_top_peaks`: `peak_rank`, `peak_rank_in_year`, `hour_ending`, `ontario_demand_mw`,
  `temperature_c`, `apparent_temperature_c`, `relative_humidity_pct`, `threshold_mw`.
- `gold_temp_sensitivity`: `temp_bin_c`.
- `gold_sensitivity_yearly`: `year` and every slope and r2 column.
- `gold_city_weather_daily`: `temp_mean_c`, `temp_min_c`, `temp_max_c`, `relative_humidity_pct`.
- `gold_forecast`: `hour_ending`, `ape_pct`.
- `gold_forecast_eval`: `mape_pct`, `mae_mw`, `rmse_mw`, `peak_ape_pct`, `skill_vs_naive_pct`.
- `gold_dim_city`: `city_id`, `latitude`, `longitude`, `population_weight`.
- `gold_dim_site`: `site_id`, `latitude`, `longitude`.
- `gold_dim_meter`: `site_id`.

## 7. Column formats and data categories

| Columns | Format string |
|---|---|
| Every `*_mw` column, `capacity_kw`, `rated_kw`, `rated_kw_total` | `#,0` |
| Every `*_gwh` column | `#,0.0` |
| Temperatures (`temperature_c`, `temp_*_c`, `apparent_temperature_c`), degree columns | `0.0` |
| `*_pct` columns stored in percent units (`ape_pct`, `mape_pct`, `peak_ape_pct`, `skill_vs_naive_pct`, `yoy_energy_pct`, humidity, cloud cover) | `0.0` (rename the visual header to "... (%)") |
| Fractions: `load_factor`, `onpeak_share`, `population_weight`, `heating_r2`, `cooling_r2` | `0.0%` (r2 columns: `0.00`) |
| Dates (`est_date`, `month_start`, `issue_date`, `install_date`, `customer_since`, `run_date`) | `yyyy-mm-dd` |
| Timestamps (`target_time`, `checked_at`) | `yyyy-mm-dd hh:nn` (UTC) |

Data categories: `latitude` and `longitude` of `gold_dim_city` and `gold_dim_site` as Latitude and
Longitude; `city_name` and `gold_dim_site[city]` as City.

Measure formats are on the first comment line of each block in `measures.dax` and in section 9.

## 8. Display folders

| Table | Folder | Columns |
|---|---|---|
| `gold_dim_date` | Calendar | `est_date`, `year`, `quarter`, `month`, `month_name`, `month_short`, `month_start`, `year_month`, `day_of_month`, `day_name`, `day_short` |
| `gold_dim_date` | Day type | `is_weekend`, `is_holiday`, `holiday_name`, `is_business_day`, `season` |
| `gold_demand_hourly` | Load | `target_time`, `hour_ending`, `hour_est`, `is_onpeak`, `ontario_demand_mw`, `market_demand_mw` |
| `gold_demand_hourly` | Weather | the temperature, humidity, cloud, radiation, wind and degree columns |
| `gold_demand_daily` | Load | `energy_gwh`, `onpeak_energy_gwh`, `peak_mw`, `peak_hour_ending`, `min_mw`, `avg_mw`, `load_factor` |
| `gold_demand_daily` | Weather | `temp_mean_c`, `temp_min_c`, `temp_max_c`, `hdd`, `cdd` |
| `gold_demand_daily` | Completeness | `hours`, `is_complete_day` |
| `gold_forecast` | Values | `forecast_mw`, `naive168_mw`, `actual_mw`, `abs_error_mw`, `ape_pct` |
| `gold_forecast` | Run | `split`, `model_name`, `model_version`, `issue_date`, `weather_source` |

Measure folders (set on each measure): Demand, Peaks, Weather, Forecast, Data quality, Fleet.

## 9. Measures

Paste them from `powerbi/measures.dax` into the home table named in each section header.

| Measure | Home table | Format | Folder |
|---|---|---|---|
| Total Energy (GWh) | `gold_demand_hourly` | `#,0.0` | Demand |
| Avg Load (MW) | `gold_demand_hourly` | `#,0` | Demand |
| Load Factor | `gold_demand_hourly` | `0.0%` | Demand |
| On-peak Share % | `gold_demand_hourly` | `0.0%` | Demand |
| Energy YoY % | `gold_demand_hourly` | `+0.0%;-0.0%;0.0%` | Demand |
| Avg Daily Energy (GWh) | `gold_demand_daily` | `#,0.0` | Demand |
| Peak Load (MW) | `gold_demand_hourly` | `#,0` | Peaks |
| Peak Load Date | `gold_demand_hourly` | `yyyy-mm-dd` | Peaks |
| Peak Load Hour (HE) | `gold_demand_hourly` | `0` | Peaks |
| Hours Above 99th Percentile | `gold_top_peaks` | `#,0` | Peaks |
| Peak Threshold (MW) | `gold_top_peaks` | `#,0` | Peaks |
| Avg Temperature (C) | `gold_demand_hourly` | `0.0` | Weather |
| Heating Slope (MW per C) | `gold_demand_hourly` | `#,0` | Weather |
| Cooling Slope (MW per C) | `gold_demand_hourly` | `#,0` | Weather |
| Avg Demand by Temp Bin (MW) | `gold_temp_sensitivity` | `#,0` | Weather |
| Avg City Temperature (C) | `gold_city_weather_daily` | `0.0` | Weather |
| City Heating Degree Days | `gold_city_weather_daily` | `#,0` | Weather |
| City Cooling Degree Days | `gold_city_weather_daily` | `#,0` | Weather |
| Actual (MW) | `gold_forecast` | `#,0` | Forecast |
| Forecast (MW) | `gold_forecast` | `#,0` | Forecast |
| Naive 168 (MW) | `gold_forecast` | `#,0` | Forecast |
| Forecast MAPE % | `gold_forecast` | `0.00%` | Forecast |
| Naive MAPE % | `gold_forecast` | `0.00%` | Forecast |
| Forecast Skill % (vs naive) | `gold_forecast` | `0.0%` | Forecast |
| Skill Target | `gold_forecast` | `0%` | Forecast |
| Skill vs Target | `gold_forecast` | text | Forecast |
| Forecast MAE (MW) | `gold_forecast` | `#,0` | Forecast |
| Forecast RMSE (MW) | `gold_forecast` | `#,0` | Forecast |
| Peak-hour APE % | `gold_forecast` | `0.00%` | Forecast |
| Forecast Split Shown | `gold_forecast` | text | Forecast |
| Eval Row Matches Split (hidden) | `gold_forecast_eval` | `0` | Forecast |
| DQ Checks Failed | `silver_dq_results` | `0` | Data quality |
| DQ Checks Warned | `silver_dq_results` | `0` | Data quality |
| DQ Last Run | `silver_dq_results` | `yyyy-mm-dd hh:nn` | Data quality |
| Is Latest DQ Run (hidden) | `silver_dq_results` | `0` | Data quality |
| DQ Status Colour (hidden) | `silver_dq_results` | text | Data quality |
| Last Demand Date | `gold_demand_hourly` | `yyyy-mm-dd` | Data quality |
| Meter Count | `gold_dim_meter` | `0` | Fleet |
| Active Meters | `gold_dim_meter` | `0` | Fleet |
| Rated Capacity (kW) | `gold_dim_meter` | `#,0` | Fleet |
| Site Count | `gold_dim_site` | `0` | Fleet |

Percent measures return fractions (0.034 shows as 3.4 %). The gold percent columns (`ape_pct`,
`mape_pct`, ...) hold percent units (3.4), which is why the measures divide them by 100.

## 10. Settings, access and licences

- Direct Lake refresh: in the workspace, `sm_gridpulse` > Settings > Refresh, keep "Keep your Direct
  Lake data up to date" on. After each `nb_gold` / `nb_predict` run the model then points to the new
  Delta version without an import refresh. If a notebook changes a column name or type, open the
  model, fix the broken field and click Refresh once.
- No calculated columns or calculated tables: every derived column is made in `nb_gold`, where it
  is tested and reused, and Direct Lake has limits on calculated objects.
- No row-level security: the model holds no personal data. `customer_hash` is pseudonymous and
  hidden.
- Personas: Admin Mohamed NACIR (workspace Admin), Data Engineer Hamza ZIOUINE (builds the model),
  Analyst Omar MOUNABBIH (workspace Viewer, reads the report).
- Licences: creating or editing a semantic model or report needs Power BI Pro, PPU or the free
  60-day individual trial; Hamza and Omar start the trial the first time Fabric asks.
- Viewer access to Direct Lake data: if Omar, as Viewer, gets a data access error on the report,
  the model is reading the Lakehouse with the viewer's own identity. Fix it in `sm_gridpulse` >
  Settings > Gateway and cloud connections by binding the Lakehouse source to a fixed-identity cloud
  connection (owned by Hamza), so viewers need only access to the model and report.

## 11. Click steps (Fabric UI)

Prerequisite: `nb_silver`, `nb_gold`, `nb_forecast` and `nb_predict` have run, so the 13 gold
tables and `silver_dq_results` exist under `lh_gridpulse` > Tables.

1. Open `ws_gridpulse` > `lh_gridpulse` (Lakehouse view).
2. Ribbon: New semantic model. Name `sm_gridpulse`, workspace `ws_gridpulse`.
3. Tick the 14 tables of section 1 (expand `dbo` / Tables if the list is grouped). Confirm. The
   model opens in the web model editor; later, reopen it from the workspace (`sm_gridpulse` > Open
   data model).
4. Relationships: Manage relationships. Delete anything not in section 2. Then New relationship
   for R1 to R9: pick the from table and column, the to table and column, Cardinality "Many to
   one (*:1)", Cross filter direction "Single", tick "Make this relationship active", Save. In
   diagram view you can also drag the from column onto the to column and then edit the
   relationship to check cardinality and direction.
5. Date table: select `gold_dim_date` > Mark as date table > date column `est_date` > Save.
6. Sort by column: select each column of section 4 in the Data pane, then in Properties (or the
   Column tools ribbon) set Sort by column.
7. Hide: right-click each column of section 5 > Hide in report view (or Properties > Is hidden).
8. Summarize by: for each column of section 6, Properties > Advanced > Summarize by > None.
9. Formats and data categories: Properties > Formatting > Format (custom format string from
   section 7); Data category for the latitude, longitude and city columns.
10. Display folders: Properties > Display folder (section 8).
11. Measures: select the home table > New measure > paste the block from `measures.dax` > Enter.
    Then set Format and Display folder (section 9). Hide the three helper measures.
12. Settings: workspace > `sm_gridpulse` > Settings > Refresh: "Keep your Direct Lake data up to
    date" on. Add a description ("GridPulse gold model, Direct Lake on lh_gridpulse").
13. Export the definition for the repo (PLAN T7.1): through workspace Git integration
    (`sm_gridpulse.SemanticModel` folder in TMDL), or `fab export` in TMDL format into
    `powerbi/sm_gridpulse.SemanticModel/`.

## 12. Checks after the build

Use a scratch report page (or Explore this data) and compare:

| Check | Expected |
|---|---|
| `COUNTROWS` of each table | Same order as section 1 (a little higher after new daily loads) |
| Year slicer on `gold_dim_date[year]` with a card `Total Energy (GWh)` | Changes per year; no blank row in the slicer (a blank row means a broken key) |
| `Heating Slope (MW per C)` and `Cooling Slope (MW per C)` for one complete year | Equal to `heating_mw_per_c` and `cooling_mw_per_c` of `gold_sensitivity_yearly` for that year |
| `Forecast MAPE %` for one month and split | Equal to `mape_pct / 100` of the `lightgbm` row of `gold_forecast_eval` for that month and split (if not, note the difference and its cause, for example a different hour filter) |
| `Forecast Skill % (vs naive)` for one month and split | Equal to `skill_vs_naive_pct / 100` of that row |
| `DQ Checks Failed` | 0 when the last pipeline run succeeded |
| Month and day names in a visual | In calendar order, not alphabetical |

## 13. Why Direct Lake, and what if the volume grows

Direct Lake reads the Delta tables that `nb_gold` writes straight from OneLake, so there is no
import copy to refresh and no scheduled refresh to fit into the pipeline: when the notebook rerun
finishes during the demo, the report shows the new data (DESIGN D14). Import mode would add a
refresh step and a second copy of the data; DirectQuery would send every visual as SQL to the
Lakehouse SQL endpoint and be slower. Our volume is tiny for Direct Lake: the largest fact,
`gold_demand_hourly`, has 68,784 rows, while the smallest Fabric SKUs allow 300 million rows per
table.

If volume grows, for example meter-level history instead of one provincial series, the plan is:
keep pre-aggregated gold tables (daily, monthly, top peaks) as the report's main source; partition
large facts by month and run `OPTIMIZE` (V-Order) so the Delta tables stay within the Direct Lake
limits on files and row groups; size the capacity to the guardrails of the chosen SKU, because past
them a Direct Lake model either falls back to DirectQuery (slower) or fails, depending on its
settings; consider Import with incremental refresh only for a very large, slowly changing history.
Second-level data such as live meter readings stays in the Eventhouse and is shown by the Real-Time
Dashboard `rtd_gridpulse`, not by this model.
