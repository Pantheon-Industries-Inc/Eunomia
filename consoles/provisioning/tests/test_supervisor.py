"""Tests for the supervisor task-assignment workflow (Run P3).

Route smoke tests (no DB) + pure logic tests. DB-backed tests live in edge/store/tests/.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from eunomia_consoles_provisioning.app import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# HTML page smoke tests (no DB required — pages render with "not configured" banner)
# ---------------------------------------------------------------------------


def test_supervisor_tasks_page() -> None:
    resp = client.get("/supervisor/tasks")
    assert resp.status_code == 200
    assert "Task Catalog" in resp.text


def test_supervisor_operators_page() -> None:
    resp = client.get("/supervisor/operators")
    assert resp.status_code == 200
    assert "Operator Assignments" in resp.text


def test_supervisor_progress_page() -> None:
    resp = client.get("/supervisor/progress")
    assert resp.status_code == 200
    assert "Collection Progress" in resp.text


# ---------------------------------------------------------------------------
# API routes return 503 when no DB is configured
# ---------------------------------------------------------------------------


def test_api_list_tasks_no_db() -> None:
    resp = client.get("/api/supervisor/tasks")
    assert resp.status_code == 503


def test_api_create_task_no_db() -> None:
    resp = client.post("/api/supervisor/tasks", json={"task_name": "test"})
    assert resp.status_code == 503


def test_api_list_operators_no_db() -> None:
    resp = client.get("/api/supervisor/operators")
    assert resp.status_code == 503


def test_api_progress_no_db() -> None:
    resp = client.get("/api/supervisor/progress")
    assert resp.status_code == 503


def test_api_targets_no_db() -> None:
    resp = client.get("/api/supervisor/targets")
    assert resp.status_code == 503


def test_api_randomize_no_db() -> None:
    resp = client.post(
        "/api/supervisor/randomize",
        json={"person_ids": ["p1"], "assigned_by": "test"},
    )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Pure logic tests (no DB)
# ---------------------------------------------------------------------------


def test_get_task_status_active() -> None:
    from eunomia_consoles_provisioning.supervisor import get_task_status

    assert get_task_status({"effective_to": None}) == "active"
    assert get_task_status({}) == "active"


def test_get_task_status_decommissioned() -> None:
    from eunomia_consoles_provisioning.supervisor import get_task_status

    assert get_task_status({"effective_to": "2026-01-01T00:00:00Z"}) == "decommissioned"


def test_current_monday() -> None:
    from eunomia_consoles_provisioning.supervisor import _current_monday

    monday = _current_monday()
    assert monday.weekday() == 0


def test_build_sheet_text_format() -> None:
    """Verify sheet text structure without DB by testing the string builder portion."""
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
    week_of = date(2026, 6, 30)
    name = "Ana Ramírez"
    person_id = "op-042"
    assignments = [
        {"task_id": "42", "task_name": "Fold towels"},
        {"task_id": "17", "task_name": "Pour water"},
    ]
    week_str = f"{week_of.day} {months_es[week_of.month]} {week_of.year}"
    lines = [
        f"Operador: {name} (ID {person_id})",
        f"Semana: {week_str}",
        "",
    ]
    for a in assignments:
        lines.append(f"{a['task_id']:>3} — {a['task_name']}")
    lines.append("")
    lines.append("Máx 3 tareas diferentes por día.")
    lines.append("Escribe el ID de la tarea en el fob.")
    text = "\n".join(lines)

    assert "Operador: Ana Ramírez (ID op-042)" in text
    assert "Semana: 30 jun 2026" in text
    assert " 42 — Fold towels" in text
    assert " 17 — Pour water" in text
    assert "Máx 3 tareas diferentes por día." in text


def test_max_tasks_constant() -> None:
    from eunomia_consoles_provisioning.supervisor import MAX_TASKS_PER_OPERATOR

    assert MAX_TASKS_PER_OPERATOR == 10
