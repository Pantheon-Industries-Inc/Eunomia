"""VLM-based goal completion check."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from eunomia_qc.rubric import CheckResult, load_task_rubric

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


async def check_goal_completion(
    task: dict[str, Any],
    frames: list["Frame"],
    vlm: "VLMClient | None",
    **_: Any,
) -> CheckResult:
    prompt = task.get("prompt") or task.get("task_name") or ""
    if not prompt.strip():
        return CheckResult(
            id="mvo_7",
            group="goal_completion",
            name="Goal completion",
            status="na",
            when=(),
            how="",
            why="No task prompt or task_name to evaluate goal completion",
            confidence="calibrated",
            non_negotiable=True,
        )
    if vlm is None or not frames:
        return CheckResult(
            id="mvo_7",
            group="goal_completion",
            name="Goal completion",
            status="skipped",
            when=(),
            how="",
            why="VLM not available or no frames",
            confidence="unverified",
            non_negotiable=True,
        )

    question = f"Looking at the final frame(s), does the end-state match this task goal: {prompt}?"

    rubric_defs = load_task_rubric(task)
    end_state_criteria = [
        d.pass_condition
        for d in rubric_defs
        if d.category == "end_state" and d.non_negotiable
    ]
    if end_state_criteria:
        criteria_str = "; ".join(end_state_criteria)
        question += (
            f" Additionally, verify these end-state criteria are met: {criteria_str}."
        )

    question += " Answer true only if the goal appears to be completed."

    final_frames = frames[-3:] if len(frames) >= 3 else frames
    resp = await vlm.ask(
        question,
        [f.data for f in final_frames],
        VLM_RESPONSE_SCHEMA,
    )
    if resp["answer"]:
        return CheckResult(
            id="mvo_7",
            group="goal_completion",
            name="Goal completion",
            status="pass",
            when=(),
            how="",
            why=resp["reason"],
            confidence="calibrated",
            non_negotiable=True,
        )
    return CheckResult(
        id="mvo_7",
        group="goal_completion",
        name="Goal completion",
        status="fail",
        when=((final_frames[0].timestamp_s, final_frames[-1].timestamp_s),),
        how=resp["reason"],
        why="VLM determined goal was not completed",
        confidence="calibrated",
        non_negotiable=True,
    )
