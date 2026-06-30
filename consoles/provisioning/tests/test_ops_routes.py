"""Smoke tests for ops dashboard routes.

These test that routes respond correctly when the store is unavailable (the default — no
EUNOMIA_STORE_DSN set). The ops pages should render the "unavailable" template, not crash.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from eunomia_consoles_provisioning.app import app

client = TestClient(app)


def test_ops_overview_no_db() -> None:
    resp = client.get("/ops/")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_ops_operators_no_db() -> None:
    resp = client.get("/ops/operators")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_ops_kits_no_db() -> None:
    resp = client.get("/ops/kits")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_ops_tasks_no_db() -> None:
    resp = client.get("/ops/tasks")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_ops_anomalies_no_db() -> None:
    resp = client.get("/ops/anomalies")
    assert resp.status_code == 200
    assert "Store unavailable" in resp.text


def test_ops_partial_stats_no_db() -> None:
    resp = client.get("/ops/partials/overview-stats")
    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower()


def test_ops_partial_episodes_no_db() -> None:
    resp = client.get("/ops/partials/recent-episodes")
    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower()


def test_ops_partial_anomaly_count_no_db() -> None:
    resp = client.get("/ops/partials/anomaly-count")
    assert resp.status_code == 200


def test_existing_routes_still_work() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_nav_includes_ops_link() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'href="/ops/"' in resp.text
    assert "Ops" in resp.text
