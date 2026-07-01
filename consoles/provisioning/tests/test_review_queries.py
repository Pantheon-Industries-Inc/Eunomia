"""Pure logic tests for review query helpers (no database required)."""

from __future__ import annotations

from eunomia_consoles_provisioning.ops.review_queries import (
    _format_duration,
    _parse_location,
    build_human_verdict_event,
    mint_event_id,
)


# ---------------------------------------------------------------------------
# _parse_location
# ---------------------------------------------------------------------------


def test_parse_location_normalized() -> None:
    tier, path = _parse_location(
        "normalized:/data/kit01/normalized/VID_001_workspace.mp4"
    )
    assert tier == "normalized"
    assert path == "/data/kit01/normalized/VID_001_workspace.mp4"


def test_parse_location_bare() -> None:
    tier, path = _parse_location("/data/kit01/DCIM/100_INSTA/VID_001.insv")
    assert tier == ""
    assert path == "/data/kit01/DCIM/100_INSTA/VID_001.insv"


def test_parse_location_styx_tier() -> None:
    tier, path = _parse_location("styx:/archive/kit01")
    assert tier == "styx"
    assert path == "/archive/kit01"


# ---------------------------------------------------------------------------
# _format_duration
# ---------------------------------------------------------------------------


def test_format_duration_seconds() -> None:
    assert _format_duration(600) == "20s"


def test_format_duration_minutes() -> None:
    assert _format_duration(2700) == "1m 30s"


def test_format_duration_hours() -> None:
    assert _format_duration(108000) == "1h 00m"


def test_format_duration_none() -> None:
    assert _format_duration(None) == "0s"


# ---------------------------------------------------------------------------
# mint_event_id
# ---------------------------------------------------------------------------


def test_mint_event_id_deterministic() -> None:
    a = mint_event_id("qa_human_verdict", "ep-001", "mo")
    b = mint_event_id("qa_human_verdict", "ep-001", "mo")
    assert a == b


def test_mint_event_id_changes_with_parts() -> None:
    a = mint_event_id("qa_human_verdict", "ep-001", "mo", "2026-01-01")
    b = mint_event_id("qa_human_verdict", "ep-001", "mo", "2026-01-02")
    assert a != b


# ---------------------------------------------------------------------------
# build_human_verdict_event
# ---------------------------------------------------------------------------


def test_build_human_verdict_event_shape() -> None:
    event = build_human_verdict_event(
        episode_id="ep-001",
        verdict="accept",
        reviewer="mo",
        comment="looks good",
        auto_verdict="review",
        auto_score=78,
    )
    assert event["schema"] == "eunomia-operational-event/v1"
    assert event["event_type"] == "qa_human_verdict"
    assert event["entity"] == "episode"
    assert event["entity_id"] == "ep-001"
    assert event["payload"]["verdict"] == "accept"
    assert event["payload"]["reviewer"] == "mo"
    assert event["payload"]["comment"] == "looks good"
    assert event["payload"]["overrides_auto_verdict"] == "review"
    assert event["payload"]["auto_score"] == 78
    assert "event_id" in event
    assert "as_of" in event


def test_build_human_verdict_event_has_unique_event_id() -> None:
    e1 = build_human_verdict_event("ep-001", "accept", "mo", "", "review", 78)
    e2 = build_human_verdict_event("ep-001", "reject", "mo", "", "review", 78)
    assert e1["event_id"] != e2["event_id"]


def test_build_human_verdict_event_reason_includes_reviewer() -> None:
    event = build_human_verdict_event("ep-001", "accept", "alice", "", "", 0)
    assert "alice" in event["reason"]
