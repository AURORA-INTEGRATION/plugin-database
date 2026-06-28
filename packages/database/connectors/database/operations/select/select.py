"""Database connector — SELECT operation.

Runs the query-builder form (table/columns/where/order_by/limit) or, when a
manual `sql` is supplied, executes that instead. Read-only.
"""
from __future__ import annotations

from aurora_engine.connector_helper import get_connector_config

from connectors.database.client import build_select, run_query


def run(input: dict, context: dict) -> dict:
    config = get_connector_config("database", input["db_alias"])

    sql = input.get("sql")
    params = input.get("params") or {}
    if not sql:
        sql, params = build_select(
            table=input["table"],
            columns=input.get("columns"),
            where=input.get("where"),
            order_by=input.get("order_by"),
            limit=input.get("limit"),
        )

    rows = run_query(config, sql, params)
    return {"rows": rows, "count": len(rows), "sql": sql}
