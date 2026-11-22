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
