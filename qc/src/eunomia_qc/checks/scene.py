"""VLM-based scene integrity checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from eunomia_qc.rubric import CheckResult

if TYPE_CHECKING:
    from eunomia_qc.frames import Frame
    from eunomia_qc.vlm import VLMClient

VLM_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["answer", "reason"],
}


def _select_frames(frames: list["Frame"], count: int) -> list["Frame"]:
    """Select evenly-spaced frames from the list."""
    if len(frames) <= count:
        return list(frames)
    step = (len(frames) - 1) / (count - 1)
    return [frames[round(i * step)] for i in range(count)]


async def check_arm_visibility(
    frames: list["Frame"], vlm: "VLMClient | None", **_: Any
) -> CheckResult:
    if vlm is None or not frames:
        return CheckResult(
            id="mvo_3",
            group="scene_integrity",
            name="Arm visibility",
            status="skipped",
            when=(),
            how="",
            why="VLM not available or no frames",
            confidence="unverified",
            non_negotiable=True,
        )

    selected = _select_frames(frames, 3)
    resp = await vlm.ask(
        "Is a robotic arm or human arm visible and actively operating in each of these frames? "
        "Answer true only if an arm is clearly visible in all frames.",
        [f.data for f in selected],
        VLM_RESPONSE_SCHEMA,
    )
    if resp["answer"]:
        return CheckResult(
            id="mvo_3",
            group="scene_integrity",
            name="Arm visibility",
            status="pass",
            when=(),
            how="",
            why=resp["reason"],
            confidence="calibrated",
            non_negotiable=True,
        )
    return CheckResult(
        id="mvo_3",
        group="scene_integrity",
        name="Arm visibility",
        status="fail",
        when=((selected[0].timestamp_s, selected[-1].timestamp_s),),
        how=resp["reason"],
        why="VLM detected arm not visible in one or more frames",
        confidence="calibrated",
        non_negotiable=True,
    )


async def check_object_presence(
    episode: dict[str, Any],
    task: dict[str, Any],
    frames: list["Frame"],
    vlm: "VLMClient | None",
    **_: Any,
) -> CheckResult:
    metadata = task.get("metadata") or {}
    props = metadata.get("props")
    if not props:
        return CheckResult(
            id="mvo_4",
            group="scene_integrity",
            name="Object presence",
            status="na",
            when=(),
            how="",
            why="No props listed in task metadata",
            confidence="calibrated",
            non_negotiable=False,
        )
    if vlm is None or not frames:
        return CheckResult(
            id="mvo_4",
            group="scene_integrity",
            name="Object presence",
            status="skipped",
            when=(),
            how="",
            why="VLM not available or no frames",
            confidence="unverified",
            non_negotiable=False,
        )

    selected = [frames[0], frames[-1]] if len(frames) >= 2 else frames[:1]
    objects_str = ", ".join(props)
    resp = await vlm.ask(
        f"Are all of the following objects visible in these frames: {objects_str}? "
        "Answer true only if every listed object is visible.",
        [f.data for f in selected],
        VLM_RESPONSE_SCHEMA,
    )
    if resp["answer"]:
        return CheckResult(
            id="mvo_4",
            group="scene_integrity",
            name="Object presence",
            status="pass",
            when=(),
            how="",
            why=resp["reason"],
            confidence="calibrated",
            non_negotiable=False,
        )
    return CheckResult(
        id="mvo_4",
        group="scene_integrity",
        name="Object presence",
        status="fail",
        when=((selected[0].timestamp_s, selected[-1].timestamp_s),),
        how=resp["reason"],
        why=f"VLM could not confirm presence of all objects: {objects_str}",
        confidence="calibrated",
        non_negotiable=False,
    )


async def check_object_containment(
    frames: list["Frame"], vlm: "VLMClient | None", **_: Any
) -> CheckResult:
    if vlm is None or len(frames) < 2:
        return CheckResult(
            id="mvo_5",
            group="scene_integrity",
            name="Object containment",
            status="skipped",
            when=(),
            how="",
            why="VLM not available or fewer than 2 frames",
            confidence="unverified",
            non_negotiable=True,
        )

    resp = await vlm.ask(
        "Compare the first and last frame. Did any object leave the visible scene area "
        "(fall off table, get knocked away, disappear from view)? "
        "Answer true if all objects remained within the scene.",
        [frames[0].data, frames[-1].data],
        VLM_RESPONSE_SCHEMA,
    )
    if resp["answer"]:
        return CheckResult(
            id="mvo_5",
            group="scene_integrity",
            name="Object containment",
            status="pass",
            when=(),
            how="",
            why=resp["reason"],
            confidence="calibrated",
            non_negotiable=True,
        )
    return CheckResult(
        id="mvo_5",
        group="scene_integrity",
        name="Object containment",
        status="fail",
        when=((frames[0].timestamp_s, frames[-1].timestamp_s),),
        how=resp["reason"],
        why="VLM detected object leaving scene between first and last frame",
        confidence="calibrated",
        non_negotiable=True,
    )


async def check_lighting(
    frames: list["Frame"], vlm: "VLMClient | None", **_: Any
) -> CheckResult:
    if vlm is None or not frames:
        return CheckResult(
            id="mvo_6",
            group="scene_integrity",
            name="Lighting consistency",
            status="skipped",
            when=(),
            how="",
            why="VLM not available or no frames",
            confidence="unverified",
            non_negotiable=False,
        )

    selected = _select_frames(frames, 3)
    resp = await vlm.ask(
        "Is the lighting adequate and consistent across these frames? "
        "Check for harsh shadows, over-exposure, darkness, or flickering. "
        "Answer true if lighting is acceptable for quality video capture.",
        [f.data for f in selected],
        VLM_RESPONSE_SCHEMA,
    )
    if resp["answer"]:
        return CheckResult(
            id="mvo_6",
            group="scene_integrity",
            name="Lighting consistency",
            status="pass",
            when=(),
            how="",
            why=resp["reason"],
            confidence="calibrated",
            non_negotiable=False,
        )
    return CheckResult(
        id="mvo_6",
        group="scene_integrity",
        name="Lighting consistency",
        status="fail",
        when=((selected[0].timestamp_s, selected[-1].timestamp_s),),
        how=resp["reason"],
        why="VLM detected lighting issue",
        confidence="calibrated",
        non_negotiable=False,
    )
