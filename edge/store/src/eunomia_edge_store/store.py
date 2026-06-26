"""The store API — upsert current-state rows + append-only events.

- Timestamp fields are parsed to instants on write and normalized back to canonical UTC ISO on read
  (NOTE F5). Object/array fields round-trip through JSONB unchanged.
- Writes never reject on a dangling reference (NOTE F6): out-of-order arrival is normal; the
  ``resolvers`` module is where dangling refs are surfaced.
- ``operational_event`` is append-only and idempotent on ``event_id`` (insert; conflict → no-op).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from eunomia_edge_store import schema
from eunomia_edge_store.timestamps import parse_instant, to_iso

EVENT_TABLE = "operational_event"


def _timestamp_columns(table: sa.Table) -> frozenset[str]:
    return frozenset(c.name for c in table.columns if isinstance(c.type, sa.DateTime))


def to_row(table: sa.Table, record: dict[str, Any]) -> dict[str, Any]:
    """Project a contract record onto the table's columns, parsing timestamp fields to instants."""
    ts = _timestamp_columns(table)
    row: dict[str, Any] = {}
    for col in table.columns:
        if col.name not in record:
            continue
        value = record[col.name]
        if value is not None and col.name in ts:
            value = parse_instant(value)
        row[col.name] = value
    return row


def from_row(table: sa.Table, mapping: dict[str, Any]) -> dict[str, Any]:
    """Normalize a fetched row back to a contract-shaped dict (timestamps → canonical UTC ISO)."""
    ts = _timestamp_columns(table)
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        out[key] = to_iso(value) if (key in ts and value is not None) else value
    return out


def upsert(conn: Connection, table_name: str, record: dict[str, Any]) -> None:
    """Insert-or-update a current-state row by its primary key."""
    table = schema.TABLES[table_name]
    row = to_row(table, record)
    pk = [c.name for c in table.primary_key.columns]
    stmt = pg_insert(table).values(**row)
    updatable = {name: stmt.excluded[name] for name in row if name not in pk}
    if updatable:
        stmt = stmt.on_conflict_do_update(index_elements=pk, set_=updatable)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=pk)
    conn.execute(stmt)


def get(conn: Connection, table_name: str, **key: Any) -> dict[str, Any] | None:
    """Fetch one current-state row by primary-key columns; None if absent."""
    table = schema.TABLES[table_name]
    where = [table.c[name] == value for name, value in key.items()]
    result = conn.execute(sa.select(table).where(*where)).mappings().first()
    return None if result is None else from_row(table, dict(result))


def append_event(conn: Connection, event: dict[str, Any]) -> None:
    """Append an operational event (append-only; idempotent on event_id)."""
    table = schema.TABLES[EVENT_TABLE]
    row = to_row(table, event)
    stmt = (
        pg_insert(table)
        .values(**row)
        .on_conflict_do_nothing(index_elements=["event_id"])
    )
    conn.execute(stmt)


def count(conn: Connection, table_name: str) -> int:
    table = (
        schema.TABLES[table_name]
        if table_name in schema.TABLES
        else _native(table_name)
    )
    return int(conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one())


def _native(table_name: str) -> sa.Table:
    natives = {
        "camera_id_ledger": schema.camera_id_ledger,
        "import_backup": schema.import_backup,
    }
    if table_name not in natives:
        raise KeyError(table_name)
    return natives[table_name]
