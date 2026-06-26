"""No-DB unit tests for the timezone-correct timestamp helpers (NOTE F5), the pure non-destructive
merge decision (NOTE F1), and the swappable camera_id format (NOTE F7)."""

from __future__ import annotations

from datetime import datetime, timezone

from eunomia_edge_store import allocator
from eunomia_edge_store.importer import plan_merge
from eunomia_edge_store.timestamps import parse_instant, same_instant, to_iso


def test_same_instant_is_timezone_correct() -> None:
    # The same moment in two zones compares equal (instant, not string) — NOTE F5.
    assert same_instant("2026-06-26T10:00:00-04:00", "2026-06-26T14:00:00Z")
    assert same_instant("2026-06-26T14:00:00Z", "2026-06-26T14:00:00+00:00")
    assert not same_instant("2026-06-26T10:00:00Z", "2026-06-26T11:00:00Z")


def test_same_instant_handles_none() -> None:
    assert same_instant(None, None)
    assert not same_instant("2026-06-26T00:00:00Z", None)
    assert not same_instant(None, "2026-06-26T00:00:00Z")


def test_parse_instant_assumes_utc_for_naive_and_normalizes() -> None:
    assert parse_instant("2026-06-26T00:00:00") == datetime(
        2026, 6, 26, tzinfo=timezone.utc
    )
    assert parse_instant("2026-06-26T00:00:00Z").tzinfo == timezone.utc
    assert to_iso("2026-06-26T10:00:00-04:00") == "2026-06-26T14:00:00+00:00"
    assert to_iso(None) is None


def test_plan_merge_created_when_absent() -> None:
    plan = plan_merge("hardware_unit", None, {"unit_id": "u1", "side": "left"})
    assert plan.action == "created"
    assert plan.values == {"unit_id": "u1", "side": "left"}
    assert plan.drift == {}


def test_plan_merge_unchanged_when_authoritative_matches() -> None:
    existing = {"unit_id": "u1", "side": "left", "status": "deployed"}
    plan = plan_merge("hardware_unit", existing, {"side": "left", "status": "deployed"})
    assert plan.action == "unchanged"
    assert plan.values == {}


def test_plan_merge_updates_and_records_drift() -> None:
    existing = {"unit_id": "u1", "side": "left"}
    plan = plan_merge("hardware_unit", existing, {"side": "right"})
    assert plan.action == "updated"
    assert plan.values == {"side": "right"}
    assert plan.drift == {"side": {"from": "left", "to": "right"}}


def test_plan_merge_preserves_camera_id_verbatim() -> None:
    # An existing camera_id is NEVER overwritten; the attempted change is flagged, not applied (F7).
    existing = {"unit_id": "u1", "camera_id": "CAM-existing"}
    plan = plan_merge("hardware_unit", existing, {"camera_id": "CAM-other"})
    assert "camera_id" not in plan.values
    assert plan.drift["camera_id"] == {"kept": "CAM-existing", "ignored": "CAM-other"}


def test_plan_merge_fills_absent_camera_id() -> None:
    existing = {"unit_id": "u1", "camera_id": None}
    plan = plan_merge("hardware_unit", existing, {"camera_id": "CAM-7"})
    assert plan.action == "updated"
    assert plan.values == {"camera_id": "CAM-7"}


def test_camera_id_format_is_a_swappable_constant() -> None:
    assert "{n}" in allocator.CAMERA_ID_FORMAT
    assert allocator.format_camera_id(7) == "CAM-7"
