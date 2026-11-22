"""Spark transformations of the Lakehouse layers (bronze, silver, gold) and the data-quality checks.

Every function takes and returns Spark DataFrames and has no side effects: reading and writing
tables is the notebook's job (through `gridpulse.lakehouse`). That keeps each step testable with a
local SparkSession on the real raw files.
"""
