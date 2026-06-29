"""Fob JSONL log parser — dispatches by ``"T"`` type discriminator.

Parses the operational log extracted from a fob via ``cmd=dumplog``. The format is defined by
F9's ``operational_record.h``. Unknown types and subtypes are skipped gracefully (forward-compatible).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class OrdinalEntry:
    ordinal: int
    wallclock_unix: int
    kit_id: str
    fob_id: str
    fob_session_id: str
    episode_id: str


@dataclass(frozen=True)
class EpisodeStarted:
    ordinal: int
    kit_id: str
    episode_id: str
    operator_id: str
    station_id: str
    task_id: str
    task_name: str
    rotation_id: str
    task_source: str


@dataclass(frozen=True)
class EpisodeStopped:
    episode_id: str
    ordinal: int
    stop_reason: str
    archive: int
    recording_suspect: int


@dataclass(frozen=True)
class EpisodeDiscarded:
    episode_id: str
    ordinal: int


@dataclass(frozen=True)
class SessionSignin:
    session_id: str
    kit_id: str
    operator_id: str
    site_id: str
    fob_id: str
    fob_session_id: str


@dataclass(frozen=True)
class StationAssignment:
    station_id: str
    task_id: str
    task_name: str
    rotation_id: str
    task_source: str
    kit_id: str


@dataclass
class FobLogResult:
    ordinals: list[OrdinalEntry] = field(default_factory=list)
    episode_starts: list[EpisodeStarted] = field(default_factory=list)
    episode_stops: list[EpisodeStopped] = field(default_factory=list)
    episode_discards: list[EpisodeDiscarded] = field(default_factory=list)
    session_signins: list[SessionSignin] = field(default_factory=list)
    assignments: list[StationAssignment] = field(default_factory=list)
    skipped_lines: list[tuple[int, str, str]] = field(default_factory=list)
    parse_errors: list[tuple[int, str, str]] = field(default_factory=list)


def _require(obj: dict, *keys: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise KeyError(f"missing required fields: {', '.join(missing)}")


def _parse_ordinal(obj: dict) -> OrdinalEntry:
    _require(obj, "o", "t", "k", "f", "s", "e")
    return OrdinalEntry(
        ordinal=int(obj["o"]),
        wallclock_unix=int(obj["t"]),
        kit_id=str(obj["k"]),
        fob_id=str(obj["f"]),
        fob_session_id=str(obj["s"]),
        episode_id=str(obj["e"]),
    )


def _parse_episode_start(obj: dict) -> EpisodeStarted:
    _require(obj, "o", "k", "e", "op", "stn", "tid", "tn", "rv", "ts")
    return EpisodeStarted(
        ordinal=int(obj["o"]),
        kit_id=str(obj["k"]),
        episode_id=str(obj["e"]),
        operator_id=str(obj["op"]),
        station_id=str(obj["stn"]),
        task_id=str(obj["tid"]),
        task_name=str(obj["tn"]),
        rotation_id=str(obj["rv"]),
        task_source=str(obj["ts"]),
    )


def _parse_episode_stop(obj: dict) -> EpisodeStopped:
    _require(obj, "e", "o", "r", "a", "rs")
    return EpisodeStopped(
        episode_id=str(obj["e"]),
        ordinal=int(obj["o"]),
        stop_reason=str(obj["r"]),
        archive=int(obj["a"]),
        recording_suspect=int(obj["rs"]),
    )


def _parse_episode_discard(obj: dict) -> EpisodeDiscarded:
    _require(obj, "e", "o")
    return EpisodeDiscarded(
        episode_id=str(obj["e"]),
        ordinal=int(obj["o"]),
    )


def _parse_session_signin(obj: dict) -> SessionSignin:
    _require(obj, "sid", "k", "op", "site", "fob", "fob_sid")
    return SessionSignin(
        session_id=str(obj["sid"]),
        kit_id=str(obj["k"]),
        operator_id=str(obj["op"]),
        site_id=str(obj["site"]),
        fob_id=str(obj["fob"]),
        fob_session_id=str(obj["fob_sid"]),
    )


def _parse_assignment(obj: dict) -> StationAssignment:
    _require(obj, "stn", "tid", "tn", "rv", "ts", "k")
    return StationAssignment(
        station_id=str(obj["stn"]),
        task_id=str(obj["tid"]),
        task_name=str(obj["tn"]),
        rotation_id=str(obj["rv"]),
        task_source=str(obj["ts"]),
        kit_id=str(obj["k"]),
    )


_EPISODE_DISPATCH = {
    "start": _parse_episode_start,
    "stop": _parse_episode_stop,
    "discard": _parse_episode_discard,
}


def parse_fob_log(path: Path) -> FobLogResult:
    """Parse a fob JSONL dump file. Unknown types/subtypes are skipped; malformed lines are errors."""
    result = FobLogResult()

    lines = path.read_text(encoding="utf-8").splitlines()
    for line_no, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue

        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            result.parse_errors.append((line_no, raw_line, f"JSON: {exc}"))
            continue

        if not isinstance(obj, dict):
            result.parse_errors.append((line_no, raw_line, "not a JSON object"))
            continue

        t = obj.get("T")
        if t is None:
            result.parse_errors.append((line_no, raw_line, "missing 'T' discriminator"))
            continue

        try:
            if t == "O":
                result.ordinals.append(_parse_ordinal(obj))
            elif t == "E":
                st = obj.get("st")
                handler = _EPISODE_DISPATCH.get(st)  # type: ignore[arg-type]
                if handler is None:
                    result.skipped_lines.append(
                        (line_no, raw_line, f"unknown episode subtype: {st!r}")
                    )
                    continue
                entry = handler(obj)
                if isinstance(entry, EpisodeStarted):
                    result.episode_starts.append(entry)
                elif isinstance(entry, EpisodeStopped):
                    result.episode_stops.append(entry)
                elif isinstance(entry, EpisodeDiscarded):
                    result.episode_discards.append(entry)
            elif t == "S":
                st = obj.get("st")
                if st == "signin":
                    result.session_signins.append(_parse_session_signin(obj))
                elif st == "call":
                    result.skipped_lines.append(
                        (line_no, raw_line, "LLAMAR call-lead (being removed in R1)")
                    )
                else:
                    result.skipped_lines.append(
                        (line_no, raw_line, f"unknown session subtype: {st!r}")
                    )
            elif t == "A":
                result.assignments.append(_parse_assignment(obj))
            else:
                result.skipped_lines.append((line_no, raw_line, f"unknown type: {t!r}"))
        except (KeyError, ValueError, TypeError) as exc:
            result.parse_errors.append((line_no, raw_line, str(exc)))

    return result
