"""Stream integrity checks — frame drops and recording suspect flag."""

from __future__ import annotations

from typing import Any

from eunomia_qc.rubric import CheckResult

FPS = 30
FRAME_DROP_LOW = 0.8
FRAME_DROP_HIGH = 1.5


async def check_frame_drops(
    episode: dict[str, Any], task: dict[str, Any], **_: Any
) -> CheckResult:
    expected_s = task.get("expected_duration_s")
    if expected_s is None:
        return CheckResult(
            id="mvo_1",
            group="stream_integrity",
            name="Frame drop detection",
            status="na",
            when=(),
            how="",
            why="No expected_duration_s on task — cannot evaluate frame drops",
            confidence="trusted",
            non_negotiable=True,
        )

    archive = episode.get("archive", 0) or 0
    expected_frames = expected_s * FPS
    low = expected_frames * FRAME_DROP_LOW
    high = expected_frames * FRAME_DROP_HIGH
    actual_s = archive / FPS

    if low <= archive <= high:
        return CheckResult(
            id="mvo_1",
            group="stream_integrity",
            name="Frame drop detection",
            status="pass",
            when=(),
            how="",
            why=f"Frame count {archive} within [{low:.0f}, {high:.0f}] expected range",
            confidence="trusted",
            non_negotiable=True,
        )

    return CheckResult(
        id="mvo_1",
        group="stream_integrity",
        name="Frame drop detection",
        status="fail",
        when=((0.0, actual_s),),
        how=f"Frame count {archive} outside expected range [{low:.0f}, {high:.0f}]",
        why=f"Expected {expected_frames:.0f} frames ({expected_s}s × {FPS}fps), got {archive}",
        confidence="trusted",
        non_negotiable=True,
    )


async def check_recording_suspect(episode: dict[str, Any], **_: Any) -> CheckResult:
    suspect = episode.get("recording_suspect", 0)
    if suspect == 1:
        return CheckResult(
            id="mvo_2",
            group="stream_integrity",
            name="Recording suspect flag",
            status="fail",
            when=(),
            how="Coordinator could not confirm clip grew during recording",
            why="recording_suspect flag set to 1 by firmware",
            confidence="trusted",
            non_negotiable=True,
        )
    return CheckResult(
        id="mvo_2",
        group="stream_integrity",
        name="Recording suspect flag",
        status="pass",
        when=(),
        how="",
        why="recording_suspect flag is 0",
        confidence="trusted",
        non_negotiable=True,
    )
