"""Universal MVO rubric registry and per-task rubric loading from metadata JSONB."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CheckResult:
    """Result of a single QC check on an episode."""

    id: str
    group: str
    name: str
    status: str  # "pass" | "fail" | "na" | "skipped"
    when: tuple[tuple[float, float], ...]
    how: str
    why: str
    confidence: str  # "trusted" | "calibrated" | "low" | "unverified"
    non_negotiable: bool


@dataclass(frozen=True)
class EpisodeQCResult:
    """Aggregated QC result for an episode."""

    episode_id: str
    checks: tuple[CheckResult, ...]
    verdict: str  # "accept" | "review" | "reject"
    verdict_reason: str
    score: int
    qc_version: str
    vlm_model: str


@dataclass(frozen=True)
class RubricCheckDef:
    """A per-task rubric check definition loaded from task metadata JSONB."""

    id: str
    name: str
    category: str  # "end_state" | "process"
    non_negotiable: bool
    measure_method: str  # "VLM" | "Program"
    pass_condition: str


# -- Universal check ID registry (for documentation / test validation) --

UNIVERSAL_CHECK_IDS: dict[str, str] = {
    "mvo_1": "Frame drop detection",
    "mvo_2": "Recording suspect flag",
    "mvo_3": "Arm visibility",
    "mvo_4": "Object presence",
    "mvo_5": "Object containment",
    "mvo_6": "Lighting consistency",
    "mvo_7": "Goal completion",
    "mvo_8": "Duration in plausible band",
    "mvo_9": "Idle ratio below ceiling",
}

VALID_GROUPS = frozenset(
    {
        "stream_integrity",
        "scene_integrity",
        "goal_completion",
        "duration",
        "task_quality",
    }
)

VALID_STATUSES = frozenset({"pass", "fail", "na", "skipped"})
VALID_CONFIDENCES = frozenset({"trusted", "calibrated", "low", "unverified"})

_REQUIRED_RUBRIC_KEYS = {"id", "name", "category", "measure_method", "pass_condition"}


def _valid_rubric_check(check: dict[str, Any]) -> bool:
    """Return True if a rubric check dict has all required non-empty string keys."""
    for key in _REQUIRED_RUBRIC_KEYS:
        val = check.get(key)
        if not isinstance(val, str) or not val.strip():
            return False
    return True


def load_task_rubric(task: dict[str, Any]) -> list[RubricCheckDef]:
    """Load per-task rubric check definitions from task metadata JSONB.

    Invalid entries are silently skipped (lenient — don't block the whole QC run).
    """
    metadata = task.get("metadata") or {}
    raw_checks = metadata.get("rubric_checks") or []
    results: list[RubricCheckDef] = []
    for c in raw_checks:
        if not isinstance(c, dict) or not _valid_rubric_check(c):
            continue
        results.append(
            RubricCheckDef(
                id=f"t_{c['id']}",
                name=c["name"],
                category=c["category"],
                non_negotiable=bool(c.get("non_negotiable", False)),
                measure_method=c["measure_method"],
                pass_condition=c["pass_condition"],
            )
        )
    return results
