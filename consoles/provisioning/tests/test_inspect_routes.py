"""Smoke tests for store inspector routes.

Tests that routes respond correctly when the store is unavailable (no EUNOMIA_STORE_DSN set).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from eunomia_consoles_provisioning.app import app

client = TestClient(app)


def test_inspect_episodes_no_db() -> None:
    resp = client.get("/ops/inspect/episodes")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_inspect_episode_detail_no_db() -> None:
    resp = client.get("/ops/inspect/episodes/ep_nonexistent")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_inspect_events_no_db() -> None:
    resp = client.get("/ops/inspect/events")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_inspect_sessions_no_db() -> None:
    resp = client.get("/ops/inspect/sessions")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_inspect_tasks_no_db() -> None:
    resp = client.get("/ops/inspect/tasks")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_inspect_nav_links() -> None:
    resp = client.get("/ops/")
    assert resp.status_code == 200
    assert 'href="/ops/inspect/episodes"' in resp.text
    assert "Inspect" in resp.text


def test_import_page_loads() -> None:
    resp = client.get("/ops/import")
    assert resp.status_code == 200
    assert "Import" in resp.text
    assert "Scan Drain" in resp.text
    assert "Fob Log" in resp.text
    assert "Run QC" in resp.text


def test_import_nav_link() -> None:
    resp = client.get("/ops/")
    assert resp.status_code == 200
    assert 'href="/ops/import"' in resp.text
