"""Database connector — Custom Query operation.

Runs free-form SQL with bound parameters. Read vs write is auto-detected from
the leading keyword (overridable via `write`): a read returns rows/count, a
write returns affected_rows.
"""
from __future__ import annotations

import re

from aurora_engine.connector_helper import get_connector_config

from connectors.database.client import run_execute, run_query

# Leading keywords that produce a result set.
_READ_RE = re.compile(r"^\s*(?:--[^\n]*\n|\s)*\b(SELECT|WITH|SHOW|PRAGMA|EXPLAIN|VALUES)\b", re.IGNORECASE)


def _is_read(sql: str) -> bool:
    return bool(_READ_RE.match(sql or ""))


def run(input: dict, context: dict) -> dict:
    config = get_connector_config("database", input["db_alias"])
    sql = input["sql"]
    params = input.get("params") or {}

    write = input.get("write")
    is_read = (not write) if write is not None else _is_read(sql)

    if is_read:
        rows = run_query(config, sql, params)
        return {"rows": rows, "count": len(rows), "sql": sql}

    affected = run_execute(config, sql, params)
    return {"affected_rows": affected, "sql": sql}
