"""Bronze, silver, gold and quality checks on the 6-day lake fixture (real IESO and Open-Meteo
excerpts around the real 2025-05-01 HE1 gap), with a local SparkSession."""

from __future__ import annotations

import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from tests.conftest import LAKE

pytestmark = pytest.mark.spark
RUN = date(2025, 5, 5)
INGESTED = datetime(2025, 5, 5, 13, 15, tzinfo=UTC)


@pytest.fixture(scope="module")
def frames(spark):
    from gridpulse.medallion import bronze, silver
    from gridpulse.medallion.common import cities_frame

    cities = cities_frame(spark)
    ieso_files = sorted(str(p) for p in (LAKE / "ieso").glob("*.csv"))
    om_files = sorted(str(p) for p in (LAKE / "openmeteo").glob("*.json"))
    b_ieso = bronze.read_ieso(spark, ieso_files, INGESTED, RUN).cache()
    b_om = bronze.read_openmeteo(spark, om_files, cities, INGESTED, RUN).cache()
    demand = silver.demand_hourly(b_ieso).cache()
    wx_city = silver.weather_city_hourly(b_om).cache()
    wx_ont = silver.weather_ontario_hourly(wx_city, cities).cache()
    dw = silver.demand_weather_hourly(demand, wx_ont).cache()
    return {"cities": cities, "b_ieso": b_ieso, "b_om": b_om, "demand": demand,
            "wx_city": wx_city, "wx_ont": wx_ont, "dw": dw}  # fmt: skip


def epoch(df, col="target_time"):
    from pyspark.sql import functions as F

    return [datetime.fromtimestamp(r[0], UTC) for r in df.select(F.unix_seconds(col)).collect()]


def test_bronze_ieso_parses_rows_and_lineage(frames) -> None:
    b = frames["b_ieso"]
    assert b.count() == 143
    row = b.orderBy("local_date", "hour_ending").first()
    assert (row["local_date"], row["hour_ending"], row["ontario_demand_mw"]) == (
        date(2025, 4, 28), 1, 12776.0)  # fmt: skip
    assert row["source_file"] == "PUB_Demand_2025_v396.csv"
    assert row["source_year"] == 2025 and row["file_version"] == "v396"
    created = epoch(b.limit(1), "file_created_at")[0]
    assert created == datetime(2026, 1, 31, 12, 30, 13, tzinfo=UTC)  # 07:30:13 EST


def test_bronze_openmeteo_one_row_per_city_hour(frames) -> None:
    b = frames["b_om"]
    assert b.count() == 149 * 5
    assert b.where("city_key IS NULL").count() == 0
    assert {r[0] for r in b.select("city_key").distinct().collect()} == {
        "toronto", "ottawa", "london", "windsor", "sudbury"}  # fmt: skip
    first = epoch(b.orderBy("valid_time").limit(1), "valid_time")[0]
    assert first == datetime(2025, 4, 28, 0, tzinfo=UTC)


def test_silver_target_time_is_hour_ending_in_fixed_est(frames) -> None:
    from pyspark.sql import functions as F

    d = frames["demand"]
    he1 = d.where((F.col("est_date") == date(2025, 4, 28)) & (F.col("hour_ending") == 1))
    he24 = d.where((F.col("est_date") == date(2025, 4, 28)) & (F.col("hour_ending") == 24))
    assert epoch(he1) == [datetime(2025, 4, 28, 5, tzinfo=UTC)]  # EDT season, still UTC-5
    assert epoch(he24) == [datetime(2025, 4, 29, 4, tzinfo=UTC)]


def test_silver_newest_revision_wins(spark, frames, tmp_path: Path) -> None:
    """An older version of the same year with different values must lose the dedupe."""
    from gridpulse.medallion import bronze, silver

    src = next((LAKE / "ieso").glob("*.csv"))
    old = tmp_path / "PUB_Demand_2025_v300.csv"
    text = src.read_text(encoding="utf-8")
    text = text.replace("Created at 2026-01-31", "Created at 2025-06-01")
    old.write_text(text.replace("2025-04-28,1,16048,12776", "2025-04-28,1,16048,99999"), "utf-8")
    b = bronze.read_ieso(spark, [str(src), str(old)], INGESTED, RUN)
    assert b.count() == 286
    d = silver.demand_hourly(b)
    assert d.count() == 143
    first = d.orderBy("target_time").first()
    assert first["ontario_demand_mw"] == 12776.0 and first["source_file"] == src.name


def test_weighted_temperature_matches_manual_weights(frames) -> None:
    from pyspark.sql import functions as F

    from gridpulse.config import CITIES

    t0 = datetime(2025, 4, 30, 18, tzinfo=UTC)
    per_city = {r["city_key"]: r["temperature_2m"] for r in
                frames["wx_city"].where(F.col("valid_time") == F.lit(t0)).collect()}  # fmt: skip
    expected = sum(c.weight * per_city[c.key] for c in CITIES) / sum(c.weight for c in CITIES)
    row = frames["wx_ont"].where(F.col("valid_time") == F.lit(t0)).first()
    assert row["temperature_2m_w"] == pytest.approx(expected)
    assert row["n_cities"] == 5
    assert row["hdd_w"] == pytest.approx(max(0.0, 18 - expected))
    assert row["temperature_2m_toronto"] == per_city["toronto"]


def test_quality_known_gap_warns_and_unknown_gap_fails(spark, frames) -> None:
    from pyspark.sql import functions as F

    from gridpulse.medallion import quality

    res = {r.check_name: r for r in quality.check_demand(frames["b_ieso"], frames["demand"], RUN)}
    assert res["hourly_gaps"].status == "WARN" and res["hourly_gaps"].observed == 1
    assert res["hours_per_day_24"].status == "WARN"
    assert res["unique_target_time"].status == "PASS"
    assert res["freshness_days"].status == "PASS"  # newest day 2025-05-03, run 2025-05-05

    holed = frames["demand"].where(
        ~((F.col("est_date") == date(2025, 4, 29)) & (F.col("hour_ending") == 12))
    )
    res2 = {r.check_name: r for r in quality.check_demand(frames["b_ieso"], holed, RUN)}
    assert res2["hourly_gaps"].status == "FAIL" and res2["hourly_gaps"].observed == 2
    assert res2["hours_per_day_24"].status == "FAIL"

    late_checks = quality.check_demand(frames["b_ieso"], frames["demand"], date(2025, 5, 20))
    late = {r.check_name: r for r in late_checks}
    assert late["freshness_days"].status == "FAIL"


def test_quality_weather_and_join(frames) -> None:
    from gridpulse.medallion import quality

    w = {r.check_name: r for r in quality.check_weather(frames["b_om"], frames["wx_city"])}
    assert all(r.status == "PASS" for r in w.values()), w
    j = quality.check_join(frames["dw"])[0]
    assert j.status == "PASS" and j.observed == 0


def test_pseudonymisation_removes_pii(spark) -> None:
    from gridpulse import reference
    from gridpulse.medallion import quality, silver

    folder = str(Path(__file__).parents[2] / "data" / "reference")
    b_sites, b_cust, b_met = (reference.read_csv(spark, folder, t) for t in reference.LOAD_ORDER)
    c1 = silver.customers_pseudo(b_cust, "salt-a")
    m1 = silver.meters(b_met, "salt-a")
    c2 = silver.customers_pseudo(b_cust, "salt-b")
    assert not set(silver.PII_COLUMNS) & set(c1.columns + m1.columns)
    h1 = {r[0] for r in c1.select("customer_hash").collect()}
    assert len(h1) == 50 and all(len(h) == 64 for h in h1)
    assert h1.isdisjoint({r[0] for r in c2.select("customer_hash").collect()})  # salt matters
    assert {r[0] for r in m1.select("customer_hash").collect()} <= h1  # joinable
    checks = quality.check_reference(silver.sites(b_sites), b_met, b_cust, c1, m1)
    assert all(r.status == "PASS" for r in checks), checks


def test_gold_daily_energy_peak_and_onpeak(spark, frames) -> None:
    from pyspark.sql import functions as F

    from gridpulse.dims import date_dimension
    from gridpulse.medallion import gold

    dim = spark.createDataFrame(date_dimension(date(2025, 4, 28), date(2025, 5, 10)))
    hourly = gold.demand_hourly(frames["dw"], dim).cache()
    daily = gold.demand_daily(hourly).where(F.col("est_date") == date(2025, 4, 29)).first()
    raw = frames["demand"].where(F.col("est_date") == date(2025, 4, 29))
    mw = [r[0] for r in raw.select("ontario_demand_mw").collect()]
    assert daily["hours"] == 24 and daily["is_complete_day"]
    assert daily["energy_gwh"] == pytest.approx(sum(mw) / 1000)
    assert daily["peak_mw"] == max(mw)
    onpeak = hourly.where((F.col("est_date") == date(2025, 4, 29)) & F.col("is_onpeak")).count()
    assert onpeak == 16  # Tuesday, HE8..HE23
    weekend = hourly.where((F.col("est_date") == date(2025, 5, 3)) & F.col("is_onpeak")).count()
    assert weekend == 0
    gap_day = gold.demand_daily(hourly).where(F.col("est_date") == date(2025, 5, 1)).first()
    assert gap_day["hours"] == 23 and not gap_day["is_complete_day"]


def test_gold_top_peaks_and_sensitivity(spark, frames) -> None:
    from gridpulse.dims import date_dimension
    from gridpulse.medallion import gold

    dim = spark.createDataFrame(date_dimension(date(2025, 4, 28), date(2025, 5, 10)))
    hourly = gold.demand_hourly(frames["dw"], dim)
    top = gold.top_peaks(hourly, fraction=0.05).orderBy("peak_rank").collect()
    mw = sorted((r[0] for r in hourly.select("ontario_demand_mw").collect()), reverse=True)
    assert top[0]["ontario_demand_mw"] == mw[0] and top[0]["peak_rank"] == 1
    assert 5 <= len(top) <= 10  # ~5 % of 143 hours
    bins = gold.temp_sensitivity(hourly)
    assert bins.agg({"hours": "sum"}).first()[0] == 143


def test_local_store_replace_semantics(spark, tmp_path: Path) -> None:
    from gridpulse.lakehouse import LocalStore

    store = LocalStore(spark, tmp_path / "Tables", tmp_path / "Files")
    a = spark.createDataFrame([("a.csv", 1), ("b.csv", 2)], "source_file string, v int")
    store.write(a, "t")
    store.write(spark.createDataFrame([("b.csv", 20)], "source_file string, v int"), "t",
                replace={"source_file": ["b.csv"]})  # fmt: skip
    got = sorted(tuple(r) for r in store.read("t").collect())
    assert got == [("a.csv", 1), ("b.csv", 20)]
    store.write(spark.createDataFrame([("b.csv", 20)], "source_file string, v int"), "t",
                replace={"source_file": ["b.csv"]})  # fmt: skip
    assert store.read("t").count() == 2  # rerun: no duplicate


def test_notebooks_end_to_end_on_fixture(spark, tmp_path: Path, monkeypatch) -> None:
    """nb_bronze -> nb_silver -> nb_gold exactly as Fabric runs them, on the fixture, twice:
    the second (daily, non-full) run must not change any row count (success criterion 1)."""
    from gridpulse import reference
    from gridpulse.lakehouse import LocalStore
    from gridpulse.notebook import run_notebook

    root = Path(__file__).parents[2]
    files = tmp_path / "Files"
    for sub in ("ieso", "openmeteo", "openmeteo_prevruns"):
        shutil.copytree(LAKE / sub, files / "bronze" / sub)
    store = LocalStore(spark, tmp_path / "Tables", files)
    for t in reference.LOAD_ORDER:
        store.write(reference.read_csv(spark, str(root / "data" / "reference"), t), f"bronze_{t}")
    monkeypatch.setenv("GRIDPULSE_HASH_SALT", "test-salt")
    ns = {"spark": spark, "store": store, "display": lambda *a, **k: None}

    def run(name: str, **params):
        nb = root / "fabric" / f"nb_{name}.Notebook" / "notebook-content.py"
        return run_notebook(nb, {"run_date": "2025-05-04", **params}, dict(ns))

    run("bronze", full_refresh=True)
    silver_ns = run("silver")
    run("gold")
    statuses = {r.check_name: r.status for r in silver_ns["results"]}
    assert statuses["hourly_gaps"] == "WARN" and "FAIL" not in statuses.values()
    tables = ["bronze_ieso_demand", "bronze_openmeteo_hourly", "silver_demand_hourly",
              "silver_demand_weather_hourly", "gold_demand_hourly", "gold_demand_daily",
              "gold_dim_date", "gold_dim_meter", "silver_dq_results",
              "bronze_openmeteo_prevruns", "silver_weather_prevruns_ontario"]  # fmt: skip
    counts = {t: store.read(t).count() for t in tables}
    assert counts["silver_demand_hourly"] == 143 and counts["gold_demand_daily"] == 6
    assert counts["bronze_openmeteo_prevruns"] == 149 * 5 * 2
    assert counts["silver_weather_prevruns_ontario"] == 149 * 2
    assert statuses["coverage"] == "PASS"

    # Daily rerun of the same run_date: same counts, no duplicates anywhere.
    run("bronze", full_refresh=False)
    run("silver")
    run("gold")
    assert {t: store.read(t).count() for t in tables} == counts


def _prevruns(spark, files: list[str]):
    from gridpulse.medallion import bronze, silver
    from gridpulse.medallion.common import cities_frame

    cities = cities_frame(spark)
    b = bronze.read_openmeteo_prevruns(spark, files, cities, INGESTED, RUN).cache()
    city = silver.weather_prevruns_city(b).cache()
    ont = silver.weather_prevruns_ontario(city, cities).cache()
    return b, city, ont


def _ontario_pandas(ont, lead: int):
    import pandas as pd
    from pyspark.sql import functions as F

    from gridpulse.features import WEATHER_COLUMNS

    rows = ont.where(F.col("lead_days") == lead).select(
        F.unix_seconds("valid_time").alias("s"), *WEATHER_COLUMNS
    )
    pdf = rows.toPandas().sort_values("s").reset_index(drop=True)
    pdf.insert(0, "valid_time", pd.to_datetime(pdf.pop("s"), unit="s", utc=True))
    return pdf


def test_prevruns_bronze_silver_match_the_pandas_aggregation(spark) -> None:
    """Spark silver_weather_prevruns_ontario == gridpulse.weather_lead.load_prevruns (the code the
    lead-matched backtest used), for both leads, every weather column."""
    import numpy as np

    from gridpulse import weather_lead as wl
    from gridpulse.features import WEATHER_COLUMNS
    from gridpulse.medallion import quality

    files = sorted(str(p) for p in (LAKE / "openmeteo_prevruns").glob("*.json"))
    b, city, ont = _prevruns(spark, files)
    assert b.count() == 149 * 5 * 2 and b.where("city_key IS NULL").count() == 0
    assert {r[0] for r in b.select("lead_days").distinct().collect()} == {1, 2}
    for lead in (1, 2):
        got = _ontario_pandas(ont, lead)
        ref = wl.load_prevruns(LAKE / "openmeteo_prevruns", lead)
        assert got["valid_time"].tolist() == ref["valid_time"].tolist()
        np.testing.assert_allclose(
            got[list(WEATHER_COLUMNS)].to_numpy(dtype=float),
            ref[list(WEATHER_COLUMNS)].to_numpy(dtype=float),
            rtol=1e-12,
            atol=1e-9,
        )
    checks = {r.check_name: r.status for r in quality.check_prevruns(b, city, ont, RUN)}
    assert set(checks.values()) == {"PASS"}, checks


def test_prevruns_incomplete_hours_stay_null(spark, tmp_path: Path) -> None:
    """A variable missing for one city nulls that Ontario aggregate (and HDD/CDD when it is the
    temperature) instead of averaging over the other cities; the other columns stay."""
    import json

    import numpy as np

    src = LAKE / "openmeteo_prevruns" / "2025-04.json"
    payload = json.loads(src.read_text(encoding="utf-8"))
    payload[0]["hourly"]["snowfall_previous_day1"][:3] = [None] * 3  # Toronto, 00..02Z
    payload[1]["hourly"]["temperature_2m_previous_day1"][5] = None  # Ottawa, 05Z
    bad = tmp_path / "2025-04.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    _, _, ont = _prevruns(spark, [str(bad)])
    d1 = _ontario_pandas(ont, 1)
    assert d1["snowfall_w"].iloc[:3].isna().all() and d1["snowfall_w"].iloc[3:].notna().all()
    assert np.isnan(d1.loc[5, ["temperature_2m_w", "temperature_2m_mean", "hdd_w", "cdd_w"]]
                    .to_numpy(dtype=float)).all()  # fmt: skip
    assert d1.loc[5, "wind_speed_10m_w"] == d1.loc[5, "wind_speed_10m_w"]  # not NaN
    d2 = _ontario_pandas(ont, 2)
    assert d2[list(d2.columns[1:])].notna().all().all()
