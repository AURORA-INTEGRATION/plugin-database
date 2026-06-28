"""Database connector — INSERT operation."""
from __future__ import annotations

from aurora_engine.connector_helper import get_connector_config

from connectors.database.client import build_insert, run_execute


def run(input: dict, context: dict) -> dict:
    config = get_connector_config("database", input["db_alias"])
    sql, params = build_insert(table=input["table"], values=input["values"])
    affected = run_execute(config, sql, params)
    return {"affected_rows": affected, "sql": sql}
