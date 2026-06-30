"""Tests for verdict aggregation logic."""

from __future__ import annotations

from eunomia_qc.grader import grade
from eunomia_qc.rubric import CheckResult


def _check(
    *,
    id: str = "test_1",
    status: str = "pass",
    confidence: str = "trusted",
    non_negotiable: bool = False,
    name: str = "Test check",
) -> CheckResult:
    return CheckResult(
        id=id,
        group="stream_integrity",
        name=name,
        status=status,
        when=(),
        how="fail reason" if status == "fail" else "",
        why="test",
        confidence=confidence,
        non_negotiable=non_negotiable,
    )


class TestVerdictLogic:
    def test_all_pass(self) -> None:
        checks = [_check(status="pass"), _check(id="t2", status="pass")]
        verdict, reason, score = grade(checks)
        assert verdict == "accept"
        assert score == 100

    def test_non_negotiable_fail_rejects(self) -> None:
        checks = [
            _check(status="pass"),
            _check(
                id="mvo_2", status="fail", non_negotiable=True, name="Recording suspect"
            ),
        ]
        verdict, reason, score = grade(checks)
        assert verdict == "reject"
        assert "Non-negotiable" in reason
        assert "Recording suspect" in reason
        assert score == 50

    def test_goal_fail_rejects(self) -> None:
        checks = [
            _check(status="pass"),
            _check(id="mvo_7", status="fail", name="Goal completion"),
        ]
        verdict, reason, score = grade(checks)
        assert verdict == "reject"
        assert "Goal completion" in reason

    def test_negotiable_fail_calibrated_reviews(self) -> None:
        checks = [
            _check(status="pass"),
            _check(id="mvo_6", status="fail", confidence="calibrated", name="Lighting"),
        ]
        verdict, reason, score = grade(checks)
        assert verdict == "review"
        assert "Negotiable" in reason
        assert "Lighting" in reason

    def test_negotiable_fail_trusted_reviews(self) -> None:
        checks = [
            _check(status="pass"),
            _check(id="mvo_8", status="fail", confidence="trusted", name="Duration"),
        ]
        verdict, reason, score = grade(checks)
        assert verdict == "review"

    def test_low_confidence_fail_reviews(self) -> None:
        checks = [
            _check(status="pass"),
            _check(id="t1", status="fail", confidence="low", name="Low conf"),
        ]
        verdict, reason, score = grade(checks)
        assert verdict == "review"
        assert "Low-confidence" in reason

    def test_unverified_confidence_fail_reviews(self) -> None:
        checks = [
            _check(id="t1", status="fail", confidence="unverified", name="Unverified"),
        ]
        verdict, reason, score = grade(checks)
        assert verdict == "review"

    def test_no_applicable_checks_reviews(self) -> None:
        checks = [
            _check(status="skipped"),
            _check(id="t2", status="na"),
        ]
        verdict, reason, score = grade(checks)
        assert verdict == "review"
        assert "No applicable" in reason
        assert score == 100

    def test_empty_checks_reviews(self) -> None:
        verdict, reason, score = grade([])
        assert verdict == "review"
        assert score == 100


class TestVerdictPriority:
    def test_reject_over_review(self) -> None:
        checks = [
            _check(id="mvo_2", status="fail", non_negotiable=True, name="NN fail"),
            _check(id="mvo_6", status="fail", confidence="calibrated", name="Neg fail"),
        ]
        verdict, reason, score = grade(checks)
        assert verdict == "reject"
        assert "Non-negotiable" in reason

    def test_non_negotiable_before_goal(self) -> None:
        checks = [
            _check(id="mvo_1", status="fail", non_negotiable=True, name="Frame drops"),
            _check(id="mvo_7", status="fail", name="Goal"),
        ]
        verdict, reason, score = grade(checks)
        assert verdict == "reject"
        assert "Non-negotiable" in reason
        assert "Frame drops" in reason


class TestScoring:
    def test_score_calculation(self) -> None:
        checks = [
            _check(status="pass"),
            _check(id="t2", status="pass"),
            _check(id="t3", status="pass"),
            _check(id="t4", status="fail"),
        ]
        _, _, score = grade(checks)
        assert score == 75

    def test_skipped_excluded_from_score(self) -> None:
        checks = [
            _check(status="pass"),
            _check(id="t2", status="pass"),
            _check(id="t3", status="skipped"),
            _check(id="t4", status="na"),
        ]
        _, _, score = grade(checks)
        assert score == 100

    def test_mixed_with_skipped(self) -> None:
        checks = [
            _check(status="pass"),
            _check(id="t2", status="fail"),
            _check(id="t3", status="skipped"),
        ]
        _, _, score = grade(checks)
        assert score == 50

    def test_all_fail(self) -> None:
        checks = [
            _check(status="fail", non_negotiable=True),
            _check(id="t2", status="fail"),
        ]
        _, _, score = grade(checks)
        assert score == 0
