"""House style check: no em dash (U+2014) or en dash (U+2013) in any text file of the repo.

Scans every file git tracks or would track (respects .gitignore), skips binaries. Exit code 1
and one line per hit when something is found. Run by the test suite and before each commit.

    uv run python scripts/check_text.py [paths...]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BANNED = {chr(0x2014): "em dash", chr(0x2013): "en dash"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".ps1", ".sql", ".kql",
                 ".dax", ".tmdl", ".svg", ".html", ".csv", ".cfg", ".ini", ".gitignore",
                 ".gitattributes", ".pbism", ".pbir", ""}  # fmt: skip


def candidate_files() -> list[Path]:
    out = subprocess.run(  # noqa: S603 - fixed git invocation, no user input
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return [ROOT / p for p in out.splitlines() if p]


def scan(paths: list[Path]) -> list[str]:
    hits = []
    for p in paths:
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for ch, name in BANNED.items():
                if ch in line:
                    hits.append(f"{p.relative_to(ROOT)}:{i}: {name}: {line.strip()[:100]}")
    return hits


def main(argv: list[str]) -> int:
    paths = [Path(a).resolve() for a in argv] if argv else candidate_files()
    hits = scan(paths)
    for h in hits:
        print(h)
    print(f"{len(paths)} files checked, {len(hits)} dash(es) found")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
