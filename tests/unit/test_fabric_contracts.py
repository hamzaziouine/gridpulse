"""Fabric API contracts checked against the live tenant on 2026-11-23.

`tests/fixtures/fabric_connection_types.json` is the answer of
GET /v1/connections/supportedConnectionTypes (3 of 298 types kept). The deploy script builds its
connection requests from hard-coded names; these tests pin them to what the API accepts.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
TYPES = {
    t["type"]: t
    for t in json.loads((ROOT / "tests/fixtures/fabric_connection_types.json").read_text("utf-8"))[
        "value"
    ]
}
DEPLOY = (ROOT / "infra/fabric/deploy_fabric.ps1").read_text("utf-8")

spec = importlib.util.spec_from_file_location("run_kql", ROOT / "infra/fabric/run_kql.py")
run_kql = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_kql)


def test_http_connection_type_exists_with_anonymous_auth() -> None:
    default = re.search(r"\$HttpConnectionType = '([^']+)'", DEPLOY).group(1)
    t = TYPES[default]
    assert "Anonymous" in t["supportedCredentialTypes"]
    (method,) = t["creationMethods"]
    # fab mkdir infers the creation method from the single parameter we pass (url)
    assert [p["name"] for p in method["parameters"]] == ["url"]
    assert "connectionDetails.parameters.url=" in DEPLOY


def test_sql_connection_body_uses_the_exact_creation_method_and_parameters() -> None:
    m = re.search(r"type = 'SQL'; creationMethod = '([^']+)'", DEPLOY)
    t = TYPES["SQL"]
    method = next(x for x in t["creationMethods"] if x["name"] == m.group(1))
    names = {p["name"] for p in method["parameters"]}
    assert names == {"server", "database"}
    assert "name = 'server'" in DEPLOY and "name = 'database'" in DEPLOY
    assert "Basic" in t["supportedCredentialTypes"]


def test_outlook_connection_type_is_oauth_only() -> None:
    # Hence created once in the UI (OAuth consent), never by the script.
    assert "Anonymous" not in TYPES["MicrosoftOutlook"]["supportedCredentialTypes"]
    assert "OAuth2" in TYPES["MicrosoftOutlook"]["supportedCredentialTypes"]


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_kusto_scope_comes_from_cluster_metadata() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/rest/auth/metadata"
        return httpx.Response(
            200,
            json={
                "AzureAD": {
                    "KustoServiceResourceId": "https://kusto.kusto.windows.net",
                    "LoginMfaRequired": False,
                }
            },
        )

    scope = run_kql.resolve_scope("https://x.z0.kusto.fabric.microsoft.com/", _client(handler))
    assert scope == "https://kusto.kusto.windows.net/.default"


def test_kusto_scope_mfa_and_fallbacks() -> None:
    mfa = _client(
        lambda r: httpx.Response(
            200,
            json={
                "AzureAD": {
                    "KustoServiceResourceId": "https://kusto.kusto.windows.net",
                    "LoginMfaRequired": True,
                }
            },
        )
    )
    assert run_kql.resolve_scope("https://c", mfa) == "https://kusto.kustomfa.windows.net/.default"
    missing = _client(lambda r: httpx.Response(404))
    assert run_kql.resolve_scope("https://c", missing) == run_kql.KUSTO_SCOPE

    def boom(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    assert run_kql.resolve_scope("https://c", _client(boom)) == run_kql.KUSTO_SCOPE
