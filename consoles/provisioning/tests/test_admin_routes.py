"""Smoke tests for admin catalog routes.

These test that routes respond correctly when the store is unavailable (the default — no
EUNOMIA_STORE_DSN set). The admin pages should render the "unavailable" template, not crash.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from eunomia_consoles_provisioning.app import app

client = TestClient(app)


def test_admin_index_redirects() -> None:
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/admin/hardware"


def test_admin_hardware_list_no_db() -> None:
    resp = client.get("/admin/hardware")
    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower()


def test_admin_hardware_new_returns_form() -> None:
    resp = client.get("/admin/hardware/new")
    assert resp.status_code == 200
    assert "New Hardware Type" in resp.text


def test_admin_hardware_create_no_db() -> None:
    resp = client.post(
        "/admin/hardware",
        data={
            "catalog_id": "test-cam",
            "display_name": "Test Camera",
            "category": "camera",
        },
    )
    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower()


def test_admin_hardware_create_bad_slug() -> None:
    resp = client.post(
        "/admin/hardware",
        data={
            "catalog_id": "BAD SLUG!",
            "display_name": "Test",
            "category": "camera",
        },
    )
    assert resp.status_code == 200
    assert "lowercase" in resp.text.lower()


def test_admin_firmware_list_no_db() -> None:
    resp = client.get("/admin/firmware")
    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower()


def test_admin_firmware_new_no_db() -> None:
    resp = client.get("/admin/firmware/new")
    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower()


def test_admin_setups_list_no_db() -> None:
    resp = client.get("/admin/setups")
    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower()


def test_admin_setups_new_no_db() -> None:
    resp = client.get("/admin/setups/new")
    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower()


def test_admin_setups_create_bad_slug() -> None:
    resp = client.post(
        "/admin/setups",
        data={
            "setup_id": "BAD!",
            "display_name": "Test",
            "components": "[]",
        },
    )
    assert resp.status_code == 200
    assert "lowercase" in resp.text.lower()


def test_admin_setups_create_bad_json() -> None:
    resp = client.post(
        "/admin/setups",
        data={
            "setup_id": "test-setup",
            "display_name": "Test",
            "components": "not json",
        },
    )
    assert resp.status_code == 200
    assert "valid JSON" in resp.text
