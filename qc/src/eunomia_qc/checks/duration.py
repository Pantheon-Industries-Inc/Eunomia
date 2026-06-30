"""Duration band and idle ratio checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from eunomia_qc.rubric import CheckResult

if TYPE_CHECKING:
    from eunomia_qc.frames import Frame

FPS = 30
DURATION_TOLERANCE = 0.5
IDLE_CEILING = 0.4
BYTE_DIFF_THRESHOLD = 0.02


async def check_duration_band(
    episode: dict[str, Any], task: dict[str, Any], **_: Any
) -> CheckResult:
    expected_s = task.get("expected_duration_s")
    if expected_s is None:
        return CheckResult(
            id="mvo_8",
            group="duration",
            name="Duration in plausible band",
            status="na",
            when=(),
            how="",
            why="No expected_duration_s on task",
            confidence="trusted",
            non_negotiable=False,
        )

    archive = episode.get("archive", 0) or 0
    actual_s = archive / FPS
    low = expected_s * (1 - DURATION_TOLERANCE)
    high = expected_s * (1 + DURATION_TOLERANCE)

    if low <= actual_s <= high:
        return CheckResult(
            id="mvo_8",
            group="duration",
            name="Duration in plausible band",
            status="pass",
            when=(),
            how="",
            why=f"Duration {actual_s:.1f}s within [{low:.1f}s, {high:.1f}s]",
            confidence="trusted",
            non_negotiable=False,
        )

    return CheckResult(
        id="mvo_8",
        group="duration",
        name="Duration in plausible band",
        status="fail",
        when=((0.0, actual_s),),
        how=f"Duration {actual_s:.1f}s outside expected band [{low:.1f}s, {high:.1f}s]",
        why=f"Expected {expected_s}s ± {DURATION_TOLERANCE * 100:.0f}%",
        confidence="trusted",
        non_negotiable=False,
    )


async def check_idle_ratio(frames: list["Frame"], **_: Any) -> CheckResult:
    if len(frames) < 2:
        return CheckResult(
            id="mvo_9",
            group="duration",
            name="Idle ratio below ceiling",
            status="na",
            when=(),
            how="",
            why="Fewer than 2 frames available for motion estimation",
            confidence="calibrated",
            non_negotiable=False,
        )

    idle_count = 0
    for i in range(1, len(frames)):
        prev_size = len(frames[i - 1].data)
        curr_size = len(frames[i].data)
        if prev_size == 0:
            continue
        diff_ratio = abs(curr_size - prev_size) / prev_size
        if diff_ratio < BYTE_DIFF_THRESHOLD:
            idle_count += 1

    total_pairs = len(frames) - 1
    idle_ratio = idle_count / total_pairs if total_pairs > 0 else 0.0

    if idle_ratio < IDLE_CEILING:
        return CheckResult(
            id="mvo_9",
            group="duration",
            name="Idle ratio below ceiling",
            status="pass",
            when=(),
            how="",
            why=f"Idle ratio {idle_ratio:.2f} below ceiling {IDLE_CEILING}",
            confidence="calibrated",
            non_negotiable=False,
        )

    return CheckResult(
        id="mvo_9",
        group="duration",
        name="Idle ratio below ceiling",
        status="fail",
        when=((frames[0].timestamp_s, frames[-1].timestamp_s),),
        how=f"Idle ratio {idle_ratio:.2f} exceeds ceiling {IDLE_CEILING}",
        why=f"{idle_count}/{total_pairs} frame pairs show no significant motion (byte-diff < {BYTE_DIFF_THRESHOLD})",
        confidence="calibrated",
        non_negotiable=False,
    )
