"""Ingest pipeline — scan drain output and fob logs into S1.

Orchestrates the sidecar parser, fob log parser, and event builder to write ``episode``,
``footage_reference``, ``session``, and ``operational_event`` records to the S1 store.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Connection

from eunomia_edge_store import store
from eunomia_ingest import events
from eunomia_ingest.fob_log import FobLogResult, StationAssignment, parse_fob_log
from eunomia_ingest.sidecar import DrainScanResult, SidecarRecord, scan_drain

EPISODE_SCHEMA = "eunomia-episode/v1"
SESSION_SCHEMA = "eunomia-session/v1"
FOOTAGE_REF_SCHEMA = "eunomia-footage-reference/v1"


@dataclass
class Anomaly:
    anomaly_type: str
    detail: str
    entity_id: str = ""
    kit_id: str = ""


@dataclass
class IngestReport:
    sidecars_processed: int = 0
    sidecars_skipped: int = 0
    episodes_created: int = 0
    episodes_enriched: int = 0
    events_appended: int = 0
    sessions_created: int = 0
    footage_refs_created: int = 0
    footage_orphans: int = 0
    sidecar_orphans: int = 0
    fob_log_lines: int = 0
    fob_log_skipped: int = 0
    fob_log_errors: int = 0
    anomalies: list[Anomaly] = field(default_factory=list)


def _sidecar_to_episode(sc: SidecarRecord) -> dict[str, Any]:
    recorded_at: str | None = None
    if sc.started_unix is not None:
        recorded_at = datetime.fromtimestamp(sc.started_unix, tz=UTC).isoformat()

    return {
        "schema": EPISODE_SCHEMA,
        "episode_id": sc.episode_id,
        "display_id": sc.display_id or "",
        "bimanual_episode_id": sc.bimanual_episode_id or "",
        "episode_ordinal": sc.episode_ordinal or 0,
        "global_episode_seq": sc.global_episode_seq,
        "kit_id": sc.kit_id,
        "side": sc.side,
        "person_id": sc.operator_id,
        "session_id": sc.session_id,
        "task_id": sc.task_id,
        "rotation_id": sc.rotation_id,
        "station_id": sc.station_id,
        "recorded_at": recorded_at or "",
        "ingested_at": datetime.now(UTC).isoformat(),
        "archive": sc.archive,
        "recording_suspect": sc.recording_suspect,
        "paired": False,
        "void": False,
        "needs_review": False,
        "sidecar_raw": sc.raw,
        "firmware_version": sc.fob_build,
    }


def _sidecar_to_footage_ref(sc: SidecarRecord) -> dict[str, Any]:
    locations: list[str] = []
    if sc.footage_exists and sc.footage_path is not None:
        locations.append(str(sc.footage_path))
    return {
        "schema": FOOTAGE_REF_SCHEMA,
        "episode_id": sc.episode_id,
        "footage_state": "on_styx",
        "locations": locations,
    }


def ingest_drain(root: Path, conn: Connection) -> IngestReport:
    """Scan a drain output directory and write episodes + footage references to S1."""
    scan = scan_drain(root)
    return write_drain_to_store(scan, conn)


def write_drain_to_store(scan: DrainScanResult, conn: Connection) -> IngestReport:
    """Write parsed drain scan results to S1."""
    report = IngestReport()
    report.sidecars_processed = len(scan.records)
    report.sidecars_skipped = len(scan.skipped)
    report.footage_orphans = len(scan.footage_orphans)

    for sc in scan.records:
        episode = _sidecar_to_episode(sc)
        store.upsert(conn, "episode", episode)
        report.episodes_created += 1

        footage_ref = _sidecar_to_footage_ref(sc)
        store.upsert(conn, "footage_reference", footage_ref)
        report.footage_refs_created += 1

        if sc.recording_suspect:
            report.anomalies.append(
                Anomaly(
                    "recording_suspect",
                    f"coordinator could not confirm clip grew: {sc.sidecar_path}",
                    entity_id=sc.episode_id,
                    kit_id=sc.kit_id,
                )
            )

        if not sc.footage_exists:
            report.sidecar_orphans += 1
            report.anomalies.append(
                Anomaly(
                    "sidecar_without_footage",
                    f"expected footage not found: {sc.footage_path}",
                    entity_id=sc.episode_id,
                    kit_id=sc.kit_id,
                )
            )

    for path, hard_errors in scan.skipped:
        report.anomalies.append(
            Anomaly(
                "sidecar_hard_error",
                f"{path}: {'; '.join(hard_errors)}",
            )
        )

    for path in scan.footage_orphans:
        report.anomalies.append(Anomaly("footage_without_sidecar", str(path)))

    _write_anomaly_events(report.anomalies, conn)
    return report


def ingest_fob_log(
    path: Path, conn: Connection, *, kit_id: str | None = None
) -> IngestReport:
    """Parse a fob JSONL log and write events + sessions + episode enrichments to S1."""
    log = parse_fob_log(path)
    return write_fob_log_to_store(log, conn, kit_id=kit_id)


def write_fob_log_to_store(
    log: FobLogResult, conn: Connection, *, kit_id: str | None = None
) -> IngestReport:
    """Write parsed fob log results to S1."""
    report = IngestReport()
    total_lines = (
        len(log.ordinals)
        + len(log.episode_starts)
        + len(log.episode_stops)
        + len(log.episode_discards)
        + len(log.session_signins)
        + len(log.assignments)
        + len(log.skipped_lines)
        + len(log.parse_errors)
    )
    report.fob_log_lines = total_lines
    report.fob_log_skipped = len(log.skipped_lines)
    report.fob_log_errors = len(log.parse_errors)

    # Build wallclock lookup from ordinal entries: episode_id -> wallclock, fob_session_id -> earliest
    episode_wallclocks: dict[str, int] = {}
    session_wallclocks: dict[str, int] = {}
    for entry in log.ordinals:
        episode_wallclocks[entry.episode_id] = entry.wallclock_unix
        prev = session_wallclocks.get(entry.fob_session_id)
        if prev is None or entry.wallclock_unix < prev:
            session_wallclocks[entry.fob_session_id] = entry.wallclock_unix

    # Sessions
    for signin in log.session_signins:
        event = events.build_session_opened_event(signin)
        store.append_event(conn, event)
        report.events_appended += 1

        signed_in_at: str | None = None
        wc = session_wallclocks.get(signin.fob_session_id)
        if wc is not None:
            signed_in_at = datetime.fromtimestamp(wc, tz=UTC).isoformat()

        session_record: dict[str, Any] = {
            "schema": SESSION_SCHEMA,
            "session_id": signin.session_id,
            "person_id": signin.operator_id,
            "kit_id": kit_id or signin.kit_id,
            "site_id": signin.site_id,
            "fob_session_id": signin.fob_session_id,
        }
        if signed_in_at is not None:
            session_record["signed_in_at"] = signed_in_at
        store.upsert(conn, "session", session_record)
        report.sessions_created += 1

    # Episode starts
    for start in log.episode_starts:
        wc = episode_wallclocks.get(start.episode_id)
        event = events.build_episode_started_event(start, wallclock_unix=wc)
        store.append_event(conn, event)
        report.events_appended += 1

        existing = store.get(conn, "episode", episode_id=start.episode_id)
        if existing is not None:
            enrichment: dict[str, Any] = {
                "episode_id": start.episode_id,
                "person_id": start.operator_id,
                "task_id": start.task_id,
                "station_id": start.station_id,
                "rotation_id": start.rotation_id,
            }
            store.upsert(conn, "episode", enrichment)
            report.episodes_enriched += 1
        else:
            print(
                f"INFO episode {start.episode_id} not yet in store (fob log only, awaiting sidecar)",
                file=sys.stderr,
            )

    # Episode stops
    for stop in log.episode_stops:
        wc = episode_wallclocks.get(stop.episode_id)
        event = events.build_episode_stopped_event(stop, wallclock_unix=wc)
        store.append_event(conn, event)
        report.events_appended += 1

    # Episode discards
    for discard in log.episode_discards:
        wc = episode_wallclocks.get(discard.episode_id)
        event = events.build_episode_discarded_event(discard, wallclock_unix=wc)
        store.append_event(conn, event)
        report.events_appended += 1

    # Assignments
    for assignment in log.assignments:
        effective_kit = kit_id or assignment.kit_id
        a = assignment
        if kit_id and kit_id != assignment.kit_id:
            a = StationAssignment(
                station_id=a.station_id,
                task_id=a.task_id,
                task_name=a.task_name,
                rotation_id=a.rotation_id,
                task_source=a.task_source,
                kit_id=effective_kit,
            )
        event = events.build_station_task_assigned_event(a)
        store.append_event(conn, event)
        report.events_appended += 1

    # Log errors as anomalies
    for line_no, raw_line, error in log.parse_errors:
        report.anomalies.append(
            Anomaly("fob_log_parse_error", f"line {line_no}: {error}")
        )

    _write_anomaly_events(report.anomalies, conn)
    return report


def _write_anomaly_events(anomalies: list[Anomaly], conn: Connection) -> None:
    for a in anomalies:
        event = events.build_ingest_anomaly_event(
            a.anomaly_type,
            a.detail,
            entity_id=a.entity_id,
            related_kit_id=a.kit_id or None,
        )
        store.append_event(conn, event)
