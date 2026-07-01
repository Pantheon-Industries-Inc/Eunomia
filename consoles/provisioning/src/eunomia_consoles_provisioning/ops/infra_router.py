"""Infrastructure health routes — SD card status, camera map, system health."""

from __future__ import annotations

import json
import os
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from eunomia_consoles_provisioning.ops import infra_queries

TEMPLATES_DIR = Path(__file__).parent / "templates"

infra_router = APIRouter(prefix="/infra", tags=["infra"])
infra_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

SYNC_STATUS_DEFAULT = "/var/log/eunomia-sync/status.json"


def _ingest_root() -> Path | None:
    val = os.environ.get("EUNOMIA_INGEST_ROOT")
    return Path(val) if val else None


def _sync_status_path() -> Path:
    return Path(os.environ.get("EUNOMIA_SYNC_STATUS", SYNC_STATUS_DEFAULT))


def _ctx(request: Request, **kwargs: Any) -> dict[str, Any]:
    return {"request": request, **kwargs}


# ---------------------------------------------------------------------------
# Full pages
# ---------------------------------------------------------------------------


@infra_router.get("/", response_class=HTMLResponse)
async def infra_overview(request: Request) -> HTMLResponse:
    root = _ingest_root()
    health = infra_queries.system_health()
    sync = infra_queries.read_sync_status(_sync_status_path())

    card_stats: dict[str, int] | None = None
    freshness: dict[str, Any] | None = None
    ingesting = 0
    if root is not None:
        status = infra_queries.read_sd_card_status(root)
        if status is not None:
            card_stats = infra_queries.card_summary(status)
            freshness = infra_queries.status_freshness(status)
            ingesting = infra_queries.active_ingest_count(status)

    return infra_templates.TemplateResponse(
        request,
        "infra_overview.html",
        _ctx(
            request,
            health=health,
            sync=sync,
            card_stats=card_stats,
            freshness=freshness,
            ingesting=ingesting,
            has_ingest_root=root is not None,
        ),
    )


@infra_router.get("/cards", response_class=HTMLResponse)
async def infra_cards(request: Request) -> HTMLResponse:
    root = _ingest_root()
    if root is None:
        return infra_templates.TemplateResponse(
            request,
            "infra_cards.html",
            _ctx(request, status=None, freshness=None, has_ingest_root=False),
        )

    status = infra_queries.read_sd_card_status(root)
    freshness = None
    if status is not None:
        freshness = infra_queries.status_freshness(status)

    return infra_templates.TemplateResponse(
        request,
        "infra_cards.html",
        _ctx(request, status=status, freshness=freshness, has_ingest_root=True),
    )


@infra_router.get("/cameras", response_class=HTMLResponse)
async def infra_cameras(request: Request) -> HTMLResponse:
    root = _ingest_root()
    if root is None:
        return infra_templates.TemplateResponse(
            request,
            "infra_cameras.html",
            _ctx(
                request,
                camera_map=None,
                warnings=[],
                has_ingest_root=False,
                ingesting=0,
            ),
        )

    camera_map = infra_queries.read_camera_map(root) or {}
    warnings = infra_queries.camera_map_warnings(camera_map)

    ingesting = 0
    status = infra_queries.read_sd_card_status(root)
    if status is not None:
        ingesting = infra_queries.active_ingest_count(status)

    return infra_templates.TemplateResponse(
        request,
        "infra_cameras.html",
        _ctx(
            request,
            camera_map=camera_map,
            warnings=warnings,
            has_ingest_root=True,
            ingesting=ingesting,
        ),
    )


# ---------------------------------------------------------------------------
# Camera map mutations
# ---------------------------------------------------------------------------


@infra_router.post("/cameras/save", response_class=HTMLResponse)
async def infra_cameras_save(
    request: Request, camera_map_json: str = Form(...)
) -> HTMLResponse:
    root = _ingest_root()
    if root is None:
        return HTMLResponse(
            '<div class="badge badge-danger">Camera map editing requires Styx access</div>',
            status_code=400,
        )

    try:
        data = json.loads(camera_map_json)
    except json.JSONDecodeError:
        return HTMLResponse(
            '<div class="badge badge-danger">Invalid JSON</div>', status_code=400
        )

    for serial, entry in data.items():
        if isinstance(entry, dict):
            entry["last_updated"] = datetime.now(UTC).isoformat()

    infra_queries.save_camera_map(root, data)

    camera_map = infra_queries.read_camera_map(root) or {}
    warnings = infra_queries.camera_map_warnings(camera_map)

    return infra_templates.TemplateResponse(
        request,
        "partials/infra_camera_table.html",
        _ctx(request, camera_map=camera_map, warnings=warnings),
    )


@infra_router.post("/cameras/add", response_class=HTMLResponse)
async def infra_cameras_add(
    request: Request,
    serial: str = Form(...),
    alias: str = Form(default=""),
    operator: str = Form(default=""),
    side: str = Form(default=""),
    notes: str = Form(default=""),
) -> HTMLResponse:
    root = _ingest_root()
    if root is None:
        return HTMLResponse(
            '<div class="badge badge-danger">Camera map editing requires Styx access</div>',
            status_code=400,
        )

    camera_map = infra_queries.read_camera_map(root) or {}

    serial = serial.strip()
    if not serial:
        return HTMLResponse(
            '<div class="badge badge-danger">Serial is required</div>',
            status_code=400,
        )

    camera_map[serial] = {
        "serial": serial,
        "alias": alias.strip(),
        "operator": operator.strip(),
        "side": side.strip(),
        "active": True,
        "notes": notes.strip(),
        "last_updated": datetime.now(UTC).isoformat(),
    }

    infra_queries.save_camera_map(root, camera_map)

    camera_map = infra_queries.read_camera_map(root) or {}
    warnings = infra_queries.camera_map_warnings(camera_map)

    return infra_templates.TemplateResponse(
        request,
        "partials/infra_camera_table.html",
        _ctx(request, camera_map=camera_map, warnings=warnings),
    )


# ---------------------------------------------------------------------------
# HTMX partials
# ---------------------------------------------------------------------------


@infra_router.get("/partials/system-health", response_class=HTMLResponse)
async def partial_system_health(request: Request) -> HTMLResponse:
    health = infra_queries.system_health()
    return infra_templates.TemplateResponse(
        request,
        "partials/infra_system_health.html",
        _ctx(request, health=health),
    )


@infra_router.get("/partials/sync-status", response_class=HTMLResponse)
async def partial_sync_status(request: Request) -> HTMLResponse:
    sync = infra_queries.read_sync_status(_sync_status_path())
    return infra_templates.TemplateResponse(
        request,
        "partials/infra_sync_status.html",
        _ctx(request, sync=sync),
    )


@infra_router.get("/partials/card-summary", response_class=HTMLResponse)
async def partial_card_summary(request: Request) -> HTMLResponse:
    root = _ingest_root()
    if root is None:
        return HTMLResponse('<span class="text-muted">SD cards: Styx-local</span>')
    status = infra_queries.read_sd_card_status(root)
    if status is None:
        return HTMLResponse(
            '<span class="text-muted">SD card status unavailable</span>'
        )
    card_stats = infra_queries.card_summary(status)
    freshness = infra_queries.status_freshness(status)
    return infra_templates.TemplateResponse(
        request,
        "partials/infra_card_summary.html",
        _ctx(request, card_stats=card_stats, freshness=freshness),
    )


@infra_router.get("/partials/card-table", response_class=HTMLResponse)
async def partial_card_table(request: Request) -> HTMLResponse:
    root = _ingest_root()
    if root is None:
        return HTMLResponse(
            '<div class="text-muted">SD card status is Styx-local</div>'
        )
    status = infra_queries.read_sd_card_status(root)
    if status is None:
        return HTMLResponse('<div class="text-muted">SD card status unavailable</div>')
    freshness = infra_queries.status_freshness(status)
    return infra_templates.TemplateResponse(
        request,
        "partials/infra_card_table.html",
        _ctx(request, status=status, freshness=freshness),
    )
