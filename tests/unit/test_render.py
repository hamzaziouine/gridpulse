"""infra/fabric/render.py: tokens, pipeline validation, environment assembly (offline)."""

from __future__ import annotations

import copy
import importlib.util
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("render", ROOT / "infra" / "fabric" / "render.py")
assert spec and spec.loader
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)
DAILY = ROOT / "fabric" / "pl_daily_ingest.DataPipeline" / "pipeline-content.json"
BACKFILL = ROOT / "fabric" / "pl_backfill.DataPipeline" / "pipeline-content.json"


@pytest.fixture
def wheel(tmp_path: Path) -> Path:
    w = tmp_path / "gridpulse-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(w, "w") as z:
        z.writestr("gridpulse/__init__.py", "__version__ = '0.0.0'\n")
    return w


def values(**extra):
    return render.computed(date(2026, 11, 22)) | render.dry_run_ids() | extra


def test_dry_run_renders_every_item_without_tokens(tmp_path: Path, wheel: Path) -> None:
    items = render.render_all(values(), tmp_path / "out", wheel)
    names = {p.name for p in items}
    assert {"nb_bronze.Notebook", "nb_silver.Notebook", "nb_gold.Notebook",
            "nb_forecast.Notebook", "nb_predict.Notebook", "pl_daily_ingest.DataPipeline",
            "pl_backfill.DataPipeline", "env_gridpulse.Environment"} <= names  # fmt: skip
    for f in (tmp_path / "out").rglob("*"):
        if f.is_file() and f.suffix in (".py", ".json", ".yml"):
            assert "{{" not in f.read_text(encoding="utf-8"), f
    libs = tmp_path / "out/env_gridpulse.Environment/Libraries/CustomLibraries"
    assert (libs / wheel.name).exists()


def test_backfill_counts_are_ints_and_query_matches_config(tmp_path: Path, wheel: Path) -> None:
    render.render_all(values(), tmp_path / "out", wheel)
    body = json.loads((tmp_path / "out/pl_backfill.DataPipeline/pipeline-content.json").read_text())
    params = body["properties"]["parameters"]
    assert params["year_count"]["defaultValue"] == 8  # 2019..2026
    assert params["month_count"]["defaultValue"] == 95  # 2019-01..2026-11
    daily = (tmp_path / "out/pl_daily_ingest.DataPipeline/pipeline-content.json").read_text()
    assert "models=gfs_seamless" in daily and "latitude=43.65,45.42" in daily


def test_without_outlook_connection_the_mail_is_dropped(tmp_path: Path, wheel: Path) -> None:
    v = values()
    del v["CONN_OUTLOOK"]
    render.render_all(v, tmp_path / "out", wheel)
    body = json.loads(
        (tmp_path / "out/pl_daily_ingest.DataPipeline/pipeline-content.json").read_text()
    )
    acts = {a["name"]: a for a in body["properties"]["activities"]}
    assert "mail_failure" not in acts
    assert acts["fail_pipeline"]["dependsOn"] == [
        {"activity": "nb_predict", "dependencyConditions": ["Failed", "Skipped"]}]  # fmt: skip


def test_validation_catches_broken_wiring() -> None:
    src = json.loads(DAILY.read_text())
    body = json.loads(render.render_text(json.dumps(src), values()))
    assert render.validate_pipeline(body) == []
    broken = copy.deepcopy(body)
    broken["properties"]["activities"][-3]["dependsOn"][0]["activity"] = "nb_typo"
    assert any("unknown 'nb_typo'" in e for e in render.validate_pipeline(broken))
    bad_conn = json.loads(render.render_text(json.dumps(src), values(CONN_SQL="not-a-guid")))
    assert any("not a GUID" in e for e in render.validate_pipeline(bad_conn))


def test_unresolved_and_missing_tokens_fail(tmp_path: Path, wheel: Path) -> None:
    with pytest.raises(ValueError, match="unresolved"):
        render.render_text("id {{NOPE}}", {})
    v = values()
    del v["LAKEHOUSE_ID"]
    with pytest.raises(ValueError, match="missing values"):
        render.render_all(v, tmp_path / "out", wheel)


def test_daily_pipeline_shape() -> None:
    body = json.loads(DAILY.read_text())
    acts = {a["name"]: a for a in body["properties"]["activities"]}
    chain = ["nb_bronze", "nb_silver", "nb_gold", "nb_predict"]
    for prev, nxt in zip(chain, chain[1:], strict=False):
        assert acts[nxt]["dependsOn"] == [{"activity": prev, "dependencyConditions": ["Succeeded"]}]
    bronze_deps = {d["activity"] for d in acts["nb_bronze"]["dependsOn"]}
    assert bronze_deps == {"cp_ieso_demand", "cp_openmeteo_history", "cp_openmeteo_forecast",
                           "cp_openmeteo_prevruns", "fe_sql_reference"}  # fmt: skip
    assert acts["nb_bronze"]["typeProperties"]["parameters"]["full_refresh"]["value"] is False
    assert acts["mail_failure"]["dependsOn"][0]["dependencyConditions"] == ["Failed", "Skipped"]
    prev = acts["cp_openmeteo_prevruns"]["typeProperties"]
    url = prev["source"]["datasetSettings"]["typeProperties"]["location"]["relativeUrl"]["value"]
    assert "{{PREVRUNS_QUERY}}" in url and "v_month_start" in url and "v_data_day" in url
    assert prev["source"]["datasetSettings"]["externalReferences"]["connection"] == (
        "{{CONN_OPENMETEO_PREV}}"
    )
    sink = prev["sink"]["datasetSettings"]["typeProperties"]["location"]
    assert sink["folderPath"] == "bronze/openmeteo_prevruns"


def test_backfill_pulls_previous_runs_and_trains_on_matched_weather() -> None:
    body = json.loads(BACKFILL.read_text())
    acts = {a["name"]: a for a in body["properties"]["activities"]}
    assert "fe_prevruns_months" in {d["activity"] for d in acts["nb_bronze"]["dependsOn"]}
    fe = acts["fe_prevruns_months"]["typeProperties"]
    assert fe["isSequential"] is True
    assert "prevruns_month_count" in fe["items"]["value"]
    params = body["properties"]["parameters"]
    assert params["prevruns_start_month"]["defaultValue"] == "2024-01-01"
    nb = acts["nb_forecast"]["typeProperties"]["parameters"]
    assert nb["train_weather"]["value"] == "matched"


def test_prevruns_tokens_render() -> None:
    v = render.computed(date(2026, 11, 22))
    assert v["PREVRUNS_MONTHS"] == 35  # 2024-01 .. 2026-11
    assert "temperature_2m_previous_day1" in v["PREVRUNS_QUERY"]
    assert "snowfall_previous_day2" in v["PREVRUNS_QUERY"]
    assert "start_date" not in v["PREVRUNS_QUERY"]
    body = json.loads(render.render_text(BACKFILL.read_text(), values()))
    assert body["properties"]["parameters"]["prevruns_month_count"]["defaultValue"] == 35


def test_kql_file_splits_into_three_idempotent_commands() -> None:
    spec2 = importlib.util.spec_from_file_location("run_kql", ROOT / "infra/fabric/run_kql.py")
    assert spec2 and spec2.loader
    run_kql = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(run_kql)
    cmds = run_kql.split_commands((ROOT / "realtime/kql/00_tables.kql").read_text("utf-8"))
    assert [c.split()[0] for c in cmds] == [".create-merge", ".create-or-alter", ".alter-merge"]
    assert "meter_readings_json" in cmds[1] and "7d" in cmds[2]


def test_environment_pins_runtime_13_and_a_small_pool(tmp_path: Path, wheel: Path) -> None:
    # Without Setting/Sparkcompute.yml Fabric chose runtime 2.0 on 2026-11-23 and the
    # environment publish failed (sparkLibraries Failed): the wheel targets Python 3.11.
    render.render_all(values(), tmp_path / "out", wheel)
    env = tmp_path / "out" / "env_gridpulse.Environment"
    s = render.parse_sparkcompute((env / "Setting" / "Sparkcompute.yml").read_text("utf-8"))
    assert s["runtime_version"] == "1.3"
    assert (s["driver_cores"], s["driver_memory"]) == ("4", "28g")
    assert (s["executor_cores"], s["executor_memory"]) == ("4", "28g")
    assert s["dynamic_executor_allocation.enabled"] == "true"
    assert s["dynamic_executor_allocation.min_executors"] == "1"
    assert s["dynamic_executor_allocation.max_executors"] == "2"
    assert "instance_pool_id" not in s  # starter pool
    assert (env / "Libraries" / "CustomLibraries" / wheel.name).exists()
    assert render.validate_environment(env) == []


def test_environment_validation_rejects_a_wrong_runtime_or_missing_file(tmp_path: Path) -> None:
    item = tmp_path / "env_x.Environment"
    assert "missing" in render.validate_environment(item)[0]
    (item / "Setting").mkdir(parents=True)
    src = ROOT / "fabric" / "env_gridpulse.Environment" / "Setting" / "Sparkcompute.yml"
    text = src.read_text("utf-8").replace("runtime_version: 1.3", "runtime_version: 2.0")
    text = text.replace("max_executors: 2", "max_executors: 0").replace("28g", "30g")
    (item / "Setting" / "Sparkcompute.yml").write_text(text, "utf-8")
    errors = " ".join(render.validate_environment(item))
    assert "runtime_version must be 1.3" in errors
    assert "min_executors <= max_executors" in errors
    assert "driver_memory" in errors and "executor_memory" in errors
