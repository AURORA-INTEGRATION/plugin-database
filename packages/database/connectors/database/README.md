# Connector `database`

Multi-file connector. Unlike a flat connector spec, the database connector
ships a shared **client** plus a set of **operations**; the designer renders a
form (and a live SQL preview) for each operation instead of a raw flowservice
step.

```
connectors/database/
  connector.yml          # kind: connector — connection spec (driver/host/…) + studio metadata
  client.py              # shared pooled SQLAlchemy engine + dynamic-query builders
  operations/
    select/              # SELECT  (query-builder: table/columns/where/order/limit)
    insert/              # INSERT  (column form)
    update/              # UPDATE  (column form + where; WHERE required by default)
    delete/              # DELETE  (where; WHERE required by default)
    customQuery/         # free SQL with named params (read/write auto-detected)
    storedProcedure/     # CALL / EXEC / BEGIN per driver
```

Each `operations/<op>/<op>.yml` is a normal `kind: python_service`:
- `input:` / `output:` — the runtime contract (engine-validated).
- `ui:` — designer-only hints (`mode`, `fields`, `preview`); the engine ignores
  this block. Field `source:` values (`tables`, `columns`, `procedures`) drive
  schema introspection autofill.

## How it runs

1. Create a `database` connector instance in the admin (`/admin/connectors`):
   driver, host, port, username, password, database.
2. In the designer, right-click → **Database** → pick an operation.
3. The operation resolves the instance config via
   `get_connector_config("database", db_alias)`, builds a parametrized statement
   through `client.py`, and executes it on the pooled engine.

## Safety

- Identifiers (table/column/procedure) are validated against a strict whitelist
  (`client.quote_ident`); **values** always go through bound parameters.
- `update` / `delete` refuse to run without a `where` unless
  `allow_no_where: true` is set.

## Drivers

`postgresql`, `mysql`, `sqlite`, `mssql`, `oracle`. The matching DBAPI driver
(`psycopg2`, `pymysql`, `pyodbc`, `oracledb`) must be installed in the engine
environment; it is imported lazily on first connection.
