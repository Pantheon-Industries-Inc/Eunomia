"""Raw record queries for the store inspector.

All queries take a SQLAlchemy ``Connection`` and return plain dicts/lists. The inspector shows
every field as-is — no aggregation, no derived columns.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from eunomia_edge_store.schema import TABLES


def episode_list(
    conn: Connection,
    *,
    limit: int = 10,
    offset: int = 0,
    episode_id: str | None = None,
    kit_id: str | None = None,
    task_id: str | None = None,
    operator_id: str | None = None,
) -> list[dict[str, Any]]:
    ep = TABLES["episode"]
    person = TABLES["person"]
    task = TABLES["task"]

    wheres: list[sa.ColumnElement[bool]] = []
    if episode_id:
        wheres.append(ep.c.episode_id.ilike(f"%{episode_id}%"))
    if kit_id:
        wheres.append(ep.c.kit_id == kit_id)
    if task_id:
        wheres.append(ep.c.task_id == task_id)
    if operator_id:
        wheres.append(ep.c.person_id == operator_id)

    stmt = (
        sa.select(
            ep.c.episode_id,
            ep.c.display_id,
            ep.c.recorded_at,
            ep.c.kit_id,
            ep.c.person_id,
            ep.c.task_id,
            ep.c.archive,
            ep.c.recording_suspect,
            ep.c.void,
            ep.c.ingested_at,
            person.c.name.label("operator_name"),
            task.c.task_name,
        )
        .outerjoin(person, ep.c.person_id == person.c.person_id)
        .outerjoin(
            task,
            sa.and_(
                ep.c.task_id == task.c.task_id,
                ep.c.task_version == task.c.version,
                ep.c.rotation_id == task.c.rotation_id,
            ),
        )
    )
    if wheres:
        stmt = stmt.where(sa.and_(*wheres))

    stmt = (
        stmt.order_by(ep.c.recorded_at.desc().nulls_last()).limit(limit).offset(offset)
    )
    return [dict(r) for r in conn.execute(stmt).mappings().all()]


def episode_detail(conn: Connection, episode_id: str) -> dict[str, Any] | None:
    ep = TABLES["episode"]
    row = (
        conn.execute(sa.select(ep).where(ep.c.episode_id == episode_id))
        .mappings()
        .first()
    )
    if row is None:
        return None
    return dict(row)


def episode_events(conn: Connection, episode_id: str) -> list[dict[str, Any]]:
    oe = TABLES["operational_event"]
    stmt = (
        sa.select(oe)
        .where(sa.and_(oe.c.entity == "episode", oe.c.entity_id == episode_id))
        .order_by(oe.c.as_of.desc().nulls_last())
    )
    return [dict(r) for r in conn.execute(stmt).mappings().all()]


def episode_footage_ref(conn: Connection, episode_id: str) -> dict[str, Any] | None:
    fr = TABLES["footage_reference"]
    row = (
        conn.execute(sa.select(fr).where(fr.c.episode_id == episode_id))
        .mappings()
        .first()
    )
    if row is None:
        return None
    return dict(row)


def episode_session(conn: Connection, session_id: str) -> dict[str, Any] | None:
    s = TABLES["session"]
    row = (
        conn.execute(sa.select(s).where(s.c.session_id == session_id))
        .mappings()
        .first()
    )
    if row is None:
        return None
    return dict(row)


def event_list(
    conn: Connection,
    *,
    limit: int = 10,
    offset: int = 0,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    oe = TABLES["operational_event"]
    stmt = sa.select(oe).order_by(oe.c.as_of.desc().nulls_last()).limit(limit)
    if event_type:
        stmt = stmt.where(oe.c.event_type == event_type)
    stmt = stmt.offset(offset)
    return [dict(r) for r in conn.execute(stmt).mappings().all()]


def event_types(conn: Connection) -> list[str]:
    oe = TABLES["operational_event"]
    rows = (
        conn.execute(sa.select(sa.distinct(oe.c.event_type)).order_by(oe.c.event_type))
        .scalars()
        .all()
    )
    return list(rows)


def session_list(
    conn: Connection,
    *,
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, Any]]:
    s = TABLES["session"]
    person = TABLES["person"]
    stmt = (
        sa.select(s, person.c.name.label("operator_name"))
        .outerjoin(person, s.c.person_id == person.c.person_id)
        .order_by(s.c.signed_in_at.desc().nulls_last())
        .limit(limit)
        .offset(offset)
    )
    return [dict(r) for r in conn.execute(stmt).mappings().all()]


def task_list_raw(
    conn: Connection,
    *,
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, Any]]:
    t = TABLES["task"]
    stmt = (
        sa.select(t)
        .order_by(t.c.task_id, t.c.version.desc())
        .limit(limit)
        .offset(offset)
    )
    return [dict(r) for r in conn.execute(stmt).mappings().all()]
