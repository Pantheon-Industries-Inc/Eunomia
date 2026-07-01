"""Pure-logic tests for the sidecar parser (no DB)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eunomia_ingest.sidecar import parse_sidecar, scan_drain

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DRAIN_ROOT = FIXTURES / "drain"


@pytest.fixture
def drain_root() -> Path:
    return DRAIN_ROOT


def test_parse_valid_full_sidecar(drain_root: Path) -> None:
    path = (
        drain_root
        / "kit_07"
        / "DCIM"
        / "100_INSTA"
        / "VID_20260624_100000_042.eunomia.json"
    )
    record, errors = parse_sidecar(path)
    assert errors == []
    assert record is not None
    assert record.episode_id == "550e8400-e29b-41d4-a716-446655440000"
    assert record.global_episode_seq == 1009
    assert record.kit_id == "kit_07"
    assert record.side == "left"
    assert record.camera_id == "cam_A"
    assert record.operator_id == "op_123"
    assert record.station_id == "5"
    assert record.task_id == "t_fold"
    assert record.session_id == "sess_xyz"
    assert record.rotation_id == "r2"
    assert record.task_source == "sd_assignment"
    assert record.episode_ordinal == 12
    assert record.bimanual_episode_id == "bi_88"
    assert record.display_id == "20260624_op123_5_000012"
    assert record.started_unix == 1750000000.5
    assert record.stopped_unix == 1750000123.0
    assert record.stop_reason == "operator"
    assert record.archive == 0
    assert record.recording_suspect == 0
    assert record.camera_firmware == "1.1.6"
    assert record.fob_id == "fob_3"
    assert record.site_id == "mx_1"
    assert record.modality == "umi"


def test_parse_minimal_sidecar(drain_root: Path) -> None:
    path = (
        drain_root
        / "kit_07"
        / "DCIM"
        / "100_INSTA"
        / "VID_20260624_101000_043.eunomia.json"
    )
    record, errors = parse_sidecar(path)
    assert errors == []
    assert record is not None
    assert record.episode_id == "660e8400-e29b-41d4-a716-446655440001"
    assert record.global_episode_seq == 1010
    assert record.bimanual_episode_id is None
    assert record.display_id is None
    assert record.recording_suspect == 1


def test_parse_sidecar_hard_errors(drain_root: Path) -> None:
    path = drain_root / "kit_08" / "DCIM" / "100_INSTA" / "bad_sidecar.eunomia.json"
    record, errors = parse_sidecar(path)
    assert record is None
    assert len(errors) > 0


def test_parse_sidecar_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "broken.eunomia.json"
    bad.write_text("not json {{{")
    record, errors = parse_sidecar(bad)
    assert record is None
    assert any("JSON" in e for e in errors)


def test_parse_sidecar_not_object(tmp_path: Path) -> None:
    bad = tmp_path / "array.eunomia.json"
    bad.write_text("[1, 2, 3]")
    record, errors = parse_sidecar(bad)
    assert record is None
    assert any("object" in e for e in errors)


def test_footage_resolution(drain_root: Path) -> None:
    path = (
        drain_root
        / "kit_07"
        / "DCIM"
        / "100_INSTA"
        / "VID_20260624_100000_042.eunomia.json"
    )
    record, _ = parse_sidecar(path)
    assert record is not None
    assert record.footage_exists is True
    assert record.footage_path is not None
    assert record.footage_path.name == "VID_20260624_100000_00_042.insv"


def test_scan_drain_discovers_all(drain_root: Path) -> None:
    result = scan_drain(drain_root)
    assert len(result.records) == 2
    assert len(result.skipped) == 1
    episode_ids = {r.episode_id for r in result.records}
    assert "550e8400-e29b-41d4-a716-446655440000" in episode_ids
    assert "660e8400-e29b-41d4-a716-446655440001" in episode_ids


def test_scan_drain_finds_orphan_footage(drain_root: Path) -> None:
    result = scan_drain(drain_root)
    orphan_names = {p.name for p in result.footage_orphans}
    assert "VID_20260624_102000_00_044.insv" in orphan_names


def test_scan_drain_reports_skipped(drain_root: Path) -> None:
    result = scan_drain(drain_root)
    assert len(result.skipped) == 1
    skipped_path, errors = result.skipped[0]
    assert "bad_sidecar" in skipped_path.name
    assert len(errors) > 0


def test_scan_drain_empty_dir(tmp_path: Path) -> None:
    result = scan_drain(tmp_path)
    assert result.records == []
    assert result.skipped == []
    assert result.footage_orphans == []


def test_parse_sidecar_captures_raw_dict(drain_root: Path) -> None:
    path = (
        drain_root
        / "kit_07"
        / "DCIM"
        / "100_INSTA"
        / "VID_20260624_100000_042.eunomia.json"
    )
    record, _ = parse_sidecar(path)
    assert record is not None
    assert isinstance(record.raw, dict)
    assert record.raw["schema"] == "eunomia-sidecar/v1"
    assert record.raw["identity"]["kit_id"] == "kit_07"
    assert record.raw["provenance"]["fob_build"] == "3.8.3"


def test_raw_preserves_unknown_fields(tmp_path: Path) -> None:
    sidecar = {
        "schema": "eunomia-sidecar/v1",
        "seq": 1,
        "global_episode_seq": 1,
        "identity": {
            "camera_id": "c",
            "kit_id": "k",
            "side": "right",
            "operator_id": "o",
            "station_id": "s",
            "task_id": "t",
            "task_name": "n",
            "session_id": "s",
            "episode_id": "raw-test-uuid",
            "rotation_id": "r",
            "prompt": "p",
            "task_source": "none",
        },
        "provenance": {"future_sensor": "lidar_v2"},
        "files": {"back": "MISSING.insv"},
    }
    p = tmp_path / "raw.eunomia.json"
    p.write_text(json.dumps(sidecar))
    record, _ = parse_sidecar(p)
    assert record is not None
    assert record.raw["provenance"]["future_sensor"] == "lidar_v2"


def test_sidecar_without_footage(tmp_path: Path) -> None:
    """Sidecar referencing a footage file that doesn't exist."""
    sidecar = {
        "schema": "eunomia-sidecar/v1",
        "seq": 1,
        "global_episode_seq": 1,
        "identity": {
            "camera_id": "c",
            "kit_id": "k",
            "side": "right",
            "operator_id": "o",
            "station_id": "s",
            "task_id": "t",
            "task_name": "n",
            "session_id": "s",
            "episode_id": "aaa-bbb-ccc",
            "rotation_id": "r",
            "prompt": "p",
            "task_source": "none",
        },
        "files": {"back": "MISSING.insv"},
    }
    p = tmp_path / "test.eunomia.json"
    p.write_text(json.dumps(sidecar))
    record, errors = parse_sidecar(p)
    assert record is not None
    assert record.footage_exists is False
    assert record.footage_path is not None
    assert record.footage_path.name == "MISSING.insv"
