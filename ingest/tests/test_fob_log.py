"""Pure-logic tests for the fob log parser (no DB)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eunomia_ingest.fob_log import parse_fob_log

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FOB_DUMP = FIXTURES / "fob_dump.jsonl"


@pytest.fixture
def fob_dump() -> Path:
    return FOB_DUMP


def test_parse_all_known_types(fob_dump: Path) -> None:
    result = parse_fob_log(fob_dump)
    assert len(result.ordinals) == 2
    assert len(result.episode_starts) == 2
    assert len(result.episode_stops) == 2
    assert len(result.episode_discards) == 1
    assert len(result.session_signins) == 1
    assert len(result.assignments) == 1


def test_ordinal_entry_fields(fob_dump: Path) -> None:
    result = parse_fob_log(fob_dump)
    o = result.ordinals[0]
    assert o.ordinal == 1
    assert o.wallclock_unix == 1750000000
    assert o.kit_id == "kit_07"
    assert o.fob_id == "fob_3"
    assert o.fob_session_id == "1a2b3c4d"
    assert o.episode_id == "550e8400-e29b-41d4-a716-446655440000"


def test_episode_start_fields(fob_dump: Path) -> None:
    result = parse_fob_log(fob_dump)
    s = result.episode_starts[0]
    assert s.ordinal == 1
    assert s.kit_id == "kit_07"
    assert s.episode_id == "550e8400-e29b-41d4-a716-446655440000"
    assert s.operator_id == "op_123"
    assert s.station_id == "5"
    assert s.task_id == "t_fold"
    assert s.task_name == "Fold the towel"
    assert s.rotation_id == "r2"
    assert s.task_source == "sd_assignment"


def test_episode_stop_fields(fob_dump: Path) -> None:
    result = parse_fob_log(fob_dump)
    s = result.episode_stops[0]
    assert s.episode_id == "550e8400-e29b-41d4-a716-446655440000"
    assert s.ordinal == 1
    assert s.stop_reason == "operator"
    assert s.archive == 0
    assert s.recording_suspect == 0


def test_episode_discard_fields(fob_dump: Path) -> None:
    result = parse_fob_log(fob_dump)
    d = result.episode_discards[0]
    assert d.episode_id == "770e8400-e29b-41d4-a716-446655440002"
    assert d.ordinal == 3


def test_session_signin_fields(fob_dump: Path) -> None:
    result = parse_fob_log(fob_dump)
    s = result.session_signins[0]
    assert s.session_id == "sess_xyz"
    assert s.kit_id == "kit_07"
    assert s.operator_id == "op_123"
    assert s.site_id == "mx_1"
    assert s.fob_id == "fob_3"
    assert s.fob_session_id == "1a2b3c4d"


def test_assignment_fields(fob_dump: Path) -> None:
    result = parse_fob_log(fob_dump)
    a = result.assignments[0]
    assert a.station_id == "5"
    assert a.task_id == "t_fold"
    assert a.task_name == "Fold the towel"
    assert a.rotation_id == "r2"
    assert a.task_source == "sd_assignment"
    assert a.kit_id == "kit_07"


def test_llamar_call_skipped(fob_dump: Path) -> None:
    result = parse_fob_log(fob_dump)
    llamar_skips = [s for s in result.skipped_lines if "LLAMAR" in s[2]]
    assert len(llamar_skips) == 1


def test_unknown_type_skipped(fob_dump: Path) -> None:
    result = parse_fob_log(fob_dump)
    unknown_skips = [s for s in result.skipped_lines if "unknown type" in s[2]]
    assert len(unknown_skips) == 1


def test_malformed_json_error(fob_dump: Path) -> None:
    result = parse_fob_log(fob_dump)
    json_errors = [e for e in result.parse_errors if "JSON" in e[2]]
    assert len(json_errors) == 1


def test_unknown_session_subtype_skipped(tmp_path: Path) -> None:
    log = tmp_path / "test.jsonl"
    log.write_text('{"T":"S","st":"future_event","sid":"s1","k":"k1"}\n')
    result = parse_fob_log(log)
    assert len(result.skipped_lines) == 1
    assert "unknown session subtype" in result.skipped_lines[0][2]


def test_missing_required_field_error(tmp_path: Path) -> None:
    log = tmp_path / "test.jsonl"
    log.write_text('{"T":"O","o":1}\n')
    result = parse_fob_log(log)
    assert len(result.parse_errors) == 1
    assert "missing required" in result.parse_errors[0][2]


def test_empty_log(tmp_path: Path) -> None:
    log = tmp_path / "empty.jsonl"
    log.write_text("")
    result = parse_fob_log(log)
    assert result.ordinals == []
    assert result.episode_starts == []
    assert result.parse_errors == []


def test_blank_lines_skipped(tmp_path: Path) -> None:
    log = tmp_path / "blanks.jsonl"
    log.write_text("\n\n  \n")
    result = parse_fob_log(log)
    assert result.ordinals == []
    assert result.parse_errors == []


def test_line_numbers_tracked(fob_dump: Path) -> None:
    result = parse_fob_log(fob_dump)
    all_line_nos = [s[0] for s in result.skipped_lines] + [
        e[0] for e in result.parse_errors
    ]
    assert all(isinstance(n, int) and n >= 1 for n in all_line_nos)


def test_task_source_boot_config_accepted(tmp_path: Path) -> None:
    """R1 note: old logs use boot_config, new logs use operator. Both accepted."""
    log = tmp_path / "test.jsonl"
    lines = [
        json.dumps(
            {
                "T": "E",
                "st": "start",
                "o": 1,
                "k": "k",
                "e": "e1",
                "op": "o",
                "stn": "s",
                "tid": "t",
                "tn": "n",
                "rv": "r",
                "ts": "boot_config",
            }
        ),
        json.dumps(
            {
                "T": "E",
                "st": "start",
                "o": 2,
                "k": "k",
                "e": "e2",
                "op": "o",
                "stn": "s",
                "tid": "t",
                "tn": "n",
                "rv": "r",
                "ts": "operator",
            }
        ),
    ]
    log.write_text("\n".join(lines))
    result = parse_fob_log(log)
    assert len(result.episode_starts) == 2
    assert result.episode_starts[0].task_source == "boot_config"
    assert result.episode_starts[1].task_source == "operator"
    assert result.parse_errors == []
