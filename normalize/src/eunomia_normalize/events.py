"""Deterministic event_id minting + footage_normalized event construction."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

EUNOMIA_NS = uuid.UUID("e8a1c3d0-4f2b-4e6a-9c0f-1a2b3c4d5e6f")
EVENT_SCHEMA = "eunomia-operational-event/v1"


def mint_event_id(*parts: str) -> str:
    return str(uuid.uuid5(EUNOMIA_NS, ":".join(parts)))


def build_footage_normalized_event(
    episode_id: str,
    normalized_path: str,
    duration_s: float,
    resolution: str = "960x720",
    codec: str = "mp4v",
) -> dict:
    return {
        "schema": EVENT_SCHEMA,
        "event_id": mint_event_id("footage_normalized", episode_id),
        "event_type": "footage_normalized",
        "entity": "episode",
        "entity_id": episode_id,
        "as_of": datetime.now(UTC).isoformat(),
        "payload": {
            "normalized_path": normalized_path,
            "resolution": resolution,
            "codec": codec,
            "duration_s": round(duration_s, 2),
        },
    }
