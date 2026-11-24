"""Repository rules: house style, no raw IESO data, no secrets in tracked files."""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("check_text", ROOT / "scripts" / "check_text.py")
assert spec and spec.loader
check_text = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_text)


def tracked() -> list[str]:
    out = subprocess.run(  # noqa: S603
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return out.splitlines()


def test_no_em_or_en_dashes() -> None:
    hits = check_text.scan(check_text.candidate_files())
    assert not hits, "\n".join(hits)


def test_no_bulk_source_files_tracked() -> None:
    files = tracked()
    assert not [f for f in files if f.startswith("data/raw/")]
    big_ieso = [f for f in files if "PUB_Demand" in f and not f.startswith("tests/fixtures/")]
    assert not big_ieso
    assert not [f for f in files if f.startswith(("mlruns/", "data/lakehouse/", ".venv/"))]


def test_no_secret_looking_values_tracked() -> None:
    patterns = [
        re.compile(r"SharedAccessKey=[A-Za-z0-9+/=]{20,}"),
        re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
        re.compile(r"(?i)password\s*=\s*['\"][^'\"{}<>$]{8,}['\"]"),
        re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    ]
    hits = []
    for f in tracked():
        p = ROOT / f
        if p.suffix.lower() in {".png", ".pdf", ".whl", ".parquet"} or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits += [f"{f}: {pat.pattern}" for pat in patterns if pat.search(text)]
    assert not hits, hits


GUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# Public Azure built-in policy definition "Require a tag on resources".
ALLOWED_GUIDS = {"871b6d14-10aa-478d-b590-94f262ecfa99"}
ALLOWED_MAIL_DOMAINS = ("example.com", "onelake.dfs.fabric.microsoft.com")


def _texts() -> list[tuple[str, str]]:
    out = []
    for f in tracked():
        p = ROOT / f
        if f == "uv.lock" or p.suffix.lower() in {".png", ".pdf", ".whl", ".parquet"}:
            continue
        if not p.is_file():
            continue
        try:
            out.append((f, p.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return out


def test_no_real_tenant_ids_or_emails_tracked() -> None:
    """Subscription, tenant and Entra object ids and personal e-mails live only in the
    git-ignored infra/local.settings.json. Only fake ids (all-zero prefix), public built-in
    definitions and example addresses may appear in tracked files."""
    assert "infra/local.settings.json" not in tracked()
    hits = []
    for f, text in _texts():
        for g in GUID_RE.findall(text):
            if not g.startswith("00000000-") and g.lower() not in ALLOWED_GUIDS:
                hits.append(f"{f}: {g}")
        for m in EMAIL_RE.findall(text):
            if not m.lower().endswith(ALLOWED_MAIL_DOMAINS):
                hits.append(f"{f}: {m}")
    assert not hits, hits


def test_local_settings_values_never_tracked() -> None:
    """When a real infra/local.settings.json exists, none of its values is in a tracked file."""
    import json

    local = ROOT / "infra" / "local.settings.json"
    if not local.exists():
        return
    s = json.loads(local.read_text("utf-8-sig"))
    values = [s["azure"]["subscriptionId"], s["azure"]["tenantId"]]
    values += [m for m in s["fabric"]["alertTo"].split(";") if m]
    values += [p["objectId"] for p in s["fabric"]["personas"]]
    hits = [f"{f}: {v}" for f, text in _texts() for v in values if v and v in text]
    assert not hits, hits


def test_local_settings_example_has_only_placeholders() -> None:
    import json

    ex = json.loads((ROOT / "infra" / "local.settings.example.json").read_text("utf-8"))
    flat = json.dumps(ex)
    assert not GUID_RE.search(flat) and not EMAIL_RE.search(flat)
    assert set(ex) >= {"azure", "fabric"}
    assert {"subscriptionId", "tenantId"} <= set(ex["azure"])
    assert {"alertTo", "personas"} <= set(ex["fabric"])
