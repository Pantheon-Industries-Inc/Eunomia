"""Discover .insv files in a drain directory that need normalization.

Scans for ``*.eunomia.json`` sidecars (same glob as ingest), resolves the footage path from
``files.back``, and checks whether a ``normalized/`` output already exists.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

SIDECAR_GLOB = "*.eunomia.json"
FOOTAGE_EXTENSIONS = frozenset({".insv", ".mp4"})


@dataclass(frozen=True)
class NormalizeCandidate:
    """A footage file that needs normalization."""

    episode_id: str
    footage_path: Path
    output_dir: Path
    output_stem: str


@dataclass
class DiscoverResult:
    candidates: list[NormalizeCandidate] = field(default_factory=list)
    already_normalized: list[Path] = field(default_factory=list)
    no_footage: list[Path] = field(default_factory=list)


def _output_stem(footage_path: Path) -> str:
    return footage_path.stem.replace("_00_", "_")


def _output_exists(output_dir: Path, stem: str) -> bool:
    return (output_dir / f"{stem}_workspace.mp4").exists()


def discover(root: Path, *, force: bool = False) -> DiscoverResult:
    """Walk a drain directory and find footage files needing normalization."""
    result = DiscoverResult()

    for sidecar_path in sorted(root.rglob(SIDECAR_GLOB)):
        try:
            raw = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Cannot parse sidecar %s: %s", sidecar_path, exc)
            continue

        if not isinstance(raw, dict):
            continue

        identity = raw.get("identity", {})
        episode_id = identity.get("episode_id", "")
        files = raw.get("files", {})
        back = files.get("back", "")

        if not back:
            result.no_footage.append(sidecar_path)
            continue

        footage_path = sidecar_path.parent / back
        if not footage_path.exists():
            result.no_footage.append(sidecar_path)
            continue

        if footage_path.suffix.lower() not in FOOTAGE_EXTENSIONS:
            continue

        output_dir = footage_path.parent / "normalized"
        stem = _output_stem(footage_path)

        if not force and _output_exists(output_dir, stem):
            result.already_normalized.append(footage_path)
            log.debug("Already normalized: %s", footage_path)
            continue

        result.candidates.append(
            NormalizeCandidate(
                episode_id=episode_id,
                footage_path=footage_path,
                output_dir=output_dir,
                output_stem=stem,
            )
        )

    return result
