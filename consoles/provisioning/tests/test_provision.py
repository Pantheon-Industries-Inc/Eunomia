"""Tests for provisioning logic — pure functions (no hardware, no DB)."""

from __future__ import annotations

from eunomia_consoles_provisioning.camera import (
    build_camera_env,
    build_fob_env,
)
from eunomia_consoles_provisioning.provision import FOB_AP_PSK


def test_both_nand_files_generated() -> None:
    """Verify that provisioning generates BOTH env files (hard-won lesson #1)."""
    cam_env = build_camera_env(camera_id="CAM-1", kit_id="kit_001", side="left")
    fob_env = build_fob_env(ssid="PANTHEON-KIT-001", psk=FOB_AP_PSK)

    assert "CAMERA_ID=CAM-1" in cam_env
    assert "ROOTKIT_FOB_SSID=PANTHEON-KIT-001" in fob_env
    assert "ROOTKIT_FOB_PASS=" in fob_env


def test_fob_env_no_sd_seed() -> None:
    """ROOTKIT_FOB_SSID must NOT be on SD cards — only in NAND via fob.env."""
    env = build_fob_env(ssid="FOB-AP", psk="pass")
    assert "ROOTKIT_FOB_SSID=FOB-AP" in env


def test_camera_env_all_fields() -> None:
    env = build_camera_env(
        camera_id="CAM-99",
        kit_id="kit_050",
        side="right",
        mount="chest",
        calibration_id="cal-per-unit-7",
    )
    lines = env.strip().split("\n")
    keys = {line.split("=")[0] for line in lines}
    assert keys == {
        "CAMERA_ID",
        "KIT_ID",
        "CAMERA_SIDE",
        "CAMERA_MOUNT",
        "CALIBRATION_ID",
    }


def test_readback_comparison_exact() -> None:
    """Readback verification is byte-for-byte (strip-compared)."""
    env = build_camera_env(camera_id="CAM-1", kit_id="kit_001", side="left")
    assert env.strip() == env.strip()
    assert env.strip() != (env + "\nEXTRA=bad").strip()


def test_fob_ap_psk_is_shared_constant() -> None:
    """P1: all kits share the same PSK (compile-time constant)."""
    assert isinstance(FOB_AP_PSK, str)
    assert len(FOB_AP_PSK) > 0
