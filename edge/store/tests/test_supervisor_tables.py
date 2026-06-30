"""DB-backed tests for the P3 supervisor tables (operator_task_assignment, collection_target).

Requires EUNOMIA_STORE_TEST_DSN — skips without it (same pattern as test_db_store.py).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection

from eunomia_edge_store import schema, store


# ---------------------------------------------------------------------------
# task_catalog_seq
# ---------------------------------------------------------------------------


def test_task_catalog_seq_monotonic(conn: Connection) -> None:
    """Sequence mints incrementing values (retire-not-reuse)."""
    v1 = conn.execute(sa.select(schema.task_catalog_seq.next_value())).scalar_one()
    v2 = conn.execute(sa.select(schema.task_catalog_seq.next_value())).scalar_one()
    assert int(v2) > int(v1)


# ---------------------------------------------------------------------------
# operator_task_assignment
# ---------------------------------------------------------------------------


def _insert_person(conn: Connection, person_id: str) -> None:
    store.upsert(
        conn,
        "person",
        {
            "schema": "eunomia-person/v1",
            "person_id": person_id,
            "name": f"Test {person_id}",
            "role": "operator",
            "status": "active",
            "site_ids": ["site-1"],
        },
    )


def _insert_task(conn: Connection, task_id: str) -> None:
    store.upsert(
        conn,
        "task",
        {
            "schema": "eunomia-task/v1",
            "task_id": task_id,
            "version": 1,
            "rotation_id": "default",
            "task_name": f"Task {task_id}",
            "prompt": f"Do task {task_id}",
        },
    )


def test_ota_insert_and_read(conn: Connection) -> None:
    t = schema.operator_task_assignment
    conn.execute(
        t.insert().values(
            person_id="op-1",
            task_id="1",
            assigned_by="supervisor",
            week_of=date(2026, 6, 30),
        )
    )
    row = conn.execute(sa.select(t).where(t.c.person_id == "op-1")).mappings().first()
    assert row is not None
    assert row["task_id"] == "1"
    assert row["status"] == "active"
    assert row["week_of"] == date(2026, 6, 30)


def test_ota_unique_constraint(conn: Connection) -> None:
    """Same (person, task, week) is rejected."""
    t = schema.operator_task_assignment
    conn.execute(
        t.insert().values(
            person_id="op-2",
            task_id="1",
            assigned_by="supervisor",
            week_of=date(2026, 6, 30),
        )
    )
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            t.insert().values(
                person_id="op-2",
                task_id="1",
                assigned_by="supervisor",
                week_of=date(2026, 6, 30),
            )
        )


def test_ota_different_weeks_ok(conn: Connection) -> None:
    """Same (person, task) in different weeks is fine."""
    t = schema.operator_task_assignment
    conn.execute(
        t.insert().values(
            person_id="op-3",
            task_id="1",
            assigned_by="supervisor",
            week_of=date(2026, 6, 30),
        )
    )
    conn.execute(
        t.insert().values(
            person_id="op-3",
            task_id="1",
            assigned_by="supervisor",
            week_of=date(2026, 7, 7),
        )
    )
    rows = conn.execute(sa.select(t).where(t.c.person_id == "op-3")).mappings().all()
    assert len(rows) == 2


def test_ota_status_update(conn: Connection) -> None:
    """Can flip active→removed."""
    t = schema.operator_task_assignment
    conn.execute(
        t.insert().values(
            person_id="op-4",
            task_id="1",
            assigned_by="supervisor",
            week_of=date(2026, 6, 30),
        )
    )
    conn.execute(
        t.update()
        .where(t.c.person_id == "op-4", t.c.task_id == "1")
        .values(status="removed", removed_at=datetime.now(timezone.utc))
    )
    row = conn.execute(sa.select(t).where(t.c.person_id == "op-4")).mappings().first()
    assert row is not None
    assert row["status"] == "removed"
    assert row["removed_at"] is not None


# ---------------------------------------------------------------------------
# collection_target
# ---------------------------------------------------------------------------


def test_ct_insert_and_read(conn: Connection) -> None:
    ct = schema.collection_target
    conn.execute(
        ct.insert().values(
            task_id="1",
            target_hours=100.0,
            period="2026-Q3",
            created_by="supervisor",
        )
    )
    row = conn.execute(sa.select(ct).where(ct.c.task_id == "1")).mappings().first()
    assert row is not None
    assert float(row["target_hours"]) == 100.0
    assert row["period"] == "2026-Q3"


def test_ct_unique_constraint(conn: Connection) -> None:
    """Same (task, period) is rejected on plain insert."""
    ct = schema.collection_target
    conn.execute(
        ct.insert().values(
            task_id="2",
            target_hours=50.0,
            period="2026-Q3",
            created_by="supervisor",
        )
    )
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            ct.insert().values(
                task_id="2",
                target_hours=75.0,
                period="2026-Q3",
                created_by="supervisor",
            )
        )


def test_ct_upsert_via_supervisor(conn: Connection) -> None:
    """The supervisor upsert_target function handles conflicts."""
    from eunomia_consoles_provisioning.supervisor import upsert_target

    upsert_target(
        conn, task_id="3", target_hours=100.0, period="2026-Q3", created_by="sup"
    )
    upsert_target(
        conn, task_id="3", target_hours=150.0, period="2026-Q3", created_by="sup"
    )
    ct = schema.collection_target
    row = (
        conn.execute(sa.select(ct).where(ct.c.task_id == "3", ct.c.period == "2026-Q3"))
        .mappings()
        .first()
    )
    assert row is not None
    assert float(row["target_hours"]) == 150.0


# ---------------------------------------------------------------------------
# Supervisor business logic (DB-backed)
# ---------------------------------------------------------------------------


def test_create_task_mints_id(conn: Connection) -> None:
    from eunomia_consoles_provisioning.supervisor import create_task

    t1 = create_task(conn, task_name="Fold towels", category="laundry")
    t2 = create_task(conn, task_name="Pour water", category="kitchen")
    assert int(t1["task_id"]) < int(t2["task_id"])
    assert t1["task_name"] == "Fold towels"
    assert t1["category"] == "laundry"


def test_create_task_with_family(conn: Connection) -> None:
    from eunomia_consoles_provisioning.supervisor import create_task

    t = create_task(
        conn,
        task_name="lift 3 blocks",
        category="direct_manipulation",
        family="lift_blocks",
    )
    assert t["family"] == "lift_blocks"
    assert t["category"] == "direct_manipulation"


def test_decommission_task(conn: Connection) -> None:
    from eunomia_consoles_provisioning.supervisor import (
        create_task,
        decommission_task,
        get_task_status,
        list_tasks,
    )

    t = create_task(conn, task_name="Old task")
    assert get_task_status(t) == "active"

    decommission_task(conn, t["task_id"])
    tasks = list_tasks(conn)
    found = next(x for x in tasks if x["task_id"] == t["task_id"])
    assert get_task_status(found) == "decommissioned"


def test_decommission_not_found(conn: Connection) -> None:
    from eunomia_consoles_provisioning.supervisor import decommission_task

    with pytest.raises(ValueError, match="not found"):
        decommission_task(conn, "nonexistent-999")


def test_assign_and_unassign(conn: Connection) -> None:
    from eunomia_consoles_provisioning.supervisor import (
        assign_task,
        create_task,
        get_operator_assignments,
        unassign_task,
    )

    _insert_person(conn, "op-10")
    t = create_task(conn, task_name="Test task")
    week = date(2026, 6, 30)

    assign_task(
        conn, person_id="op-10", task_id=t["task_id"], week_of=week, assigned_by="sup"
    )
    assignments = get_operator_assignments(conn, "op-10", week)
    assert len(assignments) == 1
    assert assignments[0]["task_id"] == t["task_id"]

    unassign_task(conn, person_id="op-10", task_id=t["task_id"], week_of=week)
    assignments = get_operator_assignments(conn, "op-10", week)
    assert len(assignments) == 0


def test_10_task_cap(conn: Connection) -> None:
    from eunomia_consoles_provisioning.supervisor import assign_task, create_task

    _insert_person(conn, "op-cap")
    week = date(2026, 6, 30)
    for _ in range(10):
        t = create_task(conn, task_name=f"Task {_}")
        assign_task(
            conn,
            person_id="op-cap",
            task_id=t["task_id"],
            week_of=week,
            assigned_by="sup",
        )

    extra = create_task(conn, task_name="Task 11")
    with pytest.raises(ValueError, match="10 active tasks"):
        assign_task(
            conn,
            person_id="op-cap",
            task_id=extra["task_id"],
            week_of=week,
            assigned_by="sup",
        )


def test_10_task_cap_unassign_then_assign(conn: Connection) -> None:
    from eunomia_consoles_provisioning.supervisor import (
        assign_task,
        create_task,
        unassign_task,
    )

    _insert_person(conn, "op-cap2")
    week = date(2026, 6, 30)
    tasks = []
    for i in range(10):
        t = create_task(conn, task_name=f"Task {i}")
        assign_task(
            conn,
            person_id="op-cap2",
            task_id=t["task_id"],
            week_of=week,
            assigned_by="sup",
        )
        tasks.append(t)

    unassign_task(conn, person_id="op-cap2", task_id=tasks[0]["task_id"], week_of=week)
    extra = create_task(conn, task_name="Task replacement")
    assign_task(
        conn,
        person_id="op-cap2",
        task_id=extra["task_id"],
        week_of=week,
        assigned_by="sup",
    )


def test_duplicate_assignment_rejected(conn: Connection) -> None:
    from eunomia_consoles_provisioning.supervisor import assign_task, create_task

    _insert_person(conn, "op-dup")
    t = create_task(conn, task_name="Dup task")
    week = date(2026, 6, 30)
    assign_task(
        conn, person_id="op-dup", task_id=t["task_id"], week_of=week, assigned_by="sup"
    )

    with pytest.raises(ValueError, match="already assigned"):
        assign_task(
            conn,
            person_id="op-dup",
            task_id=t["task_id"],
            week_of=week,
            assigned_by="sup",
        )


def test_week_of_must_be_monday(conn: Connection) -> None:
    from eunomia_consoles_provisioning.supervisor import assign_task

    _insert_person(conn, "op-wk")
    with pytest.raises(ValueError, match="Monday"):
        assign_task(
            conn,
            person_id="op-wk",
            task_id="1",
            week_of=date(2026, 7, 1),
            assigned_by="sup",
        )


def test_assign_person_not_found(conn: Connection) -> None:
    from eunomia_consoles_provisioning.supervisor import assign_task

    with pytest.raises(LookupError, match="not found"):
        assign_task(
            conn,
            person_id="nonexistent",
            task_id="1",
            week_of=date(2026, 6, 30),
            assigned_by="sup",
        )


def test_reassign_after_removal(conn: Connection) -> None:
    """A removed assignment can be re-activated."""
    from eunomia_consoles_provisioning.supervisor import (
        assign_task,
        create_task,
        get_operator_assignments,
        unassign_task,
    )

    _insert_person(conn, "op-reass")
    t = create_task(conn, task_name="Reass task")
    week = date(2026, 6, 30)

    assign_task(
        conn,
        person_id="op-reass",
        task_id=t["task_id"],
        week_of=week,
        assigned_by="sup",
    )
    unassign_task(conn, person_id="op-reass", task_id=t["task_id"], week_of=week)
    assign_task(
        conn,
        person_id="op-reass",
        task_id=t["task_id"],
        week_of=week,
        assigned_by="sup",
    )

    assignments = get_operator_assignments(conn, "op-reass", week)
    assert len(assignments) == 1


def test_list_operators_with_assignments(conn: Connection) -> None:
    from eunomia_consoles_provisioning.supervisor import (
        assign_task,
        create_task,
        list_operators_with_assignments,
    )

    _insert_person(conn, "op-list1")
    _insert_person(conn, "op-list2")
    t = create_task(conn, task_name="Listed task")
    week = date(2026, 6, 30)
    assign_task(
        conn,
        person_id="op-list1",
        task_id=t["task_id"],
        week_of=week,
        assigned_by="sup",
    )

    ops = list_operators_with_assignments(conn, week_of=week)
    by_id = {op["person_id"]: op for op in ops}
    assert "op-list1" in by_id
    assert len(by_id["op-list1"]["assignments"]) == 1
    assert "op-list2" in by_id
    assert len(by_id["op-list2"]["assignments"]) == 0


def test_build_sheet_text(conn: Connection) -> None:
    from eunomia_consoles_provisioning.supervisor import (
        assign_task,
        build_sheet_text,
        create_task,
    )

    _insert_person(conn, "op-sheet")
    t = create_task(conn, task_name="Fold towels")
    week = date(2026, 6, 30)
    assign_task(
        conn,
        person_id="op-sheet",
        task_id=t["task_id"],
        week_of=week,
        assigned_by="sup",
    )

    text = build_sheet_text(conn, "op-sheet", week)
    assert "Operador: Test op-sheet (ID op-sheet)" in text
    assert "Semana: 30 jun 2026" in text
    assert "Fold towels" in text
    assert "Máx 3 tareas diferentes por día." in text


def test_permanent_id_non_reassignment(conn: Connection) -> None:
    """Decommissioned task ID is never reused — new task gets a higher ID."""
    from eunomia_consoles_provisioning.supervisor import (
        create_task,
        decommission_task,
    )

    t1 = create_task(conn, task_name="Will decommission")
    decommission_task(conn, t1["task_id"])
    t2 = create_task(conn, task_name="New after decommission")
    assert int(t2["task_id"]) > int(t1["task_id"])
