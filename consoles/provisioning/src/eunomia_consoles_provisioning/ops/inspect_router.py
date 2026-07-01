"""Store inspector routes — raw record browsing over S1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from eunomia_consoles_provisioning.ops import inspect_queries
from eunomia_consoles_provisioning.ops.db import get_conn

TEMPLATES_DIR = Path(__file__).parent / "templates"

inspect_router = APIRouter(tags=["ops-inspect"])
_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
_templates.env.filters["to_pretty_json"] = lambda v: json.dumps(
    v, indent=2, default=str, ensure_ascii=False
)


def _ctx(request: Request, **kwargs: Any) -> dict[str, Any]:
    return {"request": request, **kwargs}


@inspect_router.get("/inspect/episodes", response_class=HTMLResponse)
async def inspect_episodes(
    request: Request,
    episode_id: str | None = Query(default=None),
    kit_id: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    operator_id: str | None = Query(default=None),
    setup_version_id: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return _templates.TemplateResponse(request, "unavailable.html", _ctx(request))
    limit = 10
    with conn:
        episodes = inspect_queries.episode_list(
            conn,
            limit=limit,
            offset=offset,
            episode_id=episode_id,
            kit_id=kit_id,
            task_id=task_id,
            operator_id=operator_id,
            setup_version_id=setup_version_id,
        )
    return _templates.TemplateResponse(
        request,
        "inspect_episodes.html",
        _ctx(
            request,
            episodes=episodes,
            q_episode_id=episode_id or "",
            q_kit_id=kit_id or "",
            q_task_id=task_id or "",
            q_operator_id=operator_id or "",
            q_setup_version_id=setup_version_id or "",
            offset=offset,
            limit=limit,
            has_more=len(episodes) == limit,
        ),
    )


@inspect_router.get("/inspect/episodes/{episode_id}", response_class=HTMLResponse)
async def inspect_episode_detail(request: Request, episode_id: str) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return _templates.TemplateResponse(request, "unavailable.html", _ctx(request))
    with conn:
        episode = inspect_queries.episode_detail(conn, episode_id)
        if episode is None:
            return HTMLResponse("Episode not found", status_code=404)
        related_events = inspect_queries.episode_events(conn, episode_id)
        footage_ref = inspect_queries.episode_footage_ref(conn, episode_id)
        session = None
        if episode.get("session_id"):
            session = inspect_queries.episode_session(conn, episode["session_id"])
    return _templates.TemplateResponse(
        request,
        "inspect_episode_detail.html",
        _ctx(
            request,
            episode=episode,
            related_events=related_events,
            footage_ref=footage_ref,
            session=session,
        ),
    )


@inspect_router.get("/inspect/events", response_class=HTMLResponse)
async def inspect_events(
    request: Request,
    event_type: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return _templates.TemplateResponse(request, "unavailable.html", _ctx(request))
    limit = 10
    with conn:
        events = inspect_queries.event_list(
            conn, limit=limit, offset=offset, event_type=event_type
        )
        types = inspect_queries.event_types(conn)
    return _templates.TemplateResponse(
        request,
        "inspect_events.html",
        _ctx(
            request,
            events=events,
            event_types=types,
            selected_type=event_type or "",
            offset=offset,
            limit=limit,
            has_more=len(events) == limit,
        ),
    )


@inspect_router.get("/inspect/sessions", response_class=HTMLResponse)
async def inspect_sessions(
    request: Request,
    offset: int = Query(default=0, ge=0),
) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return _templates.TemplateResponse(request, "unavailable.html", _ctx(request))
    limit = 10
    with conn:
        sessions = inspect_queries.session_list(conn, limit=limit, offset=offset)
    return _templates.TemplateResponse(
        request,
        "inspect_sessions.html",
        _ctx(
            request,
            sessions=sessions,
            offset=offset,
            limit=limit,
            has_more=len(sessions) == limit,
        ),
    )


@inspect_router.get("/inspect/tasks", response_class=HTMLResponse)
async def inspect_tasks(
    request: Request,
    offset: int = Query(default=0, ge=0),
) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return _templates.TemplateResponse(request, "unavailable.html", _ctx(request))
    limit = 10
    with conn:
        tasks = inspect_queries.task_list_raw(conn, limit=limit, offset=offset)
    return _templates.TemplateResponse(
        request,
        "inspect_tasks.html",
        _ctx(
            request,
            tasks=tasks,
            offset=offset,
            limit=limit,
            has_more=len(tasks) == limit,
        ),
    )
