"""QC engine pipeline — read episode from S1, run checks, write verdict."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from eunomia_edge_store import schema, store
from eunomia_qc.checks.duration import check_duration_band, check_idle_ratio
from eunomia_qc.checks.goal import check_goal_completion
from eunomia_qc.checks.scene import (
    check_arm_visibility,
    check_lighting,
    check_object_containment,
    check_object_presence,
)
from eunomia_qc.checks.stream import check_frame_drops, check_recording_suspect
from eunomia_qc.checks.task_rubric import check_task_rubric
from eunomia_qc.events import QC_VERSION, build_qa_verdict_event
from eunomia_qc.frames import Frame, FrameExtractionError, extract_frames
from eunomia_qc.grader import grade
from eunomia_qc.rubric import CheckResult, EpisodeQCResult
from eunomia_qc.vlm import CostBudgetExceeded, VLMClient

log = logging.getLogger(__name__)


def load_episodes_for_date(conn: Connection, date: str) -> list[dict[str, Any]]:
    ep = schema.TABLES["episode"]
    start = datetime.fromisoformat(f"{date}T00:00:00+00:00")
    end = start + timedelta(days=1)
    rows = (
        conn.execute(
            sa.select(ep)
            .where(ep.c.recorded_at >= start, ep.c.recorded_at < end)
            .where(ep.c.void.is_(False))
            .order_by(ep.c.recorded_at)
        )
        .mappings()
        .all()
    )
    return [store.from_row(ep, dict(r)) for r in rows]


def _load_task(conn: Connection, episode: dict[str, Any]) -> dict[str, Any] | None:
    task_id = episode.get("task_id")
    if not task_id:
        return None
    version = episode.get("task_version")
    rotation_id = episode.get("rotation_id")
    kwargs: dict[str, Any] = {"task_id": task_id}
    if version is not None:
        kwargs["version"] = version
    if rotation_id is not None:
        kwargs["rotation_id"] = rotation_id
    return store.get(conn, "task", **kwargs)


def _resolve_footage_path(conn: Connection, episode_id: str) -> Path | None:
    ref = store.get(conn, "footage_reference", episode_id=episode_id)
    if not ref:
        return None
    for loc in ref.get("locations") or []:
        if isinstance(loc, dict):
            p = Path(loc.get("path", ""))
            if p.exists():
                return p
    return None


def _extract_frames_safe(video_path: Path | None) -> list[Frame]:
    if video_path is None:
        return []
    try:
        return extract_frames(video_path, count=5)
    except FrameExtractionError as exc:
        log.warning("Frame extraction failed: %s", exc)
        return []


async def _run_checks(
    episode: dict[str, Any],
    task: dict[str, Any],
    frames: list[Frame],
    vlm: VLMClient | None,
) -> list[CheckResult]:
    checks: list[CheckResult] = []

    checks.append(await check_frame_drops(episode=episode, task=task))
    checks.append(await check_recording_suspect(episode=episode))

    checks.append(await check_duration_band(episode=episode, task=task))
    checks.append(await check_idle_ratio(frames=frames))

    vlm_checks = await asyncio.gather(
        check_arm_visibility(frames=frames, vlm=vlm),
        check_object_presence(episode=episode, task=task, frames=frames, vlm=vlm),
        check_object_containment(frames=frames, vlm=vlm),
        check_lighting(frames=frames, vlm=vlm),
        check_goal_completion(task=task, frames=frames, vlm=vlm),
    )
    checks.extend(vlm_checks)

    try:
        task_checks = await check_task_rubric(task=task, frames=frames, vlm=vlm)
        checks.extend(task_checks)
    except CostBudgetExceeded:
        log.warning("VLM cost budget exceeded during task rubric checks")

    return checks


async def grade_episode(
    conn: Connection,
    episode: dict[str, Any],
    vlm: VLMClient | None,
    *,
    dry_run: bool = False,
) -> EpisodeQCResult | None:
    episode_id = episode["episode_id"]

    task = _load_task(conn, episode)
    if task is None:
        log.warning(
            "No task found for episode %s (task_id=%s)",
            episode_id,
            episode.get("task_id"),
        )
        task = {}

    video_path = _resolve_footage_path(conn, episode_id)
    if video_path is None:
        log.info("No local footage for episode %s — skipping VLM checks", episode_id)

    frames = await asyncio.to_thread(_extract_frames_safe, video_path)

    try:
        checks = await _run_checks(episode, task, frames, vlm)
    except CostBudgetExceeded:
        log.warning("VLM cost budget exceeded for episode %s", episode_id)
        return None

    verdict, verdict_reason, score = grade(checks)

    result = EpisodeQCResult(
        episode_id=episode_id,
        checks=tuple(checks),
        verdict=verdict,
        verdict_reason=verdict_reason,
        score=score,
        qc_version=QC_VERSION,
        vlm_model=vlm.model if vlm else "none",
    )

    if not dry_run:
        event = build_qa_verdict_event(result)
        await asyncio.to_thread(store.append_event, conn, event)
        log.info(
            "Wrote qa_verdict for episode %s: %s (score=%d)", episode_id, verdict, score
        )

    return result


async def run_checks_for_date(
    conn: Connection,
    date: str,
    vlm: VLMClient | None,
    *,
    dry_run: bool = False,
) -> list[EpisodeQCResult]:
    episodes = await asyncio.to_thread(load_episodes_for_date, conn, date)
    log.info("Found %d episodes for %s", len(episodes), date)

    results: list[EpisodeQCResult] = []
    for episode in episodes:
        result = await grade_episode(conn, episode, vlm, dry_run=dry_run)
        if result is not None:
            results.append(result)

    return results
