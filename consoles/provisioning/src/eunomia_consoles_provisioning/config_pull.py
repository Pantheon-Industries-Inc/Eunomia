"""Config-pull endpoints — serve task-config to fobs at boot (P2).

Endpoint 1 (``/api/task-config/{kit_id}``) returns the F9-compatible site-wide task-config
(assignments + roster). Endpoint 2 (``/api/station/{station_id}``) returns the Victor-compatible
per-station projection. Neither is login-protected (the fob calls them server-to-server).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Connection, Engine

from eunomia_edge_store import resolvers, schema, store

router = APIRouter()

_SITE_TZ_DEFAULT = "PST8PDT,M3.2.0,M11.1.0"

_engine_instance: Engine | None = None


def _get_engine() -> Engine:
    global _engine_instance  # noqa: PLW0603
    if _engine_instance is None:
        from eunomia_edge_store.config import StoreConfig
        from eunomia_edge_store.engine import make_engine

        _engine_instance = make_engine(StoreConfig.from_env())
    return _engine_instance


def _get_conn() -> Iterator[Connection]:
    with _get_engine().connect() as conn:
        yield conn


def _site_tz() -> str:
    return os.environ.get("EUNOMIA_SITE_TZ", _SITE_TZ_DEFAULT)


# ---------------------------------------------------------------------------
# Query logic (pure functions — take a Connection, testable without FastAPI)
# ---------------------------------------------------------------------------


def get_site_for_kit(conn: Connection, kit_id: str) -> str | None:
    """Resolve kit_id → site_id via session history. None if kit unknown or no site."""
    if store.get(conn, "kit", kit_id=kit_id) is None:
        return None
    session_table = schema.TABLES["session"]
    row = conn.execute(
        sa.select(session_table.c.site_id)
        .where(session_table.c.kit_id == kit_id, session_table.c.site_id != "")
        .order_by(session_table.c.signed_in_at.desc().nulls_last())
        .limit(1)
    ).first()
    return row[0] if row else None


def list_site_assignments(conn: Connection, site_id: str) -> list[dict[str, Any]]:
    """Active task→station assignments for a site, with resolved task fields."""
    now = datetime.now(timezone.utc)
    tsa = schema.TABLES["task_station_assignment"]
    rows = (
        conn.execute(
            sa.select(tsa).where(
                tsa.c.site_id == site_id,
                tsa.c.effective_from <= now,
                sa.or_(tsa.c.effective_to.is_(None), tsa.c.effective_to > now),
            )
        )
        .mappings()
        .all()
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        rec = store.from_row(tsa, dict(row))
        tv = rec.get("task_version") or 0
        rid = rec.get("rotation_id") or ""
        task = store.get(
            conn, "task", task_id=rec["task_id"], version=tv, rotation_id=rid
        )
        result.append(
            {
                "station_id": rec["station_id"],
                "task_id": rec["task_id"],
                "task_name": (task or {}).get("task_name", ""),
                "prompt": (task or {}).get("prompt", ""),
                "rotation_id": rid,
                "task_version": tv,
            }
        )
    return result


def list_site_roster(conn: Connection, site_id: str) -> list[str]:
    """Active person_ids for a site."""
    from eunomia_consoles_provisioning.roster import list_persons

    return [p["person_id"] for p in list_persons(conn, site_id)]


def build_task_config(conn: Connection, kit_id: str) -> dict[str, Any] | None:
    """Full F9-compatible task-config response. None if kit/site unknown."""
    site_id = get_site_for_kit(conn, kit_id)
    if site_id is None:
        return None
    return {
        "site_id": site_id,
        "tz": _site_tz(),
        "assignments": list_site_assignments(conn, site_id),
        "roster": list_site_roster(conn, site_id),
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def lookup_station(conn: Connection, station_id: str) -> dict[str, Any] | None:
    """Victor-compatible per-station lookup. None if not found."""
    station_table = schema.TABLES["station"]
    row = (
        conn.execute(
            sa.select(station_table).where(station_table.c.station_id == station_id)
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    rec = store.from_row(station_table, dict(row))
    site_id = rec["site_id"]
    now = datetime.now(timezone.utc)
    assignment = resolvers.resolve_task_station_assignment(
        conn, site_id=site_id, station_id=station_id, at=now
    )
    task_name = ""
    prompt = ""
    if assignment:
        tv = assignment.get("task_version") or 0
        rid = assignment.get("rotation_id") or ""
        task = store.get(
            conn, "task", task_id=assignment["task_id"], version=tv, rotation_id=rid
        )
        if task:
            task_name = task.get("task_name", "")
            prompt = task.get("prompt", "")
    return {
        "id": station_id,
        "label": rec.get("label") or f"Station {station_id}",
        "task_name": task_name,
        "prompt": prompt,
        "tz": _site_tz(),
    }


# ---------------------------------------------------------------------------
# Endpoints (NOT login-protected — fob calls these server-to-server)
# ---------------------------------------------------------------------------


@router.get("/api/task-config/{kit_id}")
def get_task_config(
    kit_id: str, conn: Connection = Depends(_get_conn)
) -> dict[str, Any]:
    result = build_task_config(conn, kit_id)
    if result is None:
        raise HTTPException(status_code=404, detail={"error": "unknown kit"})
    return result


@router.get("/api/station/{station_id}")
def get_station(
    station_id: str, conn: Connection = Depends(_get_conn)
) -> dict[str, Any]:
    result = lookup_station(conn, station_id)
    if result is None:
        raise HTTPException(status_code=404, detail={"error": "station not found"})
    return result
