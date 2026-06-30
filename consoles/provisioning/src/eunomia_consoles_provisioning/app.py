"""FastAPI provisioning console — bench flash/assign UI + API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from eunomia_consoles_provisioning import ship_gate, site
from eunomia_consoles_provisioning.fob import parse_status
from eunomia_consoles_provisioning.ops.router import ops_router

TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Eunomia Provisioning Console", version="0.0.0")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.include_router(ops_router)


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
