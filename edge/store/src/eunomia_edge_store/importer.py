"""The documented-shape registry importer (NOTE F1).

A **non-destructive merge** (drift-detect + backup), never a destructive overwrite — the
camera_map-incident lesson. The authoritative source wins on the identity fields; every other existing
value is preserved, and rows absent from the import are NEVER deleted. Before any mutation the prior
row is written to the insert-only ``import_backup`` table (the audit). Existing camera_ids are
preserved verbatim (NOTE F7); a camera with none gets one minted by the allocator.

Built against the DOCUMENTED registry shape + the committed synthetic fixture (``fixtures/``) — the
real ``fleet``/``stations`` files were moved/absent; swap the source loader once the live location is
confirmed. The merge DECISION is a pure function (``plan_merge``) so it is unit-testable with no DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from eunomia_edge_store import allocator, schema, store

# The authoritative fields the registry owns on a merge (it wins on these); everything else on an
# existing row is preserved. camera_id is special: PRESERVED verbatim, never overwritten (NOTE F7).
_AUTHORITATIVE: dict[str, tuple[str, ...]] = {
    "hardware_unit": (
        "type",
        "body_serial",
        "insv_serial",
        "mac",
        "kit_id",
        "side",
        "status",
        "hardware_version",
        "fob_id",
        "board",
        "mount",
    ),
    # registered_at is set once on create (it stays in the inserted record) but is NOT an
    # authoritative-overwrite field — re-importing must not re-stamp it, so a re-import stays
    # idempotent regardless of the as_of timezone.
    "station": ("status", "label"),
}
_PRESERVE: dict[str, tuple[str, ...]] = {"hardware_unit": ("camera_id",), "station": ()}

HARDWARE_UNIT_SCHEMA = "eunomia-hardware-unit/v1"
STATION_SCHEMA = "eunomia-station/v1"
ASSIGNMENT_SCHEMA = "eunomia-task-station-assignment/v1"


@dataclass(frozen=True)
class MergePlan:
    action: str  # created | updated | unchanged
    values: dict[
        str, Any
    ]  # fields to write (created: full record; updated: only the changed fields)
    drift: dict[
        str, Any
    ]  # field -> {from, to} for authoritative changes; {kept, ignored} for preserves


def plan_merge(
    entity: str, existing: dict[str, Any] | None, incoming: dict[str, Any]
) -> MergePlan:
    """PURE merge decision (no DB): what a non-destructive import would do to one row."""
    if existing is None:
        return MergePlan(action="created", values=dict(incoming), drift={})
    values: dict[str, Any] = {}
    drift: dict[str, Any] = {}
    for f in _AUTHORITATIVE.get(entity, ()):
        if f in incoming and incoming[f] is not None and incoming[f] != existing.get(f):
            drift[f] = {"from": existing.get(f), "to": incoming[f]}
            values[f] = incoming[f]
    for f in _PRESERVE.get(entity, ()):
        # A set value is preserved verbatim; flag (but do not apply) an incoming change.
        if incoming.get(f) is not None and existing.get(f) not in (None, incoming[f]):
            drift[f] = {"kept": existing.get(f), "ignored": incoming[f]}
        elif existing.get(f) is None and incoming.get(f) is not None:
            # An absent value may be filled additively (non-destructive).
            values[f] = incoming[f]
    return MergePlan(
        action="updated" if values else "unchanged", values=values, drift=drift
    )


@dataclass
class RegistryReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    allocated_camera_ids: dict[str, str] = field(default_factory=dict)
    assignments_created: list[str] = field(default_factory=list)
    dangling: list[Any] = field(default_factory=list)
    backups: int = 0


def import_registry(
    conn: Connection,
    registry: dict[str, Any],
    *,
    run_id: str,
    as_of: datetime,
    allocate_missing: bool = True,
) -> RegistryReport:
    """Apply a documented-shape registry as a non-destructive merge; return what changed."""
    report = RegistryReport()
    site_id = registry["site_id"]
    for cam in registry.get("cameras", []):
        _import_camera(
            conn, cam, run_id=run_id, allocate_missing=allocate_missing, report=report
        )
    for st in registry.get("stations", []):
        _import_station(
            conn, st, site_id=site_id, run_id=run_id, as_of=as_of, report=report
        )
    return report


def _backup(
    conn: Connection,
    *,
    run_id: str,
    entity: str,
    key: dict[str, Any],
    before: dict[str, Any] | None,
    drift: dict[str, Any],
    action: str,
) -> None:
    conn.execute(
        schema.import_backup.insert().values(
            import_run_id=run_id,
            entity=entity,
            natural_key=key,
            before_image=before,
            drift=drift,
            action=action,
        )
    )


def _import_camera(
    conn: Connection,
    cam: dict[str, Any],
    *,
    run_id: str,
    allocate_missing: bool,
    report: RegistryReport,
) -> None:
    unit_id = cam.get("unit_id") or f"unit-{cam['body_serial']}"
    incoming: dict[str, Any] = {
        "schema": HARDWARE_UNIT_SCHEMA,
        "unit_id": unit_id,
        "type": "camera",
        "body_serial": cam.get("body_serial"),
        "insv_serial": cam.get("insv_serial"),
        "mac": cam.get("mac"),
        "kit_id": cam.get("kit_id"),
        "side": cam.get("side"),
        "status": cam.get("status", "provisioned"),
        "camera_id": cam.get("camera_id"),
    }
    existing = store.get(conn, "hardware_unit", unit_id=unit_id)
    plan = plan_merge("hardware_unit", existing, incoming)

    # camera_id: preserve existing verbatim; else use incoming verbatim; else mint one (NOTE F7).
    existing_cam = existing.get("camera_id") if existing else None
    if existing_cam is None and incoming.get("camera_id") is None and allocate_missing:
        minted = allocator.allocate_camera_id(
            conn, body_serial=cam.get("body_serial"), allocated_by=run_id
        )
        incoming["camera_id"] = minted
        report.allocated_camera_ids[unit_id] = minted
        if plan.action == "unchanged":
            plan = MergePlan(
                action="updated", values={"camera_id": minted}, drift=plan.drift
            )
        else:
            plan.values["camera_id"] = minted

    table = schema.TABLES["hardware_unit"]
    key = {"unit_id": unit_id}
    if plan.action == "created":
        conn.execute(table.insert().values(**store.to_row(table, incoming)))
        _backup(
            conn,
            run_id=run_id,
            entity="hardware_unit",
            key=key,
            before=None,
            drift={},
            action="created",
        )
        report.backups += 1
        report.created.append(unit_id)
    elif plan.action == "updated":
        _backup(
            conn,
            run_id=run_id,
            entity="hardware_unit",
            key=key,
            before=existing,
            drift=plan.drift,
            action="updated",
        )
        report.backups += 1
        conn.execute(
            sa.update(table)
            .where(table.c.unit_id == unit_id)
            .values(**store.to_row(table, {**key, **plan.values}))
        )
        report.updated.append(unit_id)
    else:
        report.unchanged.append(unit_id)


def _import_station(
    conn: Connection,
    st: dict[str, Any],
    *,
    site_id: str,
    run_id: str,
    as_of: datetime,
    report: RegistryReport,
) -> None:
    station_id = str(st["station_id"])
    incoming = {
        "schema": STATION_SCHEMA,
        "site_id": site_id,
        "station_id": station_id,
        "status": st.get("status", "active"),
        "label": st.get("label"),
        "registered_at": as_of.isoformat(),
    }
    existing = store.get(conn, "station", site_id=site_id, station_id=station_id)
    plan = plan_merge("station", existing, incoming)
    table = schema.TABLES["station"]
    key = {"site_id": site_id, "station_id": station_id}
    if plan.action == "created":
        conn.execute(table.insert().values(**store.to_row(table, incoming)))
        _backup(
            conn,
            run_id=run_id,
            entity="station",
            key=key,
            before=None,
            drift={},
            action="created",
        )
        report.backups += 1
        report.created.append(f"{site_id}/{station_id}")
    elif plan.action == "updated":
        _backup(
            conn,
            run_id=run_id,
            entity="station",
            key=key,
            before=existing,
            drift=plan.drift,
            action="updated",
        )
        report.backups += 1
        conn.execute(
            sa.update(table)
            .where(table.c.site_id == site_id, table.c.station_id == station_id)
            .values(**store.to_row(table, {**key, **plan.values}))
        )
        report.updated.append(f"{site_id}/{station_id}")
    else:
        report.unchanged.append(f"{site_id}/{station_id}")

    if st.get("task_id"):
        _ensure_assignment(
            conn, st, site_id=site_id, station_id=station_id, as_of=as_of, report=report
        )


def _ensure_assignment(
    conn: Connection,
    st: dict[str, Any],
    *,
    site_id: str,
    station_id: str,
    as_of: datetime,
    report: RegistryReport,
) -> None:
    # Append-only + idempotent: a deterministic assignment_id means re-importing the same mapping is a
    # no-op (on-conflict-do-nothing), while a genuinely new mapping appends a new row.
    task_id = st["task_id"]
    task_version = st.get("task_version")
    rotation_id = st.get("rotation_id")
    assignment_id = f"imp:{site_id}:{station_id}:{task_id}:{task_version}:{rotation_id}"
    record = {
        "schema": ASSIGNMENT_SCHEMA,
        "assignment_id": assignment_id,
        "site_id": site_id,
        "station_id": station_id,
        "task_id": task_id,
        "task_version": task_version,
        "rotation_id": rotation_id,
        "effective_from": as_of.isoformat(),
    }
    table = schema.TABLES["task_station_assignment"]
    result = conn.execute(
        pg_insert(table)
        .values(**store.to_row(table, record))
        .on_conflict_do_nothing(index_elements=["assignment_id"])
    )
    if result.rowcount:
        report.assignments_created.append(assignment_id)
