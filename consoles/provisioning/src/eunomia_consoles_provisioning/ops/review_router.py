"""QA review interface routes — review queue, episode review, scorecards, verdicts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from eunomia_edge_store import store
from eunomia_consoles_provisioning.ops import review_queries
from eunomia_consoles_provisioning.ops.db import get_conn

TEMPLATES_DIR = Path(__file__).parent / "templates"

review_router = APIRouter(tags=["ops-review"])
_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

VALID_VERDICTS = {"accept", "review", "reject"}


def _ctx(request: Request, **kwargs: Any) -> dict[str, Any]:
    return {"request": request, **kwargs}


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------


@review_router.get("/review", response_class=HTMLResponse)
async def review_queue_page(
    request: Request,
    operator_id: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    auto_verdict: str | None = Query(default=None),
    human_verdict_filter: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return _templates.TemplateResponse(request, "unavailable.html", _ctx(request))
    limit = 25
    with conn:
        episodes = review_queries.review_queue(
            conn,
            limit=limit,
            offset=offset,
            operator_id=operator_id,
            task_id=task_id,
            auto_verdict=auto_verdict,
            human_verdict_filter=human_verdict_filter,
            date_from=date_from,
            date_to=date_to,
        )
    return _templates.TemplateResponse(
        request,
        "review_queue.html",
        _ctx(
            request,
            episodes=episodes,
            q_operator_id=operator_id or "",
            q_task_id=task_id or "",
            q_auto_verdict=auto_verdict or "",
            q_human_verdict_filter=human_verdict_filter or "",
            q_date_from=date_from or "",
            q_date_to=date_to or "",
            offset=offset,
            limit=limit,
            has_more=len(episodes) == limit,
        ),
    )


@review_router.get("/review/partials/queue-table", response_class=HTMLResponse)
async def review_queue_table_partial(
    request: Request,
    operator_id: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    auto_verdict: str | None = Query(default=None),
    human_verdict_filter: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return HTMLResponse('<p class="text-muted">Store unavailable</p>')
    limit = 25
    with conn:
        episodes = review_queries.review_queue(
            conn,
            limit=limit,
            offset=offset,
            operator_id=operator_id,
            task_id=task_id,
            auto_verdict=auto_verdict,
            human_verdict_filter=human_verdict_filter,
            date_from=date_from,
            date_to=date_to,
        )
    return _templates.TemplateResponse(
        request,
        "partials/review_queue_table.html",
        _ctx(
            request,
            episodes=episodes,
            offset=offset,
            limit=limit,
            has_more=len(episodes) == limit,
            q_operator_id=operator_id or "",
            q_task_id=task_id or "",
            q_auto_verdict=auto_verdict or "",
            q_human_verdict_filter=human_verdict_filter or "",
            q_date_from=date_from or "",
            q_date_to=date_to or "",
        ),
    )


# ---------------------------------------------------------------------------
# Episode review
# ---------------------------------------------------------------------------


@review_router.get("/review/scorecards", response_class=HTMLResponse)
async def review_scorecards_page(
    request: Request,
    period: str = Query(default="week"),
) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return _templates.TemplateResponse(request, "unavailable.html", _ctx(request))
    with conn:
        scorecards = review_queries.operator_scorecards(conn, period=period)
    return _templates.TemplateResponse(
        request,
        "review_scorecards.html",
        _ctx(request, scorecards=scorecards, selected_period=period),
    )


@review_router.get("/review/{episode_id}", response_class=HTMLResponse)
async def review_episode_page(request: Request, episode_id: str) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return _templates.TemplateResponse(request, "unavailable.html", _ctx(request))
    with conn:
        ctx = review_queries.episode_review_context(conn, episode_id)
        if ctx is None:
            return HTMLResponse("Episode not found", status_code=404)
        prev_id = review_queries.adjacent_episode_id(conn, episode_id, direction="prev")
        next_id = review_queries.adjacent_episode_id(conn, episode_id, direction="next")
    ctx["prev_episode_id"] = prev_id
    ctx["next_episode_id"] = next_id
    return _templates.TemplateResponse(
        request, "review_episode.html", _ctx(request, **ctx)
    )


# ---------------------------------------------------------------------------
# Verdict submission
# ---------------------------------------------------------------------------


@review_router.post("/review/{episode_id}/verdict", response_class=HTMLResponse)
async def submit_verdict(
    request: Request,
    episode_id: str,
    verdict: str = Form(...),
    reviewer: str = Form(default=""),
    comment: str = Form(default=""),
) -> HTMLResponse:
    if verdict not in VALID_VERDICTS:
        return HTMLResponse(
            f'<p class="fail">Invalid verdict: {verdict}</p>', status_code=400
        )
    reviewer = reviewer.strip() or "anonymous"

    conn = get_conn()
    if conn is None:
        return HTMLResponse('<p class="fail">Store unavailable</p>', status_code=503)

    with conn:
        auto_event = review_queries.episode_qa_verdict(conn, episode_id)
        auto_payload = (auto_event or {}).get("payload") or {}
        auto_verdict = auto_payload.get("verdict", "")
        auto_score = auto_payload.get("score", 0)

        event = review_queries.build_human_verdict_event(
            episode_id=episode_id,
            verdict=verdict,
            reviewer=reviewer,
            comment=comment,
            auto_verdict=auto_verdict,
            auto_score=auto_score,
        )
        store.append_event(conn, event)
        conn.commit()

    badge_class = {
        "accept": "badge-ok",
        "review": "badge-warn",
        "reject": "badge-danger",
    }
    cls = badge_class.get(verdict, "")
    return HTMLResponse(
        f'<div id="verdict-result">'
        f'<span class="badge {cls}">{verdict.upper()}</span> '
        f'<span class="text-muted">by {reviewer}</span>'
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Bulk accept
# ---------------------------------------------------------------------------


@review_router.post("/review/bulk-accept", response_class=HTMLResponse)
async def bulk_accept(
    request: Request,
    reviewer: str = Form(default=""),
) -> HTMLResponse:
    reviewer = reviewer.strip() or "anonymous"
    form = await request.form()
    episode_ids = form.getlist("episode_ids")

    if not episode_ids:
        return HTMLResponse('<p class="text-muted">No episodes selected.</p>')

    conn = get_conn()
    if conn is None:
        return HTMLResponse('<p class="fail">Store unavailable</p>', status_code=503)

    accepted = 0
    with conn:
        for eid in episode_ids:
            auto_event = review_queries.episode_qa_verdict(conn, str(eid))
            auto_payload = (auto_event or {}).get("payload") or {}
            event = review_queries.build_human_verdict_event(
                episode_id=str(eid),
                verdict="accept",
                reviewer=reviewer,
                comment="Bulk accepted",
                auto_verdict=auto_payload.get("verdict", ""),
                auto_score=auto_payload.get("score", 0),
            )
            store.append_event(conn, event)
            accepted += 1
        conn.commit()

    return HTMLResponse(
        f'<div class="card"><p class="pass">Accepted {accepted} episode(s).</p>'
        f'<p class="text-muted">Reload the page to see updated verdicts.</p></div>'
    )


# ---------------------------------------------------------------------------
# Stats partial for overview
# ---------------------------------------------------------------------------


@review_router.get("/review/partials/review-stats", response_class=HTMLResponse)
async def review_stats_partial(request: Request) -> HTMLResponse:
    conn = get_conn()
    if conn is None:
        return HTMLResponse("")
    with conn:
        count = review_queries.review_queue_count(conn)
    return _templates.TemplateResponse(
        request,
        "partials/review_stats.html",
        _ctx(request, awaiting_review=count),
    )


# ---------------------------------------------------------------------------
# Static media mount (video serving)
# ---------------------------------------------------------------------------


def mount_media(router: APIRouter) -> None:
    """Mount the drain directory as a static file server for video playback."""
    drain_dir = os.environ.get("EUNOMIA_DRAIN_DIR")
    if drain_dir and os.path.isdir(drain_dir):
        router.mount("/media", StaticFiles(directory=drain_dir), name="ops-media")
