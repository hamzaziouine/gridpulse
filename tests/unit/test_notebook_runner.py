"""The local runner for Fabric notebook source files (gridpulse.notebook)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gridpulse.notebook import parameter_names, parse_cells, run_notebook

ROOT = Path(__file__).parents[2]
NB = """# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {"name": "synapse_pyspark"}
# META }

# MARKDOWN ********************

# # Title

# PARAMETERS CELL ********************

run_date = ""
factor = 2

# METADATA ********************

# META {"language": "python"}

# CELL ********************

seen_run_date = run_date
result = factor * base
"""


def test_parse_cells_kinds_in_order() -> None:
    kinds = [c.kind for c in parse_cells(NB)]
    assert kinds == ["metadata", "markdown", "parameters", "metadata", "code"]


def test_parameters_are_injected_after_the_parameters_cell(tmp_path: Path) -> None:
    f = tmp_path / "notebook-content.py"
    f.write_text(NB, encoding="utf-8")
    ns = run_notebook(f, {"run_date": "2026-11-07", "factor": 5}, {"base": 3})
    assert ns["seen_run_date"] == "2026-11-07"
    assert ns["result"] == 15
    defaults = run_notebook(f, {}, {"base": 3})
    assert defaults["seen_run_date"] == "" and defaults["result"] == 6


def test_unknown_parameter_is_refused(tmp_path: Path) -> None:
    f = tmp_path / "notebook-content.py"
    f.write_text(NB, encoding="utf-8")
    with pytest.raises(ValueError, match="not parameters"):
        run_notebook(f, {"typo": 1}, {"base": 1})


def test_not_a_notebook() -> None:
    with pytest.raises(ValueError, match="first line"):
        parse_cells("print('hi')\n")


NOTEBOOKS = sorted((ROOT / "fabric").glob("nb_*.Notebook/notebook-content.py"))


def test_repo_has_the_medallion_notebooks() -> None:
    names = {p.parent.name for p in NOTEBOOKS}
    assert {"nb_bronze.Notebook", "nb_silver.Notebook", "nb_gold.Notebook"} <= names


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.parent.name)
def test_repo_notebooks_parse_and_declare_run_date(path: Path) -> None:
    name = path.parent.name
    text = path.read_text("utf-8")
    cells = parse_cells(text)
    assert sum(c.kind == "parameters" for c in cells) == 1
    assert "run_date" in parameter_names(cells)
    for c in cells:
        if c.kind in ("code", "parameters"):
            compile(c.source, name, "exec")  # valid Python
    assert "{{LAKEHOUSE_ID}}" in text and "{{WORKSPACE_ID}}" in text
