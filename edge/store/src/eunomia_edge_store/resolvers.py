"""As-of resolution + loud dangling-reference flagging (NOTE F6).

There are NO hard foreign keys — the as-of grain + out-of-order arrival break simple FKs. But a
reference to a missing kit / task / station is NEVER a silent orphan: the resolver surfaces it as a
``DanglingReference``. The resolver enforces; the store does not hide gaps.

As-of resolution picks the row whose ``[effective_from, effective_to)`` window contains the instant;
the latest ``effective_from`` wins on overlap (the documented task_station_assignment rule).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from eunomia_edge_store import schema
from eunomia_edge_store.store import from_row


@dataclass(frozen=True)
class Reference:
    """A reference column-set on ``source`` that should point at a row of ``target``."""

    source_columns: tuple[str, ...]
    target: str
    target_columns: tuple[str, ...]


@dataclass(frozen=True)
class DanglingReference:
    source: str
    target: str
    key: dict[str, Any]


# Every reference column is indexed (schema.py) but not FK'd; these drive the loud dangling check.
REFERENCES: dict[str, tuple[Reference, ...]] = {
    "episode": (
        Reference(("kit_id",), "kit", ("kit_id",)),
        Reference(("session_id",), "session", ("session_id",)),
        Reference(("person_id",), "person", ("person_id",)),
        Reference(("calibration_id",), "calibration", ("calibration_id",)),
        Reference(("capture_stack_id",), "capture_stack", ("capture_stack_id",)),
        Reference(
            ("task_id", "task_version", "rotation_id"),
            "task",
            ("task_id", "version", "rotation_id"),
        ),
    ),
    "session": (
        Reference(("person_id",), "person", ("person_id",)),
        Reference(("kit_id",), "kit", ("kit_id",)),
    ),
    "kit": (
        Reference(("left_cam_unit_id",), "hardware_unit", ("unit_id",)),
        Reference(("right_cam_unit_id",), "hardware_unit", ("unit_id",)),
        Reference(("fob_unit_id",), "hardware_unit", ("unit_id",)),
        Reference(("setup_version_id",), "setup_version", ("setup_id",)),
    ),
    "hardware_unit": (
        Reference(("kit_id",), "kit", ("kit_id",)),
        Reference(("hardware_catalog_id",), "hardware_catalog", ("catalog_id",)),
    ),
    "capture_stack": (Reference(("kit_id",), "kit", ("kit_id",)),),
    "footage_reference": (Reference(("episode_id",), "episode", ("episode_id",)),),
    "task_station_assignment": (Reference(("task_id",), "task", ("task_id",)),),
}


_NATIVE_TABLES: dict[str, sa.Table] = {
    "hardware_catalog": schema.hardware_catalog,
    "firmware_catalog": schema.firmware_catalog,
    "setup_version": schema.setup_version,
}


def _resolve_table(name: str) -> sa.Table:
    if name in schema.TABLES:
        return schema.TABLES[name]
    if name in _NATIVE_TABLES:
        return _NATIVE_TABLES[name]
    raise KeyError(f"Unknown table: {name}")


def _exists(conn: Connection, target: str, key: dict[str, Any]) -> bool:
    table = _resolve_table(target)
    where = [table.c[name] == value for name, value in key.items()]
    return (
        conn.execute(sa.select(sa.literal(1)).where(*where).limit(1)).first()
        is not None
    )


def find_dangling_references(
    conn: Connection, table_name: str, record: dict[str, Any]
) -> list[DanglingReference]:
    """Surface every reference in ``record`` that points at a missing row (loud, never silent)."""
    dangling: list[DanglingReference] = []
    for ref in REFERENCES.get(table_name, ()):
        # Match only the components present (non-null) in the record. An all-null reference is no
        # reference at all (skip); a partially-specified key checks the present subset.
        key = {
            tgt: record[src]
            for src, tgt in zip(ref.source_columns, ref.target_columns, strict=True)
            if record.get(src) is not None
        }
        if not key:
            continue
        if not _exists(conn, ref.target, key):
            dangling.append(
                DanglingReference(source=table_name, target=ref.target, key=key)
            )
    return dangling


def resolve_task_station_assignment(
    conn: Connection, *, site_id: str, station_id: str, at: datetime
) -> dict[str, Any] | None:
    """The as-of station→task assignment: the row whose window contains ``at`` (latest start wins)."""
    table = schema.TABLES["task_station_assignment"]
    stmt = (
        sa.select(table)
        .where(
            table.c.site_id == site_id,
            table.c.station_id == station_id,
            table.c.effective_from <= at,
            sa.or_(table.c.effective_to.is_(None), table.c.effective_to > at),
        )
        .order_by(table.c.effective_from.desc())
        .limit(1)
    )
    row = conn.execute(stmt).mappings().first()
    return None if row is None else from_row(table, dict(row))


def resolve_capture_stack(
    conn: Connection, *, kit_id: str, at: datetime
) -> dict[str, Any] | None:
    """The as-of capture_stack for a kit: the row whose window contains ``at`` (latest start wins)."""
    table = schema.TABLES["capture_stack"]
    stmt = (
        sa.select(table)
        .where(
            table.c.kit_id == kit_id,
            sa.or_(table.c.effective_from.is_(None), table.c.effective_from <= at),
            sa.or_(table.c.effective_to.is_(None), table.c.effective_to > at),
        )
        .order_by(table.c.effective_from.desc().nulls_last())
        .limit(1)
    )
    row = conn.execute(stmt).mappings().first()
    return None if row is None else from_row(table, dict(row))
