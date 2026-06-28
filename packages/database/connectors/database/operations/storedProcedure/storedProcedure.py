"""Database connector — Stored Procedure operation.

Call statement form is chosen per driver by the client (CALL / EXEC / BEGIN).
"""
from __future__ import annotations

from aurora_engine.connector_helper import get_connector_config

from connectors.database.client import call_procedure


def run(input: dict, context: dict) -> dict:
    config = get_connector_config("database", input["db_alias"])
    rows = call_procedure(config, name=input["name"], args=input.get("args") or {})
    return {"rows": rows, "count": len(rows), "sql": f"call {input['name']}"}
