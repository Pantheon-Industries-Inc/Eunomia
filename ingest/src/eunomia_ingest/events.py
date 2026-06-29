"""Deterministic event_id minting + operational event record construction.

Every ``event_id`` is a stable UUID5 derived from the event's natural key — re-importing the same
source data produces the same event_ids, making the pipeline idempotent (the store's
``append_event`` uses ``ON CONFLICT DO NOTHING``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from eunomia_ingest.fob_log import (
    EpisodeDiscarded,
    EpisodeStarted,
    EpisodeStopped,
    SessionSignin,
    StationAssignment,
)

EUNOMIA_NS = uuid.UUID("e8a1c3d0-4f2b-4e6a-9c0f-1a2b3c4d5e6f")

EVENT_SCHEMA = "eunomia-operational-event/v1"


def mint_event_id(*parts: str) -> str:
    return str(uuid.uuid5(EUNOMIA_NS, ":".join(parts)))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_episode_started_event(
    entry: EpisodeStarted, wallclock_unix: int | None = None
) -> dict:
    as_of = (
        datetime.fromtimestamp(wallclock_unix, tz=UTC).isoformat()
        if wallclock_unix is not None
        else None
    )
    return {
        "schema": EVENT_SCHEMA,
        "event_id": mint_event_id("episode_started", entry.episode_id),
        "event_type": "episode_started",
        "entity": "episode",
        "entity_id": entry.episode_id,
        "as_of": as_of,
        "related_kit_id": entry.kit_id,
        "payload": {
            "task_id": entry.task_id,
            "task_name": entry.task_name,
            "station_id": entry.station_id,
            "operator_id": entry.operator_id,
            "rotation_id": entry.rotation_id,
            "task_source": entry.task_source,
            "ordinal": entry.ordinal,
            "kit_id": entry.kit_id,
        },
    }


def build_episode_stopped_event(
    entry: EpisodeStopped, wallclock_unix: int | None = None
) -> dict:
    as_of = (
        datetime.fromtimestamp(wallclock_unix, tz=UTC).isoformat()
        if wallclock_unix is not None
        else None
    )
    return {
        "schema": EVENT_SCHEMA,
        "event_id": mint_event_id("episode_stopped", entry.episode_id),
        "event_type": "episode_stopped",
        "entity": "episode",
        "entity_id": entry.episode_id,
        "as_of": as_of,
        "payload": {
            "stop_reason": entry.stop_reason,
            "archive": entry.archive,
            "recording_suspect": entry.recording_suspect,
            "ordinal": entry.ordinal,
        },
    }


def build_episode_discarded_event(
    entry: EpisodeDiscarded, wallclock_unix: int | None = None
) -> dict:
    as_of = (
        datetime.fromtimestamp(wallclock_unix, tz=UTC).isoformat()
        if wallclock_unix is not None
        else None
    )
    return {
        "schema": EVENT_SCHEMA,
        "event_id": mint_event_id("episode_discarded", entry.episode_id),
        "event_type": "episode_discarded",
        "entity": "episode",
        "entity_id": entry.episode_id,
        "as_of": as_of,
        "payload": {"ordinal": entry.ordinal},
    }


def build_session_opened_event(entry: SessionSignin) -> dict:
    return {
        "schema": EVENT_SCHEMA,
        "event_id": mint_event_id("session_opened", entry.session_id),
        "event_type": "session_opened",
        "entity": "session",
        "entity_id": entry.session_id,
        "related_kit_id": entry.kit_id,
        "payload": {
            "kit_id": entry.kit_id,
            "operator_id": entry.operator_id,
            "site_id": entry.site_id,
            "fob_id": entry.fob_id,
            "fob_session_id": entry.fob_session_id,
        },
    }


def build_station_task_assigned_event(entry: StationAssignment) -> dict:
    return {
        "schema": EVENT_SCHEMA,
        "event_id": mint_event_id(
            "station_task_assigned",
            entry.kit_id,
            entry.station_id,
            entry.task_id,
            entry.rotation_id,
        ),
        "event_type": "station_task_assigned",
        "entity": "task_station_assignment",
        "entity_id": f"{entry.kit_id}:{entry.station_id}:{entry.task_id}",
        "related_kit_id": entry.kit_id,
        "payload": {
            "station_id": entry.station_id,
            "task_id": entry.task_id,
            "task_name": entry.task_name,
            "rotation_id": entry.rotation_id,
            "task_source": entry.task_source,
            "kit_id": entry.kit_id,
        },
    }


def build_ingest_anomaly_event(
    anomaly_type: str,
    detail: str,
    *,
    entity: str = "episode",
    entity_id: str = "",
    related_kit_id: str | None = None,
) -> dict:
    return {
        "schema": EVENT_SCHEMA,
        "event_id": mint_event_id("ingest_anomaly", anomaly_type, entity_id, detail),
        "event_type": "ingest_anomaly",
        "entity": entity,
        "entity_id": entity_id or "unknown",
        "as_of": _now_iso(),
        "related_kit_id": related_kit_id,
        "payload": {
            "anomaly_type": anomaly_type,
            "detail": detail,
        },
    }
