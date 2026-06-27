"""Tests for the ship-gate evaluation logic."""

from __future__ import annotations

from eunomia_consoles_provisioning.fob import FobStatus
from eunomia_consoles_provisioning.ship_gate import evaluate


def _status(**overrides: object) -> FobStatus:
    defaults = {
        "kit_id": "kit_001",
        "cams": 2,
        "sides": "aa:bb:cc:dd:ee:01,aa:bb:cc:dd:ee:02",
        "time_set": True,
        "ap_ssid": "PANTHEON-KIT-001",
    }
    defaults.update(overrides)
    return FobStatus(**defaults)  # type: ignore[arg-type]


def test_all_pass() -> None:
    result = evaluate(_status())
    assert result.passed
    assert result.summary == "SHIP"
    assert len(result.failures) == 0


def test_empty_kit_id_fails() -> None:
    result = evaluate(_status(kit_id=""))
    assert not result.passed
    assert any(c.name == "kit_provisioned" and not c.passed for c in result.checks)


def test_insufficient_cams_fails() -> None:
    result = evaluate(_status(cams=1))
    assert not result.passed
    assert any(c.name == "cameras_locked" and not c.passed for c in result.checks)


def test_no_sides_fails() -> None:
    result = evaluate(_status(sides=""))
    assert not result.passed
    assert any(c.name == "sides_bound" and not c.passed for c in result.checks)


def test_single_side_fails() -> None:
    result = evaluate(_status(sides="aa:bb:cc:dd:ee:01"))
    assert not result.passed


def test_ntp_required_but_not_set() -> None:
    result = evaluate(_status(time_set=False), require_time=True)
    assert not result.passed
    assert any(c.name == "ntp_synced" and not c.passed for c in result.checks)


def test_ntp_not_required_skips_check() -> None:
    result = evaluate(_status(time_set=False), require_time=False)
    assert result.passed
    assert not any(c.name == "ntp_synced" for c in result.checks)


def test_allow_n_property() -> None:
    s = _status(sides="a,b,c")
    assert s.allow_n == 3


def test_allow_n_empty() -> None:
    s = _status(sides="")
    assert s.allow_n == 0


def test_gate_result_summary_with_failures() -> None:
    result = evaluate(_status(kit_id="", cams=0, sides=""))
    assert not result.passed
    assert "FAIL:" in result.summary
    assert len(result.failures) >= 3
