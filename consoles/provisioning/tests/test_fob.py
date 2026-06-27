"""Tests for fob serial protocol — pure parsing (no hardware)."""

from __future__ import annotations

import json

from eunomia_consoles_provisioning.fob import FobStatus, parse_status


def test_parse_status_full() -> None:
    raw = json.dumps(
        {
            "kit_id": "kit_001",
            "operator_id": "op-42",
            "station": "1000",
            "cams": 2,
            "ordinal": 15,
            "time_set": True,
            "ap_ssid": "PANTHEON-KIT-001",
            "ap_ch": 6,
            "sides": "aa:bb:cc:dd:ee:01,aa:bb:cc:dd:ee:02",
            "free_heap": 200000,
            "min_heap": 150000,
            "largest_free_block": 100000,
            "log_bytes": 512,
        }
    )
    s = parse_status(raw)
    assert s.kit_id == "kit_001"
    assert s.cams == 2
    assert s.ordinal == 15
    assert s.time_set is True
    assert s.ap_ch == 6
    assert s.allow_n == 2
    assert s.largest_free_block == 100000


def test_parse_status_minimal() -> None:
    raw = json.dumps({"kit_id": "k", "cams": 0})
    s = parse_status(raw)
    assert s.kit_id == "k"
    assert s.cams == 0
    assert s.allow_n == 0
    assert s.sides == ""


def test_allow_n_counts_sides() -> None:
    s = FobStatus(sides="a,b")
    assert s.allow_n == 2


def test_allow_n_empty_sides() -> None:
    s = FobStatus(sides="")
    assert s.allow_n == 0


def test_raw_preserved() -> None:
    data = {"kit_id": "x", "extra_field": 42}
    s = parse_status(json.dumps(data))
    assert s.raw["extra_field"] == 42
