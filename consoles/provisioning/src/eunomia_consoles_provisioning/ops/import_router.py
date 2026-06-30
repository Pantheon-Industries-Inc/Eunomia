"""Web-triggered import and QC routes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from eunomia_consoles_provisioning.ops.db import get_conn

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

import_router = APIRouter(tags=["ops-import"])
_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
_templates.env.filters["to_pretty_json"] = lambda v: json.dumps(
    v, indent=2, default=str, ensure_ascii=False
)


def _ctx(request: Request, **kwargs: Any) -> dict[str, Any]:
    return {"request": request, **kwargs}


@import_router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request) -> HTMLResponse:
    default_drain = os.environ.get("EUNOMIA_DRAIN_DIR", "")
    return _templates.TemplateResponse(
        request, "import.html", _ctx(request, default_drain_dir=default_drain)
    )


@import_router.post("/import/scan-drain", response_class=HTMLResponse)
async def scan_drain_action(request: Request, path: str = Form(...)) -> HTMLResponse:
    drain_path = Path(path)
    if not drain_path.is_dir():
        return HTMLResponse(
            '<div class="card"><p class="fail">Error: path does not exist or is not a '
            "directory.</p></div>"
        )

    conn = get_conn()
    if conn is None:
        return HTMLResponse(
            '<div class="card"><p class="fail">Store unavailable — set '
            "EUNOMIA_STORE_DSN.</p></div>"
        )

    try:
        from eunomia_ingest.ingest import IngestReport, ingest_drain

        report: IngestReport = await asyncio.to_thread(ingest_drain, drain_path, conn)
        conn.commit()
    except Exception as exc:
        log.exception("Scan drain failed")
        conn.rollback()
        return HTMLResponse(f'<div class="card"><p class="fail">Error: {exc}</p></div>')
    finally:
        conn.close()

    anomaly_lines = [f"{a.anomaly_type}: {a.detail}" for a in report.anomalies[:20]]
    return HTMLResponse(
        '<div class="card">'
        '<h3 style="margin-bottom:0.5rem">Ingest Report</h3>'
        "<table>"
        f"<tr><td>Sidecars processed</td><td><strong>{report.sidecars_processed}</strong></td></tr>"
        f"<tr><td>Sidecars skipped</td><td>{report.sidecars_skipped}</td></tr>"
        f"<tr><td>Episodes created</td><td><strong>{report.episodes_created}</strong></td></tr>"
        f"<tr><td>Episodes enriched</td><td>{report.episodes_enriched}</td></tr>"
        f"<tr><td>Events appended</td><td>{report.events_appended}</td></tr>"
        f"<tr><td>Sessions created</td><td>{report.sessions_created}</td></tr>"
        f"<tr><td>Footage refs created</td><td>{report.footage_refs_created}</td></tr>"
        f"<tr><td>Footage orphans</td><td>{report.footage_orphans}</td></tr>"
        f"<tr><td>Sidecar orphans</td><td>{report.sidecar_orphans}</td></tr>"
        f"<tr><td>Anomalies</td><td>{len(report.anomalies)}</td></tr>"
        "</table>"
        + (
            '<pre style="margin-top:0.5rem;font-size:0.8rem;max-height:200px;overflow:auto">'
            + "\n".join(anomaly_lines)
            + "</pre>"
            if anomaly_lines
            else ""
        )
        + "</div>"
    )


@import_router.post("/import/fob-log", response_class=HTMLResponse)
async def import_fob_log_action(
    request: Request, path: str = Form(...)
) -> HTMLResponse:
    log_path = Path(path)
    if not log_path.is_file():
        return HTMLResponse(
            '<div class="card"><p class="fail">Error: file does not exist.</p></div>'
        )

    conn = get_conn()
    if conn is None:
        return HTMLResponse(
            '<div class="card"><p class="fail">Store unavailable — set '
            "EUNOMIA_STORE_DSN.</p></div>"
        )

    try:
        from eunomia_ingest.ingest import IngestReport, ingest_fob_log

        report: IngestReport = await asyncio.to_thread(ingest_fob_log, log_path, conn)
        conn.commit()
    except Exception as exc:
        log.exception("Fob log import failed")
        conn.rollback()
        return HTMLResponse(f'<div class="card"><p class="fail">Error: {exc}</p></div>')
    finally:
        conn.close()

    return HTMLResponse(
        '<div class="card">'
        '<h3 style="margin-bottom:0.5rem">Fob Log Import Report</h3>'
        "<table>"
        f"<tr><td>Lines parsed</td><td><strong>{report.fob_log_lines}</strong></td></tr>"
        f"<tr><td>Lines skipped</td><td>{report.fob_log_skipped}</td></tr>"
        f"<tr><td>Parse errors</td><td>{report.fob_log_errors}</td></tr>"
        f"<tr><td>Events appended</td><td>{report.events_appended}</td></tr>"
        f"<tr><td>Sessions created</td><td>{report.sessions_created}</td></tr>"
        f"<tr><td>Episodes enriched</td><td>{report.episodes_enriched}</td></tr>"
        f"<tr><td>Anomalies</td><td>{len(report.anomalies)}</td></tr>"
        "</table></div>"
    )


@import_router.post("/import/qc-run", response_class=HTMLResponse)
async def run_qc_action(request: Request, date: str = Form(...)) -> HTMLResponse:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return HTMLResponse(
            '<div class="card"><p class="fail">Error: OPENROUTER_API_KEY not set.</p></div>'
        )

    conn = get_conn()
    if conn is None:
        return HTMLResponse(
            '<div class="card"><p class="fail">Store unavailable — set '
            "EUNOMIA_STORE_DSN.</p></div>"
        )

    try:
        from eunomia_qc.engine import run_checks_for_date
        from eunomia_qc.vlm import VLMClient

        vlm = VLMClient(api_key=api_key)
        results = await run_checks_for_date(conn, date, vlm)
        conn.commit()
    except Exception as exc:
        log.exception("QC run failed")
        conn.rollback()
        return HTMLResponse(f'<div class="card"><p class="fail">Error: {exc}</p></div>')
    finally:
        conn.close()

    accept = sum(1 for r in results if r.verdict == "accept")
    review = sum(1 for r in results if r.verdict == "review")
    reject = sum(1 for r in results if r.verdict == "reject")

    rows = "".join(
        f"<tr><td>{r.episode_id}</td>"
        f'<td><span class="badge {"badge-ok" if r.verdict == "accept" else "badge-warn" if r.verdict == "review" else "badge-danger"}">'
        f"{r.verdict}</span></td>"
        f"<td>{r.score}</td>"
        f"<td>{r.verdict_reason}</td></tr>"
        for r in results
    )

    return HTMLResponse(
        '<div class="card">'
        f'<h3 style="margin-bottom:0.5rem">QC Results for {date}</h3>'
        f"<p>Episodes checked: <strong>{len(results)}</strong> &mdash; "
        f'<span class="badge badge-ok">{accept} accept</span> '
        f'<span class="badge badge-warn">{review} review</span> '
        f'<span class="badge badge-danger">{reject} reject</span></p>'
        + (
            '<div class="table-wrap"><table>'
            "<thead><tr><th>Episode</th><th>Verdict</th><th>Score</th><th>Reason</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
            if results
            else '<p class="text-muted">No episodes found for this date.</p>'
        )
        + "</div>"
    )
