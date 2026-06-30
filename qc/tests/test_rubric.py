"""Tests for rubric registry and task rubric loading."""

from __future__ import annotations

from eunomia_qc.rubric import (
    UNIVERSAL_CHECK_IDS,
    VALID_CONFIDENCES,
    VALID_GROUPS,
    VALID_STATUSES,
    CheckResult,
    load_task_rubric,
)


class TestUniversalRegistry:
    def test_check_ids_are_unique(self) -> None:
        ids = list(UNIVERSAL_CHECK_IDS.keys())
        assert len(ids) == len(set(ids))

    def test_nine_universal_checks(self) -> None:
        assert len(UNIVERSAL_CHECK_IDS) == 9

    def test_all_ids_prefixed_mvo(self) -> None:
        for cid in UNIVERSAL_CHECK_IDS:
            assert cid.startswith("mvo_"), f"{cid} should start with mvo_"

    def test_valid_enums(self) -> None:
        assert "pass" in VALID_STATUSES
        assert "fail" in VALID_STATUSES
        assert "na" in VALID_STATUSES
        assert "skipped" in VALID_STATUSES
        assert "trusted" in VALID_CONFIDENCES
        assert "calibrated" in VALID_CONFIDENCES
        assert "stream_integrity" in VALID_GROUPS
        assert "task_quality" in VALID_GROUPS


class TestCheckResult:
    def test_frozen(self) -> None:
        cr = CheckResult(
            id="mvo_1",
            group="stream_integrity",
            name="Test",
            status="pass",
            when=(),
            how="",
            why="ok",
            confidence="trusted",
            non_negotiable=False,
        )
        with __import__("pytest").raises(AttributeError):
            cr.status = "fail"  # type: ignore[misc]

    def test_hashable(self) -> None:
        cr = CheckResult(
            id="mvo_1",
            group="stream_integrity",
            name="Test",
            status="pass",
            when=(),
            how="",
            why="ok",
            confidence="trusted",
            non_negotiable=False,
        )
        assert hash(cr) is not None


class TestLoadTaskRubric:
    def test_well_formed_metadata(self) -> None:
        task = {
            "metadata": {
                "rubric_checks": [
                    {
                        "id": "fold_1",
                        "name": "Edges flush",
                        "category": "end_state",
                        "non_negotiable": True,
                        "measure_method": "VLM",
                        "pass_condition": "Folded edges are flush",
                    }
                ]
            }
        }
        defs = load_task_rubric(task)
        assert len(defs) == 1
        assert defs[0].id == "t_fold_1"
        assert defs[0].name == "Edges flush"
        assert defs[0].non_negotiable is True
        assert defs[0].measure_method == "VLM"

    def test_missing_metadata(self) -> None:
        assert load_task_rubric({}) == []
        assert load_task_rubric({"metadata": None}) == []
        assert load_task_rubric({"metadata": {}}) == []

    def test_missing_rubric_checks_key(self) -> None:
        task = {"metadata": {"props": ["towel"]}}
        assert load_task_rubric(task) == []

    def test_skips_invalid_entries(self) -> None:
        task = {
            "metadata": {
                "rubric_checks": [
                    {
                        "id": "good",
                        "name": "Good check",
                        "category": "end_state",
                        "measure_method": "VLM",
                        "pass_condition": "ok",
                    },
                    {
                        "id": "",
                        "name": "Bad",
                        "category": "end_state",
                        "measure_method": "VLM",
                        "pass_condition": "ok",
                    },
                    {
                        "name": "Missing id",
                        "category": "end_state",
                        "measure_method": "VLM",
                        "pass_condition": "ok",
                    },
                    "not_a_dict",
                    42,
                ]
            }
        }
        defs = load_task_rubric(task)
        assert len(defs) == 1
        assert defs[0].id == "t_good"

    def test_non_negotiable_defaults_false(self) -> None:
        task = {
            "metadata": {
                "rubric_checks": [
                    {
                        "id": "x",
                        "name": "X",
                        "category": "process",
                        "measure_method": "VLM",
                        "pass_condition": "cond",
                    },
                ]
            }
        }
        defs = load_task_rubric(task)
        assert defs[0].non_negotiable is False

    def test_multiple_checks(self) -> None:
        task = {
            "metadata": {
                "rubric_checks": [
                    {
                        "id": "a",
                        "name": "A",
                        "category": "end_state",
                        "measure_method": "VLM",
                        "pass_condition": "cond a",
                    },
                    {
                        "id": "b",
                        "name": "B",
                        "category": "process",
                        "measure_method": "Program",
                        "pass_condition": "cond b",
                    },
                ]
            }
        }
        defs = load_task_rubric(task)
        assert len(defs) == 2
        assert defs[0].id == "t_a"
        assert defs[1].id == "t_b"
