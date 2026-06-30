"""Ops dashboard routes — read-only views over the S1 store."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from eunomia_consoles_provisioning.ops import queries
from eunomia_consoles_provisioning.ops.db import get_conn
from eunomia_consoles_provisioning.ops.import_router import import_router
from eunomia_consoles_provisioning.ops.inspect_router import inspect_router

TEMPLATES_DIR = Path(__file__).parent / "templates"

ops_router = APIRouter(prefix="/ops", tags=["ops"])
ops_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

ops_router.include_router(inspect_router)
ops_router.include_router(import_router)


def _ctx(request: Request, **kwargs: Any) -> dict[str, Any]:
    return {"request": request, **kwargs}


# ---------------------------------------------------------------------------
# Full pages
# ---------------------------------------------------------------------------


@ops_router.get("/", response_class=HTMLResponse)
async def overview(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return ops_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        stats = queries.overview_stats(conn)
        episodes = queries.recent_episodes(conn)
        anomalies = queries.anomaly_count(conn)
    return ops_templates.TemplateResponse(
        request,
        "overview.html",
        _ctx(request, stats=stats, episodes=episodes, anomaly_count=anomalies),
    )


@ops_router.get("/operators", response_class=HTMLResponse)
async def operators_page(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return ops_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        operators = queries.operator_list(conn)
    return ops_templates.TemplateResponse(
        request, "operators.html", _ctx(request, operators=operators)
    )


@ops_router.get("/operators/{person_id}", response_class=HTMLResponse)
async def operator_detail_page(request: Request, person_id: str) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return ops_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        person = queries.operator_detail(conn, person_id)
        if person is None:
            return HTMLResponse("Operator not found", status_code=404)
        counts = queries.operator_episode_counts(conn, person_id)
        hours_by_task = queries.operator_hours_by_task(conn, person_id)
        sessions = queries.operator_sessions(conn, person_id)
    return ops_templates.TemplateResponse(
        request,
        "operator_detail.html",
        _ctx(
            request,
            person=person,
            counts=counts,
            hours_by_task=hours_by_task,
            sessions=sessions,
        ),
    )


@ops_router.get("/kits", response_class=HTMLResponse)
async def kits_page(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return ops_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        kits = queries.kit_list(conn)
    return ops_templates.TemplateResponse(
        request, "kits.html", _ctx(request, kits=kits)
    )


@ops_router.get("/kits/{kit_id}", response_class=HTMLResponse)
async def kit_detail_page(request: Request, kit_id: str) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return ops_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        kit = queries.kit_detail(conn, kit_id)
        if kit is None:
            return HTMLResponse("Kit not found", status_code=404)
        stats = queries.kit_episode_stats(conn, kit_id)
        operator = queries.kit_current_operator(conn, kit_id)
        anomalies = queries.kit_anomalies(conn, kit_id)
    return ops_templates.TemplateResponse(
        request,
        "kit_detail.html",
        _ctx(
            request,
            kit=kit,
            stats=stats,
            current_operator=operator,
            anomalies=anomalies,
        ),
    )


@ops_router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return ops_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        tasks = queries.task_list(conn)
    return ops_templates.TemplateResponse(
        request, "tasks.html", _ctx(request, tasks=tasks)
    )


@ops_router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail_page(request: Request, task_id: str) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return ops_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        task = queries.task_detail(conn, task_id)
        if task is None:
            return HTMLResponse("Task not found", status_code=404)
        operators = queries.task_operators(conn, task_id)
        versions = queries.task_versions(conn, task_id)
    return ops_templates.TemplateResponse(
        request,
        "task_detail.html",
        _ctx(request, task=task, operators=operators, versions=versions),
    )


@ops_router.get("/anomalies", response_class=HTMLResponse)
async def anomalies_page(
    request: Request,
    anomaly_type: str | None = Query(default=None),
    kit_id: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return ops_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    limit = 50
    with conn:
        anomalies = queries.anomaly_feed(
            conn,
            limit=limit,
            offset=offset,
            anomaly_type=anomaly_type,
            kit_id=kit_id,
        )
    return ops_templates.TemplateResponse(
        request,
        "anomalies.html",
        _ctx(
            request,
            anomalies=anomalies,
            anomaly_types=queries.ANOMALY_TYPES,
            selected_type=anomaly_type or "",
            selected_kit=kit_id or "",
            offset=offset,
            limit=limit,
            has_more=len(anomalies) == limit,
        ),
    )


@ops_router.get("/pipeline", response_class=HTMLResponse)
async def pipeline_page(
    request: Request,
    time_range: str = Query(default="week", alias="range"),
) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return ops_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    periods = queries._period_starts()
    since_map = {
        "today": periods["today"],
        "week": periods["week"],
        "month": periods["month"],
        "all": datetime(2020, 1, 1, tzinfo=UTC),
    }
    since = since_map.get(time_range, periods["week"])
    with conn:
        health = queries.pipeline_health(conn, since)
        stalls = queries.pipeline_stalls(conn)
    return ops_templates.TemplateResponse(
        request,
        "pipeline.html",
        _ctx(request, health=health, stalls=stalls, range=time_range),
    )


# ---------------------------------------------------------------------------
# HTMX partials (no full page wrapper)
# ---------------------------------------------------------------------------


@ops_router.get("/partials/overview-stats", response_class=HTMLResponse)
async def partial_overview_stats(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return HTMLResponse('<div class="warn">Store unavailable</div>')
    with conn:
        stats = queries.overview_stats(conn)
    return ops_templates.TemplateResponse(
        request, "partials/overview_stats.html", _ctx(request, stats=stats)
    )


@ops_router.get("/partials/recent-episodes", response_class=HTMLResponse)
async def partial_recent_episodes(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return HTMLResponse('<div class="warn">Store unavailable</div>')
    with conn:
        episodes = queries.recent_episodes(conn)
    return ops_templates.TemplateResponse(
        request, "partials/recent_episodes.html", _ctx(request, episodes=episodes)
    )


@ops_router.get("/partials/anomaly-count", response_class=HTMLResponse)
async def partial_anomaly_count(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return HTMLResponse('<span class="warn">—</span>')
    with conn:
        count = queries.anomaly_count(conn)
    return ops_templates.TemplateResponse(
        request, "partials/anomaly_count.html", _ctx(request, anomaly_count=count)
    )
