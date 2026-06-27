"""Uplink-safety gate — port of Victor's netwifi.py::uplink_safe().

The Mac MUST have a non-WiFi uplink (USB tether, ethernet) before switching en0 to a camera/fob AP.
Joining the AP without a backup uplink strands the Mac. Non-circumventable.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass
class UplinkStatus:
    safe: bool
    default_interface: str
    reason: str


def get_default_interface() -> str:
    """Return the interface name carrying the default route (macOS)."""
    try:
        result = subprocess.run(
            ["route", "-n", "get", "default"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        match = re.search(r"interface:\s*(\S+)", result.stdout)
        return match.group(1) if match else ""
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def uplink_safe() -> UplinkStatus:
    """Check whether the Mac has a non-WiFi uplink for the default route.

    Safe iff the default route is NOT on en0 (WiFi). A USB tether, ethernet
    dongle, or Thunderbolt bridge carries the internet while en0 joins the
    camera/fob AP.
    """
    iface = get_default_interface()
    if not iface:
        return UplinkStatus(
            safe=False,
            default_interface="",
            reason="Could not determine default route interface",
        )
    if iface == "en0":
        return UplinkStatus(
            safe=False,
            default_interface=iface,
            reason="Default route is on en0 (WiFi) — plug in a USB tether or ethernet before provisioning",
        )
    return UplinkStatus(
        safe=True,
        default_interface=iface,
        reason=f"Default route on {iface} (non-WiFi) — safe to join camera AP",
    )
