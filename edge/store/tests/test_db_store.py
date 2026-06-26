"""DB-backed smoke: round-trip (NOTE F5), allocator (F7), as-of resolvers + dangling flagging (F6),
and the non-destructive importer (F1/F7). Skips without EUNOMIA_STORE_TEST_DSN."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Connection

from eunomia_edge_store import allocator, importer, resolvers, schema, store
from eunomia_edge_store.timestamps import parse_instant, same_instant

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _episode(episode_id: str, recorded_at: str, **over: object) -> dict[str, object]:
    rec: dict[str, object] = {
        "schema": "eunomia-episode/v1",
        "episode_id": episode_id,
        "global_episode_seq": 1,
        "kit_id": "kit-1",
        "side": "left",
        "task_id": "task-1",
        "station_id": "1000",
        "session_id": "sess-1",
        "recorded_at": recorded_at,
    }
    rec.update(over)
    return rec


def test_timestamp_roundtrip_is_instant_equal(conn: Connection) -> None:
    store.upsert(conn, "episode", _episode("ep-tz", "2026-06-26T10:00:00-04:00"))
    got = store.get(conn, "episode", episode_id="ep-tz")
    assert got is not None
    # Stored as timestamptz, read back normalized to UTC ISO — a different STRING, the SAME instant.
    assert same_instant(got["recorded_at"], "2026-06-26T14:00:00Z")
    assert got["recorded_at"] == "2026-06-26T14:00:00+00:00"


def test_upsert_is_idempotent_and_updates(conn: Connection) -> None:
    store.upsert(conn, "episode", _episode("ep-1", "2026-06-26T00:00:00Z"))
    store.upsert(
        conn, "episode", _episode("ep-1", "2026-06-26T00:00:00Z", needs_review=True)
    )
    got = store.get(conn, "episode", episode_id="ep-1")
    assert got is not None and got["needs_review"] is True
    assert store.count(conn, "episode") == 1


def test_append_event_is_append_only_idempotent(conn: Connection) -> None:
    event = {
        "schema": "eunomia-operational-event/v1",
        "event_id": "evt-1",
        "event_type": "camera_id_allocated",
        "entity": "hardware_unit",
        "entity_id": "unit-1",
        "as_of": "2026-06-26T00:00:00Z",
        "payload": {"camera_id": "CAM-1"},
    }
    store.append_event(conn, event)
    store.append_event(conn, event)  # idempotent on event_id
    assert store.count(conn, "operational_event") == 1


def test_allocator_is_monotonic_retire_not_reuse(conn: Connection) -> None:
    first = allocator.allocate_camera_id(conn, body_serial="BS-1")
    second = allocator.allocate_camera_id(conn, body_serial="BS-2")
    assert first != second
    assert first.startswith("CAM-") and second.startswith("CAM-")
    assert int(second.split("-")[1]) > int(first.split("-")[1])  # never reissued
    assert allocator.is_allocated(conn, first)
    assert not allocator.is_allocated(conn, "CAM-never-minted")


def test_resolve_task_station_assignment_as_of(conn: Connection) -> None:
    base = {
        "schema": "eunomia-task-station-assignment/v1",
        "site_id": "site-01",
        "station_id": "1000",
    }
    store.upsert(
        conn,
        "task_station_assignment",
        {
            **base,
            "assignment_id": "a1",
            "task_id": "task-A",
            "effective_from": "2026-06-01T00:00:00Z",
            "effective_to": "2026-06-15T00:00:00Z",
        },
    )
    store.upsert(
        conn,
        "task_station_assignment",
        {
            **base,
            "assignment_id": "a2",
            "task_id": "task-B",
            "effective_from": "2026-06-15T00:00:00Z",
        },
    )
    early = resolvers.resolve_task_station_assignment(
        conn,
        site_id="site-01",
        station_id="1000",
        at=parse_instant("2026-06-10T00:00:00Z"),
    )
    late = resolvers.resolve_task_station_assignment(
        conn,
        site_id="site-01",
        station_id="1000",
        at=parse_instant("2026-06-20T00:00:00Z"),
    )
    assert early is not None and early["task_id"] == "task-A"
    assert late is not None and late["task_id"] == "task-B"


def test_find_dangling_references_is_loud_then_clears(conn: Connection) -> None:
    episode = _episode("ep-dangle", "2026-06-26T00:00:00Z", kit_id="ghost-kit")
    store.upsert(conn, "episode", episode)
    dangling = resolvers.find_dangling_references(conn, "episode", episode)
    assert "kit" in {d.target for d in dangling}  # surfaced, never a silent orphan
    store.upsert(conn, "kit", {"schema": "eunomia-kit/v1", "kit_id": "ghost-kit"})
    after = resolvers.find_dangling_references(conn, "episode", episode)
    assert "kit" not in {d.target for d in after}


def test_importer_non_destructive_preserves_and_allocates(conn: Connection) -> None:
    registry = json.loads((FIXTURES / "fleet.synthetic.json").read_text())
    at = parse_instant("2026-06-26T00:00:00Z")
    report = importer.import_registry(conn, registry, run_id="run-1", as_of=at)

    kept = store.get(conn, "hardware_unit", unit_id="unit-BS-1001")
    minted = store.get(conn, "hardware_unit", unit_id="unit-BS-1002")
    assert (
        kept is not None and kept["camera_id"] == "CAM-existing-1"
    )  # preserved verbatim (F7)
    assert minted is not None and minted["camera_id"].startswith(
        "CAM-"
    )  # allocated (F7)
    assert "unit-BS-1002" in report.allocated_camera_ids
    assert store.get(conn, "station", site_id="site-01", station_id="1000") is not None
    assert report.assignments_created  # station→task assignment appended
    assert (
        store.count(conn, "import_backup") >= 1
    )  # the non-destructive-merge audit (F1)

    # Re-import the same registry: idempotent — camera_id preserved, nothing re-allocated.
    report2 = importer.import_registry(conn, registry, run_id="run-2", as_of=at)
    again = store.get(conn, "hardware_unit", unit_id="unit-BS-1001")
    assert again is not None and again["camera_id"] == "CAM-existing-1"
    assert not report2.allocated_camera_ids


def test_importer_records_drift_and_backup_without_overwriting_camera_id(
    conn: Connection,
) -> None:
    registry = json.loads((FIXTURES / "fleet.synthetic.json").read_text())
    at = parse_instant("2026-06-26T00:00:00Z")
    importer.import_registry(conn, registry, run_id="r1", as_of=at)

    changed = json.loads(json.dumps(registry))
    changed["cameras"][0]["side"] = "right"  # an authoritative change
    changed["cameras"][0]["camera_id"] = (
        "CAM-attempted-overwrite"  # must be ignored (F7)
    )
    report = importer.import_registry(conn, changed, run_id="r2", as_of=at)

    assert "unit-BS-1001" in report.updated
    unit = store.get(conn, "hardware_unit", unit_id="unit-BS-1001")
    assert unit is not None
    assert unit["side"] == "right"  # authoritative field updated
    assert (
        unit["camera_id"] == "CAM-existing-1"
    )  # camera_id preserved across the update (F7)

    backups = (
        conn.execute(
            select(schema.import_backup).where(
                schema.import_backup.c.action == "updated"
            )
        )
        .mappings()
        .all()
    )
    drifts = [b["drift"] for b in backups if b["entity"] == "hardware_unit"]
    assert any(
        "side" in (d or {}) for d in drifts
    )  # before-image + drift recorded (F1)
