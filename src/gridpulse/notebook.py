"""Run a Fabric notebook source file (`notebook-content.py`) outside Fabric.

Fabric keeps a notebook in Git as plain Python with comment markers:

    # Fabric notebook source
    # METADATA ********************            then "# META {...}" lines (JSON)
    # MARKDOWN ********************            then "# "-prefixed markdown lines
    # PARAMETERS CELL ********************     the parameters cell
    # CELL ********************                a code cell

When a pipeline (or `fab job run -P`) passes parameters, Fabric runs an injected cell right after
the parameters cell. `run_notebook` does the same: code cells run in order in one namespace (like a
notebook session), with the injected assignments after the parameters cell. The caller provides
what Fabric would: `spark`, plus optionally `store` and `display`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MARKER_RE = re.compile(r"^# (METADATA|MARKDOWN|PARAMETERS CELL|CELL) \*{5,}\s*$")
KINDS = {"METADATA": "metadata", "MARKDOWN": "markdown", "PARAMETERS CELL": "parameters",
         "CELL": "code"}  # fmt: skip


@dataclass(frozen=True)
class Cell:
    kind: str  # code | parameters | markdown | metadata
    source: str
    line: int  # 1-based line of the marker


def parse_cells(text: str) -> list[Cell]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "# Fabric notebook source":
        raise ValueError("not a Fabric notebook source file (first line)")
    cells: list[Cell] = []
    kind, start, buf = None, 0, []
    for i, ln in enumerate(lines[1:], start=2):
        m = MARKER_RE.match(ln)
        if m:
            if kind is not None:
                cells.append(Cell(kind, "\n".join(buf).strip("\n"), start))
            kind, start, buf = KINDS[m.group(1)], i, []
        else:
            buf.append(ln)
    if kind is not None:
        cells.append(Cell(kind, "\n".join(buf).strip("\n"), start))
    return cells


def parameter_names(cells: list[Cell]) -> list[str]:
    names: list[str] = []
    for c in cells:
        if c.kind == "parameters":
            names += re.findall(r"^([A-Za-z_]\w*)\s*=", c.source, flags=re.MULTILINE)
    return names


def run_notebook(
    path: str | Path, params: dict[str, Any] | None = None, namespace: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Execute the code cells of a Fabric notebook file; returns the final namespace."""
    path = Path(path)
    cells = parse_cells(path.read_text(encoding="utf-8"))
    params = dict(params or {})
    unknown = set(params) - set(parameter_names(cells))
    if unknown:
        raise ValueError(f"{path.name}: not parameters of this notebook: {sorted(unknown)}")
    ns: dict[str, Any] = {"__name__": "__fabric_notebook__", "__file__": str(path)}
    ns.update(namespace or {})
    for c in cells:
        if c.kind not in ("code", "parameters"):
            continue
        exec(compile(c.source, f"{path.name}:cell@{c.line}", "exec"), ns)  # noqa: S102
        if c.kind == "parameters":
            ns.update(params)  # Fabric's injected parameters cell
    return ns
