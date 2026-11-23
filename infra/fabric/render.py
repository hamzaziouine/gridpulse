"""Render the Fabric item definitions in fabric/ into build/fabric/, ready for `fab import`.

The sources in fabric/ hold `{{TOKEN}}` placeholders for ids that only exist after deployment
(workspace, lakehouse, environment, notebooks, connections). deploy_fabric.ps1 collects the ids
into infra/fabric/ids.local.json (git-ignored) and calls this script; `--dry-run` uses fixed fake
GUIDs instead so the whole chain can be checked offline. Rendering fails if any token is left,
if a pipeline activity depends on an activity that does not exist, or if an id is not a GUID.

    uv run python infra/fabric/render.py --dry-run
    uv run python infra/fabric/render.py --ids infra/fabric/ids.local.json --wheel dist/<wheel>
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "fabric"
OUT = ROOT / "build" / "fabric"
sys.path.insert(0, str(ROOT / "src"))

ID_TOKENS = (
    "WORKSPACE_ID", "LAKEHOUSE_ID", "ENVIRONMENT_ID",
    "NB_BRONZE_ID", "NB_SILVER_ID", "NB_GOLD_ID", "NB_FORECAST_ID", "NB_PREDICT_ID",
    "CONN_IESO_HTTP", "CONN_OPENMETEO_HIST", "CONN_OPENMETEO_FC", "CONN_SQL", "CONN_OUTLOOK",
)  # fmt: skip
TEXT_TOKENS = ("ALERT_TO", "SQL_DATABASE")
NUMERIC_TOKENS = ("BACKFILL_YEARS", "BACKFILL_MONTHS")
GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
TOKEN_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
OPTIONAL = {"CONN_OUTLOOK"}  # created in the UI; without it the mail activity is dropped


def computed(today: date) -> dict[str, Any]:
    from gridpulse.config import FIRST_YEAR
    from gridpulse.openmeteo import base_params

    return {
        "OPENMETEO_QUERY": urllib.parse.urlencode(base_params(), safe=",:"),
        "BACKFILL_YEARS": today.year - FIRST_YEAR + 1,
        "BACKFILL_MONTHS": (today.year - FIRST_YEAR) * 12 + today.month,
        "SQL_DATABASE": "sqldb-hz2611-gridpulse",
    }


def dry_run_ids() -> dict[str, Any]:
    ids = {t: f"00000000-0000-4000-8000-{i:012d}" for i, t in enumerate(ID_TOKENS, 1)}
    # Real addresses come from infra/local.settings.json through ids.local.json (deploy_fabric.ps1).
    return ids | {"ALERT_TO": "alerts@example.com"}


def render_text(text: str, values: dict[str, Any]) -> str:
    for name in NUMERIC_TOKENS:
        if name in values:
            text = text.replace(f'"{{{{{name}}}}}"', str(int(values[name])))
    text = TOKEN_RE.sub(lambda m: str(values.get(m.group(1), m.group(0))), text)
    left = sorted(set(TOKEN_RE.findall(text)))
    if left:
        raise ValueError(f"unresolved tokens: {left}")
    return text


def _walk(activities: list[dict], scope: str, errors: list[str]) -> None:
    names = [a["name"] for a in activities]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        errors.append(f"{scope}: duplicate activity names {sorted(dupes)}")
    for a in activities:
        for d in a.get("dependsOn", []):
            if d["activity"] not in names:
                errors.append(f"{scope}/{a['name']}: depends on unknown {d['activity']!r}")
        tp = a.get("typeProperties", {})
        if a["type"] == "TridentNotebook":
            for key in ("notebookId", "workspaceId"):
                if not GUID_RE.match(str(tp.get(key, ""))):
                    errors.append(f"{scope}/{a['name']}: {key} is not a GUID")
        for inner in ("activities", "ifTrueActivities", "ifFalseActivities"):
            if inner in tp:
                _walk(tp[inner], f"{scope}/{a['name']}", errors)


def _connections(obj: Any, errors: list[str], path: str = "") -> None:
    if isinstance(obj, dict):
        conn = obj.get("externalReferences", {}).get("connection")
        if conn is not None and not GUID_RE.match(str(conn)):
            errors.append(f"{path}: connection {conn!r} is not a GUID")
        for k, v in obj.items():
            _connections(v, errors, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _connections(v, errors, f"{path}[{i}]")


def validate_pipeline(body: dict) -> list[str]:
    errors: list[str] = []
    _walk(body["properties"]["activities"], "pipeline", errors)
    _connections(body, errors)
    return errors


def drop_alert_mail(body: dict) -> dict:
    """No Outlook connection yet: remove the mail and let the Fail activity follow the last
    notebook directly (the run still shows as failed in the Monitor hub)."""
    acts = body["properties"]["activities"]
    mail = next(a for a in acts if a["name"] == "mail_failure")
    fail = next(a for a in acts if a["name"] == "fail_pipeline")
    fail["dependsOn"] = mail["dependsOn"]
    body["properties"]["activities"] = [a for a in acts if a["name"] != "mail_failure"]
    return body


def render_all(values: dict[str, Any], out: Path = OUT, wheel: Path | None = None,
               src: Path = SRC) -> list[Path]:  # fmt: skip
    missing = [t for t in (*ID_TOKENS, *TEXT_TOKENS) if t not in values and t not in OPTIONAL]
    if missing:
        raise ValueError(f"missing values: {missing}")
    with_mail = bool(values.get("CONN_OUTLOOK"))
    if out.exists():
        shutil.rmtree(out)
    items = []
    for item in sorted(p for p in src.iterdir() if p.is_dir() and "." in p.name):
        dest = out / item.name
        for f in sorted(item.rglob("*")):
            if not f.is_file():
                continue
            target = dest / f.relative_to(item)
            target.parent.mkdir(parents=True, exist_ok=True)
            if f.name == "pipeline-content.json":
                body = json.loads(f.read_text(encoding="utf-8"))
                if not with_mail:
                    body = drop_alert_mail(body)
                text = render_text(json.dumps(body, indent=2), values)
                body = json.loads(text)
                errors = validate_pipeline(body)
                if errors:
                    raise ValueError(f"{item.name}: " + "; ".join(errors))
                target.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
            elif f.suffix in (".py", ".json", ".yml", ".yaml", ".tmdl", ".pbism", ".pbir"):
                target.write_text(render_text(f.read_text(encoding="utf-8"), values), "utf-8")
            else:
                shutil.copy2(f, target)
        if item.name.endswith(".Environment"):
            if wheel is None:
                raise ValueError("the environment needs the gridpulse wheel (--wheel)")
            libs = dest / "Libraries" / "CustomLibraries"
            libs.mkdir(parents=True, exist_ok=True)
            shutil.copy2(wheel, libs / wheel.name)
        items.append(dest)
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--ids", type=Path, help="ids.local.json written by deploy_fabric.ps1")
    src.add_argument("--dry-run", action="store_true", help="fake GUIDs, offline check")
    ap.add_argument("--wheel", type=Path, help="gridpulse wheel (default: newest in dist/)")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    values = computed(date.today())
    values |= dry_run_ids() if a.dry_run else json.loads(a.ids.read_text(encoding="utf-8-sig"))
    wheel = a.wheel or max((ROOT / "dist").glob("gridpulse-*.whl"), default=None,
                           key=lambda p: p.stat().st_mtime)  # fmt: skip
    for p in render_all(values, a.out, wheel):
        n = sum(1 for f in p.rglob("*") if f.is_file())
        print(f"{p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}: {n} file(s)")
    print(f"alert mail: {'on' if values.get('CONN_OUTLOOK') else 'off (no CONN_OUTLOOK)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
