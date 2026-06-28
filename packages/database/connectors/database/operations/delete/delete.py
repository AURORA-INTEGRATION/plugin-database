"""Database connector — DELETE operation.

WHERE required by default (set `allow_no_where: true` to wipe the table).
"""
from __future__ import annotations

from aurora_engine.connector_helper import get_connector_config

from connectors.database.client import build_delete, run_execute


def run(input: dict, context: dict) -> dict:
    where = input.get("where")
    if not where and not input.get("allow_no_where"):
        raise ValueError(
            "delete without WHERE refused; pass `where` or set allow_no_where: true"
        )

    config = get_connector_config("database", input["db_alias"])
    sql, params = build_delete(table=input["table"], where=where)
    affected = run_execute(config, sql, params)
    return {"affected_rows": affected, "sql": sql}
