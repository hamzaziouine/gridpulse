"""A small local Spark session for tests and scripts/run_local.py (never used inside Fabric).

Settings mirror what the notebooks assume in Fabric: session time zone UTC, Arrow on for
pandas conversion. Windows needs a JDK 17 (Spark 3.5 supports Java 8/11/17) in JAVA_HOME, and the
worker Python must be this interpreter, otherwise Spark picks whatever `python` is on PATH.
"""

from __future__ import annotations

import os
import sys
from glob import glob
from pathlib import Path

JDK_CANDIDATES = (
    "C:/Program Files/Java/jdk-17*",
    "C:/Program Files/Eclipse Adoptium/jdk-17*",
    "C:/Program Files/Microsoft/jdk-17*",
    "/usr/lib/jvm/*17*",
)


def find_jdk17() -> str | None:
    """JAVA_HOME if it is set, else the first JDK 17 found in the usual install folders."""
    if os.environ.get("JAVA_HOME"):
        return os.environ["JAVA_HOME"]
    for pattern in JDK_CANDIDATES:
        hits = sorted(glob(pattern))
        if hits and Path(hits[-1], "bin").exists():
            return hits[-1]
    return None


def local_spark(app: str = "gridpulse-local", memory: str = "1g", cores: int = 2):
    """Start (or reuse) a local SparkSession bound to 127.0.0.1 with the UI off."""
    jdk = find_jdk17()
    if jdk:
        os.environ["JAVA_HOME"] = jdk
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")
    from pyspark.sql import SparkSession

    return (
        SparkSession.builder.master(f"local[{cores}]")
        .appName(app)
        .config("spark.driver.memory", memory)
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "4")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.execution.arrow.pyspark.enabled", "true")
        .config("spark.sql.execution.arrow.pyspark.fallback.enabled", "false")
        .getOrCreate()
    )
