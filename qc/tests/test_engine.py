"""Tests for QC engine pipeline."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from eunomia_qc.engine import _parse_location, _resolve_footage_path, _run_checks
from eunomia_qc.frames import Frame
from eunomia_qc.vlm import VLMClient


class MockVLM:
    """Mock VLM that always returns a specified answer."""

    def __init__(self, answer: bool = True, reason: str = "Mock VLM response") -> None:
        self.answer = answer
        self.reason = reason
        self.model = "mock-model"
        self.call_count = 0
        self.api_key = "mock"
        self.max_retries = 1
        self.timeout_s = 1.0
        self.cost_budget_usd = 100.0
        self._cumulative_cost = 0.0

    @property
    def cumulative_cost(self) -> float:
        return self._cumulative_cost

    async def ask(
        self, question: str, images: list[bytes], response_schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.call_count += 1
        return {"answer": self.answer, "reason": self.reason}


def _make_frame(index: int, ts: float, size: int = 1000) -> Frame:
    return Frame(index=index, timestamp_s=ts, data=bytes([index % 256]) * size)


def _sample_episode() -> dict[str, Any]:
    return {
        "episode_id": "ep-test-001",
        "archive": 3600,
        "recording_suspect": 0,
        "task_id": "task-1",
        "task_version": 1,
        "rotation_id": "default",
        "void": False,
    }


def _sample_task() -> dict[str, Any]:
    return {
        "task_id": "task-1",
        "task_name": "Fold towel",
        "prompt": "Fold the towel neatly in half",
        "expected_duration_s": 120,
        "metadata": {
            "props": ["towel"],
            "rubric_checks": [
                {
                    "id": "fold_1",
                    "name": "Edges flush",
                    "category": "end_state",
                    "non_negotiable": True,
                    "measure_method": "VLM",
                    "pass_condition": "Folded edges are flush and aligned",
                },
                {
                    "id": "fold_2",
                    "name": "Smooth surface",
                    "category": "process",
                    "non_negotiable": False,
                    "measure_method": "Program",
                    "pass_condition": "Surface smoothness < 5mm deviation",
                },
            ],
        },
    }


class TestParseLocation:
    def test_tier_path(self) -> None:
        tier, path = _parse_location("normalized:/foo/bar.mp4")
        assert tier == "normalized"
        assert path == "/foo/bar.mp4"

    def test_bare_path(self) -> None:
        tier, path = _parse_location("/foo/bar.insv")
        assert tier == ""
        assert path == "/foo/bar.insv"

    def test_styx_tier(self) -> None:
        tier, path = _parse_location("styx:/pool/drain/VID.insv")
        assert tier == "styx"
        assert path == "/pool/drain/VID.insv"


class TestResolveFootagePath:
    def test_prefers_normalized_tier(self, tmp_path: Any) -> None:
        raw = tmp_path / "raw.insv"
        raw.write_bytes(b"\x00")
        norm = tmp_path / "workspace.mp4"
        norm.write_bytes(b"\x00")

        locations = [str(raw), f"normalized:{norm}"]

        class FakeConn:
            pass

        from unittest.mock import patch

        def mock_get(conn: Any, table_name: str, **key: Any) -> dict[str, Any] | None:
            if table_name == "footage_reference":
                return {"locations": locations}
            return None

        with patch("eunomia_qc.engine.store.get", side_effect=mock_get):
            result = _resolve_footage_path(FakeConn(), "ep-001")  # type: ignore[arg-type]
        assert result == norm

    def test_falls_back_to_bare_path(self, tmp_path: Any) -> None:
        raw = tmp_path / "raw.insv"
        raw.write_bytes(b"\x00")

        locations = [str(raw)]

        class FakeConn:
            pass

        from unittest.mock import patch

        def mock_get(conn: Any, table_name: str, **key: Any) -> dict[str, Any] | None:
            if table_name == "footage_reference":
                return {"locations": locations}
            return None

        with patch("eunomia_qc.engine.store.get", side_effect=mock_get):
            result = _resolve_footage_path(FakeConn(), "ep-002")  # type: ignore[arg-type]
        assert result == raw

    def test_returns_none_for_missing_ref(self) -> None:
        class FakeConn:
            pass

        from unittest.mock import patch

        with patch("eunomia_qc.engine.store.get", return_value=None):
            result = _resolve_footage_path(FakeConn(), "ep-missing")  # type: ignore[arg-type]
        assert result is None


class TestRunChecks:
    def test_all_pass_with_vlm(self) -> None:
        vlm = cast(VLMClient, MockVLM(answer=True, reason="All good"))
        episode = _sample_episode()
        task = _sample_task()
        frames = [_make_frame(i, i * 1.0, 1000 + i * 100) for i in range(5)]

        checks = asyncio.run(_run_checks(episode, task, frames, vlm))

        statuses = {c.id: c.status for c in checks}
        assert statuses["mvo_1"] == "pass"
        assert statuses["mvo_2"] == "pass"
        assert statuses["mvo_8"] == "pass"
        assert statuses["mvo_3"] == "pass"
        assert statuses["mvo_5"] == "pass"
        assert statuses["mvo_6"] == "pass"
        assert statuses["mvo_7"] == "pass"
        assert statuses["t_fold_1"] == "pass"
        assert statuses["t_fold_2"] == "skipped"

    def test_no_vlm_skips_vlm_checks(self) -> None:
        episode = _sample_episode()
        task = _sample_task()
        frames = [_make_frame(i, i * 1.0, 1000 + i * 100) for i in range(5)]

        checks = asyncio.run(_run_checks(episode, task, frames, None))

        statuses = {c.id: c.status for c in checks}
        assert statuses["mvo_1"] == "pass"
        assert statuses["mvo_2"] == "pass"
        assert statuses["mvo_3"] == "skipped"
        assert statuses["mvo_7"] == "skipped"

    def test_no_frames_skips_vlm_and_idle(self) -> None:
        vlm = cast(VLMClient, MockVLM(answer=True))
        episode = _sample_episode()
        task = _sample_task()

        checks = asyncio.run(_run_checks(episode, task, [], vlm))

        statuses = {c.id: c.status for c in checks}
        assert statuses["mvo_1"] == "pass"
        assert statuses["mvo_9"] == "na"
        assert statuses["mvo_3"] == "skipped"

    def test_recording_suspect_rejects(self) -> None:
        vlm = cast(VLMClient, MockVLM(answer=True))
        episode = _sample_episode()
        episode["recording_suspect"] = 1
        task = _sample_task()
        frames = [_make_frame(i, i * 1.0, 1000 + i * 100) for i in range(5)]

        checks = asyncio.run(_run_checks(episode, task, frames, vlm))

        statuses = {c.id: c.status for c in checks}
        assert statuses["mvo_2"] == "fail"

    def test_vlm_fail_produces_review(self) -> None:
        vlm = cast(VLMClient, MockVLM(answer=False, reason="Lighting is poor"))
        episode = _sample_episode()
        task: dict[str, Any] = {"task_name": "Test", "expected_duration_s": 120}
        frames = [_make_frame(i, i * 1.0, 1000 + i * 100) for i in range(5)]

        checks = asyncio.run(_run_checks(episode, task, frames, vlm))

        scene_fails = [
            c for c in checks if c.group == "scene_integrity" and c.status == "fail"
        ]
        assert len(scene_fails) > 0

    def test_check_count(self) -> None:
        vlm = cast(VLMClient, MockVLM(answer=True))
        episode = _sample_episode()
        task = _sample_task()
        frames = [_make_frame(i, i * 1.0, 1000 + i * 100) for i in range(5)]

        checks = asyncio.run(_run_checks(episode, task, frames, vlm))

        # 9 universal + 2 per-task (1 VLM + 1 Program)
        assert len(checks) == 11
