"""Per-task rubric quality checks loaded from task metadata JSONB."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from eunomia_qc.rubric import CheckResult, RubricCheckDef, load_task_rubric

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
    if len(frames) <= count:
        return list(frames)
    step = (len(frames) - 1) / (count - 1)
    return [frames[round(i * step)] for i in range(count)]


async def _run_vlm_check(
    check_def: RubricCheckDef,
    frames: list["Frame"],
    vlm: "VLMClient",
) -> CheckResult:
    if check_def.category == "end_state":
        selected = frames[-3:] if len(frames) >= 3 else frames
    else:
        selected = _select_frames(frames, 5)

    resp = await vlm.ask(
        f"Looking at the video frames, is the following condition met: "
        f"{check_def.pass_condition}? "
        "Answer true if the condition is clearly satisfied.",
        [f.data for f in selected],
        VLM_RESPONSE_SCHEMA,
    )
    if resp["answer"]:
        return CheckResult(
            id=check_def.id,
            group="task_quality",
            name=check_def.name,
            status="pass",
            when=(),
            how="",
            why=resp["reason"],
            confidence="calibrated",
            non_negotiable=check_def.non_negotiable,
        )
    return CheckResult(
        id=check_def.id,
        group="task_quality",
        name=check_def.name,
        status="fail",
        when=((selected[0].timestamp_s, selected[-1].timestamp_s),),
        how=resp["reason"],
        why=f"VLM check: {check_def.pass_condition}",
        confidence="calibrated",
        non_negotiable=check_def.non_negotiable,
    )


async def check_task_rubric(
    task: dict[str, Any],
    frames: list["Frame"],
    vlm: "VLMClient | None",
    **_: Any,
) -> list[CheckResult]:
    rubric_defs = load_task_rubric(task)
    if not rubric_defs:
        return []

    results: list[CheckResult] = []
    for check_def in rubric_defs:
        if check_def.measure_method != "VLM":
            results.append(
                CheckResult(
                    id=check_def.id,
                    group="task_quality",
                    name=check_def.name,
                    status="skipped",
                    when=(),
                    how="",
                    why=f"Requires {check_def.measure_method} measurement "
                    "(deferred to Hermes enrichment)",
                    confidence="unverified",
                    non_negotiable=check_def.non_negotiable,
                )
            )
            continue

        if vlm is None or not frames:
            results.append(
                CheckResult(
                    id=check_def.id,
                    group="task_quality",
                    name=check_def.name,
                    status="skipped",
                    when=(),
                    how="",
                    why="VLM not available or no frames",
                    confidence="unverified",
                    non_negotiable=check_def.non_negotiable,
                )
            )
            continue

        result = await _run_vlm_check(check_def, frames, vlm)
        results.append(result)

    return results
