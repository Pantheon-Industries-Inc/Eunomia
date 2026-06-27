"""Tests for the config-pull endpoints (P2)."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from eunomia_consoles_provisioning.app import app
from eunomia_consoles_provisioning.config_pull import _get_conn


@pytest.fixture(autouse=True)
def _override_conn() -> Iterator[None]:
    app.dependency_overrides[_get_conn] = lambda: MagicMock()
    yield
    app.dependency_overrides.pop(_get_conn, None)


client = TestClient(app)

_SAMPLE_CONFIG = {
    "site_id": "sf",
    "tz": "PST8PDT,M3.2.0,M11.1.0",
    "assignments": [
        {
            "station_id": "1003",
            "task_id": "pour_water",
            "task_name": "Pour Water",
            "prompt": "Pour water from the bottle to fill three cups halfway.",
            "rotation_id": "A",
            "task_version": 1,
        }
    ],
    "roster": ["101", "102", "103"],
    "fetched_at": "2026-06-27T15:30:00Z",
}


@patch("eunomia_consoles_provisioning.config_pull.build_task_config")
def test_task_config_known_kit(mock_build: MagicMock) -> None:
    mock_build.return_value = _SAMPLE_CONFIG
    resp = client.get("/api/task-config/kit_001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["site_id"] == "sf"
    assert data["tz"] == "PST8PDT,M3.2.0,M11.1.0"
    assert len(data["assignments"]) == 1
    a = data["assignments"][0]
    assert a["station_id"] == "1003"
    assert a["task_id"] == "pour_water"
    assert a["task_name"] == "Pour Water"
    assert a["rotation_id"] == "A"
    assert a["task_version"] == 1
    assert data["roster"] == ["101", "102", "103"]
    assert "fetched_at" in data


@patch("eunomia_consoles_provisioning.config_pull.build_task_config")
def test_task_config_unknown_kit(mock_build: MagicMock) -> None:
    mock_build.return_value = None
    resp = client.get("/api/task-config/unknown_kit")
    assert resp.status_code == 404


@patch("eunomia_consoles_provisioning.config_pull.build_task_config")
def test_task_config_no_assignments(mock_build: MagicMock) -> None:
    mock_build.return_value = {
        "site_id": "sf",
        "tz": "PST8PDT,M3.2.0,M11.1.0",
        "assignments": [],
        "roster": ["101"],
        "fetched_at": "2026-06-27T15:30:00Z",
    }
    resp = client.get("/api/task-config/kit_001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assignments"] == []
    assert data["site_id"] == "sf"


@patch("eunomia_consoles_provisioning.config_pull.lookup_station")
def test_station_lookup(mock_lookup: MagicMock) -> None:
    mock_lookup.return_value = {
        "id": "1003",
        "label": "Table 1003",
        "task_name": "Pour Water",
        "prompt": "Pour water from the bottle to fill three cups halfway.",
        "tz": "PST8PDT,M3.2.0,M11.1.0",
    }
    resp = client.get("/api/station/1003")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "1003"
    assert data["label"] == "Table 1003"
    assert data["task_name"] == "Pour Water"
    assert "prompt" in data
    assert data["tz"] == "PST8PDT,M3.2.0,M11.1.0"


@patch("eunomia_consoles_provisioning.config_pull.lookup_station")
def test_station_not_found(mock_lookup: MagicMock) -> None:
    mock_lookup.return_value = None
    resp = client.get("/api/station/9999")
    assert resp.status_code == 404
