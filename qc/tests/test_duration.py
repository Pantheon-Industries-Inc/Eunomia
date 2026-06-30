"""Tests for duration band and idle ratio checks."""

from __future__ import annotations

import asyncio

from eunomia_qc.checks.duration import check_duration_band, check_idle_ratio
from eunomia_qc.frames import Frame


class TestDurationBand:
    def test_pass_within_band(self) -> None:
        episode = {"archive": 3600}  # 120s
        task = {"expected_duration_s": 120}
        result = asyncio.run(check_duration_band(episode=episode, task=task))
        assert result.status == "pass"
        assert result.id == "mvo_8"
        assert result.non_negotiable is False

    def test_fail_too_short(self) -> None:
        episode = {"archive": 900}  # 30s
        task = {"expected_duration_s": 120}  # band: [60s, 180s]
        result = asyncio.run(check_duration_band(episode=episode, task=task))
        assert result.status == "fail"

    def test_fail_too_long(self) -> None:
        episode = {"archive": 9000}  # 300s
        task = {"expected_duration_s": 120}  # band: [60s, 180s]
        result = asyncio.run(check_duration_band(episode=episode, task=task))
        assert result.status == "fail"

    def test_na_without_expected_duration(self) -> None:
        episode = {"archive": 3600}
        task: dict[str, object] = {}
        result = asyncio.run(check_duration_band(episode=episode, task=task))
        assert result.status == "na"

    def test_pass_at_low_boundary(self) -> None:
        episode = {"archive": 1800}  # 60s = 120 * 0.5
        task = {"expected_duration_s": 120}
        result = asyncio.run(check_duration_band(episode=episode, task=task))
        assert result.status == "pass"

    def test_pass_at_high_boundary(self) -> None:
        episode = {"archive": 5400}  # 180s = 120 * 1.5
        task = {"expected_duration_s": 120}
        result = asyncio.run(check_duration_band(episode=episode, task=task))
        assert result.status == "pass"


class TestIdleRatio:
    def _make_frame(self, index: int, ts: float, size: int) -> Frame:
        return Frame(index=index, timestamp_s=ts, data=bytes([index % 256]) * size)

    def test_pass_with_varied_frames(self) -> None:
        frames = [
            self._make_frame(0, 0.0, 1000),
            self._make_frame(1, 1.0, 1200),
            self._make_frame(2, 2.0, 900),
            self._make_frame(3, 3.0, 1100),
            self._make_frame(4, 4.0, 1300),
        ]
        result = asyncio.run(check_idle_ratio(frames=frames))
        assert result.status == "pass"
        assert result.id == "mvo_9"

    def test_fail_with_identical_frames(self) -> None:
        frames = [
            self._make_frame(0, 0.0, 1000),
            self._make_frame(1, 1.0, 1000),
            self._make_frame(2, 2.0, 1000),
            self._make_frame(3, 3.0, 1000),
            self._make_frame(4, 4.0, 1000),
        ]
        result = asyncio.run(check_idle_ratio(frames=frames))
        assert result.status == "fail"
        assert result.confidence == "calibrated"

    def test_na_with_single_frame(self) -> None:
        frames = [self._make_frame(0, 0.0, 1000)]
        result = asyncio.run(check_idle_ratio(frames=frames))
        assert result.status == "na"

    def test_na_with_empty_frames(self) -> None:
        result = asyncio.run(check_idle_ratio(frames=[]))
        assert result.status == "na"

    def test_pass_below_ceiling(self) -> None:
        # 1 idle pair out of 4 = 0.25 < 0.4 ceiling
        frames = [
            self._make_frame(0, 0.0, 1000),
            self._make_frame(1, 1.0, 1000),  # idle (same size)
            self._make_frame(2, 2.0, 1500),  # motion
            self._make_frame(3, 3.0, 1200),  # motion
            self._make_frame(4, 4.0, 900),  # motion
        ]
        result = asyncio.run(check_idle_ratio(frames=frames))
        assert result.status == "pass"
