"""Table and file access for the notebooks: Fabric Lakehouse (Delta) or a local folder.

The notebooks never call `saveAsTable` or list files directly. They go through a store, so the
same notebook source runs in Fabric (`FabricStore`: managed Delta tables and the `Files/` area of
the default Lakehouse) and on a laptop (`LocalStore`: one Parquet file per table, used by the
tests and by `scripts/run_local.py`).

Write semantics (DESIGN D8, success criterion 1: a rerun never duplicates rows):
- `write(df, name)` replaces the whole table.
- `write(df, name, replace={"col": [values]})` replaces only the rows whose `col` is in `values`
  (Delta `replaceWhere`), e.g. the files a daily run re-ingested, or one run_date of DQ results.

Local Spark on Windows cannot write files without Hadoop's winutils, so `LocalStore` goes through
pandas and pyarrow. The Spark schema is saved next to the data and reapplied on read, so types do
not drift through pandas (nullable ints, dates, timestamps).
"""

from __future__ import annotations

import fnmatch
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from pyspark.sql import DataFrame, SparkSession


class TableStore(Protocol):
    def read(self, name: str) -> DataFrame: ...

    def exists(self, name: str) -> bool: ...

    def write(
        self, df: DataFrame, name: str, *, replace: dict[str, Sequence[Any]] | None = None
    ) -> int: ...

    def list_files(self, folder: str, pattern: str = "*") -> list[str]: ...


def sql_literal(v: Any) -> str:
    """A Spark SQL literal for a replaceWhere predicate (ints, floats, strings, dates)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return repr(v)
    if isinstance(v, datetime):
        return f"TIMESTAMP '{v.isoformat(sep=' ')}'"
    if isinstance(v, date):
        return f"DATE '{v.isoformat()}'"
    return "'" + str(v).replace("'", "''") + "'"


def replace_predicate(replace: dict[str, Sequence[Any]]) -> str:
    """{"source_file": ["a.csv", "b.csv"]} -> "source_file IN ('a.csv', 'b.csv')"."""
    if not replace or any(len(v) == 0 for v in replace.values()):
        raise ValueError(f"replace needs at least one value per column: {replace!r}")
    return " AND ".join(
        f"`{col}` IN ({', '.join(sql_literal(v) for v in values)})"
        for col, values in replace.items()
    )


@dataclass
class FabricStore:
    """Managed Delta tables of the notebook's default Lakehouse (lh_gridpulse)."""

    spark: SparkSession
    files_root: str = "Files"

    def read(self, name: str) -> DataFrame:
        return self.spark.read.table(name)

    def exists(self, name: str) -> bool:
        return bool(self.spark.catalog.tableExists(name))

    def write(
        self, df: DataFrame, name: str, *, replace: dict[str, Sequence[Any]] | None = None
    ) -> int:
        n = df.count()
        writer = df.write.format("delta").mode("overwrite")
        if replace and self.exists(name):
            # Partial overwrite: Delta forbids overwriteSchema together with replaceWhere.
            writer = writer.option("replaceWhere", replace_predicate(replace))
        else:
            writer = writer.option("overwriteSchema", "true")
        writer.saveAsTable(name)
        return n

    def list_files(self, folder: str, pattern: str = "*") -> list[str]:
        import notebookutils  # Fabric-only module, available in every Fabric notebook session

        path = f"{self.files_root}/{folder}".rstrip("/")
        try:
            entries = notebookutils.fs.ls(path)
        except Exception:  # noqa: BLE001 - folder not created yet = no files
            return []
        return sorted(e.path for e in entries if e.isFile and fnmatch.fnmatch(e.name, pattern))


@dataclass
class LocalStore:
    """Parquet + schema JSON per table under `root`; raw files under `files_root`.

    `aliases` maps a Lakehouse folder to a local one, e.g. {"bronze/ieso": Path("data/raw/ieso")},
    so the local raw downloads stand in for the files the pipeline lands in Fabric.
    """

    spark: SparkSession
    root: Path
    files_root: Path
    aliases: dict[str, Path] = field(default_factory=dict)

    def _dir(self, name: str) -> Path:
        return Path(self.root) / name

    def exists(self, name: str) -> bool:
        return (self._dir(name) / "data.parquet").exists()

    def read(self, name: str) -> DataFrame:
        import pandas as pd
        from pyspark.sql.types import StructType

        d = self._dir(name)
        if not self.exists(name):
            raise FileNotFoundError(f"table {name} not found in {self.root}")
        schema = StructType.fromJson(json.loads((d / "schema.json").read_text(encoding="utf-8")))
        pdf = pd.read_parquet(d / "data.parquet")
        if pdf.empty:
            return self.spark.createDataFrame([], schema)
        return self.spark.createDataFrame(pdf[schema.fieldNames()], schema=schema)

    def write(
        self, df: DataFrame, name: str, *, replace: dict[str, Sequence[Any]] | None = None
    ) -> int:
        import pandas as pd

        d = self._dir(name)
        d.mkdir(parents=True, exist_ok=True)
        new = df.toPandas()
        n = len(new)
        if replace and self.exists(name):
            old = pd.read_parquet(d / "data.parquet")
            keep = pd.Series(True, index=old.index)
            for col, values in replace.items():
                keep &= ~old[col].isin(list(values))
            new = pd.concat([old[keep], new], ignore_index=True) if keep.any() else new
        tmp = d / "data.parquet.tmp"
        new.to_parquet(tmp, index=False)
        os.replace(tmp, d / "data.parquet")
        (d / "schema.json").write_text(df.schema.json(), encoding="utf-8")
        return n

    def list_files(self, folder: str, pattern: str = "*") -> list[str]:
        base = Path(self.aliases.get(folder, Path(self.files_root) / folder))
        if not base.exists():
            return []
        return sorted(str(p) for p in base.iterdir() if p.is_file() and p.match(pattern))


def get_secret(vault_url: str, name: str, env_fallback: str | None = None) -> str:
    """A Key Vault secret: notebookutils inside Fabric (runs as the notebook's identity),
    else the environment variable `env_fallback` (local runs and tests only)."""
    try:
        import notebookutils

        return str(notebookutils.credentials.getSecret(vault_url, name))
    except ImportError:
        pass
    if env_fallback and os.environ.get(env_fallback):
        return os.environ[env_fallback]
    raise RuntimeError(
        f"secret {name!r}: not in Fabric (no notebookutils) and ${env_fallback} is not set"
    )


def file_names(paths: Iterable[str]) -> list[str]:
    """Base names of local paths or abfss:// URLs."""
    return [p.replace("\\", "/").rsplit("/", 1)[-1] for p in paths]
