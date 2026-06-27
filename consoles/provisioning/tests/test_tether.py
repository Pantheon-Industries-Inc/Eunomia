"""Tests for the tether-safety gate."""

from __future__ import annotations

from unittest.mock import patch

from eunomia_consoles_provisioning.tether import (
    UplinkStatus,
    get_default_interface,
    uplink_safe,
)


def test_uplink_safe_non_wifi() -> None:
    with patch(
        "eunomia_consoles_provisioning.tether.get_default_interface",
        return_value="en5",
    ):
        result = uplink_safe()
    assert result.safe is True
    assert result.default_interface == "en5"


def test_uplink_unsafe_wifi() -> None:
    with patch(
        "eunomia_consoles_provisioning.tether.get_default_interface",
        return_value="en0",
    ):
        result = uplink_safe()
    assert result.safe is False
    assert "en0" in result.reason


def test_uplink_no_interface() -> None:
    with patch(
        "eunomia_consoles_provisioning.tether.get_default_interface",
        return_value="",
    ):
        result = uplink_safe()
    assert result.safe is False
    assert "Could not determine" in result.reason


def test_get_default_interface_parses_route() -> None:
    mock_output = (
        "   route to: default\n"
        "destination: default\n"
        "       mask: default\n"
        "    gateway: 192.168.1.1\n"
        "  interface: en7\n"
    )
    with patch(
        "subprocess.run",
        return_value=type("Result", (), {"stdout": mock_output, "returncode": 0})(),
    ):
        assert get_default_interface() == "en7"


def test_uplink_status_dataclass() -> None:
    s = UplinkStatus(safe=True, default_interface="en5", reason="ok")
    assert s.safe
    assert s.default_interface == "en5"
