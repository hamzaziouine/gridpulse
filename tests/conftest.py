"""Shared fixtures. Spark tests need pyspark and a JDK 17; without them they are skipped."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
LAKE = FIXTURES / "lake"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "spark: needs a local SparkSession (pyspark + JDK 17)")


@pytest.fixture(scope="session")
def spark():
    pytest.importorskip("pyspark")
    from gridpulse.localspark import find_jdk17, local_spark

    if not find_jdk17():
        pytest.skip("no JDK 17 found (set JAVA_HOME)")
    session = local_spark(app="gridpulse-tests", memory="1g")
    yield session
    session.stop()
