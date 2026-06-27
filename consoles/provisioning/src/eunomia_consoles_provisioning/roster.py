"""Person roster management — CRUD against S1 for the CONFIRM_ID source."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import Connection

from eunomia_edge_store import store


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id() -> str:
    return f"evt-{uuid4().hex[:12]}"


def list_persons(conn: Connection, site_id: str) -> list[dict[str, Any]]:
    """List active persons at a site."""
    import sqlalchemy as sa

    from eunomia_edge_store import schema

    table = schema.TABLES["person"]
    rows = (
        conn.execute(sa.select(table).where(table.c.status == "active"))
        .mappings()
        .all()
    )

    result = []
    for row in rows:
        record = store.from_row(table, dict(row))
        site_ids = record.get("site_ids", [])
        if isinstance(site_ids, list) and site_id in site_ids:
            result.append(record)
    return result


def upsert_person(
    conn: Connection,
    *,
    person_id: str,
    name: str,
    role: str = "operator",
    status: str = "active",
    site_ids: list[str] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema": "eunomia-person/v1",
        "person_id": person_id,
        "name": name,
        "role": role,
        "status": status,
        "site_ids": site_ids or [],
    }
    store.upsert(conn, "person", record)
    return record


def onboard_person(
    conn: Connection,
    *,
    person_id: str,
    name: str,
    site_id: str,
    role: str = "operator",
) -> dict[str, Any]:
    """Onboard a person: create/update record + emit lifecycle event."""
    now = _now_iso()
    record = upsert_person(
        conn,
        person_id=person_id,
        name=name,
        role=role,
        status="active",
        site_ids=[site_id],
    )
    record["onboarded_at"] = now
    store.upsert(conn, "person", record)

    store.append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": _event_id(),
            "event_type": "person_onboarded",
            "entity": "person",
            "entity_id": person_id,
            "as_of": now,
            "payload": {"name": name, "site_id": site_id, "role": role},
        },
    )
    return record


def offboard_person(conn: Connection, *, person_id: str) -> None:
    """Offboard a person: set status + emit lifecycle event."""
    now = _now_iso()
    existing = store.get(conn, "person", person_id=person_id)
    if existing is None:
        raise ValueError(f"Person {person_id} not found")

    existing["status"] = "offboarded"
    existing["offboarded_at"] = now
    store.upsert(conn, "person", existing)

    store.append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": _event_id(),
            "event_type": "person_offboarded",
            "entity": "person",
            "entity_id": person_id,
            "as_of": now,
        },
    )
