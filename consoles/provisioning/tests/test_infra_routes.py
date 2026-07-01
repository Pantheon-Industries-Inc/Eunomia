"""Smoke tests for infrastructure health routes.

Tests both Hades mode (no EUNOMIA_INGEST_ROOT) and Styx mode (with mocked filesystem).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from eunomia_consoles_provisioning.app import app

client = TestClient(app)

SAMPLE_STATUS = {
    "generated_at": "2026-07-01T12:00:00+00:00",
    "styx_local": True,
    "slots": [
        {
            "slot_key": "left_a_1",
            "operator": "op01",
            "side": "left",
            "hardware_present": True,
            "latest_status": "copying",
            "instr_class": "wait",
            "live_label": "SD1",
            "instruction": "COPYING",
        },
        {
            "slot_key": "left_a_2",
            "operator": "op01",
            "side": "right",
            "hardware_present": True,
            "latest_status": "styx-verified",
            "instr_class": "ok",
            "live_label": "SD2",
            "instruction": "SAFE TO REMOVE",
        },
    ],
    "imports": [],
    "unmapped_devices": [],
}

SAMPLE_CAMERA_MAP = {
    "IAQEB001": {
        "serial": "IAQEB001",
        "alias": "cam-1-left",
        "operator": "op01",
        "side": "left",
        "active": True,
        "notes": "",
        "last_updated": "2026-07-01T12:00:00Z",
    },
}


# ---------------------------------------------------------------------------
# Hades mode (no EUNOMIA_INGEST_ROOT)
# ---------------------------------------------------------------------------


def test_infra_overview_renders() -> None:
    resp = client.get("/ops/infra")
    assert resp.status_code == 200
    assert "Infrastructure" in resp.text


def test_infra_overview_no_ingest() -> None:
    resp = client.get("/ops/infra")
    assert resp.status_code == 200
    assert "Styx-local" in resp.text


def test_infra_cards_no_ingest() -> None:
    resp = client.get("/ops/infra/cards")
    assert resp.status_code == 200
    assert "Styx-local" in resp.text or "not running on Styx" in resp.text


def test_infra_cameras_no_ingest() -> None:
    resp = client.get("/ops/infra/cameras")
    assert resp.status_code == 200
    assert "requires Styx access" in resp.text


def test_infra_partial_sync_status() -> None:
    resp = client.get("/ops/infra/partials/sync-status")
    assert resp.status_code == 200


def test_infra_partial_system_health() -> None:
    resp = client.get("/ops/infra/partials/system-health")
    assert resp.status_code == 200
    assert "System Health" in resp.text


def test_infra_partial_card_summary_no_ingest() -> None:
    resp = client.get("/ops/infra/partials/card-summary")
    assert resp.status_code == 200
    assert "Styx-local" in resp.text


# ---------------------------------------------------------------------------
# Styx mode (with EUNOMIA_INGEST_ROOT)
# ---------------------------------------------------------------------------


def _setup_ingest_root(tmp_path: Path) -> Path:
    status_dir = tmp_path / "storage-health"
    status_dir.mkdir(parents=True)
    (status_dir / "sd-card-styx-status.json").write_text(json.dumps(SAMPLE_STATUS))

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "camera_map.json").write_text(json.dumps(SAMPLE_CAMERA_MAP))

    return tmp_path


def test_infra_cards_with_ingest(tmp_path: Path) -> None:
    root = _setup_ingest_root(tmp_path)
    with patch.dict("os.environ", {"EUNOMIA_INGEST_ROOT": str(root)}):
        resp = client.get("/ops/infra/cards")
    assert resp.status_code == 200
    assert "left_a_1" in resp.text
    assert "COPYING" in resp.text


def test_infra_cameras_renders(tmp_path: Path) -> None:
    root = _setup_ingest_root(tmp_path)
    with patch.dict("os.environ", {"EUNOMIA_INGEST_ROOT": str(root)}):
        resp = client.get("/ops/infra/cameras")
    assert resp.status_code == 200
    assert "IAQEB001" in resp.text
    assert "cam-1-left" in resp.text


def test_infra_cameras_add(tmp_path: Path) -> None:
    root = _setup_ingest_root(tmp_path)
    with patch.dict("os.environ", {"EUNOMIA_INGEST_ROOT": str(root)}):
        resp = client.post(
            "/ops/infra/cameras/add",
            data={
                "serial": "IAQEB999",
                "alias": "cam-new",
                "operator": "op02",
                "side": "right",
                "notes": "test",
            },
        )
    assert resp.status_code == 200
    assert "IAQEB999" in resp.text

    saved = json.loads((root / "config" / "camera_map.json").read_text())
    assert "IAQEB999" in saved


def test_infra_cameras_save(tmp_path: Path) -> None:
    root = _setup_ingest_root(tmp_path)
    updated_map = dict(SAMPLE_CAMERA_MAP)
    updated_map["IAQEB001"]["alias"] = "cam-renamed"

    with patch.dict("os.environ", {"EUNOMIA_INGEST_ROOT": str(root)}):
        resp = client.post(
            "/ops/infra/cameras/save",
            data={"camera_map_json": json.dumps(updated_map)},
        )
    assert resp.status_code == 200

    saved = json.loads((root / "config" / "camera_map.json").read_text())
    assert saved["IAQEB001"]["alias"] == "cam-renamed"


def test_infra_cameras_save_no_ingest() -> None:
    resp = client.post(
        "/ops/infra/cameras/save",
        data={"camera_map_json": "{}"},
    )
    assert resp.status_code == 400
    assert "requires Styx access" in resp.text


def test_infra_overview_subnav() -> None:
    resp = client.get("/ops/infra")
    assert resp.status_code == 200
    assert 'href="/ops/infra"' in resp.text
    assert "Infra" in resp.text


def test_overview_has_infra_card() -> None:
    resp = client.get("/ops/")
    assert resp.status_code == 200
    assert "Infrastructure" in resp.text or "infra" in resp.text.lower()
