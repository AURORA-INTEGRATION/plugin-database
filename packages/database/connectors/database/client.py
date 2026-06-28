"""Shared database client for the `database` connector.

One pooled SQLAlchemy engine per connector instance (keyed by a config
fingerprint). Operation scripts (select/insert/update/...) import the helpers
here instead of each opening their own connection.

SQL identifiers (table / column / procedure names) cannot be passed as bound
parameters, so the dynamic-query builders validate every identifier against a
strict whitelist (``quote_ident``) to stay injection-safe. Every *value* always
goes through bound parameters (:p0, :p1, ...).
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from typing import Any

from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.engine import URL, Engine

# driver key (connector `driver` field) -> (sqlalchemy dialect+driver, default port)
_DRIVERS: dict[str, tuple[str, int | None]] = {
    "postgresql": ("postgresql+psycopg2", 5432),
    "mysql": ("mysql+pymysql", 3306),
    "mssql": ("mssql+pyodbc", 1433),
    "oracle": ("oracle+oracledb", 1521),
    "sqlite": ("sqlite", None),
}

# A single identifier segment. Dotted names (schema.table) are validated segment
# by segment, so "public.users" passes but "users; DROP TABLE x" does not.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

# op key -> SQL comparison operator, for the WHERE builder.
_WHERE_OPS: dict[str, str] = {
    "eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
    "like": "LIKE", "ilike": "ILIKE",
}

_engines: dict[str, Engine] = {}
_lock = threading.Lock()


# ── connection / engine pool ──────────────────────────────────────────────────

def _fingerprint(config: dict[str, Any]) -> str:
    raw = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _build_url(config: dict[str, Any]) -> URL:
    driver = (config.get("driver") or "").lower()
    if driver not in _DRIVERS:
        raise ValueError(
            f"unsupported database driver: {driver!r} "
            f"(expected one of {', '.join(_DRIVERS)})"
        )
    prefix, default_port = _DRIVERS[driver]

    if driver == "sqlite":
        # `database` holds a file path (or ':memory:').
        return URL.create("sqlite", database=config.get("database") or ":memory:")

    raw_port = config.get("port")
    try:
        port = int(raw_port) if raw_port not in (None, "") else default_port
    except (TypeError, ValueError):
        port = default_port

    return URL.create(
        prefix,
        username=config.get("username"),
        password=config.get("password"),
        host=config.get("host"),
        port=port,
        database=config.get("database"),
    )


def get_engine(config: dict[str, Any]) -> Engine:
    """Return a cached, pooled engine for this connector config."""
    key = _fingerprint(config)
    eng = _engines.get(key)
    if eng is not None:
        return eng
    with _lock:
        eng = _engines.get(key)
        if eng is None:
            options = config.get("options")
            kwargs = dict(options) if isinstance(options, dict) else {}
            eng = create_engine(_build_url(config), pool_pre_ping=True, **kwargs)
            _engines[key] = eng
    return eng


# ── execution helpers ─────────────────────────────────────────────────────────

def run_query(config: dict[str, Any], sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a read query, returning all rows as a list of dicts."""
    eng = get_engine(config)
    with eng.connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(row._mapping) for row in result]


def run_execute(config: dict[str, Any], sql: str, params: dict[str, Any] | None = None) -> int:
    """Run a write command inside a transaction, returning the affected row count."""
    eng = get_engine(config)
    with eng.begin() as conn:
        result = conn.execute(text(sql), params or {})
        return result.rowcount


def test_connection(config: dict[str, Any]) -> dict[str, Any]:
    """Open a connection and run ``SELECT 1`` to verify reachability."""
    eng = get_engine(config)
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True, "driver": (config.get("driver") or "").lower()}


def call_procedure(config: dict[str, Any], name: str, args: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Invoke a stored procedure. Statement form is chosen per driver."""
    driver = (config.get("driver") or "").lower()
    proc = quote_ident(name)
    args = args or {}
    placeholders = ", ".join(f":{k}" for k in args)

    if driver == "mssql":
        sql = f"EXEC {proc} {placeholders}".strip()
    elif driver == "oracle":
        sql = f"BEGIN {proc}({placeholders}); END;"
    else:  # postgresql, mysql, sqlite(best-effort)
        sql = f"CALL {proc}({placeholders})"

    eng = get_engine(config)
    with eng.begin() as conn:
        result = conn.execute(text(sql), args)
        try:
            return [dict(row._mapping) for row in result]
        except Exception:
            return []


# ── dynamic SQL builders (the "genera query dinamiche" part) ──────────────────

def quote_ident(name: str) -> str:
    """Validate a (possibly dotted) SQL identifier. Raise on anything unsafe."""
    if not isinstance(name, str) or not name:
        raise ValueError(f"invalid SQL identifier: {name!r}")
    if not all(_IDENT_RE.match(seg) for seg in name.split(".")):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return name


def build_where(
    conditions: list[dict[str, Any]] | None,
    params: dict[str, Any],
    start: int = 0,
) -> tuple[str, int]:
    """Build a WHERE clause from ``[{field, op, value}]``.

    Mutates ``params`` (adds p<start>, p<start+1>, ...) and returns
    ``(clause, next_index)``. An empty/absent list yields an empty clause.
    """
    if not conditions:
        return "", start
    parts: list[str] = []
    i = start
    for cond in conditions:
        col = quote_ident(cond["field"])
        op = (cond.get("op") or "eq").lower()
        if op in ("is_null", "not_null"):
            parts.append(f"{col} IS {'NOT ' if op == 'not_null' else ''}NULL")
            continue
        if op == "in":
            values = cond.get("value") or []
            keys = []
            for val in values:
                p = f"p{i}"
                params[p] = val
                keys.append(f":{p}")
                i += 1
            parts.append(f"{col} IN ({', '.join(keys) or 'NULL'})")
            continue
        if op not in _WHERE_OPS:
            raise ValueError(f"unsupported where op: {op!r}")
        p = f"p{i}"
        params[p] = cond.get("value")
        i += 1
        parts.append(f"{col} {_WHERE_OPS[op]} :{p}")
    return "WHERE " + " AND ".join(parts), i


def build_select(
    table: str,
    columns: list[str] | None = None,
    where: list[dict[str, Any]] | None = None,
    order_by: list[dict[str, Any]] | None = None,
    limit: int | None = None,
) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {}
    cols = ", ".join(quote_ident(c) for c in columns) if columns else "*"
    sql = f"SELECT {cols} FROM {quote_ident(table)}"
    clause, _ = build_where(where, params)
    if clause:
        sql += " " + clause
    if order_by:
        parts = []
        for o in order_by:
            direction = "DESC" if (o.get("dir") or "asc").lower() == "desc" else "ASC"
            parts.append(f"{quote_ident(o['field'])} {direction}")
        sql += " ORDER BY " + ", ".join(parts)
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return sql, params


def build_insert(table: str, values: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not values:
        raise ValueError("insert requires a non-empty `values` map")
    cols = [quote_ident(c) for c in values]
    keys = [f"p{i}" for i in range(len(values))]
    params = dict(zip(keys, values.values()))
    placeholders = ", ".join(f":{k}" for k in keys)
    sql = f"INSERT INTO {quote_ident(table)} ({', '.join(cols)}) VALUES ({placeholders})"
    return sql, params


def build_update(
    table: str,
    values: dict[str, Any],
    where: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if not values:
        raise ValueError("update requires a non-empty `values` map")
    params: dict[str, Any] = {}
    set_parts = []
    for i, (col, val) in enumerate(values.items()):
        key = f"s{i}"
        params[key] = val
        set_parts.append(f"{quote_ident(col)} = :{key}")
    sql = f"UPDATE {quote_ident(table)} SET {', '.join(set_parts)}"
    clause, _ = build_where(where, params)  # WHERE uses p<idx>, SET uses s<idx>: no clash
    if clause:
        sql += " " + clause
    return sql, params


def build_delete(
    table: str,
    where: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {}
    sql = f"DELETE FROM {quote_ident(table)}"
    clause, _ = build_where(where, params)
    if clause:
        sql += " " + clause
    return sql, params


def proc_statement(driver: str, name: str, args: dict[str, Any] | None) -> str:
    """Render the CALL/EXEC/BEGIN statement for a stored procedure (no params)."""
    proc = quote_ident(name)
    placeholders = ", ".join(f":{k}" for k in (args or {}))
    if driver == "mssql":
        return f"EXEC {proc} {placeholders}".strip()
    if driver == "oracle":
        return f"BEGIN {proc}({placeholders}); END;"
    return f"CALL {proc}({placeholders})"


def preview_sql(operation: str, inp: dict[str, Any], driver: str = "") -> str:
    """Build the SQL a given operation *would* run, without executing it.

    Powers the designer's live preview. Mirrors each operation's `run()`.
    """
    op = operation.split(".")[-1]
    if op == "select":
        sql, _ = build_select(
            table=inp.get("table") or "", columns=inp.get("columns"),
            where=inp.get("where"), order_by=inp.get("order_by"), limit=inp.get("limit"),
        ) if not inp.get("sql") else (inp["sql"], {})
        return sql
    if op == "insert":
        sql, _ = build_insert(inp.get("table") or "", inp.get("values") or {})
        return sql
    if op == "update":
        sql, _ = build_update(inp.get("table") or "", inp.get("values") or {}, inp.get("where"))
        return sql
    if op == "delete":
        sql, _ = build_delete(inp.get("table") or "", inp.get("where"))
        return sql
    if op == "customQuery":
        return inp.get("sql") or ""
    if op == "storedProcedure":
        return proc_statement(driver, inp.get("name") or "", inp.get("args"))
    raise ValueError(f"unknown operation: {operation}")


# ── schema introspection (autofill source for the designer) ───────────────────

def list_tables(config: dict[str, Any], schema: str | None = None) -> list[dict[str, Any]]:
    """Return tables (and views) visible to the connection."""
    insp = sa_inspect(get_engine(config))
    out = [{"name": t, "schema": schema, "kind": "table"} for t in insp.get_table_names(schema=schema)]
    try:
        out += [{"name": v, "schema": schema, "kind": "view"} for v in insp.get_view_names(schema=schema)]
    except Exception:
        pass
    return out


def list_columns(config: dict[str, Any], table: str, schema: str | None = None) -> list[dict[str, Any]]:
    """Return column metadata for a table (name, type, nullable, primary key)."""
    quote_ident(table)  # validate
    insp = sa_inspect(get_engine(config))
    pk = set()
    try:
        pk = set(insp.get_pk_constraint(table, schema=schema).get("constrained_columns") or [])
    except Exception:
        pass
    cols = []
    for c in insp.get_columns(table, schema=schema):
        cols.append({
            "name": c["name"],
            "type": str(c.get("type")),
            "nullable": bool(c.get("nullable", True)),
            "primary_key": c["name"] in pk,
        })
    return cols


# information_schema.routines covers postgresql / mysql / mssql; others return [].
_ROUTINES_SQL = (
    "SELECT routine_name FROM information_schema.routines "
    "WHERE routine_type = 'PROCEDURE' ORDER BY routine_name"
)


def list_procedures(config: dict[str, Any]) -> list[str]:
    driver = (config.get("driver") or "").lower()
    if driver in ("sqlite",):
        return []
    try:
        rows = run_query(config, _ROUTINES_SQL)
        return [str(r.get("routine_name")) for r in rows if r.get("routine_name")]
    except Exception:
        return []
