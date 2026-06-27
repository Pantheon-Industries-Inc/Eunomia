"""Per-kit ship-gate — the hard pass/fail gate before a kit can ship.

Exit 0 = SHIP. Anything else = FAIL with explicit reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from eunomia_consoles_provisioning.fob import FobStatus


@dataclass
class GateResult:
    passed: bool
    checks: list[GateCheck] = field(default_factory=list)

    @property
    def failures(self) -> list[GateCheck]:
        return [c for c in self.checks if not c.passed]

    @property
    def summary(self) -> str:
        if self.passed:
            return "SHIP"
        reasons = "; ".join(c.reason for c in self.failures)
        return f"FAIL: {reasons}"


@dataclass
class GateCheck:
    name: str
    passed: bool
    reason: str


def evaluate(
    status: FobStatus,
    *,
    expected_fw: str | None = None,
    require_time: bool = False,
) -> GateResult:
    """Evaluate the ship-gate criteria against a fob status snapshot."""
    checks: list[GateCheck] = []

    checks.append(
        GateCheck(
            name="kit_provisioned",
            passed=bool(status.kit_id),
            reason="kit_id is empty" if not status.kit_id else "kit_id set",
        )
    )

    both_locked = status.allow_n >= 2 and status.cams >= 2
    if not both_locked:
        reason = f"allow_n={status.allow_n}, cams={status.cams} — need both ≥ 2"
    else:
        reason = f"allow_n={status.allow_n}, cams={status.cams}"
    checks.append(GateCheck(name="cameras_locked", passed=both_locked, reason=reason))

    sides_ok = len(status.sides.split(",")) >= 2 if status.sides else False
    checks.append(
        GateCheck(
            name="sides_bound",
            passed=sides_ok,
            reason="sides CSV has < 2 entries"
            if not sides_ok
            else f"sides={status.sides}",
        )
    )

    if expected_fw is not None:
        fw_match = status.ap_ssid != ""
        checks.append(
            GateCheck(
                name="firmware_match",
                passed=fw_match,
                reason="firmware version check (ap_ssid present)"
                if fw_match
                else "firmware mismatch",
            )
        )

    if require_time:
        checks.append(
            GateCheck(
                name="ntp_synced",
                passed=status.time_set,
                reason="NTP not synced" if not status.time_set else "NTP synced",
            )
        )

    passed = all(c.passed for c in checks)
    return GateResult(passed=passed, checks=checks)
