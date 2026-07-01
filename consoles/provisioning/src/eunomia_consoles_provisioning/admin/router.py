"""Admin catalog routes — CRUD for hardware, firmware, and setup version catalogs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from eunomia_consoles_provisioning.admin import queries
from eunomia_consoles_provisioning.ops.db import get_conn

TEMPLATES_DIR = Path(__file__).parent / "templates"

admin_router = APIRouter(prefix="/admin", tags=["admin"])
admin_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
CATEGORIES = ("camera", "fob", "gripper", "exo_cam")
HW_STATUSES = ("active", "deprecated")
FW_STATUSES = ("testing", "released", "deprecated")
SV_STATUSES = ("testing", "active", "deprecated")


def _ctx(request: Request, **kwargs: Any) -> dict[str, Any]:
    return {"request": request, **kwargs}


def _parse_json_field(raw: str) -> Any:
    if not raw or not raw.strip():
        return None
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Hardware catalog
# ---------------------------------------------------------------------------


@admin_router.get("/", response_class=HTMLResponse)
async def admin_index(request: Request) -> Response:
    return RedirectResponse(url="/admin/hardware", status_code=302)


@admin_router.get("/hardware", response_class=HTMLResponse)
async def hardware_list(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        items = queries.list_hardware(conn)
    return admin_templates.TemplateResponse(
        request, "hardware_list.html", _ctx(request, items=items, categories=CATEGORIES)
    )


@admin_router.get("/hardware/new", response_class=HTMLResponse)
async def hardware_new(request: Request) -> HTMLResponse:
    return admin_templates.TemplateResponse(
        request,
        "hardware_form.html",
        _ctx(request, item=None, categories=CATEGORIES, error=None),
    )


@admin_router.post("/hardware", response_class=HTMLResponse)
async def hardware_create(
    request: Request,
    catalog_id: str = Form(...),
    display_name: str = Form(...),
    category: str = Form(...),
    photo_url: str = Form(""),
    specs: str = Form(""),
    provisioning_steps: str = Form(""),
) -> Response:
    if not SLUG_RE.match(catalog_id):
        return admin_templates.TemplateResponse(
            request,
            "hardware_form.html",
            _ctx(
                request,
                item=None,
                categories=CATEGORIES,
                error="ID must be lowercase letters, numbers, and hyphens.",
            ),
        )
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        existing = queries.get_hardware(conn, catalog_id)
        if existing:
            return admin_templates.TemplateResponse(
                request,
                "hardware_form.html",
                _ctx(
                    request,
                    item=None,
                    categories=CATEGORIES,
                    error=f"ID '{catalog_id}' already exists.",
                ),
            )
        queries.create_hardware(
            conn,
            catalog_id=catalog_id,
            display_name=display_name,
            category=category,
            photo_url=photo_url or None,
            specs=_parse_json_field(specs),
            provisioning_steps=_parse_json_field(provisioning_steps),
        )
    return RedirectResponse(url="/admin/hardware", status_code=303)


@admin_router.get("/hardware/{catalog_id}/edit", response_class=HTMLResponse)
async def hardware_edit(request: Request, catalog_id: str) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        item = queries.get_hardware(conn, catalog_id)
    if item is None:
        return HTMLResponse("Not found", status_code=404)
    return admin_templates.TemplateResponse(
        request,
        "hardware_form.html",
        _ctx(request, item=item, categories=CATEGORIES, error=None),
    )


@admin_router.post("/hardware/{catalog_id}", response_class=HTMLResponse)
async def hardware_update(
    request: Request,
    catalog_id: str,
    display_name: str = Form(...),
    category: str = Form(...),
    photo_url: str = Form(""),
    specs: str = Form(""),
    provisioning_steps: str = Form(""),
    status: str = Form("active"),
) -> Response:
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        queries.update_hardware(
            conn,
            catalog_id,
            display_name=display_name,
            category=category,
            photo_url=photo_url or None,
            specs=_parse_json_field(specs),
            provisioning_steps=_parse_json_field(provisioning_steps),
            status=status,
        )
    return RedirectResponse(url="/admin/hardware", status_code=303)


# ---------------------------------------------------------------------------
# Firmware catalog
# ---------------------------------------------------------------------------


@admin_router.get("/firmware", response_class=HTMLResponse)
async def firmware_list(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        items = queries.list_firmware(conn)
        hardware = queries.list_hardware(conn, status="active")
    return admin_templates.TemplateResponse(
        request, "firmware_list.html", _ctx(request, items=items, hardware=hardware)
    )


@admin_router.get("/firmware/new", response_class=HTMLResponse)
async def firmware_new(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        hardware = queries.list_hardware(conn, status="active")
    return admin_templates.TemplateResponse(
        request,
        "firmware_form.html",
        _ctx(request, item=None, hardware=hardware, error=None),
    )


@admin_router.post("/firmware", response_class=HTMLResponse)
async def firmware_create(
    request: Request,
    firmware_id: str = Form(...),
    hardware_catalog_id: str = Form(...),
    version: str = Form(...),
    changelog: str = Form(""),
    sidecar_schema_version: str = Form(""),
    binary_url: str = Form(""),
) -> Response:
    if not SLUG_RE.match(firmware_id):
        conn = get_conn()
        hardware = []
        if conn:
            with conn:
                hardware = queries.list_hardware(conn, status="active")
        return admin_templates.TemplateResponse(
            request,
            "firmware_form.html",
            _ctx(
                request,
                item=None,
                hardware=hardware,
                error="ID must be lowercase letters, numbers, and hyphens.",
            ),
        )
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        queries.create_firmware(
            conn,
            firmware_id=firmware_id,
            hardware_catalog_id=hardware_catalog_id,
            version=version,
            changelog=changelog or None,
            sidecar_schema_version=sidecar_schema_version or None,
            binary_url=binary_url or None,
        )
    return RedirectResponse(url="/admin/firmware", status_code=303)


@admin_router.get("/firmware/{firmware_id}/edit", response_class=HTMLResponse)
async def firmware_edit(request: Request, firmware_id: str) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        item = queries.get_firmware(conn, firmware_id)
        hardware = queries.list_hardware(conn, status="active")
    if item is None:
        return HTMLResponse("Not found", status_code=404)
    return admin_templates.TemplateResponse(
        request,
        "firmware_form.html",
        _ctx(request, item=item, hardware=hardware, error=None),
    )


@admin_router.post("/firmware/{firmware_id}", response_class=HTMLResponse)
async def firmware_update(
    request: Request,
    firmware_id: str,
    version: str = Form(...),
    changelog: str = Form(""),
    sidecar_schema_version: str = Form(""),
    binary_url: str = Form(""),
    status: str = Form("testing"),
) -> Response:
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        queries.update_firmware(
            conn,
            firmware_id,
            version=version,
            changelog=changelog or None,
            sidecar_schema_version=sidecar_schema_version or None,
            binary_url=binary_url or None,
            status=status,
        )
    return RedirectResponse(url="/admin/firmware", status_code=303)


# ---------------------------------------------------------------------------
# Setup versions
# ---------------------------------------------------------------------------


@admin_router.get("/setups", response_class=HTMLResponse)
async def setups_list(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        items = queries.list_setups(conn)
        kit_counts = {
            s["setup_id"]: queries.kits_using_setup(conn, s["setup_id"]) for s in items
        }
    return admin_templates.TemplateResponse(
        request, "setups_list.html", _ctx(request, items=items, kit_counts=kit_counts)
    )


@admin_router.get("/setups/new", response_class=HTMLResponse)
async def setup_new(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        hardware = queries.list_hardware(conn, status="active")
    return admin_templates.TemplateResponse(
        request,
        "setup_form.html",
        _ctx(request, item=None, hardware=hardware, error=None),
    )


@admin_router.post("/setups", response_class=HTMLResponse)
async def setup_create(
    request: Request,
    setup_id: str = Form(...),
    display_name: str = Form(...),
    components: str = Form("[]"),
    constraints: str = Form(""),
    contract: str = Form(""),
) -> Response:
    if not SLUG_RE.match(setup_id):
        conn = get_conn()
        hardware = []
        if conn:
            with conn:
                hardware = queries.list_hardware(conn, status="active")
        return admin_templates.TemplateResponse(
            request,
            "setup_form.html",
            _ctx(
                request,
                item=None,
                hardware=hardware,
                error="ID must be lowercase letters, numbers, and hyphens.",
            ),
        )
    try:
        components_parsed = json.loads(components) if components.strip() else []
    except json.JSONDecodeError:
        conn = get_conn()
        hardware = []
        if conn:
            with conn:
                hardware = queries.list_hardware(conn, status="active")
        return admin_templates.TemplateResponse(
            request,
            "setup_form.html",
            _ctx(
                request,
                item=None,
                hardware=hardware,
                error="Components must be valid JSON.",
            ),
        )
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        queries.create_setup(
            conn,
            setup_id=setup_id,
            display_name=display_name,
            components=components_parsed,
            constraints=_parse_json_field(constraints),
            contract=_parse_json_field(contract),
        )
    return RedirectResponse(url="/admin/setups", status_code=303)


@admin_router.get("/setups/{setup_id}/edit", response_class=HTMLResponse)
async def setup_edit(request: Request, setup_id: str) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        item = queries.get_setup(conn, setup_id)
        hardware = queries.list_hardware(conn, status="active")
        kit_count = queries.kits_using_setup(conn, setup_id) if item else 0
    if item is None:
        return HTMLResponse("Not found", status_code=404)
    return admin_templates.TemplateResponse(
        request,
        "setup_form.html",
        _ctx(request, item=item, hardware=hardware, error=None, kit_count=kit_count),
    )


@admin_router.post("/setups/{setup_id}", response_class=HTMLResponse)
async def setup_update(
    request: Request,
    setup_id: str,
    display_name: str = Form(...),
    components: str = Form("[]"),
    constraints: str = Form(""),
    contract: str = Form(""),
    status: str = Form("testing"),
) -> Response:
    try:
        components_parsed = json.loads(components) if components.strip() else []
    except json.JSONDecodeError:
        conn = get_conn()
        hardware = []
        if conn:
            with conn:
                hardware = queries.list_hardware(conn, status="active")
        return admin_templates.TemplateResponse(
            request,
            "setup_form.html",
            _ctx(
                request,
                item=None,
                hardware=hardware,
                error="Components must be valid JSON.",
            ),
        )
    conn = get_conn()
    if conn is None:
        return admin_templates.TemplateResponse(
            request, "unavailable.html", _ctx(request)
        )
    with conn:
        queries.update_setup(
            conn,
            setup_id,
            display_name=display_name,
            components=components_parsed,
            constraints=_parse_json_field(constraints),
            contract=_parse_json_field(contract),
            status=status,
        )
    return RedirectResponse(url="/admin/setups", status_code=303)
