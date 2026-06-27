"""Provisioning orchestration — ties camera protocol + store writes.

Provision one camera end-to-end: discover → allocate camera_id → write BOTH NAND files → readback
verify → register in store → emit event. Non-destructive throughout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import Connection

from eunomia_consoles_provisioning.camera import (
    CAMERA_ENV_PATH,
    FOB_ENV_PATH,
    CameraFacts,
    build_camera_env,
    build_fob_env,
    read_file,
    write_file,
)
from eunomia_edge_store import store
from eunomia_edge_store.allocator import allocate_camera_id
from eunomia_edge_store.resolvers import find_dangling_references

FOB_AP_PSK = "pantheon"


@dataclass
class ProvisionResult:
    success: bool
    camera_id: str = ""
    unit_id: str = ""
    errors: list[str] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id() -> str:
    return f"evt-{uuid4().hex[:12]}"


def provision_camera(
    conn: Connection,
    *,
    facts: CameraFacts,
    kit_id: str,
    side: str,
    mount: str = "wrist",
    calibration_id: str = "",
    firmware_version: str = "",
    hardware_version: str = "",
    fob_ssid: str = "",
    fob_psk: str = "",
    run_id: str = "",
) -> ProvisionResult:
    """Provision one camera end-to-end (store + NAND)."""
    errors: list[str] = []
    if not fob_psk:
        fob_psk = FOB_AP_PSK
    if not fob_ssid:
        fob_ssid = f"PANTHEON-{kit_id.upper().replace('_', '-')}"

    camera_id = allocate_camera_id(
        conn, body_serial=facts.body_serial, allocated_by="provisioning-console"
    )

    camera_env = build_camera_env(
        camera_id=camera_id,
        kit_id=kit_id,
        side=side,
        mount=mount,
        calibration_id=calibration_id,
    )
    if not write_file(facts.ip, CAMERA_ENV_PATH, camera_env):
        errors.append(f"Failed to write {CAMERA_ENV_PATH}")
        return ProvisionResult(success=False, camera_id=camera_id, errors=errors)

    fob_env = build_fob_env(ssid=fob_ssid, psk=fob_psk)
    if not write_file(facts.ip, FOB_ENV_PATH, fob_env):
        errors.append(f"Failed to write {FOB_ENV_PATH}")
        return ProvisionResult(success=False, camera_id=camera_id, errors=errors)

    readback_cam = read_file(facts.ip, CAMERA_ENV_PATH)
    if readback_cam.strip() != camera_env.strip():
        errors.append(
            f"Readback mismatch on {CAMERA_ENV_PATH}: "
            f"expected {len(camera_env)} bytes, got {len(readback_cam)}"
        )
        return ProvisionResult(success=False, camera_id=camera_id, errors=errors)

    readback_fob = read_file(facts.ip, FOB_ENV_PATH)
    if readback_fob.strip() != fob_env.strip():
        errors.append(
            f"Readback mismatch on {FOB_ENV_PATH}: "
            f"expected {len(fob_env)} bytes, got {len(readback_fob)}"
        )
        return ProvisionResult(success=False, camera_id=camera_id, errors=errors)

    unit_id = f"unit-{facts.body_serial}"
    now = _now_iso()

    unit_record: dict[str, Any] = {
        "schema": "eunomia-hardware-unit/v1",
        "unit_id": unit_id,
        "type": "camera",
        "body_serial": facts.body_serial,
        "insv_serial": facts.insv_serial or None,
        "mac": facts.mac or None,
        "camera_id": camera_id,
        "kit_id": kit_id,
        "side": side,
        "status": "provisioned",
        "hardware_version": hardware_version or None,
        "mount": mount,
        "provisioning": {
            "wifi_ssid": facts.ap_ssid or fob_ssid,
            "wifi_ap": fob_ssid,
            "ip_scheme": facts.ip,
            "firmware_version": firmware_version,
        },
    }
    store.upsert(conn, "hardware_unit", unit_record)

    store.append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": _event_id(),
            "event_type": "unit_provisioned",
            "entity": "hardware_unit",
            "entity_id": unit_id,
            "as_of": now,
            "payload": {
                "camera_id": camera_id,
                "body_serial": facts.body_serial,
                "kit_id": kit_id,
                "side": side,
            },
        },
    )

    store.append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": _event_id(),
            "event_type": "camera_id_allocated",
            "entity": "hardware_unit",
            "entity_id": unit_id,
            "as_of": now,
            "payload": {"camera_id": camera_id, "body_serial": facts.body_serial},
        },
    )

    dangling = find_dangling_references(conn, "hardware_unit", unit_record)
    if dangling:
        for d in dangling:
            errors.append(f"Dangling reference: {d.target} {d.key}")

    return ProvisionResult(
        success=len(errors) == 0,
        camera_id=camera_id,
        unit_id=unit_id,
        errors=errors,
    )


def register_kit(
    conn: Connection,
    *,
    kit_id: str,
    left_unit_id: str | None = None,
    right_unit_id: str | None = None,
    fob_unit_id: str | None = None,
) -> None:
    """Create or update a kit record."""
    now = _now_iso()
    existing = store.get(conn, "kit", kit_id=kit_id)
    record: dict[str, Any] = {
        "schema": "eunomia-kit/v1",
        "kit_id": kit_id,
        "left_cam_unit_id": left_unit_id,
        "right_cam_unit_id": right_unit_id,
        "fob_unit_id": fob_unit_id,
        "effective_from": now,
    }
    if existing:
        if left_unit_id is None:
            record["left_cam_unit_id"] = existing.get("left_cam_unit_id")
        if right_unit_id is None:
            record["right_cam_unit_id"] = existing.get("right_cam_unit_id")
        if fob_unit_id is None:
            record["fob_unit_id"] = existing.get("fob_unit_id")
        record["effective_from"] = existing.get("effective_from", now)
    store.upsert(conn, "kit", record)


def register_fob(
    conn: Connection,
    *,
    fob_hw_id: str,
    kit_id: str,
    site_id: str,
    board: str = "esp32-cyd",
) -> str:
    """Register a fob as a hardware_unit and link it to the kit."""
    unit_id = f"unit-fob-{fob_hw_id}"
    now = _now_iso()

    store.upsert(
        conn,
        "hardware_unit",
        {
            "schema": "eunomia-hardware-unit/v1",
            "unit_id": unit_id,
            "type": "fob",
            "fob_id": fob_hw_id,
            "kit_id": kit_id,
            "board": board,
            "side": "left",
            "status": "provisioned",
        },
    )

    store.append_event(
        conn,
        {
            "schema": "eunomia-operational-event/v1",
            "event_id": _event_id(),
            "event_type": "unit_provisioned",
            "entity": "hardware_unit",
            "entity_id": unit_id,
            "as_of": now,
            "payload": {"fob_id": fob_hw_id, "kit_id": kit_id, "site_id": site_id},
        },
    )

    register_kit(conn, kit_id=kit_id, fob_unit_id=unit_id)
    return unit_id


def kit_cameras_complete(conn: Connection, kit_id: str) -> bool:
    """Check whether a kit has both cameras provisioned."""
    kit = store.get(conn, "kit", kit_id=kit_id)
    if kit is None:
        return False
    return bool(kit.get("left_cam_unit_id")) and bool(kit.get("right_cam_unit_id"))


def attach_calibration(
    conn: Connection,
    *,
    calibration_id: str,
    scope: str = "fleet",
    camera_serial: str | None = None,
) -> None:
    """Register a calibration record (attach existing calibration_id)."""
    now = _now_iso()
    store.upsert(
        conn,
        "calibration",
        {
            "schema": "eunomia-calibration/v1",
            "calibration_id": calibration_id,
            "scope": scope,
            "camera_serial": camera_serial,
            "effective_from": now,
        },
    )
