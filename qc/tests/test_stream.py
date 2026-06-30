"""Tests for stream integrity checks."""

from __future__ import annotations

import asyncio

from eunomia_qc.checks.stream import check_frame_drops, check_recording_suspect


class TestFrameDrops:
    def test_pass_within_range(self) -> None:
        episode = {"archive": 3600}  # 120s at 30fps
        task = {"expected_duration_s": 120}
        result = asyncio.run(check_frame_drops(episode=episode, task=task))
        assert result.status == "pass"
        assert result.id == "mvo_1"
        assert result.non_negotiable is True

    def test_fail_too_few_frames(self) -> None:
        episode = {"archive": 1000}  # ~33s at 30fps
        task = {"expected_duration_s": 120}  # expected 3600 frames
        result = asyncio.run(check_frame_drops(episode=episode, task=task))
        assert result.status == "fail"
        assert result.confidence == "trusted"

    def test_fail_too_many_frames(self) -> None:
        episode = {"archive": 10000}
        task = {"expected_duration_s": 120}  # expected 3600, high = 5400
        result = asyncio.run(check_frame_drops(episode=episode, task=task))
        assert result.status == "fail"

    def test_na_when_no_expected_duration(self) -> None:
        episode = {"archive": 3600}
        task: dict[str, object] = {}
        result = asyncio.run(check_frame_drops(episode=episode, task=task))
        assert result.status == "na"

    def test_na_when_expected_duration_none(self) -> None:
        episode = {"archive": 3600}
        task = {"expected_duration_s": None}
        result = asyncio.run(check_frame_drops(episode=episode, task=task))
        assert result.status == "na"

    def test_pass_at_boundary_low(self) -> None:
        episode = {"archive": 2880}  # exactly 0.8 * 3600
        task = {"expected_duration_s": 120}
        result = asyncio.run(check_frame_drops(episode=episode, task=task))
        assert result.status == "pass"

    def test_pass_at_boundary_high(self) -> None:
        episode = {"archive": 5400}  # exactly 1.5 * 3600
        task = {"expected_duration_s": 120}
        result = asyncio.run(check_frame_drops(episode=episode, task=task))
        assert result.status == "pass"

    def test_archive_zero(self) -> None:
        episode = {"archive": 0}
        task = {"expected_duration_s": 120}
        result = asyncio.run(check_frame_drops(episode=episode, task=task))
        assert result.status == "fail"

    def test_archive_none(self) -> None:
        episode = {"archive": None}
        task = {"expected_duration_s": 120}
        result = asyncio.run(check_frame_drops(episode=episode, task=task))
        assert result.status == "fail"


class TestRecordingSuspect:
    def test_pass_when_zero(self) -> None:
        episode = {"recording_suspect": 0}
        result = asyncio.run(check_recording_suspect(episode=episode))
        assert result.status == "pass"
        assert result.id == "mvo_2"

    def test_fail_when_one(self) -> None:
        episode = {"recording_suspect": 1}
        result = asyncio.run(check_recording_suspect(episode=episode))
        assert result.status == "fail"
        assert result.non_negotiable is True

    def test_pass_when_missing(self) -> None:
        result = asyncio.run(check_recording_suspect(episode={}))
        assert result.status == "pass"
