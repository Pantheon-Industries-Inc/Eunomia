"""Pure-logic tests for deterministic event_id minting (no DB)."""

from __future__ import annotations

from eunomia_ingest.events import (
    EVENT_SCHEMA,
    build_episode_discarded_event,
    build_episode_started_event,
    build_episode_stopped_event,
    build_ingest_anomaly_event,
    build_session_opened_event,
    build_station_task_assigned_event,
    mint_event_id,
)
from eunomia_ingest.fob_log import (
    EpisodeDiscarded,
    EpisodeStarted,
    EpisodeStopped,
    SessionSignin,
    StationAssignment,
)


def test_mint_deterministic() -> None:
    a = mint_event_id("episode_started", "eid-123")
    b = mint_event_id("episode_started", "eid-123")
    assert a == b


def test_mint_distinct() -> None:
    a = mint_event_id("episode_started", "eid-123")
    b = mint_event_id("episode_stopped", "eid-123")
    c = mint_event_id("episode_started", "eid-456")
    assert a != b
    assert a != c
    assert b != c


def test_mint_valid_uuid() -> None:
    import uuid

    result = mint_event_id("test", "value")
    parsed = uuid.UUID(result)
    assert parsed.version == 5


def test_episode_started_event() -> None:
    entry = EpisodeStarted(
        ordinal=1,
        kit_id="kit_07",
        episode_id="eid-1",
        operator_id="op_1",
        station_id="5",
        task_id="t1",
        task_name="Fold",
        rotation_id="r1",
        task_source="sd_assignment",
    )
    event = build_episode_started_event(entry, wallclock_unix=1750000000)
    assert event["schema"] == EVENT_SCHEMA
    assert event["event_type"] == "episode_started"
    assert event["entity"] == "episode"
    assert event["entity_id"] == "eid-1"
    assert event["related_kit_id"] == "kit_07"
    assert event["as_of"] is not None
    assert event["payload"]["task_id"] == "t1"
    assert event["payload"]["operator_id"] == "op_1"


def test_episode_started_no_wallclock() -> None:
    entry = EpisodeStarted(
        ordinal=1,
        kit_id="k",
        episode_id="e",
        operator_id="o",
        station_id="s",
        task_id="t",
        task_name="n",
        rotation_id="r",
        task_source="none",
    )
    event = build_episode_started_event(entry)
    assert event["as_of"] is None


def test_episode_stopped_event() -> None:
    entry = EpisodeStopped(
        episode_id="eid-1",
        ordinal=1,
        stop_reason="operator",
        archive=0,
        recording_suspect=0,
    )
    event = build_episode_stopped_event(entry)
    assert event["event_type"] == "episode_stopped"
    assert event["entity_id"] == "eid-1"
    assert event["payload"]["stop_reason"] == "operator"


def test_episode_discarded_event() -> None:
    entry = EpisodeDiscarded(episode_id="eid-1", ordinal=1)
    event = build_episode_discarded_event(entry)
    assert event["event_type"] == "episode_discarded"
    assert event["payload"]["ordinal"] == 1


def test_session_opened_event() -> None:
    entry = SessionSignin(
        session_id="sess_1",
        kit_id="kit_07",
        operator_id="op_1",
        site_id="mx_1",
        fob_id="fob_3",
        fob_session_id="abc",
    )
    event = build_session_opened_event(entry)
    assert event["event_type"] == "session_opened"
    assert event["entity"] == "session"
    assert event["entity_id"] == "sess_1"
    assert event["related_kit_id"] == "kit_07"
    assert event["payload"]["fob_session_id"] == "abc"


def test_station_task_assigned_event() -> None:
    entry = StationAssignment(
        station_id="5",
        task_id="t1",
        task_name="Fold",
        rotation_id="r1",
        task_source="sd_assignment",
        kit_id="kit_07",
    )
    event = build_station_task_assigned_event(entry)
    assert event["event_type"] == "station_task_assigned"
    assert event["entity"] == "task_station_assignment"
    assert event["entity_id"] == "kit_07:5:t1"


def test_ingest_anomaly_event() -> None:
    event = build_ingest_anomaly_event(
        "sidecar_hard_error",
        "parse failed",
        entity_id="eid-1",
        related_kit_id="kit_07",
    )
    assert event["event_type"] == "ingest_anomaly"
    assert event["payload"]["anomaly_type"] == "sidecar_hard_error"
    assert event["related_kit_id"] == "kit_07"


def test_re_mint_same_event_idempotent() -> None:
    entry = EpisodeStarted(
        ordinal=1,
        kit_id="k",
        episode_id="eid-X",
        operator_id="o",
        station_id="s",
        task_id="t",
        task_name="n",
        rotation_id="r",
        task_source="none",
    )
    e1 = build_episode_started_event(entry)
    e2 = build_episode_started_event(entry)
    assert e1["event_id"] == e2["event_id"]
