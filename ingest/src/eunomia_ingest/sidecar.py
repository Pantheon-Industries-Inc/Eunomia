"""Camera sidecar JSON parser + contract validator.

Parses ``*.eunomia.json`` sidecar files from a drain output directory, validates them against the
``eunomia-sidecar/v1`` contract, and resolves footage paths.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eunomia_contracts import sidecar as sidecar_contract

SIDECAR_GLOB = "*.eunomia.json"
FOOTAGE_EXTENSIONS = frozenset({".insv", ".mp4"})


@dataclass(frozen=True)
class SidecarRecord:
    episode_id: str
    global_episode_seq: int
    seq: int
    kit_id: str
    side: str
    camera_id: str
    operator_id: str
    station_id: str
    task_id: str
    task_name: str
    session_id: str
    rotation_id: str
    prompt: str
    task_source: str
    episode_ordinal: int | None
    bimanual_episode_id: str | None
    display_id: str | None
    started_unix: float | None
    stopped_unix: float | None
    stop_reason: str | None
    archive: int
    recording_suspect: int
    camera_firmware: str | None
    fob_id: str | None
    fob_build: str | None
    kit_version: str | None
    site_id: str | None
    modality: str | None
    setup_version_id: str | None
    raw: dict[str, Any]
    sidecar_path: Path
    footage_path: Path | None
    footage_exists: bool
    warnings: list[str]


@dataclass
class DrainScanResult:
    records: list[SidecarRecord] = field(default_factory=list)
    skipped: list[tuple[Path, list[str]]] = field(default_factory=list)
    footage_orphans: list[Path] = field(default_factory=list)


def _opt_str(val: Any) -> str | None:
    if not val:
        return None
    return str(val)


def _opt_num(val: Any) -> float | None:
    if val is None or val == 0 or val == 0.0:
        return None
    return float(val)


def _opt_int(val: Any) -> int | None:
    if val is None or val == 0:
        return None
    return int(val)


def parse_sidecar(path: Path) -> tuple[SidecarRecord | None, list[str]]:
    """Parse a sidecar JSON file and validate against the contract.

    Returns ``(record, hard_errors)``. When ``hard_errors`` is non-empty, ``record`` is ``None``.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, [f"JSON parse error: {exc}"]

    if not isinstance(raw, dict):
        return None, ["sidecar is not a JSON object"]

    hard_errors, warnings = sidecar_contract.validate_full(raw)
    if hard_errors:
        return None, hard_errors

    identity = raw.get("identity", {})
    timing = raw.get("timing", {})
    provenance = raw.get("provenance", {})
    outcome = raw.get("outcome", {})
    files = raw.get("files", {})

    back = files.get("back", "")
    footage_path = path.parent / back if back else None
    footage_exists = footage_path is not None and footage_path.exists()

    record = SidecarRecord(
        episode_id=identity.get("episode_id", ""),
        global_episode_seq=raw.get("global_episode_seq", 0),
        seq=raw.get("seq", 0),
        kit_id=identity.get("kit_id", ""),
        side=identity.get("side", ""),
        camera_id=identity.get("camera_id", ""),
        operator_id=identity.get("operator_id", ""),
        station_id=identity.get("station_id", ""),
        task_id=identity.get("task_id", ""),
        task_name=identity.get("task_name", ""),
        session_id=identity.get("session_id", ""),
        rotation_id=identity.get("rotation_id", ""),
        prompt=identity.get("prompt", ""),
        task_source=identity.get("task_source", ""),
        episode_ordinal=_opt_int(identity.get("episode_ordinal")),
        bimanual_episode_id=_opt_str(identity.get("bimanual_episode_id")),
        display_id=_opt_str(identity.get("display_id")),
        started_unix=_opt_num(timing.get("started_unix")),
        stopped_unix=_opt_num(timing.get("stopped_unix")),
        stop_reason=_opt_str(outcome.get("stop_reason")),
        archive=outcome.get("archive", 0),
        recording_suspect=outcome.get("recording_suspect", 0),
        camera_firmware=_opt_str(provenance.get("camera_firmware")),
        fob_id=_opt_str(provenance.get("fob_id")),
        fob_build=_opt_str(provenance.get("fob_build")),
        kit_version=_opt_str(provenance.get("kit_version")),
        site_id=_opt_str(provenance.get("site_id")),
        modality=_opt_str(provenance.get("modality")),
        setup_version_id=identity.get("setup_version_id"),
        raw=raw,
        sidecar_path=path,
        footage_path=footage_path,
        footage_exists=footage_exists,
        warnings=warnings,
    )
    return record, []


def scan_drain(root: Path) -> DrainScanResult:
    """Walk a drain output directory, discover sidecars, parse them, find footage orphans."""
    result = DrainScanResult()
    sidecar_dirs: set[Path] = set()
    sidecar_footage_files: set[Path] = set()

    for sidecar_path in sorted(root.rglob(SIDECAR_GLOB)):
        record, hard_errors = parse_sidecar(sidecar_path)
        if record is None:
            result.skipped.append((sidecar_path, hard_errors))
            print(
                f"SKIP {sidecar_path}: {'; '.join(hard_errors)}",
                file=sys.stderr,
            )
            continue

        result.records.append(record)
        sidecar_dirs.add(sidecar_path.parent)
        if record.footage_path is not None:
            sidecar_footage_files.add(record.footage_path.resolve())

        if not record.footage_exists:
            print(
                f"WARN sidecar without footage: {sidecar_path} (expected {record.footage_path})",
                file=sys.stderr,
            )

    for directory in sorted(sidecar_dirs):
        for f in sorted(directory.iterdir()):
            if (
                f.suffix.lower() in FOOTAGE_EXTENSIONS
                and f.resolve() not in sidecar_footage_files
            ):
                result.footage_orphans.append(f)
                print(f"WARN footage without sidecar: {f}", file=sys.stderr)

    return result
