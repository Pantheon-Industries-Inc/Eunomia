"""Smoke tests for import/QC routes.

Tests the import page loads and API endpoints handle missing store / mock the underlying functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from eunomia_consoles_provisioning.app import app

client = TestClient(app)


def test_import_page_loads() -> None:
    resp = client.get("/ops/import")
    assert resp.status_code == 200
    assert "Scan Drain" in resp.text
    assert "Import" in resp.text
    assert "Run QC" in resp.text


def test_scan_drain_no_path() -> None:
    resp = client.post("/ops/import/scan-drain", data={"path": "/nonexistent/path"})
    assert resp.status_code == 200
    assert "does not exist" in resp.text


def test_fob_log_no_file() -> None:
    resp = client.post("/ops/import/fob-log", data={"path": "/nonexistent/file.jsonl"})
    assert resp.status_code == 200
    assert "does not exist" in resp.text


def test_qc_no_api_key() -> None:
    with patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("OPENROUTER_API_KEY", None)
        resp = client.post("/ops/import/qc-run", data={"date": "2025-01-01"})
        assert resp.status_code == 200
        assert "OPENROUTER_API_KEY" in resp.text


@dataclass
class _MockIngestReport:
    sidecars_processed: int = 3
    sidecars_skipped: int = 0
    episodes_created: int = 3
    episodes_enriched: int = 0
    events_appended: int = 2
    sessions_created: int = 1
    footage_refs_created: int = 3
    footage_orphans: int = 0
    sidecar_orphans: int = 0
    fob_log_lines: int = 0
    fob_log_skipped: int = 0
    fob_log_errors: int = 0
    anomalies: list = field(default_factory=list)


def test_scan_drain_with_mock(tmp_path: Path) -> None:
    drain_dir = tmp_path / "drain"
    drain_dir.mkdir()

    mock_report = _MockIngestReport()

    with (
        patch("eunomia_consoles_provisioning.ops.import_router.get_conn") as mock_conn,
        patch("eunomia_ingest.ingest.ingest_drain", return_value=mock_report),
    ):
        mock_conn.return_value = _FakeConn()
        resp = client.post("/ops/import/scan-drain", data={"path": str(drain_dir)})

    assert resp.status_code == 200
    assert "Ingest Report" in resp.text
    assert "3" in resp.text


def test_fob_log_with_mock(tmp_path: Path) -> None:
    log_file = tmp_path / "fob.jsonl"
    log_file.write_text("{}\n")

    mock_report = _MockIngestReport(
        fob_log_lines=10, events_appended=5, sessions_created=2
    )

    with (
        patch("eunomia_consoles_provisioning.ops.import_router.get_conn") as mock_conn,
        patch("eunomia_ingest.ingest.ingest_fob_log", return_value=mock_report),
    ):
        mock_conn.return_value = _FakeConn()
        resp = client.post("/ops/import/fob-log", data={"path": str(log_file)})

    assert resp.status_code == 200
    assert "Fob Log Import Report" in resp.text


class _FakeConn:
    """Minimal mock for a SQLAlchemy Connection."""

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass
