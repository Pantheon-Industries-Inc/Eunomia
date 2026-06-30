"""Read-only queries for the ops dashboard.

All queries take a SQLAlchemy ``Connection`` and return plain dicts/lists. The dashboard never
writes to S1 — every function here is a SELECT.

Duration convention: the ``archive`` column on ``episode`` is a frame count at 30 fps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from eunomia_edge_store.schema import TABLES

FPS = 30


def frames_to_seconds(frames: int | None) -> float:
    if not frames:
        return 0.0
    return frames / FPS


def frames_to_hours(frames: int | None) -> float:
    return frames_to_seconds(frames) / 3600.0


def format_duration(frames: int | None) -> str:
    """Human-readable duration from a frame count (e.g. '1m 23s', '2h 05m')."""
    s = int(frames_to_seconds(frames))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def _period_starts() -> dict[str, datetime]:
    now = datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    return {"today": today, "week": week, "month": month}


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def overview_stats(conn: Connection) -> dict[str, Any]:
    ep = TABLES["episode"]
    periods = _period_starts()

    def _count_and_hours(since: datetime) -> tuple[int, float, int, int]:
        row = conn.execute(
            sa.select(
                sa.func.count().label("n"),
                sa.func.coalesce(sa.func.sum(ep.c.archive), 0).label("frames"),
                sa.func.count(sa.distinct(ep.c.person_id)).label("operators"),
                sa.func.count(sa.distinct(ep.c.kit_id)).label("kits"),
            ).where(ep.c.recorded_at >= since)
        ).one()
        return (
            int(row.n),
            frames_to_hours(int(row.frames)),
            int(row.operators),
            int(row.kits),
        )

    today_eps, today_hrs, operators, kits = _count_and_hours(periods["today"])
    week_eps, week_hrs, _, _ = _count_and_hours(periods["week"])
    month_eps, month_hrs, _, _ = _count_and_hours(periods["month"])

    return {
        "episodes_today": today_eps,
        "hours_today": round(today_hrs, 1),
        "operators_active": operators,
        "kits_in_use": kits,
        "episodes_week": week_eps,
        "hours_week": round(week_hrs, 1),
        "episodes_month": month_eps,
        "hours_month": round(month_hrs, 1),
    }


def anomaly_count(conn: Connection) -> int:
    oe = TABLES["operational_event"]
    row = conn.execute(
        sa.select(sa.func.count()).where(oe.c.event_type == "ingest_anomaly")
    ).scalar_one()
    return int(row)


def recent_episodes(conn: Connection, *, limit: int = 25) -> list[dict[str, Any]]:
    ep = TABLES["episode"]
    person = TABLES["person"]
    task = TABLES["task"]

    stmt = (
        sa.select(
            ep.c.episode_id,
            ep.c.display_id,
            ep.c.recorded_at,
            ep.c.kit_id,
            ep.c.station_id,
            ep.c.archive,
            ep.c.recording_suspect,
            ep.c.void,
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
        .order_by(ep.c.recorded_at.desc().nulls_last())
        .limit(limit)
    )
    rows = conn.execute(stmt).mappings().all()
    return [
        {
            **dict(r),
            "duration": format_duration(r["archive"]),
            "flagged": bool(r["recording_suspect"]) or bool(r["void"]),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------


def operator_list(conn: Connection) -> list[dict[str, Any]]:
    person = TABLES["person"]
    ep = TABLES["episode"]
    periods = _period_starts()

    stmt = (
        sa.select(
            person.c.person_id,
            person.c.name,
            person.c.role,
            person.c.status,
            sa.func.count(ep.c.episode_id).label("total"),
            sa.func.count(ep.c.episode_id)
            .filter(ep.c.recorded_at >= periods["today"])
            .label("today"),
            sa.func.count(ep.c.episode_id)
            .filter(ep.c.recorded_at >= periods["week"])
            .label("week"),
            sa.func.count(ep.c.episode_id)
            .filter(ep.c.recorded_at >= periods["month"])
            .label("month"),
            sa.func.max(ep.c.recorded_at).label("last_active"),
            sa.func.count(ep.c.episode_id)
            .filter(ep.c.recording_suspect > 0)
            .label("suspect"),
            sa.func.count(ep.c.episode_id)
            .filter(ep.c.void.is_(True))
            .label("discarded"),
        )
        .outerjoin(ep, person.c.person_id == ep.c.person_id)
        .group_by(person.c.person_id, person.c.name, person.c.role, person.c.status)
        .order_by(sa.desc("today"), sa.desc("last_active"))
    )
    rows = conn.execute(stmt).mappings().all()
    result = []
    for r in rows:
        total = int(r["total"]) if r["total"] else 0
        suspect = int(r["suspect"]) if r["suspect"] else 0
        pct = round(100 * suspect / total, 1) if total else 0.0
        result.append({**dict(r), "suspect_pct": pct})
    return result


def operator_detail(conn: Connection, person_id: str) -> dict[str, Any] | None:
    person = TABLES["person"]
    row = (
        conn.execute(sa.select(person).where(person.c.person_id == person_id))
        .mappings()
        .first()
    )
    if row is None:
        return None
    return dict(row)


def operator_hours_by_task(conn: Connection, person_id: str) -> list[dict[str, Any]]:
    ep = TABLES["episode"]
    task = TABLES["task"]

    stmt = (
        sa.select(
            task.c.task_name,
            task.c.task_id,
            sa.func.sum(ep.c.archive).label("frames"),
            sa.func.count(ep.c.episode_id).label("episodes"),
        )
        .join(
            task,
            sa.and_(
                ep.c.task_id == task.c.task_id,
                ep.c.task_version == task.c.version,
                ep.c.rotation_id == task.c.rotation_id,
            ),
        )
        .where(ep.c.person_id == person_id)
        .group_by(task.c.task_name, task.c.task_id)
        .order_by(sa.desc("frames"))
    )
    rows = conn.execute(stmt).mappings().all()
    return [
        {**dict(r), "hours": round(frames_to_hours(int(r["frames"])), 1)} for r in rows
    ]


def operator_sessions(conn: Connection, person_id: str) -> list[dict[str, Any]]:
    session = TABLES["session"]

    stmt = (
        sa.select(
            session.c.session_id,
            session.c.signed_in_at,
            session.c.signed_out_at,
            session.c.station_id,
            session.c.kit_id,
        )
        .where(session.c.person_id == person_id)
        .order_by(session.c.signed_in_at.desc().nulls_last())
    )
    return [dict(r) for r in conn.execute(stmt).mappings().all()]


def operator_episode_counts(conn: Connection, person_id: str) -> dict[str, int]:
    ep = TABLES["episode"]
    periods = _period_starts()

    stmt = sa.select(
        sa.func.count(ep.c.episode_id).label("total"),
        sa.func.count(ep.c.episode_id)
        .filter(ep.c.recorded_at >= periods["today"])
        .label("today"),
        sa.func.count(ep.c.episode_id)
        .filter(ep.c.recorded_at >= periods["week"])
        .label("week"),
        sa.func.count(ep.c.episode_id)
        .filter(ep.c.recorded_at >= periods["month"])
        .label("month"),
        sa.func.count(ep.c.episode_id)
        .filter(ep.c.recording_suspect > 0)
        .label("suspect"),
        sa.func.count(ep.c.episode_id).filter(ep.c.void.is_(True)).label("discarded"),
    ).where(ep.c.person_id == person_id)
    row = conn.execute(stmt).mappings().one()
    return dict(row)


# ---------------------------------------------------------------------------
# Kits
# ---------------------------------------------------------------------------


def kit_list(conn: Connection) -> list[dict[str, Any]]:
    kit = TABLES["kit"]
    ep = TABLES["episode"]
    hu = TABLES["hardware_unit"]
    person = TABLES["person"]
    session = TABLES["session"]

    latest_session = (
        sa.select(
            session.c.kit_id,
            session.c.person_id,
            sa.func.row_number()
            .over(
                partition_by=session.c.kit_id,
                order_by=session.c.signed_in_at.desc().nulls_last(),
            )
            .label("rn"),
        )
        .correlate(kit)
        .subquery("ls")
    )

    hu_l = hu.alias("hu_l")
    hu_r = hu.alias("hu_r")
    hu_f = hu.alias("hu_f")

    stmt = (
        sa.select(
            kit.c.kit_id,
            hu_l.c.camera_id.label("left_camera_id"),
            hu_r.c.camera_id.label("right_camera_id"),
            hu_f.c.fob_id,
            person.c.name.label("current_operator"),
            sa.func.count(sa.distinct(ep.c.episode_id)).label("episode_count"),
            sa.func.max(ep.c.ingested_at).label("last_drain"),
            sa.func.count(sa.distinct(ep.c.episode_id))
            .filter(ep.c.recording_suspect > 0)
            .label("suspect_count"),
        )
        .outerjoin(hu_l, kit.c.left_cam_unit_id == hu_l.c.unit_id)
        .outerjoin(hu_r, kit.c.right_cam_unit_id == hu_r.c.unit_id)
        .outerjoin(hu_f, kit.c.fob_unit_id == hu_f.c.unit_id)
        .outerjoin(
            latest_session,
            sa.and_(kit.c.kit_id == latest_session.c.kit_id, latest_session.c.rn == 1),
        )
        .outerjoin(person, latest_session.c.person_id == person.c.person_id)
        .outerjoin(ep, kit.c.kit_id == ep.c.kit_id)
        .group_by(
            kit.c.kit_id,
            hu_l.c.camera_id,
            hu_r.c.camera_id,
            hu_f.c.fob_id,
            person.c.name,
        )
    )
    return [dict(r) for r in conn.execute(stmt).mappings().all()]


def kit_detail(conn: Connection, kit_id: str) -> dict[str, Any] | None:
    kit = TABLES["kit"]
    hu = TABLES["hardware_unit"]

    hu_l = hu.alias("hu_l")
    hu_r = hu.alias("hu_r")
    hu_f = hu.alias("hu_f")

    stmt = (
        sa.select(
            kit.c.kit_id,
            kit.c.left_cam_unit_id,
            kit.c.right_cam_unit_id,
            kit.c.fob_unit_id,
            hu_l.c.camera_id.label("left_camera_id"),
            hu_r.c.camera_id.label("right_camera_id"),
            hu_f.c.fob_id,
        )
        .outerjoin(hu_l, kit.c.left_cam_unit_id == hu_l.c.unit_id)
        .outerjoin(hu_r, kit.c.right_cam_unit_id == hu_r.c.unit_id)
        .outerjoin(hu_f, kit.c.fob_unit_id == hu_f.c.unit_id)
        .where(kit.c.kit_id == kit_id)
    )
    row = conn.execute(stmt).mappings().first()
    if row is None:
        return None
    return dict(row)


def kit_episode_stats(conn: Connection, kit_id: str) -> dict[str, Any]:
    ep = TABLES["episode"]
    stmt = sa.select(
        sa.func.count(ep.c.episode_id).label("episode_count"),
        sa.func.count(ep.c.episode_id)
        .filter(ep.c.recording_suspect > 0)
        .label("suspect_count"),
        sa.func.max(ep.c.ingested_at).label("last_drain"),
    ).where(ep.c.kit_id == kit_id)
    return dict(conn.execute(stmt).mappings().one())


def kit_current_operator(conn: Connection, kit_id: str) -> str | None:
    session = TABLES["session"]
    person = TABLES["person"]
    stmt = (
        sa.select(person.c.name)
        .join(session, session.c.person_id == person.c.person_id)
        .where(session.c.kit_id == kit_id)
        .order_by(session.c.signed_in_at.desc().nulls_last())
        .limit(1)
    )
    row = conn.execute(stmt).scalar()
    return row


def kit_anomalies(
    conn: Connection, kit_id: str, *, limit: int = 50
) -> list[dict[str, Any]]:
    oe = TABLES["operational_event"]
    stmt = (
        sa.select(
            oe.c.event_id,
            oe.c.as_of,
            oe.c.entity_id,
            oe.c.payload,
        )
        .where(
            sa.and_(
                oe.c.event_type == "ingest_anomaly",
                oe.c.related_kit_id == kit_id,
            )
        )
        .order_by(oe.c.as_of.desc().nulls_last())
        .limit(limit)
    )
    rows = conn.execute(stmt).mappings().all()
    return [
        {
            "event_id": r["event_id"],
            "as_of": r["as_of"],
            "entity_id": r["entity_id"],
            "anomaly_type": r["payload"].get("anomaly_type", "")
            if r["payload"]
            else "",
            "detail": r["payload"].get("detail", "") if r["payload"] else "",
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def task_list(conn: Connection) -> list[dict[str, Any]]:
    ep = TABLES["episode"]
    task = TABLES["task"]

    stmt = (
        sa.select(
            task.c.task_id,
            sa.func.max(task.c.task_name).label("task_name"),
            sa.func.count(sa.distinct(ep.c.episode_id)).label("episode_count"),
            sa.func.coalesce(sa.func.sum(ep.c.archive), 0).label("frames"),
            sa.func.count(sa.distinct(ep.c.person_id)).label("operator_count"),
        )
        .outerjoin(
            ep,
            sa.and_(
                task.c.task_id == ep.c.task_id,
                task.c.version == ep.c.task_version,
                task.c.rotation_id == ep.c.rotation_id,
            ),
        )
        .group_by(task.c.task_id)
        .order_by(sa.desc("frames"))
    )
    rows = conn.execute(stmt).mappings().all()
    return [
        {
            **dict(r),
            "hours": round(frames_to_hours(int(r["frames"])), 1),
            "avg_duration": format_duration(
                int(r["frames"]) // int(r["episode_count"]) if r["episode_count"] else 0
            ),
        }
        for r in rows
    ]


def task_detail(conn: Connection, task_id: str) -> dict[str, Any] | None:
    task = TABLES["task"]
    ep = TABLES["episode"]

    stmt = (
        sa.select(
            task.c.task_id,
            sa.func.max(task.c.task_name).label("task_name"),
            sa.func.count(sa.distinct(ep.c.episode_id)).label("episode_count"),
            sa.func.coalesce(sa.func.sum(ep.c.archive), 0).label("frames"),
            sa.func.count(sa.distinct(ep.c.person_id)).label("operator_count"),
        )
        .outerjoin(
            ep,
            sa.and_(
                task.c.task_id == ep.c.task_id,
                task.c.version == ep.c.task_version,
                task.c.rotation_id == ep.c.rotation_id,
            ),
        )
        .where(task.c.task_id == task_id)
        .group_by(task.c.task_id)
    )
    row = conn.execute(stmt).mappings().first()
    if row is None:
        return None
    return {
        **dict(row),
        "hours": round(frames_to_hours(int(row["frames"])), 1),
        "avg_duration": format_duration(
            int(row["frames"]) // int(row["episode_count"])
            if row["episode_count"]
            else 0
        ),
    }


def task_operators(conn: Connection, task_id: str) -> list[dict[str, Any]]:
    ep = TABLES["episode"]
    person = TABLES["person"]

    stmt = (
        sa.select(
            person.c.person_id,
            person.c.name,
            sa.func.count(ep.c.episode_id).label("episodes"),
            sa.func.coalesce(sa.func.sum(ep.c.archive), 0).label("frames"),
            sa.func.count(ep.c.episode_id)
            .filter(ep.c.recording_suspect > 0)
            .label("suspect"),
        )
        .join(ep, person.c.person_id == ep.c.person_id)
        .where(ep.c.task_id == task_id)
        .group_by(person.c.person_id, person.c.name)
        .order_by(sa.desc("frames"))
    )
    rows = conn.execute(stmt).mappings().all()
    return [
        {
            **dict(r),
            "hours": round(frames_to_hours(int(r["frames"])), 1),
            "quality_pct": round(100 * (1 - int(r["suspect"]) / int(r["episodes"])), 1)
            if r["episodes"]
            else 100.0,
        }
        for r in rows
    ]


def task_versions(conn: Connection, task_id: str) -> list[dict[str, Any]]:
    task = TABLES["task"]
    stmt = (
        sa.select(task).where(task.c.task_id == task_id).order_by(task.c.version.desc())
    )
    return [dict(r) for r in conn.execute(stmt).mappings().all()]


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Pipeline health
# ---------------------------------------------------------------------------

_PIPELINE_HEALTH_SQL = sa.text("""\
WITH ep_events AS (
  SELECT
    e.episode_id,
    e.recorded_at,
    e.ingested_at,
    (SELECT oe.as_of FROM operational_event oe
     WHERE oe.entity_id = e.episode_id AND oe.event_type = 'footage_normalized'
     LIMIT 1) AS normalized_at,
    (SELECT oe.as_of FROM operational_event oe
     WHERE oe.entity_id = e.episode_id AND oe.event_type = 'qa_verdict'
     LIMIT 1) AS qa_verdict_at,
    (SELECT oe.as_of FROM operational_event oe
     WHERE oe.entity_id = e.episode_id AND oe.event_type = 'sync_state_transition'
     AND oe.payload->>'new_state' = 'on_hades'
     LIMIT 1) AS synced_at
  FROM episode e
  WHERE e.recorded_at >= :since AND e.void IS NOT TRUE
)
SELECT
  percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (ingested_at - recorded_at))/60.0)
    AS median_drain_to_ingest_min,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (normalized_at - ingested_at))/60.0)
    AS median_ingest_to_normalize_min,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (qa_verdict_at - normalized_at))/60.0)
    AS median_normalize_to_qc_min,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (synced_at - qa_verdict_at))/60.0)
    AS median_qc_to_sync_min,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (qa_verdict_at - recorded_at))/60.0)
    AS median_recording_to_verdict_min,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (qa_verdict_at - recorded_at))/60.0)
    AS p95_recording_to_verdict_min,
  COUNT(*) AS total_episodes,
  COUNT(ingested_at) AS ingested,
  COUNT(normalized_at) AS normalized,
  COUNT(qa_verdict_at) AS qc_complete,
  COUNT(synced_at) AS synced
FROM ep_events
""")

_PIPELINE_STALLS_SQL = sa.text("""\
WITH ep_state AS (
  SELECT
    e.episode_id,
    e.recorded_at,
    e.ingested_at,
    EXISTS (SELECT 1 FROM operational_event oe
            WHERE oe.entity_id = e.episode_id
              AND oe.event_type = 'footage_normalized') AS has_normalized,
    EXISTS (SELECT 1 FROM operational_event oe
            WHERE oe.entity_id = e.episode_id
              AND oe.event_type = 'qa_verdict') AS has_qc,
    EXISTS (SELECT 1 FROM operational_event oe
            WHERE oe.entity_id = e.episode_id
              AND oe.event_type = 'sync_state_transition'
              AND oe.payload->>'new_state' = 'on_hades') AS has_synced
  FROM episode e
  WHERE e.void IS NOT TRUE
)
SELECT 'awaiting_ingest' AS stage, COUNT(*) AS count, MIN(recorded_at) AS oldest
  FROM ep_state WHERE ingested_at IS NULL
UNION ALL
SELECT 'awaiting_normalize', COUNT(*), MIN(ingested_at)
  FROM ep_state WHERE ingested_at IS NOT NULL AND NOT has_normalized
UNION ALL
SELECT 'awaiting_qc', COUNT(*), MIN(ingested_at)
  FROM ep_state WHERE has_normalized AND NOT has_qc
UNION ALL
SELECT 'awaiting_sync', COUNT(*), MIN(ingested_at)
  FROM ep_state WHERE has_qc AND NOT has_synced
""")


def pipeline_health(conn: Connection, since: datetime) -> dict[str, Any]:
    """Per-step latency stats and funnel counts for episodes recorded since *since*."""
    row = conn.execute(_PIPELINE_HEALTH_SQL, {"since": since}).mappings().one()
    out: dict[str, Any] = {}
    for k, v in dict(row).items():
        if k.endswith("_min"):
            out[k] = round(float(v), 1) if v is not None else None
        else:
            out[k] = int(v) if v is not None else 0
    return out


def pipeline_stalls(conn: Connection) -> list[dict[str, Any]]:
    """Episodes stuck at each pipeline stage — counts and oldest timestamp."""
    rows = conn.execute(_PIPELINE_STALLS_SQL).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------


ANOMALY_TYPES = (
    "recording_suspect",
    "sidecar_without_footage",
    "sidecar_hard_error",
    "footage_without_sidecar",
    "fob_log_parse_error",
)


def anomaly_feed(
    conn: Connection,
    *,
    limit: int = 50,
    offset: int = 0,
    anomaly_type: str | None = None,
    kit_id: str | None = None,
) -> list[dict[str, Any]]:
    oe = TABLES["operational_event"]

    wheres: list[sa.ColumnElement[bool]] = [oe.c.event_type == "ingest_anomaly"]
    if anomaly_type:
        wheres.append(oe.c.payload["anomaly_type"].astext == anomaly_type)
    if kit_id:
        wheres.append(oe.c.related_kit_id == kit_id)

    stmt = (
        sa.select(
            oe.c.event_id,
            oe.c.entity_id,
            oe.c.as_of,
            oe.c.related_kit_id,
            oe.c.payload,
        )
        .where(sa.and_(*wheres))
        .order_by(oe.c.as_of.desc().nulls_last())
        .limit(limit)
        .offset(offset)
    )
    rows = conn.execute(stmt).mappings().all()
    return [
        {
            "event_id": r["event_id"],
            "as_of": r["as_of"],
            "entity_id": r["entity_id"],
            "kit_id": r["related_kit_id"],
            "anomaly_type": r["payload"].get("anomaly_type", "")
            if r["payload"]
            else "",
            "detail": r["payload"].get("detail", "") if r["payload"] else "",
        }
        for r in rows
    ]
