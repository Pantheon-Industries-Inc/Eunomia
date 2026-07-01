"""Queries for the QA review interface.

Read queries for the review queue, episode QC verdicts, human verdicts, operator scorecards,
and video path resolution. Write helpers for constructing human verdict events.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from eunomia_edge_store.schema import TABLES

EUNOMIA_NS = uuid.UUID("e8a1c3d0-4f2b-4e6a-9c0f-1a2b3c4d5e6f")
EVENT_SCHEMA = "eunomia-operational-event/v1"
FPS = 30


def mint_event_id(*parts: str) -> str:
    return str(uuid.uuid5(EUNOMIA_NS, ":".join(parts)))


def _frames_to_seconds(frames: int | None) -> float:
    return (frames / FPS) if frames else 0.0


def _format_duration(frames: int | None) -> str:
    s = int(_frames_to_seconds(frames))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def _parse_location(loc: str) -> tuple[str, str]:
    """Split a tier:path location string into (tier, path). Bare paths have tier=""."""
    if ":" in loc:
        tier, _, path_str = loc.partition(":")
        return tier, path_str
    return "", loc


def _period_start(period: str) -> datetime | None:
    now = datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        return today
    if period == "week":
        return today - timedelta(days=today.weekday())
    if period == "month":
        return today.replace(day=1)
    return None


# ---------------------------------------------------------------------------
# Video path resolution
# ---------------------------------------------------------------------------


def resolve_video_url(
    conn: Connection, episode_id: str, drain_root: str | None = None
) -> str | None:
    """Return the /ops/media/... URL for the episode's best video, or None."""
    if drain_root is None:
        drain_root = os.environ.get("EUNOMIA_DRAIN_DIR", "")
    if not drain_root:
        return None

    fr = TABLES["footage_reference"]
    row = (
        conn.execute(sa.select(fr).where(fr.c.episode_id == episode_id))
        .mappings()
        .first()
    )
    if row is None:
        return None

    locations = row.get("locations") or []
    drain = Path(drain_root)

    for tier_prefix in ("normalized", ""):
        for loc in locations:
            if not isinstance(loc, str):
                continue
            tier, path_str = _parse_location(loc)
            if tier_prefix and tier != tier_prefix:
                continue
            p = Path(path_str)
            if p.exists():
                try:
                    rel = p.relative_to(drain)
                    return f"/ops/media/{rel}"
                except ValueError:
                    continue
    return None


# ---------------------------------------------------------------------------
# Event queries
# ---------------------------------------------------------------------------


def _latest_event_of_type(
    conn: Connection, episode_id: str, event_type: str
) -> dict[str, Any] | None:
    oe = TABLES["operational_event"]
    stmt = (
        sa.select(oe)
        .where(
            oe.c.entity == "episode",
            oe.c.entity_id == episode_id,
            oe.c.event_type == event_type,
        )
        .order_by(oe.c.as_of.desc().nulls_last())
        .limit(1)
    )
    row = conn.execute(stmt).mappings().first()
    return dict(row) if row else None


def episode_qa_verdict(conn: Connection, episode_id: str) -> dict[str, Any] | None:
    return _latest_event_of_type(conn, episode_id, "qa_verdict")


def episode_human_verdict(conn: Connection, episode_id: str) -> dict[str, Any] | None:
    return _latest_event_of_type(conn, episode_id, "qa_human_verdict")


# ---------------------------------------------------------------------------
# Human verdict event construction
# ---------------------------------------------------------------------------


def build_human_verdict_event(
    episode_id: str,
    verdict: str,
    reviewer: str,
    comment: str,
    auto_verdict: str,
    auto_score: int | float,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "schema": EVENT_SCHEMA,
        "event_id": mint_event_id("qa_human_verdict", episode_id, reviewer, now),
        "event_type": "qa_human_verdict",
        "entity": "episode",
        "entity_id": episode_id,
        "as_of": now,
        "reason": f"Human QA verdict by {reviewer}",
        "payload": {
            "verdict": verdict,
            "reviewer": reviewer,
            "comment": comment,
            "overrides_auto_verdict": auto_verdict,
            "auto_score": auto_score,
        },
    }


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------


def review_queue(
    conn: Connection,
    *,
    limit: int = 25,
    offset: int = 0,
    operator_id: str | None = None,
    task_id: str | None = None,
    auto_verdict: str | None = None,
    human_verdict_filter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """Episodes needing human review: QC1 review/reject + spot_check_selected accepts."""
    ep = TABLES["episode"]
    person = TABLES["person"]
    task = TABLES["task"]
    oe = TABLES["operational_event"]
    fr = TABLES["footage_reference"]

    # Latest qa_verdict per episode (lateral-style via correlated subquery)
    auto_sub = (
        sa.select(
            oe.c.entity_id.label("ep_id"),
            oe.c.payload.label("auto_payload"),
            oe.c.as_of.label("auto_as_of"),
        )
        .where(
            oe.c.entity == "episode",
            oe.c.entity_id == ep.c.episode_id,
            oe.c.event_type == "qa_verdict",
        )
        .order_by(oe.c.as_of.desc().nulls_last())
        .limit(1)
        .correlate(ep)
        .lateral("auto_v")
    )

    # Latest qa_human_verdict per episode
    human_sub = (
        sa.select(
            oe.c.entity_id.label("ep_id"),
            oe.c.payload.label("human_payload"),
            oe.c.as_of.label("human_as_of"),
        )
        .where(
            oe.c.entity == "episode",
            oe.c.entity_id == ep.c.episode_id,
            oe.c.event_type == "qa_human_verdict",
        )
        .order_by(oe.c.as_of.desc().nulls_last())
        .limit(1)
        .correlate(ep)
        .lateral("human_v")
    )

    stmt = (
        sa.select(
            ep.c.episode_id,
            ep.c.display_id,
            ep.c.recorded_at,
            ep.c.kit_id,
            ep.c.archive,
            ep.c.recording_suspect,
            ep.c.void,
            person.c.name.label("operator_name"),
            ep.c.person_id,
            task.c.task_name,
            ep.c.task_id,
            auto_sub.c.auto_payload,
            auto_sub.c.auto_as_of,
            human_sub.c.human_payload,
            human_sub.c.human_as_of,
            fr.c.spot_check_selected,
        )
        .outerjoin(person, ep.c.person_id == person.c.person_id)
        .outerjoin(
            task,
            sa.and_(
                ep.c.task_id == task.c.task_id,
                ep.c.task_version == task.c.version,
                ep.c.rotation_id == task.c.rotation_id,
            ),
        )
        .outerjoin(auto_sub, sa.literal(True))
        .outerjoin(human_sub, sa.literal(True))
        .outerjoin(fr, ep.c.episode_id == fr.c.episode_id)
    )

    wheres: list[sa.ColumnElement[bool]] = [ep.c.void.is_(False)]

    # Queue filter: review/reject OR spot_check_selected accepts OR has human verdict
    auto_verdict_col = auto_sub.c.auto_payload["verdict"].astext
    queue_condition = sa.or_(
        auto_verdict_col.in_(["review", "reject"]),
        sa.and_(auto_verdict_col == "accept", fr.c.spot_check_selected.is_(True)),
        human_sub.c.human_payload.isnot(None),
    )
    wheres.append(queue_condition)

    # Must have a QC verdict OR a human verdict to be in the queue
    wheres.append(
        sa.or_(
            auto_sub.c.auto_payload.isnot(None),
            human_sub.c.human_payload.isnot(None),
        )
    )

    if operator_id:
        wheres.append(ep.c.person_id == operator_id)
    if task_id:
        wheres.append(ep.c.task_id == task_id)
    if auto_verdict:
        wheres.append(auto_verdict_col == auto_verdict)
    if human_verdict_filter == "reviewed":
        wheres.append(human_sub.c.human_payload.isnot(None))
    elif human_verdict_filter == "unreviewed":
        wheres.append(human_sub.c.human_payload.is_(None))
    if date_from:
        wheres.append(
            ep.c.recorded_at >= datetime.fromisoformat(f"{date_from}T00:00:00+00:00")
        )
    if date_to:
        wheres.append(
            ep.c.recorded_at
            < datetime.fromisoformat(f"{date_to}T00:00:00+00:00") + timedelta(days=1)
        )

    stmt = (
        stmt.where(sa.and_(*wheres))
        .order_by(ep.c.recorded_at.desc().nulls_last())
        .limit(limit)
        .offset(offset)
    )

    rows = conn.execute(stmt).mappings().all()
    result = []
    for r in rows:
        auto_p = r["auto_payload"] or {}
        human_p = r["human_payload"] or {}
        result.append(
            {
                "episode_id": r["episode_id"],
                "display_id": r["display_id"],
                "recorded_at": r["recorded_at"],
                "kit_id": r["kit_id"],
                "operator_name": r["operator_name"],
                "person_id": r["person_id"],
                "task_name": r["task_name"],
                "task_id": r["task_id"],
                "duration": _format_duration(r["archive"]),
                "auto_verdict": auto_p.get("verdict", ""),
                "auto_score": auto_p.get("score", 0),
                "human_verdict": human_p.get("verdict", ""),
                "human_reviewer": human_p.get("reviewer", ""),
                "has_human_verdict": bool(r["human_payload"]),
                "spot_check": bool(r["spot_check_selected"]),
            }
        )
    return result


def review_queue_count(conn: Connection) -> int:
    """Count of episodes in the review queue that have no human verdict yet."""
    ep = TABLES["episode"]
    oe = TABLES["operational_event"]
    fr = TABLES["footage_reference"]

    # Latest qa_verdict
    auto_sub = (
        sa.select(oe.c.payload)
        .where(
            oe.c.entity == "episode",
            oe.c.entity_id == ep.c.episode_id,
            oe.c.event_type == "qa_verdict",
        )
        .order_by(oe.c.as_of.desc().nulls_last())
        .limit(1)
        .correlate(ep)
        .scalar_subquery()
    )

    # Has any human verdict?
    has_human = (
        sa.select(sa.literal(1))
        .where(
            oe.c.entity == "episode",
            oe.c.entity_id == ep.c.episode_id,
            oe.c.event_type == "qa_human_verdict",
        )
        .correlate(ep)
        .exists()
    )

    auto_verdict_col = auto_sub["verdict"].astext

    stmt = (
        sa.select(sa.func.count())
        .select_from(ep)
        .outerjoin(fr, ep.c.episode_id == fr.c.episode_id)
        .where(
            ep.c.void.is_(False),
            sa.or_(
                auto_verdict_col.in_(["review", "reject"]),
                sa.and_(
                    auto_verdict_col == "accept", fr.c.spot_check_selected.is_(True)
                ),
            ),
            ~has_human,
        )
    )
    return int(conn.execute(stmt).scalar_one())


# ---------------------------------------------------------------------------
# Episode review context
# ---------------------------------------------------------------------------


def episode_review_context(conn: Connection, episode_id: str) -> dict[str, Any] | None:
    """All data needed for the single-episode review page."""
    ep = TABLES["episode"]
    person = TABLES["person"]
    task = TABLES["task"]

    stmt = (
        sa.select(
            ep,
            person.c.name.label("operator_name"),
            task.c.task_name,
        )
        .outerjoin(person, ep.c.person_id == person.c.person_id)
        .outerjoin(
            task,
            sa.and_(
                ep.c.task_id == task.c.task_id,
                ep.c.task_version == task.c.version,
                ep.c.rotation_id == task.c.rotation_id,
            ),
        )
        .where(ep.c.episode_id == episode_id)
    )
    row = conn.execute(stmt).mappings().first()
    if row is None:
        return None

    data = dict(row)
    data["duration"] = _format_duration(data.get("archive"))

    auto_event = episode_qa_verdict(conn, episode_id)
    data["auto_verdict_event"] = auto_event
    if auto_event:
        payload = auto_event.get("payload") or {}
        data["auto_verdict"] = payload.get("verdict", "")
        data["auto_score"] = payload.get("score", 0)
        checks = payload.get("checks") or []
        data["checks_failed"] = [c for c in checks if c.get("status") == "fail"]
        data["checks_passed"] = [c for c in checks if c.get("status") == "pass"]
        data["checks_other"] = [
            c for c in checks if c.get("status") not in ("pass", "fail")
        ]
    else:
        data["auto_verdict"] = ""
        data["auto_score"] = 0
        data["checks_failed"] = []
        data["checks_passed"] = []
        data["checks_other"] = []

    human_event = episode_human_verdict(conn, episode_id)
    data["human_verdict_event"] = human_event
    if human_event:
        hp = human_event.get("payload") or {}
        data["human_verdict"] = hp.get("verdict", "")
        data["human_reviewer"] = hp.get("reviewer", "")
        data["human_comment"] = hp.get("comment", "")
        data["human_as_of"] = human_event.get("as_of")
    else:
        data["human_verdict"] = ""
        data["human_reviewer"] = ""
        data["human_comment"] = ""
        data["human_as_of"] = None

    data["video_url"] = resolve_video_url(conn, episode_id)

    return data


# ---------------------------------------------------------------------------
# Adjacent episode (prev/next navigation)
# ---------------------------------------------------------------------------


def adjacent_episode_id(
    conn: Connection,
    episode_id: str,
    direction: str = "next",
) -> str | None:
    """Return the episode_id of the next (older) or prev (newer) episode that has a QC verdict."""
    ep = TABLES["episode"]
    oe = TABLES["operational_event"]

    current = conn.execute(
        sa.select(ep.c.recorded_at).where(ep.c.episode_id == episode_id)
    ).scalar_one_or_none()
    if current is None:
        return None

    has_verdict = (
        sa.select(sa.literal(1))
        .where(
            oe.c.entity == "episode",
            oe.c.entity_id == ep.c.episode_id,
            oe.c.event_type.in_(["qa_verdict", "qa_human_verdict"]),
        )
        .correlate(ep)
        .exists()
    )

    if direction == "next":
        stmt = (
            sa.select(ep.c.episode_id)
            .where(ep.c.recorded_at < current, ep.c.void.is_(False), has_verdict)
            .order_by(ep.c.recorded_at.desc().nulls_last())
            .limit(1)
        )
    else:
        stmt = (
            sa.select(ep.c.episode_id)
            .where(ep.c.recorded_at > current, ep.c.void.is_(False), has_verdict)
            .order_by(ep.c.recorded_at.asc().nulls_last())
            .limit(1)
        )
    return conn.execute(stmt).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Operator scorecards
# ---------------------------------------------------------------------------


def operator_scorecards(
    conn: Connection,
    *,
    period: str = "week",
) -> list[dict[str, Any]]:
    """Per-operator verdict counts from human QA verdicts (latest per episode)."""
    ep = TABLES["episode"]
    person = TABLES["person"]
    task = TABLES["task"]
    oe = TABLES["operational_event"]

    period_start = _period_start(period)

    # Get latest human verdict per episode via DISTINCT ON
    latest_human = (
        sa.select(
            oe.c.entity_id.label("episode_id"),
            oe.c.payload,
            oe.c.as_of,
        )
        .where(oe.c.event_type == "qa_human_verdict", oe.c.entity == "episode")
        .distinct(oe.c.entity_id)
        .order_by(oe.c.entity_id, oe.c.as_of.desc().nulls_last())
        .subquery("latest_human")
    )

    stmt = (
        sa.select(
            person.c.person_id,
            person.c.name.label("operator_name"),
            ep.c.task_id,
            task.c.task_name,
            latest_human.c.payload,
        )
        .join(latest_human, ep.c.episode_id == latest_human.c.episode_id)
        .outerjoin(person, ep.c.person_id == person.c.person_id)
        .outerjoin(
            task,
            sa.and_(
                ep.c.task_id == task.c.task_id,
                ep.c.task_version == task.c.version,
                ep.c.rotation_id == task.c.rotation_id,
            ),
        )
    )
    if period_start:
        stmt = stmt.where(ep.c.recorded_at >= period_start)

    rows = conn.execute(stmt).mappings().all()

    # Aggregate in Python (simpler than complex SQL for nested grouping)
    operators: dict[str, dict[str, Any]] = {}
    for r in rows:
        pid = r["person_id"] or "unknown"
        name = r["operator_name"] or pid
        payload = r["payload"] or {}
        verdict = payload.get("verdict", "")
        task_name = r["task_name"] or r["task_id"] or "unknown"

        if pid not in operators:
            operators[pid] = {
                "person_id": pid,
                "operator_name": name,
                "total": 0,
                "accepted": 0,
                "flagged": 0,
                "rejected": 0,
                "tasks": {},
            }
        op = operators[pid]
        op["total"] += 1
        if verdict == "accept":
            op["accepted"] += 1
        elif verdict == "review":
            op["flagged"] += 1
        elif verdict == "reject":
            op["rejected"] += 1

        if task_name not in op["tasks"]:
            op["tasks"][task_name] = {"total": 0, "accepted": 0}
        op["tasks"][task_name]["total"] += 1
        if verdict == "accept":
            op["tasks"][task_name]["accepted"] += 1

    result = []
    for op in sorted(operators.values(), key=lambda o: -o["total"]):
        op["pass_rate"] = (
            round(100 * op["accepted"] / op["total"], 1) if op["total"] else 0.0
        )
        task_list = []
        for tname, tcounts in sorted(op["tasks"].items(), key=lambda t: -t[1]["total"]):
            task_list.append(
                {
                    "task_name": tname,
                    "total": tcounts["total"],
                    "pass_rate": round(100 * tcounts["accepted"] / tcounts["total"], 1)
                    if tcounts["total"]
                    else 0.0,
                }
            )
        op["task_breakdown"] = task_list
        del op["tasks"]
        result.append(op)

    return result


def operator_qa_stats(conn: Connection, person_id: str) -> dict[str, Any]:
    """Human + auto verdict summary for one operator (for the D1 operator detail page)."""
    oe = TABLES["operational_event"]
    ep = TABLES["episode"]

    stats: dict[str, Any] = {
        "human_total": 0,
        "human_accepted": 0,
        "human_pass_rate": 0.0,
        "auto_total": 0,
        "auto_accepted": 0,
        "auto_pass_rate": 0.0,
    }

    for event_type, prefix in [("qa_human_verdict", "human"), ("qa_verdict", "auto")]:
        latest = (
            sa.select(
                oe.c.entity_id.label("episode_id"),
                oe.c.payload,
            )
            .where(oe.c.event_type == event_type, oe.c.entity == "episode")
            .distinct(oe.c.entity_id)
            .order_by(oe.c.entity_id, oe.c.as_of.desc().nulls_last())
            .subquery()
        )
        stmt = (
            sa.select(
                sa.func.count().label("total"),
                sa.func.count()
                .filter(latest.c.payload["verdict"].astext == "accept")
                .label("accepted"),
            )
            .select_from(latest)
            .join(ep, ep.c.episode_id == latest.c.episode_id)
            .where(ep.c.person_id == person_id)
        )
        row = conn.execute(stmt).mappings().one()
        total = int(row["total"])
        accepted = int(row["accepted"])
        stats[f"{prefix}_total"] = total
        stats[f"{prefix}_accepted"] = accepted
        stats[f"{prefix}_pass_rate"] = (
            round(100 * accepted / total, 1) if total else 0.0
        )

    return stats
