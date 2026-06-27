"""Tests for the FastAPI app — endpoint smoke tests."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from eunomia_consoles_provisioning.app import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_index_page() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Provisioning Console" in resp.text


def test_provision_page() -> None:
    resp = client.get("/provision")
    assert resp.status_code == 200
    assert "Provision Kit" in resp.text


def test_roster_page() -> None:
    resp = client.get("/roster")
    assert resp.status_code == 200
    assert "Operator Roster" in resp.text


def test_ship_gate_page() -> None:
    resp = client.get("/ship-gate")
    assert resp.status_code == 200
    assert "Ship Gate" in resp.text


def test_ship_gate_evaluate_pass() -> None:
    status = json.dumps(
        {
            "kit_id": "kit_001",
            "cams": 2,
            "sides": "aa:bb,cc:dd",
            "time_set": True,
            "ap_ssid": "AP",
        }
    )
    resp = client.post(
        "/api/ship-gate/evaluate",
        json={"status_json": status},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["passed"] is True
    assert data["summary"] == "SHIP"


def test_ship_gate_evaluate_fail() -> None:
    status = json.dumps({"kit_id": "", "cams": 0, "sides": ""})
    resp = client.post(
        "/api/ship-gate/evaluate",
        json={"status_json": status},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["passed"] is False
    assert "FAIL" in data["summary"]


def test_ship_gate_invalid_json() -> None:
    resp = client.post(
        "/api/ship-gate/evaluate",
        json={"status_json": "not json"},
    )
    assert resp.status_code == 400


def test_site_check_valid() -> None:
    resp = client.post(
        "/api/site-check",
        json={"fob_site_id": "site-01", "request_site_id": "site-01"},
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_site_check_mismatch() -> None:
    resp = client.post(
        "/api/site-check",
        json={"fob_site_id": "site-01", "request_site_id": "site-02"},
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
