"""Database connector — UPDATE operation.

A WHERE clause is required by default: an accidental full-table update is the
classic foot-gun, so callers must opt in with `allow_no_where: true`.
"""
from __future__ import annotations

from aurora_engine.connector_helper import get_connector_config

from connectors.database.client import build_update, run_execute


def run(input: dict, context: dict) -> dict:
    where = input.get("where")
    if not where and not input.get("allow_no_where"):
        raise ValueError(
            "update without WHERE refused; pass `where` or set allow_no_where: true"
        )

    config = get_connector_config("database", input["db_alias"])
    sql, params = build_update(table=input["table"], values=input["values"], where=where)
    affected = run_execute(config, sql, params)
    return {"affected_rows": affected, "sql": sql}
