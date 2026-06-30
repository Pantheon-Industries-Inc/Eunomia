"""Tests for the normalize CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_sidecar(
    path: Path, *, episode_id: str = "ep-001", back: str = "VID_00_043.insv"
) -> None:
    data = {
        "schema": "eunomia-sidecar/v1",
        "identity": {"episode_id": episode_id},
        "files": {"back": back},
    }
    path.write_text(json.dumps(data))


class TestCLIDryRun:
    def test_dry_run_no_writes(self, tmp_path: Path) -> None:
        sidecar = tmp_path / "ep.eunomia.json"
        footage = tmp_path / "VID_00_043.insv"
        footage.write_bytes(b"\x00" * 100)
        _write_sidecar(sidecar, back=footage.name)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "eunomia_normalize",
                "run",
                str(tmp_path),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        assert "dry run" in result.stdout
        assert "would convert" in result.stdout
        assert not (tmp_path / "normalized").exists()

    def test_invalid_path(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "eunomia_normalize", "run", "/nonexistent/path"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 2
        assert "not a directory" in result.stderr
