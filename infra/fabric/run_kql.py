"""Run the KQL management commands of a .kql file against the Eventhouse KQL database.

Used by deploy_fabric.ps1 for realtime/kql/00_tables.kql (table meter_readings, its JSON
ingestion mapping, 7-day retention). Commands are separated by blank lines; `//` lines are
comments. Each command goes to the Kusto REST management endpoint `<queryServiceUri>/v1/rest/mgmt`
with a token from DefaultAzureCredential (your `az login`). All commands are idempotent
(`.create-merge`, `.create-or-alter`, `.alter-merge`).

    uv run python infra/fabric/run_kql.py --cluster <queryServiceUri> --database eh_gridpulse \\
        --file realtime/kql/00_tables.kql
    uv run python infra/fabric/run_kql.py --file realtime/kql/00_tables.kql --dry-run

If the token scope is refused, run the same file once in the KQL queryset UI (it is the same
text) and continue.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

KUSTO_SCOPE = "https://kusto.kusto.windows.net/.default"


def split_commands(text: str) -> list[str]:
    """Blank-line separated KQL commands, comments removed."""
    blocks, cur = [], []
    for line in text.splitlines():
        if line.strip().startswith("//"):
            continue
        if not line.strip():
            if cur:
                blocks.append("\n".join(cur).strip())
                cur = []
            continue
        cur.append(line)
    if cur:
        blocks.append("\n".join(cur).strip())
    return [b for b in blocks if b]


def run(cluster: str, database: str, commands: list[str]) -> None:
    import httpx
    from azure.identity import DefaultAzureCredential

    token = DefaultAzureCredential().get_token(KUSTO_SCOPE).token
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with httpx.Client(timeout=60, headers=headers) as client:
        for cmd in commands:
            url = f"{cluster.rstrip('/')}/v1/rest/mgmt"
            r = client.post(url, json={"db": database, "csl": cmd})
            if r.status_code >= 400:
                detail = r.text[:500]
                raise SystemExit(f"KQL command failed ({r.status_code}): {cmd[:80]}\n{detail}")
            print(f"ok: {cmd.splitlines()[0][:90]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", type=Path, required=True)
    ap.add_argument("--cluster", help="Eventhouse queryServiceUri, https://....kusto.fabric...")
    ap.add_argument("--database", default="eh_gridpulse")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    commands = split_commands(a.file.read_text(encoding="utf-8"))
    if not all(c.startswith(".") for c in commands):
        raise SystemExit("only management commands (starting with '.') belong in this file")
    if a.dry_run or not a.cluster:
        for c in commands:
            print(f"would run on {a.database}: {c.splitlines()[0][:90]}")
        return 0
    run(a.cluster, a.database, commands)
    return 0


if __name__ == "__main__":
    sys.exit(main())
