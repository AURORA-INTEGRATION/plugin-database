# plugin-database

Aurora connector plugin — **Database** (SQL).

A standalone Aurora package containing the `database` connector: a pooled
SQLAlchemy client plus operations rendered as forms in the designer.

## Operations
`select` · `insert` · `update` · `delete` · `customQuery` · `storedProcedure`

Drivers: PostgreSQL, MySQL, SQLite, MSSQL, Oracle (install the matching DBAPI:
`psycopg2`, `pymysql`, `pyodbc`, `oracledb`).

## Install (Aurora engine)
Add a **Git Source** pointing at this repo:
- URL: `https://github.com/AURORA-INTEGRATION/plugin-database`
- Branch: `main`
- Packages subfolder: `packages` (default)

The engine loads `packages/database/`, registers the connector type `database`
and its operation services (`common.connectors.database.*`). Create a connector
instance under **Connectors**, then drop a `database` operation into a flow.

## Layout
```
packages/database/
  package.yml
  connectors/database/
    connector.yml      # connection spec + studio metadata
    client.py          # pooled engine, dynamic-SQL builders, introspection
    operations/<op>/   # python_service (.yml + .py) with a ui: block
```
