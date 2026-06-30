"""FastAPI provisioning console — bench flash/assign UI + API."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.engine import Connection, Engine

from eunomia_consoles_provisioning import ship_gate, site
from eunomia_consoles_provisioning.fob import parse_status
from eunomia_consoles_provisioning.ops.router import ops_router

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _try_engine() -> Engine | None:
    try:
        from eunomia_edge_store.config import StoreConfig
        from eunomia_edge_store.engine import make_engine

        return make_engine(StoreConfig.from_env())
    except Exception:
        logger.info("EUNOMIA_STORE_DSN not set — supervisor routes unavailable")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.engine = _try_engine()
    yield
    if app.state.engine is not None:
        app.state.engine.dispose()


app = FastAPI(title="Eunomia Provisioning Console", version="0.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.include_router(ops_router)


def get_conn() -> Any:
    engine: Engine | None = getattr(app.state, "engine", None)
    if engine is None:
        raise HTTPException(503, "Store not configured (set EUNOMIA_STORE_DSN)")
    with engine.connect() as conn:
        yield conn
        conn.commit()


# ---------------------------------------------------------------------------
# Pydantic models for API
# ---------------------------------------------------------------------------


class ProvisionCameraRequest(BaseModel):
    ip: str = "192.168.42.2"
    kit_id: str
    side: str
    mount: str = "wrist"
    calibration_id: str = ""
    firmware_version: str = ""
    hardware_version: str = ""


class ProvisionFobRequest(BaseModel):
    serial_port: str
    kit_id: str
    site_id: str
    cam_pass: str = ""


class ShipGateRequest(BaseModel):
    status_json: str
    expected_fw: str | None = None
    require_time: bool = False


class PersonRequest(BaseModel):
    person_id: str
    name: str
    role: str = "operator"
    site_id: str = ""


class SiteCheckRequest(BaseModel):
    fob_site_id: str
    request_site_id: str


class CreateTaskRequest(BaseModel):
    task_name: str
    prompt: str = ""
    category: str | None = None
    family: str | None = None
    expected_duration_s: float | None = None
    bimanual: bool = False


class AssignTaskRequest(BaseModel):
    task_id: str
    week_of: str | None = None
    assigned_by: str


class UnassignTaskRequest(BaseModel):
    task_id: str
    week_of: str | None = None


class UpsertTargetRequest(BaseModel):
    task_id: str
    target_hours: float
    period: str
    created_by: str


class RandomizeRequest(BaseModel):
    person_ids: list[str]
    week_of: str | None = None
    count_per_operator: int = 10
    assigned_by: str
    period: str | None = None


# ---------------------------------------------------------------------------
# HTML routes (bench UI)
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/provision", response_class=HTMLResponse)
async def provision_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "provision.html", {})


@app.get("/roster", response_class=HTMLResponse)
async def roster_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "roster.html", {})


@app.get("/ship-gate", response_class=HTMLResponse)
async def ship_gate_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "ship_gate.html", {})


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "provisioning-console"}


@app.post("/api/tether-check")
async def tether_check() -> dict[str, Any]:
    from eunomia_consoles_provisioning.tether import uplink_safe

    result = uplink_safe()
    return {
        "safe": result.safe,
        "interface": result.default_interface,
        "reason": result.reason,
    }


@app.post("/api/ship-gate/evaluate")
async def evaluate_ship_gate(req: ShipGateRequest) -> dict[str, Any]:
    try:
        status = parse_status(req.status_json)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid status JSON: {exc}"
        ) from exc

    result = ship_gate.evaluate(
        status, expected_fw=req.expected_fw, require_time=req.require_time
    )
    return {
        "passed": result.passed,
        "summary": result.summary,
        "checks": [
            {"name": c.name, "passed": c.passed, "reason": c.reason}
            for c in result.checks
        ],
    }


@app.post("/api/site-check")
async def check_site_binding(req: SiteCheckRequest) -> dict[str, Any]:
    result = site.validate_site_binding(req.fob_site_id, req.request_site_id)
    return {
        "valid": result.valid,
        "fob_site_id": result.fob_site_id,
        "request_site_id": result.request_site_id,
        "reason": result.reason,
    }


# ---------------------------------------------------------------------------
# Supervisor HTML routes
# ---------------------------------------------------------------------------


def _has_store() -> bool:
    return getattr(app.state, "engine", None) is not None


@app.get("/supervisor/tasks", response_class=HTMLResponse)
async def supervisor_tasks_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "supervisor_tasks.html", {"store_available": _has_store()}
    )


@app.get("/supervisor/operators", response_class=HTMLResponse)
async def supervisor_operators_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "supervisor_operators.html", {"store_available": _has_store()}
    )


@app.get("/supervisor/progress", response_class=HTMLResponse)
async def supervisor_progress_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "supervisor_progress.html", {"store_available": _has_store()}
    )


@app.get("/supervisor/operators/{person_id}/sheet", response_class=HTMLResponse)
async def supervisor_sheet_page(
    request: Request,
    person_id: str,
    week_of: str | None = None,
    conn: Connection = Depends(get_conn),
) -> HTMLResponse:
    from eunomia_consoles_provisioning.supervisor import build_sheet_data

    wk = _parse_week_of(week_of)
    data = build_sheet_data(conn, person_id, wk)
    return templates.TemplateResponse(request, "supervisor_sheet.html", data)


# ---------------------------------------------------------------------------
# Supervisor API routes — task catalog
# ---------------------------------------------------------------------------


def _parse_week_of(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


@app.get("/api/supervisor/tasks")
async def api_list_tasks(conn: Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    from eunomia_consoles_provisioning.supervisor import (
        get_progress,
        get_task_status,
        list_tasks,
    )

    tasks = list_tasks(conn)
    progress = {p["task_id"]: p for p in get_progress(conn)}
    result = []
    for t in tasks:
        tid = t["task_id"]
        p = progress.get(tid, {})
        result.append(
            {
                "task_id": tid,
                "task_name": t.get("task_name", ""),
                "category": t.get("category"),
                "family": t.get("family"),
                "status": get_task_status(t),
                "expected_duration_s": t.get("expected_duration_s"),
                "collected_hours": p.get("collected_hours", 0),
                "target_hours": p.get("target_hours", 0),
                "episode_count": p.get("episode_count", 0),
            }
        )
    return result


@app.post("/api/supervisor/tasks")
async def api_create_task(
    req: CreateTaskRequest, conn: Connection = Depends(get_conn)
) -> dict[str, Any]:
    from eunomia_consoles_provisioning.supervisor import create_task

    if not req.task_name.strip():
        raise HTTPException(422, "task_name is required")
    task = create_task(
        conn,
        task_name=req.task_name,
        prompt=req.prompt,
        category=req.category,
        family=req.family,
        expected_duration_s=req.expected_duration_s,
        bimanual=req.bimanual,
    )
    return task


@app.post("/api/supervisor/tasks/{task_id}/decommission")
async def api_decommission_task(
    task_id: str, conn: Connection = Depends(get_conn)
) -> dict[str, Any]:
    from eunomia_consoles_provisioning.supervisor import decommission_task

    try:
        decommission_task(conn, task_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


# ---------------------------------------------------------------------------
# Supervisor API routes — operator assignments
# ---------------------------------------------------------------------------


@app.get("/api/supervisor/operators")
async def api_list_operators(
    site_id: str | None = None,
    week_of: str | None = None,
    conn: Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    from eunomia_consoles_provisioning.supervisor import (
        list_operators_with_assignments,
    )

    wk = _parse_week_of(week_of)
    return list_operators_with_assignments(conn, site_id=site_id, week_of=wk)


@app.get("/api/supervisor/operators/{person_id}/assignments")
async def api_get_assignments(
    person_id: str,
    week_of: str | None = None,
    conn: Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    from eunomia_consoles_provisioning.supervisor import get_operator_assignments

    wk = _parse_week_of(week_of)
    return get_operator_assignments(conn, person_id, wk)


@app.post("/api/supervisor/operators/{person_id}/assign")
async def api_assign_task(
    person_id: str,
    req: AssignTaskRequest,
    conn: Connection = Depends(get_conn),
) -> dict[str, Any]:
    from eunomia_consoles_provisioning.supervisor import assign_task

    wk = _parse_week_of(req.week_of)
    try:
        return assign_task(
            conn,
            person_id=person_id,
            task_id=req.task_id,
            week_of=wk,
            assigned_by=req.assigned_by,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        code = 409 if "already assigned" in msg else 422
        raise HTTPException(code, msg) from exc


@app.post("/api/supervisor/operators/{person_id}/unassign")
async def api_unassign_task(
    person_id: str,
    req: UnassignTaskRequest,
    conn: Connection = Depends(get_conn),
) -> dict[str, Any]:
    from eunomia_consoles_provisioning.supervisor import unassign_task

    wk = _parse_week_of(req.week_of)
    try:
        unassign_task(conn, person_id=person_id, task_id=req.task_id, week_of=wk)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


# ---------------------------------------------------------------------------
# Supervisor API routes — progress + targets
# ---------------------------------------------------------------------------


@app.get("/api/supervisor/progress")
async def api_progress(
    period: str | None = None, conn: Connection = Depends(get_conn)
) -> list[dict[str, Any]]:
    from eunomia_consoles_provisioning.supervisor import get_progress

    return get_progress(conn, period=period)


@app.post("/api/supervisor/targets")
async def api_upsert_target(
    req: UpsertTargetRequest, conn: Connection = Depends(get_conn)
) -> dict[str, Any]:
    from eunomia_consoles_provisioning.supervisor import upsert_target

    if req.target_hours <= 0:
        raise HTTPException(422, "target_hours must be > 0")
    upsert_target(
        conn,
        task_id=req.task_id,
        target_hours=req.target_hours,
        period=req.period,
        created_by=req.created_by,
    )
    return {"ok": True}


@app.get("/api/supervisor/targets")
async def api_list_targets(
    period: str | None = None, conn: Connection = Depends(get_conn)
) -> list[dict[str, Any]]:
    from eunomia_consoles_provisioning.supervisor import list_targets

    return list_targets(conn, period=period)


# ---------------------------------------------------------------------------
# Supervisor API routes — assignment sheet
# ---------------------------------------------------------------------------


@app.get("/api/supervisor/operators/{person_id}/sheet/text")
async def api_sheet_text(
    person_id: str,
    week_of: str | None = None,
    conn: Connection = Depends(get_conn),
) -> PlainTextResponse:
    from eunomia_consoles_provisioning.supervisor import build_sheet_text

    wk = _parse_week_of(week_of)
    text = build_sheet_text(conn, person_id, wk)
    return PlainTextResponse(text)


# ---------------------------------------------------------------------------
# Supervisor API routes — randomizer
# ---------------------------------------------------------------------------


@app.post("/api/supervisor/randomize")
async def api_randomize(
    req: RandomizeRequest, conn: Connection = Depends(get_conn)
) -> dict[str, Any]:
    from eunomia_consoles_provisioning.supervisor import randomize_assignments

    wk = _parse_week_of(req.week_of)
    try:
        assignments = randomize_assignments(
            conn,
            person_ids=req.person_ids,
            week_of=wk,
            count_per_operator=req.count_per_operator,
            assigned_by=req.assigned_by,
            period=req.period,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"assignments": assignments}
