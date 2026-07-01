"""Tests for infrastructure health data readers."""

from __future__ import annotations

import json
from pathlib import Path

from eunomia_consoles_provisioning.ops.infra_queries import (
    active_ingest_count,
    camera_map_warnings,
    card_summary,
    format_uptime,
    read_camera_map,
    read_sd_card_status,
    read_sync_status,
    save_camera_map,
    status_freshness,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_STATUS: dict = {
    "generated_at": "2026-07-01T12:00:00+00:00",
    "styx_local": True,
    "slots": [
        {"slot_key": "left_a_1", "hardware_present": True, "latest_status": "copying"},
        {
            "slot_key": "left_a_2",
            "hardware_present": True,
            "latest_status": "styx-verified",
        },
        {"slot_key": "left_a_3", "hardware_present": False, "latest_status": ""},
        {
            "slot_key": "left_a_4",
            "hardware_present": True,
            "latest_status": "error-copy",
        },
        {
            "slot_key": "left_a_5",
            "hardware_present": True,
            "latest_status": "drained-done",
        },
        {"slot_key": "left_a_6", "hardware_present": False, "latest_status": "idle"},
    ],
    "imports": [],
    "unmapped_devices": [],
}

SAMPLE_CAMERA_MAP: dict = {
    "IAQEB001": {
        "serial": "IAQEB001",
        "alias": "cam-1-left",
        "operator": "operator01",
        "side": "left",
        "active": True,
        "notes": "",
        "last_updated": "2026-07-01T12:00:00Z",
    },
    "IAQEB002": {
        "serial": "IAQEB002",
        "alias": "cam-1-right",
        "operator": "operator01",
        "side": "right",
        "active": True,
        "notes": "",
        "last_updated": "2026-07-01T12:00:00Z",
    },
}

SAMPLE_SYNC_STATUS: dict = {
    "generated_at": "2026-07-01T12:00:00+00:00",
    "footage": {
        "last_run": "2026-07-01T11:55:00+00:00",
        "last_success": "2026-07-01T11:55:00+00:00",
        "episodes_synced_total": 42,
        "episodes_pending": 3,
        "episodes_broken": 0,
        "bytes_last_run": 1073741824,
        "effective_mbps": 28.6,
        "styx_reachable": True,
    },
    "replication": {
        "subscription_active": True,
        "lag_seconds": 2,
        "latest_end_time": "2026-07-01T11:59:58Z",
    },
}


# ---------------------------------------------------------------------------
# card_summary
# ---------------------------------------------------------------------------


def test_card_summary_counts() -> None:
    result = card_summary(SAMPLE_STATUS)
    assert result["total"] == 6
    assert result["present"] == 4
    assert result["ingesting"] == 1
    assert result["drained"] == 2
    assert result["error"] == 1
    assert result["idle"] == 2


def test_card_summary_empty() -> None:
    result = card_summary({"slots": []})
    assert result.get("total", 0) == 0
    assert result.get("ingesting", 0) == 0


# ---------------------------------------------------------------------------
# camera_map_warnings
# ---------------------------------------------------------------------------


def test_camera_map_warnings_clean() -> None:
    warnings = camera_map_warnings(SAMPLE_CAMERA_MAP)
    assert warnings == []


def test_camera_map_warnings_duplicate() -> None:
    dup_map = {
        "A": {"serial": "A", "operator": "op1", "side": "left", "active": True},
        "B": {"serial": "B", "operator": "op1", "side": "left", "active": True},
    }
    warnings = camera_map_warnings(dup_map)
    types = [w["type"] for w in warnings]
    assert "duplicate" in types


def test_camera_map_warnings_one_side() -> None:
    one_side_map = {
        "A": {"serial": "A", "operator": "op1", "side": "left", "active": True},
    }
    warnings = camera_map_warnings(one_side_map)
    types = [w["type"] for w in warnings]
    assert "one_side" in types


def test_camera_map_warnings_unassigned() -> None:
    unassigned_map = {
        "A": {"serial": "A", "operator": "", "side": "", "active": True},
    }
    warnings = camera_map_warnings(unassigned_map)
    types = [w["type"] for w in warnings]
    assert "unassigned" in types


def test_camera_map_warnings_inactive_ignored() -> None:
    inactive_map = {
        "A": {"serial": "A", "operator": "op1", "side": "left", "active": False},
    }
    warnings = camera_map_warnings(inactive_map)
    assert warnings == []


# ---------------------------------------------------------------------------
# status_freshness
# ---------------------------------------------------------------------------


def test_status_freshness_stale() -> None:
    result = status_freshness({"generated_at": "2020-01-01T00:00:00+00:00"})
    assert result["stale"] is True
    assert result["age_seconds"] > 0


def test_status_freshness_missing() -> None:
    result = status_freshness({})
    assert result["stale"] is True
    assert result["age_seconds"] == -1


# ---------------------------------------------------------------------------
# active_ingest_count
# ---------------------------------------------------------------------------


def test_active_ingest_count() -> None:
    assert active_ingest_count(SAMPLE_STATUS) == 1


def test_active_ingest_count_none() -> None:
    assert active_ingest_count({"slots": []}) == 0


# ---------------------------------------------------------------------------
# format_uptime
# ---------------------------------------------------------------------------


def test_format_uptime_days() -> None:
    assert format_uptime(90061) == "1d 1h 1m"


def test_format_uptime_hours() -> None:
    assert format_uptime(3660) == "1h 1m"


def test_format_uptime_minutes() -> None:
    assert format_uptime(300) == "5m"


def test_format_uptime_none() -> None:
    assert format_uptime(None) == "—"


# ---------------------------------------------------------------------------
# Filesystem-backed readers (tmp_path)
# ---------------------------------------------------------------------------


def test_read_sd_card_status_valid(tmp_path: Path) -> None:
    status_dir = tmp_path / "storage-health"
    status_dir.mkdir()
    (status_dir / "sd-card-styx-status.json").write_text(json.dumps(SAMPLE_STATUS))
    result = read_sd_card_status(tmp_path)
    assert result is not None
    assert result["styx_local"] is True
    assert len(result["slots"]) == 6


def test_read_sd_card_status_missing(tmp_path: Path) -> None:
    assert read_sd_card_status(tmp_path) is None


def test_read_camera_map_valid(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "camera_map.json").write_text(json.dumps(SAMPLE_CAMERA_MAP))
    result = read_camera_map(tmp_path)
    assert result is not None
    assert "IAQEB001" in result


def test_read_sync_status_valid(tmp_path: Path) -> None:
    status_file = tmp_path / "status.json"
    status_file.write_text(json.dumps(SAMPLE_SYNC_STATUS))
    result = read_sync_status(status_file)
    assert result is not None
    assert result["replication"]["subscription_active"] is True


def test_read_sync_status_missing(tmp_path: Path) -> None:
    assert read_sync_status(tmp_path / "nonexistent.json") is None


def test_save_camera_map_atomic(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    original = {"OLD": {"serial": "OLD", "operator": "op1", "side": "left"}}
    (config_dir / "camera_map.json").write_text(json.dumps(original))

    new_data = {"NEW": {"serial": "NEW", "operator": "op2", "side": "right"}}
    save_camera_map(tmp_path, new_data)

    saved = json.loads((config_dir / "camera_map.json").read_text())
    assert "NEW" in saved
    assert "OLD" not in saved

    bak = json.loads((config_dir / "camera_map.json.bak").read_text())
    assert "OLD" in bak


def test_save_camera_map_no_prior(tmp_path: Path) -> None:
    save_camera_map(tmp_path, {"A": {"serial": "A"}})
    saved = json.loads((tmp_path / "config" / "camera_map.json").read_text())
    assert "A" in saved
    assert not (tmp_path / "config" / "camera_map.json.bak").exists()
