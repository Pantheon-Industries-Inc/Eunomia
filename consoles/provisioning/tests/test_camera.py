"""Tests for camera protocol — pure functions (no hardware)."""

from __future__ import annotations

from eunomia_consoles_provisioning.camera import (
    build_camera_env,
    build_fob_env,
    build_write_file_cmd,
)


def test_build_write_file_cmd_format() -> None:
    cmd = build_write_file_cmd("/pref/test.env", "KEY=val")
    assert "mkdir -p '/pref'" in cmd
    assert "cat > '/pref/test.env' <<'X3EOF'" in cmd
    assert "KEY=val" in cmd
    assert "X3EOF" in cmd
    assert "sync" in cmd
    assert "echo WROTE /pref/test.env" in cmd


def test_build_write_file_cmd_root_dir() -> None:
    cmd = build_write_file_cmd("file.txt", "data")
    assert "mkdir -p '/'" in cmd


def test_build_camera_env() -> None:
    env = build_camera_env(
        camera_id="CAM-42",
        kit_id="kit_001",
        side="left",
        mount="wrist",
        calibration_id="cal-fleet-v1",
    )
    assert "CAMERA_ID=CAM-42" in env
    assert "KIT_ID=kit_001" in env
    assert "CAMERA_SIDE=left" in env
    assert "CAMERA_MOUNT=wrist" in env
    assert "CALIBRATION_ID=cal-fleet-v1" in env


def test_build_camera_env_no_calibration() -> None:
    env = build_camera_env(
        camera_id="CAM-1",
        kit_id="kit_002",
        side="right",
    )
    assert "CALIBRATION_ID" not in env


def test_build_fob_env() -> None:
    env = build_fob_env(ssid="PANTHEON-KIT-001", psk="pantheon")
    assert "ROOTKIT_FOB_SSID=PANTHEON-KIT-001" in env
    assert "ROOTKIT_FOB_PASS=pantheon" in env


def test_build_fob_env_no_rootkit_on_sd() -> None:
    """The fob env carries join credentials — verify it's generating the right shape."""
    env = build_fob_env(ssid="FOB-AP", psk="secret")
    lines = env.strip().split("\n")
    assert len(lines) == 2
    assert lines[0].startswith("ROOTKIT_FOB_SSID=")
    assert lines[1].startswith("ROOTKIT_FOB_PASS=")
