# Report `rpt_gridpulse`

Status (2026-11-22): specification only. Not built in Fabric yet. The report is built by Omar
MOUNABBIH in the Fabric web UI on the semantic model `sm_gridpulse` (`semantic_model_spec.md`),
with the measures of `measures.dax`. Field meanings: `docs/data_dictionary.md`.

The report answers the business questions of the proposal (section 9):

| # | Business question | Where |
|---|---|---|
| Q1 | When do demand peaks happen (hour, weekday, season), and how high are they? | Page 1 "Peaks and trends" |
| Q2 | How strongly does temperature drive demand? (load vs temperature, heating and cooling sensitivity) | Page 2 "Weather sensitivity" |
| Q3 | How accurate is our day-ahead forecast compared with actual demand and a naive baseline? (MAPE) | Page 3 "Forecast vs actual" |
| Q4 | Which sites are consuming abnormally right now? | Real-Time Dashboard `rtd_gridpulse` (KQL query Q2), reached from the "Live view" button on pages 1 and 4 |
| (support) | Is the data fresh and complete, and what does the meter fleet look like? | Page 4 "Data quality and fleet" (optional) |

Q4 is not in this report on purpose: live meter readings live in the Eventhouse `eh_gridpulse`, not
in the Lakehouse, and the Direct Lake model only covers gold tables.

---

## 1. Report-wide settings

- Page size: 16:9, 1280 x 720 (Format page > Canvas settings). View > Fit to page.
- Positions below are `(x, y, width, height)` in pixels. Set them in Format visual > General >
  Properties > Size and position. A 16 px margin and 12 px gaps are used everywhere.
- Header band on every page, y 8 to 64: page title on the left (written as the question), slicers
  on the right. KPI cards on the band y 72 to 168. Visuals below.
- Hours are IESO hour-ending in EST all year (HE18 = 17:00 to 18:00 EST). In summer the Toronto
  clock is one hour later. `target_time` is the UTC start of the hour. Put this sentence in the
  subtitle of the visuals that show hours.
- Colours (View > Themes > Customize current theme > Name and colours, so they apply everywhere):

| Use | Colour |
|---|---|
| Actual demand | `#222222` |
| LightGBM forecast | `#1F77B4` |
| Seasonal naive 168 h | `#FF7F0E` (dashed line) |
| Energy columns | `#9FB7D6` |
| Peak load line, top 1 % bars | `#B30000` |
| Winter, Spring, Summer, Fall | `#4C78A8`, `#59A14F`, `#F28E2B`, `#9C755F` |
| Heating, cooling | `#4C78A8`, `#E15759` |
| Heatmap gradient | `#FFF7EC` (lowest) to `#B30000` (highest) |
| Good, warning, bad | `#2E7D32`, `#F9A825`, `#C62828` |

- Slicers:

| Slicer | Field | Style | Pages | Notes |
|---|---|---|---|---|
| Year | `gold_dim_date[year]` | Dropdown, multi-select | 1, 2 | Synced between pages 1 and 2 only |
| Season | `gold_dim_date[season]` | Tile, multi-select | 1, 2 | Synced between pages 1 and 2 only |
| City | `gold_dim_city[city_name]` | Dropdown, multi-select | 2 | Affects only the city weather visual: demand is province-wide |
| Split | `gold_forecast[split]` | Tile, Single select on, saved on `holdout` | 3 | `backtest` and `holdout` overlap in 2026; never show both at once |
| Forecast dates | `gold_dim_date[est_date]` | Between | 3 | Filters only the hourly line chart (see interactions) |

- Lock and hide the visual-level filters that use helper measures (Filters pane, lock icon and
  eye icon), so viewers cannot break them.

---

## 2. Page 1 "Peaks and trends" (Q1)

| ID | Element | Type | Position |
|---|---|---|---|
| T1 | Title | Text box | (16, 8, 600, 48) |
| B1 | Live view (Q4) button | Button | (628, 16, 120, 40) |
| S1 | Year | Slicer | (760, 8, 200, 56) |
| S2 | Season | Slicer | (972, 8, 292, 56) |
| K1 | Peak Load (MW) | Card | (16, 72, 240, 96) |
| K2 | Avg Daily Energy (GWh) | Card | (268, 72, 240, 96) |
| K3 | Load Factor | Card | (520, 72, 240, 96) |
| K4 | Energy YoY % | Card | (772, 72, 240, 96) |
| K5 | Hours Above 99th Percentile | Card | (1024, 72, 240, 96) |
| V1 | Average load by hour and weekday | Matrix (heatmap) | (16, 180, 620, 272) |
| V2 | Monthly energy and peak load | Line and clustered column chart | (648, 180, 616, 272) |
| V3 | Top 1 % hours by month | Clustered column chart | (16, 464, 400, 240) |
| V4 | Ten highest hours | Table | (428, 464, 440, 240) |
| T2 | Interpretation | Text box | (880, 464, 384, 240) |

Title T1: "When do demand peaks happen, and how high are they?" Subtitle (smaller font): "Ontario
demand (IESO), 2019 to the latest day loaded. Hours are EST hour-ending."

KPI cards:

- K1 `Peak Load (MW)`. Reference labels (new card visual): `Peak Load Date` and `Peak Load Hour
  (HE)`. With the classic card, add them as two small cards under K1 instead.
- K2 `Avg Daily Energy (GWh)`, label "Average daily energy (complete days)".
- K3 `Load Factor`, label "Load factor (average / peak)".
- K4 `Energy YoY %`, label "Energy vs same dates a year earlier". Blank when 2019 is the only year
  selected; that is expected.
- K5 `Hours Above 99th Percentile`, reference label `Peak Threshold (MW)`.

V1 heatmap (the proposal's "hour x weekday heatmap"):

- Rows: `gold_dim_date[day_short]` (sorted Monday to Sunday by the model's sort-by column).
- Columns: `gold_demand_hourly[hour_ending]` (1 to 24).
- Values: `Avg Load (MW)`.
- Format: Row subtotals off, Column subtotals off; values font size 7. Cell elements > Background
  colour on, Format style Gradient, lowest value `#FFF7EC`, highest value `#B30000`. Turn Font
  colour on with the same gradient so the numbers disappear into the colour (the tooltip still shows
  them).
- Title: "Average load (MW) by hour-ending (EST) and weekday".

V2 trend (the proposal's "trend line"):

- X-axis: `gold_dim_date[month_start]`, Type Continuous.
- Column y-axis: `Total Energy (GWh)`, colour `#9FB7D6`.
- Line y-axis: `Peak Load (MW)`, colour `#B30000`, on the secondary axis.
- Title: "Monthly energy (GWh) and monthly peak load (MW)". Sorted by month ascending.

V3 seasonality of extremes:

- X-axis: `gold_dim_date[month_short]` (Jan to Dec by sort-by column; Sort axis > `month_short`,
  ascending).
- Y-axis: `Hours Above 99th Percentile`, colour `#B30000`.
- Title: "Hours in the top 1 % of all hours since 2019, by month".

V4 peak list:

- Columns from `gold_top_peaks`: `est_date` ("Date (EST)"), `hour_ending` ("HE"),
  `ontario_demand_mw` ("Demand (MW)"), `temperature_c` ("Temp (°C)"), `season` ("Season").
- Visual-level filter: `gold_top_peaks[target_time]`, Filter type Top N, Show items Top 10, By value
  `ontario_demand_mw` (Maximum). Sort by `ontario_demand_mw` descending.
- Title: "Ten highest hours in the selection".

T2 interpretation template (fill in after looking at the real data; replace each bracket):

> Q1. When do demand peaks happen, and how high are they?
> - Time of day: [State the hour-ending (EST) and the weekdays of the darkest cells of the heatmap.
>   Add one hour if you quote a summer peak in Toronto clock time.]
> - Season: [State the months with the highest bars in "Top 1 % hours by month" and the season of
>   most rows in the top 10 table.]
> - Level: [Quote Peak Load (MW) with its date and hour, and the top 1 % threshold.]
> - Trend: [Compare the monthly peaks across the selected years; quote Energy YoY % for the latest
>   complete year.]
> - Decision: [One sentence on which months and hours peak preparation (staffing, reserve
>   purchases) should target.]

---

## 3. Page 2 "Weather sensitivity" (Q2)

| ID | Element | Type | Position |
|---|---|---|---|
| T1 | Title | Text box | (16, 8, 596, 48) |
| S1 | Year (synced) | Slicer | (624, 8, 180, 56) |
| S2 | Season (synced) | Slicer | (816, 8, 256, 56) |
| S3 | City | Slicer | (1084, 8, 180, 56) |
| K1 | Avg Temperature (C) | Card | (16, 72, 300, 96) |
| K2 | Heating Slope (MW per C) | Card | (328, 72, 300, 96) |
| K3 | Cooling Slope (MW per C) | Card | (640, 72, 300, 96) |
| K4 | Avg Daily Energy (GWh) | Card | (952, 72, 312, 96) |
| V1 | Load vs temperature, one dot per day | Scatter chart | (16, 180, 620, 300) |
| V2 | Load per 1 °C bin | Line chart | (648, 180, 616, 300) |
| V3 | Sensitivity by year | Clustered column chart | (16, 492, 400, 212) |
| V4 | Degree days by city | Clustered bar chart | (428, 492, 400, 212) |
| T2 | Interpretation | Text box | (840, 492, 424, 212) |

Title T1: "How strongly does temperature drive demand?" Subtitle: "Temperature = population-weighted
mean of 5 Ontario cities (Open-Meteo)."

KPI cards: K1 label "Mean Ontario temperature (°C)"; K2 label "MW added per °C colder, below 15
°C"; K3 label "MW added per °C warmer, above 20 °C"; K4 as on page 1.

V1 scatter (the proposal's "load vs temperature scatter"):

- Values (details): `gold_dim_date[est_date]` (the date itself, not a date hierarchy).
- X-axis: `Avg Temperature (C)`. Y-axis: `Avg Load (MW)`.
- Legend: `gold_dim_date[season]` with the season colours. Marker size small.
- Title: "Daily mean load (MW) vs daily mean temperature (°C)". About 2,900 days in total, under the
  default point limit, so no sampling.

V2 temperature curve:

- X-axis: `gold_temp_sensitivity[temp_bin_c]`, Type Continuous.
- Y-axis: `Avg Demand by Temp Bin (MW)`. Legend: `gold_temp_sensitivity[season]`.
- Title: "Average load per 1 °C temperature bin". Subtitle: "Whole history 2019 to today: the year
  slicer does not change this chart."

V3 sensitivity trend:

- X-axis: `gold_dim_date[year]`. Y-axis: `Heating Slope (MW per C)` (`#4C78A8`) and `Cooling Slope
  (MW per C)` (`#E15759`).
- Interactions: the Year slicer does NOT filter this visual (Edit interactions > None), so every
  year stays visible; the Season slicer still applies.
- Title: "Heating and cooling sensitivity by year (MW per °C)".

V4 cities:

- Y-axis: `gold_dim_city[city_name]`. X-axis: `City Heating Degree Days` (`#4C78A8`), `City
  Cooling Degree Days` (`#E15759`).
- Visual-level filter: `gold_city_weather_daily[hours]` is 24 (complete days only; removes the
  partial first and last days).
- Title: "Heating and cooling degree days by city (base 18 °C)".

The City slicer only reaches V4 (the other visuals use province-wide demand and weather). Leave the
default interactions; it has no effect on them.

T2 interpretation template:

> Q2. How strongly does temperature drive demand?
> - Shape: [Describe the scatter: at which daily mean temperature is load lowest, and on which side
>   does it rise faster?]
> - Heating: [Quote Heating Slope for the selection as "each degree colder below 15 °C adds about
>   ... MW".]
> - Cooling: [Same with Cooling Slope above 20 °C.]
> - Over the years: [Do the yearly slopes go up, down or stay flat? Name any year that stands out.]
> - Cities: [Which city has the most heating and the most cooling degree days in the selection.]
> - Limit: [The temperature curve covers the whole history; it ignores the year slicer.]

---

## 4. Page 3 "Forecast vs actual" (Q3)

| ID | Element | Type | Position |
|---|---|---|---|
| T1 | Title | Text box | (16, 8, 560, 48) |
| S1 | Split | Slicer | (588, 8, 330, 56) |
| S2 | Forecast dates | Slicer | (930, 8, 334, 56) |
| K1 | Forecast MAPE % | Card | (16, 72, 240, 96) |
| K2 | Naive MAPE % | Card | (268, 72, 240, 96) |
| K3 | Forecast Skill % (vs naive) | Card | (520, 72, 240, 96) |
| K4 | Forecast MAE (MW) | Card | (772, 72, 240, 96) |
| K5 | Peak-hour APE % | Card | (1024, 72, 240, 96) |
| V1 | Hourly actual, forecast and naive | Line chart | (16, 180, 830, 270) |
| V2 | Monthly evaluation | Table | (858, 180, 406, 270) |
| V3 | MAPE by month | Line chart | (16, 462, 410, 242) |
| V4 | MAPE by hour of day | Clustered column chart | (438, 462, 410, 242) |
| T2 | Interpretation | Text box | (860, 462, 404, 242) |

Title T1: "How accurate is the day-ahead forecast?" Subtitle: "LightGBM, issued at 08:15 EST for the
24 hours of the next day, against the seasonal naive (same hour one week earlier)."

Split slicer: values `backtest` (monthly retrain over 2025-01 to 2026-10), `holdout` (one frozen
model trained on 2019 to 2025, scored on 2026) and `live` (daily forecast for tomorrow). Single
select; select `holdout` before saving so the report opens on it.

KPI cards:

- K1 `Forecast MAPE %`, label "LightGBM MAPE". This is KPI 3 of the proposal.
- K2 `Naive MAPE %`, label "Seasonal naive MAPE".
- K3 `Forecast Skill % (vs naive)`, reference label `Skill vs Target`. Callout value colour, fx,
  Rules: if value >= 0.3 then `#2E7D32`, else `#E65100`. 0.3 is success criterion 6 (beat the naive
  MAPE by at least 30 %).
- K4 `Forecast MAE (MW)`, label "Mean absolute error (MW)".
- K5 `Peak-hour APE %`, label "Error at each day's peak hour".
- With the `live` split the cards only cover past live forecasts whose actuals have arrived; for a
  brand-new forecast they are blank and K3 says "No hours with actuals in this selection".

V1 forecast vs actual (the proposal's "forecast vs actual line"):

- X-axis: `gold_forecast[target_time]`, Type Continuous.
- Y-axis: `Actual (MW)` (`#222222`, 2 px), `Forecast (MW)` (`#1F77B4`), `Naive 168 (MW)` (`#FF7F0E`,
  dashed: Format > Lines > Line style).
- Title: "Hourly demand: actual, LightGBM forecast and seasonal naive (MW)". Subtitle: "Hour start
  in UTC."
- Set the Forecast dates slicer to about one week inside the selected split before saving (for the
  `live` split: today and tomorrow).

V2 monthly evaluation (from `gold_forecast_eval`):

- Columns: `month_start`, `split`, `model`, `mape_pct` ("MAPE (%)"), `peak_ape_pct` ("Peak APE
  (%)"), `rmse_mw` ("RMSE (MW)"), `skill_vs_naive_pct` ("Skill (%)"). These columns are in percent
  units, so show them as plain numbers with the "(%)" header, not with a % format.
- Visual-level filter: `Eval Row Matches Split` is 1 (keeps the split chosen in S1; the `split`
  column must stay in the table). Lock and hide the filter.
- Sort by `month_start` descending. Title: "Monthly evaluation written by the forecast notebook".

V3 MAPE by month:

- X-axis: `gold_dim_date[month_start]`. Y-axis: `Forecast MAPE %` (`#1F77B4`), `Naive MAPE %`
  (`#FF7F0E`). Title: "MAPE by month, LightGBM vs seasonal naive".

V4 MAPE by hour:

- X-axis: `gold_forecast[hour_ending]` (1 to 24, ascending). Y-axis: `Forecast MAPE %`, `Naive MAPE
  %`. Title: "MAPE by hour-ending (EST)".

Interactions (Format > Edit interactions): select S2 Forecast dates and set None on K1 to K5, V2, V3
and V4, so it only zooms V1; the cards keep the error over the whole split. S1 Split filters
everything.

T2 interpretation template:

> Q3. How accurate is the day-ahead forecast compared with actual demand and a naive baseline?
> - Overall: [For the split shown, quote LightGBM MAPE, naive MAPE and the skill. State whether
>   success criterion 6 (skill of at least 30 %) is met.]
> - Peaks: [Quote the peak-hour error and compare it with the overall MAPE.]
> - Where it misses: [Name the months with the highest MAPE and the hours with the highest bars.
>   Check those dates for holidays or extreme weather before naming a cause.]
> - Backtest vs holdout: [Switch the split and say whether the two give similar errors.]
> - Live: [Show tomorrow's forecast curve and say when its actuals will arrive (the next morning,
>   after IESO posts the day).]

---

## 5. Page 4 "Data quality and fleet" (optional)

| ID | Element | Type | Position |
|---|---|---|---|
| T1 | Title | Text box | (16, 8, 700, 48) |
| B1 | Live view (Q4) button | Button | (1064, 16, 200, 40) |
| K1 | DQ Checks Failed | Card | (16, 72, 200, 96) |
| K2 | DQ Checks Warned | Card | (228, 72, 200, 96) |
| K3 | DQ Last Run | Card | (440, 72, 240, 96) |
| K4 | Last Demand Date | Card | (692, 72, 200, 96) |
| K5 | Meter Count | Card | (904, 72, 170, 96) |
| K6 | Active Meters | Card | (1086, 72, 178, 96) |
| V1 | Checks of the latest run | Table | (16, 180, 760, 330) |
| V2 | Rated capacity by site | Clustered bar chart | (788, 180, 476, 330) |
| V3 | Meters by tariff and status | Stacked column chart | (16, 522, 500, 182) |
| T2 | Interpretation | Text box | (528, 522, 736, 182) |

Title T1: "Is the data fresh and complete? What does the meter fleet look like?"

- K1: Callout value colour rule: if value > 0 then `#C62828`, else `#2E7D32`. Label "Failed checks,
  latest run". A failed check means the last run did not refresh silver and gold.
- K2: label "Warnings, latest run". K3: label "DQ last run (UTC)". K4: label "Demand loaded up to
  (EST date)".
- V1 columns from `silver_dq_results`: `run_date`, `table_name`, `check_name`, `status`, `observed`,
  `expected`, `details`. Visual-level filter `Is Latest DQ Run` is 1 (locked, hidden). Conditional
  formatting on `status`: Cell elements > Background colour > Format style Field value > `DQ Status
  Colour`. Sort by `table_name`.
- V2: Y-axis `gold_dim_site[site_name]`, X-axis `Rated Capacity (kW)`, sorted descending; tooltips
  `gold_dim_site[capacity_kw]` and `Meter Count`.
- V3: X-axis `gold_dim_meter[tariff]`, Y-axis `Meter Count`, Legend `gold_dim_meter[status]`.

T2 interpretation template:

> - Freshness: [Quote DQ last run and the last demand date. Is the data one day behind, as the
>   daily schedule intends?]
> - Checks: [How many checks passed, warned, failed. Explain each warning, for example the hour
>   2025-05-01 05:00 UTC that IESO never published.]
> - Fleet: [Number of sites and meters, how many are active, and which sites carry the most rated
>   capacity.]

---

## 6. Question 4: link to the Real-Time Dashboard

Q4 ("Which sites are consuming abnormally right now?") is answered by `rtd_gridpulse`, whose
anomaly tile runs KQL query Q2 (`realtime/kql/q2_anomaly.kql`: a site's last complete minute above
its trailing one-hour mean + 3 standard deviations) on the Eventhouse table `meter_readings`. The
same query drives the Activator alert `act_abnormal_demand`.

1. Open `rtd_gridpulse` in Fabric and copy the URL from the browser address bar.
2. In the report (pages 1 and 4): Insert > Buttons > Blank. Text "Live view (Q4)", fill `#1F77B4`,
   white text. Tooltip: "Which sites are abnormal right now? Opens the Real-Time Dashboard".
3. Format button > Action: on, Type "Web URL", Web URL: the copied link.
4. In edit mode, Ctrl+click tests the button; in reading view a normal click opens the dashboard
   in a new tab.
5. Alternative: a text box with the sentence "Live anomalies: Real-Time Dashboard" and the link set
   on the words (select the text > Insert link).

`rtd_gridpulse` is in the same workspace, so a workspace Viewer can open it. Not built in Fabric yet.

---

## 7. Build checklist for Omar

Before you start:

1. Power BI licence: the first time Fabric asks, click "Start trial" for the free 60-day Power BI
   individual trial. Without it you cannot create the report.
2. Workspace role: a Viewer cannot save new items in `ws_gridpulse`. Ask Nacir (Admin) to give you
   Contributor for the build session (workspace > Manage access), and to set you back to Viewer
   when the report is done, so the Analyst persona is least-privilege for the demo.
3. Check with Hamza that `sm_gridpulse` exists, its measures are in, and the checks of
   `semantic_model_spec.md` section 12 pass.

Build:

4. Workspace `ws_gridpulse` > `sm_gridpulse` > Create a report > Start from scratch (or New item >
   Report > pick `sm_gridpulse` > Create blank report).
5. File > Save as `rpt_gridpulse` in `ws_gridpulse`. Save again after each page.
6. Format page (click an empty area of the canvas) > Canvas settings > Type 16:9. View > Fit to
   page.
7. View > Themes > Customize current theme: put the colours of section 1 in the theme colour slots.
8. Rename "Page 1" to "Peaks and trends"; add and rename "Weather sensitivity", "Forecast vs
   actual", "Data quality and fleet".
9. Build page 1 (section 2): title and subtitle text box, then the slicers, then the five cards,
   then V1 to V4, then the empty interpretation box. Set each position in Format > General >
   Properties > Size and position.
10. Build page 2 (section 3) the same way. Copy the Year and Season slicers from page 1 (Ctrl+C,
    Ctrl+V); choose "Sync" when Power BI asks.
11. View > Sync slicers: for the Year slicer and the Season slicer, tick Sync and Visible for pages 1
    and 2 only. The City slicer exists on page 2 only.
12. Page 2 interactions: select the Year slicer > Format > Edit interactions > click None on V3.
13. Build page 3 (section 4). Split slicer: Format > Slicer settings > Selection > Single select on;
    click `holdout`. Forecast dates slicer: Style Between; pick about one week.
14. Page 3 interactions: select the Forecast dates slicer > Edit interactions > None on K1 to K5,
    V2, V3, V4.
15. Build page 4 (section 5), optional.
16. Visual-level filters (Filters pane > Filters on this visual): page 1 V4 Top N 10; page 2 V4
    `hours` is 24; page 3 V2 `Eval Row Matches Split` is 1; page 4 V1 `Is Latest DQ Run` is 1.
    Lock and hide the last two.
17. Conditional formatting: heatmap (page 1 V1), skill card (page 3 K3), failed checks card (page 4
    K1), DQ status column (page 4 V1).
18. Add the "Live view (Q4)" button on pages 1 and 4 (section 6).
19. Team review: look at the real numbers together, then fill the four interpretation boxes. Write
    only what the visuals show; keep the brackets' questions as the structure.
20. Test as a reader: Nacir sets you back to Viewer; open `rpt_gridpulse`, try every slicer, check
    that no slicer shows a "(Blank)" item, check that the Live view button opens `rtd_gridpulse`.
21. Take one screenshot per page (reading view, full page) for the PDF report and the demo fallback.
22. Export for deliverable 5 (section 9).

---

## 8. Requirements from the brief and where they are met

| Requirement (source) | Where it is met |
|---|---|
| At least 1 Power BI report (guidelines, minimum measurable requirements) | `rpt_gridpulse` |
| At least 4 meaningful visuals (guidelines) | Page 1 V1 to V4, page 2 V1 to V4, page 3 V1 to V4, page 4 V1 to V3 |
| At least 2 KPIs (guidelines); KPIs peak load MW, average daily energy GWh, forecast MAPE % (proposal 9, success criterion 4 asks for 3) | Page 1 K1 `Peak Load (MW)`, K2 `Avg Daily Energy (GWh)`; page 3 K1 `Forecast MAPE %` |
| At least 1 interactive filter / slicer (guidelines); slicers year / season / city (proposal 9) | Year and Season on pages 1 and 2, City on page 2, Split and Forecast dates on page 3 |
| KPIs, trends, categorical comparisons, filters/slicers and business interpretation (component F) | Cards; trend on page 1 V2 and page 2 V3; comparisons by season, city, year, model vs naive; one interpretation box per page |
| The dashboard must answer explicit questions, not only display charts (component F) | Each page title is the question; each interpretation box answers it |
| Proposal visual: trend line | Page 1 V2 |
| Proposal visual: load vs temperature scatter | Page 2 V1 |
| Proposal visual: hour x weekday heatmap | Page 1 V1 |
| Proposal visual: forecast vs actual line | Page 3 V1 |
| Answer questions 1 to 4 (success criterion 4) | Q1 page 1, Q2 page 2, Q3 page 3, Q4 `rtd_gridpulse` through the Live view button |
| Forecast beats seasonal-naive MAPE by at least 30 % (success criterion 6) | Page 3 K3 with the 30 % rule and the `Skill vs Target` label |
| Store predictions in an analytical table so Power BI can compare observed vs predicted (guidelines, ML section) | `gold_forecast` and `gold_forecast_eval` on page 3 |
| Quality checks (rubric, Spark processing) made visible | Page 4 V1 and K1 to K4 from `silver_dq_results` |
| Power BI report as PBIX or Fabric report (deliverable 5) | Fabric link plus `.pbix` / `.pbip` export, section 9 |
| Open the report and answer at least two business questions (demo step 5) | Pages 1 to 3 |
| Analyst persona with least privilege, no PII (guidelines section 4) | Omar is Viewer and sees only `sm_gridpulse` and this report; the model holds gold tables and `silver_dq_results`, no personal data |

---

## 9. Export for deliverable 5

1. Fabric link: open `rpt_gridpulse`, copy the browser URL into the README and the PDF report.
2. PBIX: in the open report, File > Download this file > "A copy of your report with a live
   connection to data online (.pbix)" > Download. Save it as `powerbi/rpt_gridpulse.pbix`. The file
   holds the report layout and a live connection to `sm_gridpulse`, not the data, so committing it
   does not redistribute IESO files. Opening it needs Power BI Desktop and a UIR account that can
   read `sm_gridpulse`.
3. PBIP (text files, readable in Git): open the `.pbix` in Power BI Desktop > File > Save as > Save
   as type "Power BI project files (*.pbip)" > `powerbi/rpt_gridpulse.pbip`. Desktop writes a
   `rpt_gridpulse.Report/` folder next to it. If the file type is missing, enable it under File >
   Options and settings > Options > Preview features. If the workspace is connected to GitHub
   (PLAN T1F.5), committing from the workspace Source control panel writes the same
   `rpt_gridpulse.Report/` folder.
4. Semantic model: a Direct Lake model is not downloaded as `.pbix`; its definition is exported in
   TMDL (`semantic_model_spec.md`, click step 13).
5. If "Download this file" is unavailable in the tenant, keep the Fabric link, the Git (PBIP)
   export and the page screenshots (PLAN T7.6). File > Export > PDF gives a static copy of all
   pages for the report appendix.

---

## 10. Limits to state in the report

- Nothing in this spec has run in Fabric yet; the measures were written against the gold schemas
  and checked on a local run only.
- Hours are EST hour-ending, not Toronto clock time; in summer the clock reads one hour later.
- The temperature curve (page 2 V2) covers the whole history and ignores the year slicer.
- The City slicer changes only the city weather visual: demand is published for Ontario as a whole.
- The forecast page must show one split at a time: `backtest` and `holdout` cover the same 2026
  hours.
- Question 4 is answered outside this report, in `rtd_gridpulse`, because live readings live in
  the Eventhouse.
