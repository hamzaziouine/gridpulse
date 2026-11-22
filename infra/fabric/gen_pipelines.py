"""Generate fabric/pl_daily_ingest and fabric/pl_backfill pipeline-content.json.

The JSON files are the committed source the deploy imports; this script exists so their dozens
of activities stay consistent (same Lakehouse sink, same notebook wiring, same failure path).
Edit here, rerun, commit both. `{{TOKENS}}` are filled by infra/fabric/render.py at deploy time.

    uv run python infra/fabric/gen_pipelines.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = {"timeout": "0.02:00:00", "retry": 2, "retryIntervalInSeconds": 120,
          "secureOutput": False, "secureInput": False}  # fmt: skip
NB_POLICY = {"timeout": "0.02:00:00", "retry": 0, "retryIntervalInSeconds": 30,
             "secureOutput": False, "secureInput": False}  # fmt: skip
OM_Q = "{{OPENMETEO_QUERY}}"
RUN = "@variables('v_run_date')"


def expr(v: str) -> dict:
    return {"value": v, "type": "Expression"}


def dep(name: str, *conds: str) -> dict:
    return {"activity": name, "dependencyConditions": list(conds or ("Succeeded",))}


def lakehouse(root: str) -> dict:
    return {"name": "lh_gridpulse", "properties": {"annotations": [], "type": "Lakehouse",
            "typeProperties": {"workspaceId": "{{WORKSPACE_ID}}",
                               "artifactId": "{{LAKEHOUSE_ID}}", "rootFolder": root}}}  # fmt: skip


def http_copy(name: str, deps: list, conn: str, url: str, folder: str, file_name: str,
              desc: str) -> dict:  # fmt: skip
    """Binary copy of one HTTP GET response into Files/<folder>/<file_name>."""
    return {
        "name": name, "description": desc, "type": "Copy", "dependsOn": deps, "policy": POLICY,
        "typeProperties": {
            "source": {
                "type": "BinarySource",
                "storeSettings": {"type": "HttpReadSettings", "requestMethod": "GET"},
                "formatSettings": {"type": "BinaryReadSettings"},
                "datasetSettings": {
                    "annotations": [], "type": "Binary",
                    "typeProperties": {"location": {"type": "HttpServerLocation",
                                                    "relativeUrl": expr(url)}},
                    "externalReferences": {"connection": conn},
                },
            },
            "sink": {
                "type": "BinarySink",
                "storeSettings": {"type": "LakehouseWriteSettings"},
                "datasetSettings": {
                    "annotations": [], "linkedService": lakehouse("Files"), "type": "Binary",
                    "typeProperties": {"location": {"type": "LakehouseLocation",
                                                    "folderPath": folder,
                                                    "fileName": expr(file_name)}},
                },
            },
            "enableStaging": False,
        },
    }  # fmt: skip


def sql_foreach(deps: list) -> dict:
    copy = {
        "name": "cp_sql_table", "type": "Copy", "dependsOn": [], "policy": POLICY,
        "typeProperties": {
            "source": {
                "type": "AzureSqlSource", "queryTimeout": "00:10:00", "partitionOption": "None",
                "datasetSettings": {
                    "annotations": [], "type": "AzureSqlTable", "schema": [],
                    "typeProperties": {"schema": "dbo", "table": expr("@item()"),
                                       "database": "{{SQL_DATABASE}}"},
                    "externalReferences": {"connection": "{{CONN_SQL}}"},
                },
            },
            "sink": {
                "type": "LakehouseTableSink", "tableActionOption": "Overwrite",
                "datasetSettings": {
                    "annotations": [], "linkedService": lakehouse("Tables"),
                    "type": "LakehouseTable", "schema": [],
                    "typeProperties": {"table": expr("@concat('bronze_', item())")},
                },
            },
            "enableStaging": False,
        },
    }  # fmt: skip
    return {
        "name": "fe_sql_reference",
        "description": "S3: Azure SQL dbo.sites/customers/meters to bronze_<table> (overwrite).",
        "type": "ForEach", "dependsOn": deps,
        "typeProperties": {"items": expr("@createArray('sites', 'customers', 'meters')"),
                           "isSequential": False, "batchCount": 3, "activities": [copy]},
    }  # fmt: skip


def notebook(name: str, token: str, deps: list, params: dict) -> dict:
    return {
        "name": name, "type": "TridentNotebook", "dependsOn": deps, "policy": NB_POLICY,
        "typeProperties": {
            "notebookId": token, "workspaceId": "{{WORKSPACE_ID}}",
            "parameters": {k: {"value": v, "type": t} for k, (v, t) in params.items()},
        },
    }  # fmt: skip


def set_var(name: str, var: str, value: str, deps: list) -> dict:
    return {"name": name, "type": "SetVariable", "dependsOn": deps,
            "policy": {"secureOutput": False, "secureInput": False},
            "typeProperties": {"variableName": var, "value": expr(value)}}  # fmt: skip


def failure_path(last: str) -> list[dict]:
    """T3.6. `last` failing, or skipped because an earlier step failed, sends one mail, then the
    Fail activity marks the run as failed in the Monitor hub (otherwise the handled error would
    leave the run green)."""
    mail = {
        "name": "mail_failure", "type": "Office365Outlook",
        "description": "Failure alert. The Office 365 Outlook connection uses OAuth, created once "
                       "in the UI (con_outlook_alerts).",
        "dependsOn": [dep(last, "Failed", "Skipped")],
        "policy": {"timeout": "0.00:10:00", "retry": 1, "retryIntervalInSeconds": 30,
                   "secureOutput": False, "secureInput": False},
        "typeProperties": {"inputs": {"method": "post", "path": "/v2/Mail", "body": {
            "To": "{{ALERT_TO}}",
            "Subject": "GridPulse @{pipeline().Pipeline} FAILED (run_date "
                       "@{variables('v_run_date')})",
            "Body": "<p>Pipeline <b>@{pipeline().Pipeline}</b> failed or skipped a step.</p>"
                    "<p>Run id: @{pipeline().RunId}<br>run_date: @{variables('v_run_date')}</p>"
                    "<p>Check the Monitor hub for the failing activity and the table "
                    "silver_dq_results for data-quality results.</p>",
            "Importance": "High"}}},
        "externalReferences": {"connection": "{{CONN_OUTLOOK}}"},
    }  # fmt: skip
    fail = {
        "name": "fail_pipeline", "type": "Fail",
        "dependsOn": [dep("mail_failure", "Succeeded", "Failed")],
        "typeProperties": {
            "message": expr("@concat('GridPulse run failed for run_date ', "
                            "variables('v_run_date'))"),
            "errorCode": "GRIDPULSE_RUN_FAILED",
        },
    }  # fmt: skip
    return [mail, fail]


def daily() -> dict:
    acts = [
        set_var("set_run_date", "v_run_date",
                "@if(empty(pipeline().parameters.run_date), formatDateTime(utcNow(), "
                "'yyyy-MM-dd'), pipeline().parameters.run_date)", []),
        set_var("set_data_day", "v_data_day",
                "@formatDateTime(addDays(variables('v_run_date'), -1), 'yyyy-MM-dd')",
                [dep("set_run_date")]),
        set_var("set_month_start", "v_month_start",
                "@formatDateTime(startOfMonth(variables('v_data_day')), 'yyyy-MM-dd')",
                [dep("set_data_day")]),
        http_copy("cp_ieso_demand", [dep("set_month_start")], "{{CONN_IESO_HTTP}}",
                  "@concat('PUB_Demand_', substring(variables('v_data_day'), 0, 4), '.csv')",
                  "bronze/ieso",
                  "@concat('PUB_Demand_', substring(variables('v_data_day'), 0, 4), '.csv')",
                  "S1: IESO PUB_Demand of the year that holds yesterday (the unsuffixed name is "
                  "IESO's newest version)."),
        http_copy("cp_openmeteo_history", [dep("set_month_start")], "{{CONN_OPENMETEO_HIST}}",
                  f"@concat('v1/forecast?{OM_Q}&start_date=', variables('v_month_start'), "
                  "'&end_date=', variables('v_data_day'))",
                  "bronze/openmeteo", "@concat(substring(variables('v_data_day'), 0, 7), '.json')",
                  "S2: Open-Meteo Historical Forecast API, yesterday's month up to yesterday."),
        http_copy("cp_openmeteo_forecast", [dep("set_month_start")], "{{CONN_OPENMETEO_FC}}",
                  f"@concat('v1/forecast?{OM_Q}&forecast_days=3')",
                  "bronze/openmeteo_forecast", "@concat(variables('v_run_date'), '.json')",
                  "S2: Open-Meteo Forecast API, next 3 days, input of tomorrow's forecast."),
        sql_foreach([dep("set_month_start")]),
        notebook("nb_bronze", "{{NB_BRONZE_ID}}",
                 [dep("cp_ieso_demand"), dep("cp_openmeteo_history"),
                  dep("cp_openmeteo_forecast"), dep("fe_sql_reference")],
                 {"run_date": (expr(RUN), "string"), "full_refresh": (False, "bool")}),
        notebook("nb_silver", "{{NB_SILVER_ID}}", [dep("nb_bronze")],
                 {"run_date": (expr(RUN), "string")}),
        notebook("nb_gold", "{{NB_GOLD_ID}}", [dep("nb_silver")],
                 {"run_date": (expr(RUN), "string")}),
        notebook("nb_predict", "{{NB_PREDICT_ID}}", [dep("nb_gold")],
                 {"run_date": (expr(RUN), "string")}),
        *failure_path("nb_predict"),
    ]  # fmt: skip
    return {"properties": {
        "description": "GridPulse daily batch ingestion (DESIGN D8). Scheduled 13:15 UTC = 08:15 "
                       "EST, after IESO posts yesterday. Re-runnable for any run_date: bronze "
                       "replaces the rows of the files it re-copies, silver and gold are rebuilt.",
        "activities": acts,
        "parameters": {"run_date": {"type": "string", "defaultValue": ""}},
        "variables": {"v_run_date": {"type": "String"}, "v_data_day": {"type": "String"},
                      "v_month_start": {"type": "String"}},
        "annotations": ["gridpulse", "batch"],
    }}  # fmt: skip


def backfill() -> dict:
    m0 = "addToTime(pipeline().parameters.start_month, item(), 'Month')"
    m_end = "addDays(addToTime(pipeline().parameters.start_month, add(item(), 1), 'Month'), -1)"
    yday = "addDays(utcNow(), -1)"
    end = (f"if(greater(ticks({m_end}), ticks({yday})), formatDateTime({yday}, 'yyyy-MM-dd'), "
           f"formatDateTime({m_end}, 'yyyy-MM-dd'))")  # fmt: skip
    om = http_copy(
        "cp_openmeteo_month", [], "{{CONN_OPENMETEO_HIST}}",
        f"@concat('v1/forecast?{OM_Q}&start_date=', formatDateTime({m0}, 'yyyy-MM-dd'), "
        f"'&end_date=', {end})",
        "bronze/openmeteo", f"@concat(formatDateTime({m0}, 'yyyy-MM'), '.json')",
        "One calendar month of the Historical Forecast API (capped at yesterday).")
    ieso = http_copy(
        "cp_ieso_year", [], "{{CONN_IESO_HTTP}}", "@concat('PUB_Demand_', string(item()), '.csv')",
        "bronze/ieso", "@concat('PUB_Demand_', string(item()), '.csv')",
        "One year of IESO PUB_Demand.")
    acts = [
        set_var("set_run_date", "v_run_date", "@formatDateTime(utcNow(), 'yyyy-MM-dd')", []),
        {"name": "fe_ieso_years", "type": "ForEach", "dependsOn": [dep("set_run_date")],
         "description": "S1: every year from first_year to the current year.",
         "typeProperties": {"items": expr("@range(pipeline().parameters.first_year, "
                                          "pipeline().parameters.year_count)"),
                            "isSequential": False, "batchCount": 4, "activities": [ieso]}},
        {"name": "fe_openmeteo_months", "type": "ForEach", "dependsOn": [dep("set_run_date")],
         "description": "S2: one request per month, sequential, far below Open-Meteo's limits.",
         "typeProperties": {"items": expr("@range(0, pipeline().parameters.month_count)"),
                            "isSequential": True, "activities": [om]}},
        sql_foreach([dep("set_run_date")]),
        notebook("nb_bronze", "{{NB_BRONZE_ID}}",
                 [dep("fe_ieso_years"), dep("fe_openmeteo_months"), dep("fe_sql_reference")],
                 {"run_date": (expr(RUN), "string"), "full_refresh": (True, "bool")}),
        notebook("nb_silver", "{{NB_SILVER_ID}}", [dep("nb_bronze")],
                 {"run_date": (expr(RUN), "string")}),
        notebook("nb_gold", "{{NB_GOLD_ID}}", [dep("nb_silver")],
                 {"run_date": (expr(RUN), "string")}),
        notebook("nb_forecast", "{{NB_FORECAST_ID}}", [dep("nb_gold")],
                 {"run_date": (expr(RUN), "string")}),
        *failure_path("nb_forecast"),
    ]  # fmt: skip
    return {"properties": {
        "description": "GridPulse one-off backfill: every IESO year and Open-Meteo month since "
                       "2019, full bronze refresh, silver, gold, then model training "
                       "(nb_forecast). Safe to rerun.",
        "activities": acts,
        "parameters": {"first_year": {"type": "int", "defaultValue": 2019},
                       "year_count": {"type": "int", "defaultValue": "{{BACKFILL_YEARS}}"},
                       "start_month": {"type": "string", "defaultValue": "2019-01-01"},
                       "month_count": {"type": "int", "defaultValue": "{{BACKFILL_MONTHS}}"}},
        "variables": {"v_run_date": {"type": "String"}},
        "annotations": ["gridpulse", "backfill"],
    }}  # fmt: skip


def main() -> None:
    for name, body in (("pl_daily_ingest", daily()), ("pl_backfill", backfill())):
        out = ROOT / "fabric" / f"{name}.DataPipeline" / "pipeline-content.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        print(f"{out.relative_to(ROOT)}: {len(body['properties']['activities'])} activities")


if __name__ == "__main__":
    main()
