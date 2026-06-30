"""Supervisor task-assignment workflow — catalog CRUD, operator assignments, progress tracking.

Run P3. Store-native tables (operator_task_assignment, collection_target) are NOT contract entities;
the task catalog entries are contract entities (task table) minted with permanent numeric IDs from
task_catalog_seq.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from eunomia_edge_store import schema, store

MAX_TASKS_PER_OPERATOR = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id() -> str:
    return f"evt-{uuid4().hex[:12]}"


def _current_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


# ---------------------------------------------------------------------------
# Task catalog
# ---------------------------------------------------------------------------


def mint_task_id(conn: Connection) -> str:
    """Mint a permanent numeric task_id from task_catalog_seq (retire-not-reuse)."""
    n = conn.execute(sa.select(schema.task_catalog_seq.next_value())).scalar_one()
    return str(int(n))


def create_task(
    conn: Connection,
    *,
    task_name: str,
    prompt: str = "",
    category: str | None = None,
    family: str | None = None,
    expected_duration_s: float | None = None,
    bimanual: bool = False,
    metadata: dict[str, Any] | None = None,
    created_by: str = "supervisor",
) -> dict[str, Any]:
    """Create a new catalog task with a permanent numeric ID."""
    task_id = mint_task_id(conn)
    now = _now_iso()
    record: dict[str, Any] = {
        "schema": "eunomia-task/v1",
        "task_id": task_id,
        "version": 1,
        "rotation_id": "default",
        "task_name": task_name,
        "prompt": prompt or task_name,
        "category": category,
        "family": family,
        "bimanual": bimanual,
        "expected_duration_s": expected_duration_s,
        "metadata": metadata,
        "effective_from": now,
    }
    store.upsert(conn, "task", record)
    store.append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": _event_id(),
            "event_type": "task_created",
            "entity": "task",
            "entity_id": task_id,
            "as_of": now,
            "payload": {
                "task_name": task_name,
                "category": category,
                "family": family,
                "created_by": created_by,
            },
        },
    )
    return record


def list_tasks(conn: Connection) -> list[dict[str, Any]]:
    """List all catalog tasks (latest version per task_id)."""
    table = schema.TABLES["task"]
    rows = (
        conn.execute(sa.select(table).order_by(table.c.task_id.cast(sa.BigInteger)))
        .mappings()
        .all()
    )

    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        record = store.from_row(table, dict(row))
        tid = record["task_id"]
        existing = seen.get(tid)
        if existing is None or record.get("version", 0) > existing.get("version", 0):
            seen[tid] = record
    return list(seen.values())


def decommission_task(
    conn: Connection, task_id: str, *, decommissioned_by: str = "supervisor"
) -> None:
    """Decommission a task (set effective_to on all versions). Never deletes."""
    table = schema.TABLES["task"]
    now = _now_iso()
    rows = (
        conn.execute(sa.select(table).where(table.c.task_id == task_id))
        .mappings()
        .all()
    )
    if not rows:
        raise ValueError(f"Task {task_id} not found")
    for row in rows:
        record = store.from_row(table, dict(row))
        if record.get("effective_to") is not None:
            continue
        record["effective_to"] = now
        store.upsert(conn, "task", record)
    store.append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": _event_id(),
            "event_type": "task_decommissioned",
            "entity": "task",
            "entity_id": task_id,
            "as_of": now,
            "payload": {"decommissioned_by": decommissioned_by},
        },
    )


def get_task_status(task: dict[str, Any]) -> str:
    """Return 'active' or 'decommissioned' based on effective_to."""
    return "decommissioned" if task.get("effective_to") is not None else "active"


# ---------------------------------------------------------------------------
# Operator task assignment
# ---------------------------------------------------------------------------


def _active_assignment_count(conn: Connection, person_id: str, week_of: date) -> int:
    t = schema.operator_task_assignment
    result = conn.execute(
        sa.select(sa.func.count()).where(
            t.c.person_id == person_id,
            t.c.week_of == week_of,
            t.c.status == "active",
        )
    ).scalar_one()
    return int(result)


def assign_task(
    conn: Connection,
    *,
    person_id: str,
    task_id: str,
    week_of: date | None = None,
    assigned_by: str,
) -> dict[str, Any]:
    """Add a task to an operator's weekly list. Enforces 10-task cap."""
    if week_of is None:
        week_of = _current_monday()
    if week_of.weekday() != 0:
        raise ValueError("week_of must be a Monday")

    person = store.get(conn, "person", person_id=person_id)
    if person is None:
        raise LookupError(f"Person {person_id} not found")

    task_table = schema.TABLES["task"]
    task_row = (
        conn.execute(sa.select(task_table).where(task_table.c.task_id == task_id))
        .mappings()
        .first()
    )
    if task_row is None:
        raise LookupError(f"Task {task_id} not found")

    count = _active_assignment_count(conn, person_id, week_of)
    if count >= MAX_TASKS_PER_OPERATOR:
        raise ValueError(
            f"Operator {person_id} already has {MAX_TASKS_PER_OPERATOR} active tasks this week"
        )

    t = schema.operator_task_assignment
    existing = (
        conn.execute(
            sa.select(t).where(
                t.c.person_id == person_id,
                t.c.task_id == task_id,
                t.c.week_of == week_of,
            )
        )
        .mappings()
        .first()
    )

    now = _now_iso()
    if existing is not None:
        if existing["status"] == "active":
            raise ValueError(
                f"Task {task_id} already assigned to {person_id} for week {week_of}"
            )
        conn.execute(
            t.update()
            .where(t.c.id == existing["id"])
            .values(
                status="active",
                removed_at=None,
                assigned_at=sa.func.now(),
                assigned_by=assigned_by,
            )
        )
    else:
        conn.execute(
            t.insert().values(
                person_id=person_id,
                task_id=task_id,
                assigned_by=assigned_by,
                week_of=week_of,
            )
        )

    store.append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": _event_id(),
            "event_type": "operator_task_assigned",
            "entity": "person",
            "entity_id": person_id,
            "as_of": now,
            "payload": {
                "task_id": task_id,
                "week_of": week_of.isoformat(),
                "assigned_by": assigned_by,
            },
        },
    )
    return {"person_id": person_id, "task_id": task_id, "week_of": week_of.isoformat()}


def unassign_task(
    conn: Connection,
    *,
    person_id: str,
    task_id: str,
    week_of: date | None = None,
) -> None:
    """Remove a task from an operator's weekly list."""
    if week_of is None:
        week_of = _current_monday()

    t = schema.operator_task_assignment
    existing = (
        conn.execute(
            sa.select(t).where(
                t.c.person_id == person_id,
                t.c.task_id == task_id,
                t.c.week_of == week_of,
                t.c.status == "active",
            )
        )
        .mappings()
        .first()
    )
    if existing is None:
        raise LookupError(
            f"No active assignment of task {task_id} for {person_id} week {week_of}"
        )

    conn.execute(
        t.update()
        .where(t.c.id == existing["id"])
        .values(status="removed", removed_at=sa.func.now())
    )

    store.append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": _event_id(),
            "event_type": "operator_task_unassigned",
            "entity": "person",
            "entity_id": person_id,
            "as_of": _now_iso(),
            "payload": {
                "task_id": task_id,
                "week_of": week_of.isoformat(),
            },
        },
    )


def get_operator_assignments(
    conn: Connection, person_id: str, week_of: date | None = None
) -> list[dict[str, Any]]:
    """Get an operator's active task list for a given week."""
    if week_of is None:
        week_of = _current_monday()

    t = schema.operator_task_assignment
    task_table = schema.TABLES["task"]

    rows = (
        conn.execute(
            sa.select(t)
            .where(
                t.c.person_id == person_id,
                t.c.week_of == week_of,
                t.c.status == "active",
            )
            .order_by(t.c.assigned_at)
        )
        .mappings()
        .all()
    )

    result = []
    for row in rows:
        task_row = (
            conn.execute(
                sa.select(task_table).where(task_table.c.task_id == row["task_id"])
            )
            .mappings()
            .first()
        )
        task_name = ""
        if task_row is not None:
            rec = store.from_row(task_table, dict(task_row))
            task_name = rec.get("task_name", "")
        result.append(
            {
                "task_id": row["task_id"],
                "task_name": task_name,
                "assigned_at": row["assigned_at"].isoformat()
                if row["assigned_at"]
                else None,
            }
        )
    return result


def list_operators_with_assignments(
    conn: Connection,
    *,
    site_id: str | None = None,
    week_of: date | None = None,
) -> list[dict[str, Any]]:
    """List active operators with their current-week task assignments."""
    if week_of is None:
        week_of = _current_monday()

    person_table = schema.TABLES["person"]
    rows = (
        conn.execute(sa.select(person_table).where(person_table.c.status == "active"))
        .mappings()
        .all()
    )

    result = []
    for row in rows:
        person = store.from_row(person_table, dict(row))
        if site_id:
            person_sites = person.get("site_ids", [])
            if isinstance(person_sites, list) and site_id not in person_sites:
                continue
        assignments = get_operator_assignments(conn, person["person_id"], week_of)
        result.append(
            {
                "person_id": person["person_id"],
                "name": person.get("name", ""),
                "role": person.get("role", ""),
                "assignment_count": len(assignments),
                "assignments": assignments,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Progress tracking (session-based, Option A)
# ---------------------------------------------------------------------------


def get_progress(
    conn: Connection, *, period: str | None = None
) -> list[dict[str, Any]]:
    """Hours collected per task (from session records) vs collection targets."""
    session_table = schema.TABLES["session"]

    hours_query = (
        sa.select(
            session_table.c.task_id,
            sa.func.sum(
                sa.func.extract(
                    "epoch",
                    session_table.c.signed_out_at - session_table.c.signed_in_at,
                )
                / 3600.0
                - session_table.c.total_pause_ms / 3600000.0
            ).label("hours_collected"),
            sa.func.count().label("session_count"),
        )
        .where(
            session_table.c.task_id.is_not(None),
            session_table.c.signed_out_at.is_not(None),
        )
        .group_by(session_table.c.task_id)
    )
    hours_by_task: dict[str, dict[str, Any]] = {}
    for row in conn.execute(hours_query).mappings().all():
        hours_by_task[row["task_id"]] = {
            "hours_collected": round(float(row["hours_collected"] or 0), 1),
            "session_count": int(row["session_count"]),
        }

    episode_table = schema.TABLES["episode"]
    ep_query = (
        sa.select(
            episode_table.c.task_id,
            sa.func.count().label("episode_count"),
        )
        .where(
            sa.or_(episode_table.c.archive == 0, episode_table.c.archive.is_(None)),
            sa.or_(episode_table.c.void.is_(False), episode_table.c.void.is_(None)),
        )
        .group_by(episode_table.c.task_id)
    )
    episodes_by_task: dict[str, int] = {}
    for row in conn.execute(ep_query).mappings().all():
        episodes_by_task[row["task_id"]] = int(row["episode_count"])

    ct = schema.collection_target
    targets: dict[str, float] = {}
    target_query = sa.select(ct)
    if period:
        target_query = target_query.where(ct.c.period == period)
    for row in conn.execute(target_query).mappings().all():
        tid = row["task_id"]
        targets[tid] = targets.get(tid, 0) + float(row["target_hours"])

    ota = schema.operator_task_assignment
    week_of = _current_monday()
    op_query = (
        sa.select(
            ota.c.task_id,
            sa.func.array_agg(sa.distinct(ota.c.person_id)).label("operators"),
        )
        .where(ota.c.status == "active", ota.c.week_of == week_of)
        .group_by(ota.c.task_id)
    )
    operators_by_task: dict[str, list[str]] = {}
    for row in conn.execute(op_query).mappings().all():
        operators_by_task[row["task_id"]] = list(row["operators"])

    tasks = list_tasks(conn)
    all_task_ids = {t["task_id"] for t in tasks} | set(targets.keys())

    task_lookup = {t["task_id"]: t for t in tasks}
    result = []
    for tid in sorted(
        all_task_ids, key=lambda x: int(x) if x.isdigit() else float("inf")
    ):
        task = task_lookup.get(tid, {})
        h = hours_by_task.get(tid, {"hours_collected": 0, "session_count": 0})
        target = targets.get(tid, 0)
        pct = round(h["hours_collected"] / target * 100, 1) if target > 0 else 0
        result.append(
            {
                "task_id": tid,
                "task_name": task.get("task_name", tid),
                "category": task.get("category"),
                "family": task.get("family"),
                "status": get_task_status(task) if task else "unknown",
                "target_hours": target,
                "collected_hours": h["hours_collected"],
                "pct": pct,
                "session_count": h["session_count"],
                "episode_count": episodes_by_task.get(tid, 0),
                "operators": operators_by_task.get(tid, []),
            }
        )
    return result


# ---------------------------------------------------------------------------
# Collection targets
# ---------------------------------------------------------------------------


def upsert_target(
    conn: Connection,
    *,
    task_id: str,
    target_hours: float,
    period: str,
    created_by: str,
) -> None:
    """Upsert a collection target for a task+period."""
    ct = schema.collection_target
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = (
        pg_insert(ct)
        .values(
            task_id=task_id,
            target_hours=target_hours,
            period=period,
            created_by=created_by,
        )
        .on_conflict_do_update(
            constraint="uq_ct_task_period",
            set_={"target_hours": target_hours, "created_by": created_by},
        )
    )
    conn.execute(stmt)


def list_targets(
    conn: Connection, *, period: str | None = None
) -> list[dict[str, Any]]:
    ct = schema.collection_target
    query = sa.select(ct)
    if period:
        query = query.where(ct.c.period == period)
    rows = conn.execute(query.order_by(ct.c.task_id)).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Assignment sheet
# ---------------------------------------------------------------------------


def build_sheet_text(
    conn: Connection, person_id: str, week_of: date | None = None
) -> str:
    """Build a WhatsApp-friendly plain-text assignment sheet (Spanish)."""
    if week_of is None:
        week_of = _current_monday()

    person = store.get(conn, "person", person_id=person_id)
    name = person.get("name", person_id) if person else person_id

    assignments = get_operator_assignments(conn, person_id, week_of)

    months_es = [
        "",
        "ene",
        "feb",
        "mar",
        "abr",
        "may",
        "jun",
        "jul",
        "ago",
        "sep",
        "oct",
        "nov",
        "dic",
    ]
    week_str = f"{week_of.day} {months_es[week_of.month]} {week_of.year}"

    lines = [
        f"Operador: {name} (ID {person_id})",
        f"Semana: {week_str}",
        "",
    ]
    for a in assignments:
        tid = a["task_id"]
        tname = a["task_name"]
        lines.append(f"{tid:>3} — {tname}")

    lines.append("")
    lines.append("Máx 3 tareas diferentes por día.")
    lines.append("Escribe el ID de la tarea en el fob.")
    return "\n".join(lines)


def build_sheet_data(
    conn: Connection, person_id: str, week_of: date | None = None
) -> dict[str, Any]:
    """Build data for the printable HTML assignment sheet."""
    if week_of is None:
        week_of = _current_monday()

    person = store.get(conn, "person", person_id=person_id)
    name = person.get("name", person_id) if person else person_id

    assignments = get_operator_assignments(conn, person_id, week_of)
    return {
        "person_id": person_id,
        "name": name,
        "week_of": week_of.isoformat(),
        "week_of_display": week_of.strftime("%B %d, %Y"),
        "assignments": assignments,
    }


# ---------------------------------------------------------------------------
# Randomizer
# ---------------------------------------------------------------------------


def randomize_assignments(
    conn: Connection,
    *,
    person_ids: list[str],
    week_of: date | None = None,
    count_per_operator: int = 10,
    assigned_by: str,
    period: str | None = None,
) -> list[dict[str, Any]]:
    """Draw random tasks for each operator, weighted by underserved targets.

    Returns the list of assignments made (for preview). Tasks below their target
    hours get higher weight.
    """
    if week_of is None:
        week_of = _current_monday()
    if week_of.weekday() != 0:
        raise ValueError("week_of must be a Monday")

    active_tasks = [t for t in list_tasks(conn) if get_task_status(t) == "active"]
    if not active_tasks:
        return []

    progress = {p["task_id"]: p for p in get_progress(conn, period=period)}

    def _weight(task: dict[str, Any]) -> float:
        tid = task["task_id"]
        p = progress.get(tid)
        if p and p["target_hours"] > 0:
            deficit = max(0, p["target_hours"] - p["collected_hours"])
            return 1.0 + deficit
        return 1.0

    task_pool = active_tasks
    weights = [_weight(t) for t in task_pool]

    results: list[dict[str, Any]] = []
    for pid in person_ids:
        existing = get_operator_assignments(conn, pid, week_of)
        existing_ids = {a["task_id"] for a in existing}
        slots = min(count_per_operator, MAX_TASKS_PER_OPERATOR) - len(existing_ids)
        if slots <= 0:
            continue

        available = [
            (t, w)
            for t, w in zip(task_pool, weights)
            if t["task_id"] not in existing_ids
        ]
        if not available:
            continue
        avail_tasks, avail_weights = zip(*available)
        pick_count = min(slots, len(avail_tasks))
        chosen = random.sample(
            list(range(len(avail_tasks))),
            k=pick_count,
            counts=[max(1, int(w * 10)) for w in avail_weights],
        )
        seen: set[int] = set()
        for idx in chosen:
            if idx in seen:
                continue
            seen.add(idx)
            task = avail_tasks[idx]
            assignment = assign_task(
                conn,
                person_id=pid,
                task_id=task["task_id"],
                week_of=week_of,
                assigned_by=assigned_by,
            )
            results.append(assignment)
    return results
