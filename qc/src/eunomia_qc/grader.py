"""Aggregate CheckResult lists into Accept/Review/Reject verdicts."""

from __future__ import annotations

from eunomia_qc.rubric import CheckResult


def grade(checks: list[CheckResult]) -> tuple[str, str, int]:
    """Return (verdict, verdict_reason, score).

    Verdict priority: reject > review > accept.
    """
    applicable = [c for c in checks if c.status in ("pass", "fail")]
    passed = [c for c in applicable if c.status == "pass"]
    score = round(100 * len(passed) / len(applicable)) if applicable else 100

    # 1. Any non-negotiable fail → reject
    for c in checks:
        if c.status == "fail" and c.non_negotiable:
            return "reject", f"Non-negotiable check failed: {c.name}", score

    # 2. Goal completion fail → reject
    for c in checks:
        if c.id == "mvo_7" and c.status == "fail":
            return "reject", "Goal completion check failed", score

    # 3. Any negotiable fail with trusted/calibrated confidence → review
    for c in checks:
        if c.status == "fail" and c.confidence in ("trusted", "calibrated"):
            return "review", f"Negotiable check failed: {c.name}", score

    # 4. Any fail with low/unverified confidence → review
    for c in checks:
        if c.status == "fail" and c.confidence in ("low", "unverified"):
            return "review", f"Low-confidence failure: {c.name}", score

    # 5. No applicable checks → review
    if not applicable:
        return "review", "No applicable checks — manual review needed", score

    # 6. All pass
    return "accept", "All checks passed", score
