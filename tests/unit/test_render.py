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
                           "fe_sql_reference"}  # fmt: skip
    assert acts["nb_bronze"]["typeProperties"]["parameters"]["full_refresh"]["value"] is False
    assert acts["mail_failure"]["dependsOn"][0]["dependencyConditions"] == ["Failed", "Skipped"]


def test_kql_file_splits_into_three_idempotent_commands() -> None:
    spec2 = importlib.util.spec_from_file_location("run_kql", ROOT / "infra/fabric/run_kql.py")
    assert spec2 and spec2.loader
    run_kql = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(run_kql)
    cmds = run_kql.split_commands((ROOT / "realtime/kql/00_tables.kql").read_text("utf-8"))
    assert [c.split()[0] for c in cmds] == [".create-merge", ".create-or-alter", ".alter-merge"]
    assert "meter_readings_json" in cmds[1] and "7d" in cmds[2]
