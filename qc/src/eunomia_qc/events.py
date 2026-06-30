"""Deterministic event_id minting + QA verdict event construction."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from eunomia_qc.rubric import EpisodeQCResult

EUNOMIA_NS = uuid.UUID("e8a1c3d0-4f2b-4e6a-9c0f-1a2b3c4d5e6f")
EVENT_SCHEMA = "eunomia-operational-event/v1"
QC_VERSION = "qc1.0"


def mint_event_id(*parts: str) -> str:
    return str(uuid.uuid5(EUNOMIA_NS, ":".join(parts)))


def build_qa_verdict_event(result: EpisodeQCResult) -> dict:
    return {
        "schema": EVENT_SCHEMA,
        "event_id": mint_event_id("qa_verdict", result.episode_id, result.qc_version),
        "event_type": "qa_verdict",
        "entity": "episode",
        "entity_id": result.episode_id,
        "as_of": datetime.now(UTC).isoformat(),
        "reason": result.verdict_reason,
        "payload": {
            "verdict": result.verdict,
            "score": result.score,
            "qc_version": result.qc_version,
            "vlm_model": result.vlm_model,
            "checks": [
                {
                    "id": c.id,
                    "group": c.group,
                    "name": c.name,
                    "status": c.status,
                    "when": [list(w) for w in c.when],
                    "how": c.how,
                    "why": c.why,
                    "confidence": c.confidence,
                    "non_negotiable": c.non_negotiable,
                }
                for c in result.checks
            ],
        },
    }
