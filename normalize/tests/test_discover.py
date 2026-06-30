"""Tests for the drain discovery module."""

from __future__ import annotations

import json
from pathlib import Path

from eunomia_normalize.discover import discover


def _write_sidecar(
    path: Path, *, episode_id: str = "ep-001", back: str = "VID_00_043.insv"
) -> None:
    data = {
        "schema": "eunomia-sidecar/v1",
        "identity": {"episode_id": episode_id},
        "files": {"back": back},
    }
    path.write_text(json.dumps(data))


class TestDiscover:
    def test_finds_candidate(self, tmp_path: Path) -> None:
        sidecar = tmp_path / "ep.eunomia.json"
        footage = tmp_path / "VID_00_043.insv"
        footage.write_bytes(b"\x00" * 100)
        _write_sidecar(sidecar, back=footage.name)

        result = discover(tmp_path)

        assert len(result.candidates) == 1
        assert result.candidates[0].episode_id == "ep-001"
        assert result.candidates[0].footage_path == footage
        assert not result.already_normalized
        assert not result.no_footage

    def test_skips_already_normalized(self, tmp_path: Path) -> None:
        sidecar = tmp_path / "ep.eunomia.json"
        footage = tmp_path / "VID_00_043.insv"
        footage.write_bytes(b"\x00" * 100)
        _write_sidecar(sidecar, back=footage.name)

        norm_dir = tmp_path / "normalized"
        norm_dir.mkdir()
        (norm_dir / "VID_043_workspace.mp4").write_bytes(b"\x00")

        result = discover(tmp_path)

        assert not result.candidates
        assert len(result.already_normalized) == 1

    def test_force_overrides_skip(self, tmp_path: Path) -> None:
        sidecar = tmp_path / "ep.eunomia.json"
        footage = tmp_path / "VID_00_043.insv"
        footage.write_bytes(b"\x00" * 100)
        _write_sidecar(sidecar, back=footage.name)

        norm_dir = tmp_path / "normalized"
        norm_dir.mkdir()
        (norm_dir / "VID_043_workspace.mp4").write_bytes(b"\x00")

        result = discover(tmp_path, force=True)

        assert len(result.candidates) == 1
        assert not result.already_normalized

    def test_no_footage_file(self, tmp_path: Path) -> None:
        sidecar = tmp_path / "ep.eunomia.json"
        _write_sidecar(sidecar, back="missing.insv")

        result = discover(tmp_path)

        assert not result.candidates
        assert len(result.no_footage) == 1

    def test_no_back_field(self, tmp_path: Path) -> None:
        sidecar = tmp_path / "ep.eunomia.json"
        data = {
            "schema": "eunomia-sidecar/v1",
            "identity": {"episode_id": "ep-002"},
            "files": {},
        }
        sidecar.write_text(json.dumps(data))

        result = discover(tmp_path)

        assert not result.candidates
        assert len(result.no_footage) == 1

    def test_recursive_discovery(self, tmp_path: Path) -> None:
        sub = tmp_path / "kit-01" / "DCIM" / "100INSP"
        sub.mkdir(parents=True)
        sidecar = sub / "ep.eunomia.json"
        footage = sub / "VID_00_001.insv"
        footage.write_bytes(b"\x00" * 100)
        _write_sidecar(sidecar, episode_id="ep-deep", back=footage.name)

        result = discover(tmp_path)

        assert len(result.candidates) == 1
        assert result.candidates[0].episode_id == "ep-deep"

    def test_ignores_non_footage_extensions(self, tmp_path: Path) -> None:
        sidecar = tmp_path / "ep.eunomia.json"
        txt = tmp_path / "notes.txt"
        txt.write_text("hello")
        _write_sidecar(sidecar, back="notes.txt")

        result = discover(tmp_path)

        assert not result.candidates
