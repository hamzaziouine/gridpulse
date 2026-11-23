"""Run the Fabric notebooks on this laptop, in pipeline order, on the real raw files.

What stands in for Fabric:
- `spark`: a local SparkSession (JDK 17 in JAVA_HOME, see README);
- `store`: LocalStore, Parquet tables under data/lakehouse/Tables (git-ignored);
- `Files/bronze/ieso`, `Files/bronze/openmeteo` and `Files/bronze/openmeteo_prevruns`: the local
  downloads in data/raw (scripts/pull_ieso.py, pull_openmeteo.py, pull_openmeteo_prevruns.py);
- the pipeline's Azure SQL copy (bronze_sites/meters/customers): data/reference/*.csv, the same
  rows scripts/load_sql.py loads into Azure SQL;
- Key Vault: the salt comes from $GRIDPULSE_HASH_SALT, else a random one kept in
  data/lakehouse/local_salt.txt;
- MLflow: a local file store, mlruns/ (git-ignored).
Nothing here talks to Azure or Fabric. Refuses to start above 22 GB of Windows commit charge and
stops itself above 28 GB (gridpulse.hostguard).

    uv run python scripts/run_local.py                       # bronze, silver, gold
    uv run python scripts/run_local.py --steps forecast       # train + backtest (nb_forecast)
    uv run python scripts/run_local.py --steps predict --run-date 2026-11-03
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ("bronze", "silver", "gold", "forecast", "predict")
NOTEBOOKS = {s: ROOT / "fabric" / f"nb_{s}.Notebook" / "notebook-content.py" for s in STEPS}


def local_salt(lake: Path) -> str:
    if os.environ.get("GRIDPULSE_HASH_SALT"):
        return os.environ["GRIDPULSE_HASH_SALT"]
    f = lake / "local_salt.txt"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_hex(32), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip()


def show(df, n: int = 20) -> None:
    """Stand-in for Fabric's display(): print the first rows."""
    print(df.limit(n).toPandas().to_string(max_colwidth=60))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--steps", default="bronze,silver,gold")
    ap.add_argument("--run-date", default="", help="YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--lake", type=Path, default=ROOT / "data" / "lakehouse")
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--param", action="append", default=[], help="extra notebook param k=v")
    a = ap.parse_args(argv)
    steps = [s.strip() for s in a.steps.split(",") if s.strip()]
    bad = set(steps) - set(STEPS)
    if bad:
        ap.error(f"unknown steps {sorted(bad)}; choose from {STEPS}")

    from gridpulse import hostguard

    before = hostguard.require_headroom()
    print(f"commit charge before start: {before if before is None else round(before, 2)} GB")
    dog = hostguard.CommitWatchdog()
    dog.start()

    from gridpulse import reference
    from gridpulse.lakehouse import LocalStore
    from gridpulse.localspark import local_spark
    from gridpulse.notebook import parameter_names, parse_cells, run_notebook

    os.environ["GRIDPULSE_HASH_SALT"] = local_salt(a.lake)
    os.environ.setdefault("MLFLOW_TRACKING_URI", (ROOT / "mlruns").as_uri())
    spark = local_spark(memory="2g")
    store = LocalStore(
        spark,
        root=a.lake / "Tables",
        files_root=a.lake / "Files",
        aliases={
            "bronze/ieso": a.raw / "ieso",
            "bronze/openmeteo": a.raw / "openmeteo",
            "bronze/openmeteo_prevruns": a.raw / "openmeteo_prevruns",
        },
    )
    if "silver" in steps:  # the pipeline's SQL -> Lakehouse copy activity
        for t in reference.LOAD_ORDER:
            n = store.write(reference.read_csv(spark, str(ROOT / "data" / "reference"), t),
                            f"bronze_{t}")  # fmt: skip
            print(f"bronze_{t}: {n} rows (local stand-in for the Azure SQL copy)")

    extra = dict(p.split("=", 1) for p in a.param)
    for step in steps:
        declared = parameter_names(parse_cells(NOTEBOOKS[step].read_text(encoding="utf-8")))
        params = {k: v for k, v in {"run_date": a.run_date, **extra}.items() if k in declared}
        if step == "bronze":
            params.setdefault("full_refresh", True)
        t0 = time.perf_counter()
        print(f"\n===== nb_{step} =====")
        run_notebook(NOTEBOOKS[step], params, {"spark": spark, "store": store, "display": show})
        print(f"nb_{step} done in {time.perf_counter() - t0:.1f} s, "
              f"peak commit {dog.peak_gb:.2f} GB")  # fmt: skip
    dog.stop()
    spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
