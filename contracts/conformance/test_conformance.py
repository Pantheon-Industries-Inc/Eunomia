"""Cross-target conformance for the real Eunomia contract (Run 0b) — the HYBRID validator.

Proves the three generated targets agree on the same golden fixtures:

* the **real ``jsonschema`` library** (Draft 2020-12, the dev/CI structural layer) accepts every
  ``valid/`` and rejects every ``invalid/``;
* the **shipped pure-stdlib overlay** (``eunomia_contracts.<entity>.validate_full``) supplies the
  hard-vs-warn SEVERITY split JSON Schema can't express: ``warn/`` fixtures are valid-with-warnings
  (not rejected, not silently passed), hard failures are rejected, and a malformed WARN field is
  DOWNGRADED to a warning (the structural error ``jsonschema`` flags is not a hard failure);
* the overlay also catches a SEMANTIC cross-field violation ``jsonschema`` cannot (``semantic_invalid/``:
  jsonschema accepts, the overlay hard-rejects ``void`` without ``void_reason``).

The two validators are distinct (CONTRACT §6, OQ-1): ``jsonschema`` is dev/CI-only (the structural
layer); the stdlib overlay is what SHIPS to the field. They share the generated tables, so they agree
on the hard layer by construction — this gate proves it on fixtures.

The C++ target's structural-subset agreement is proven separately by ``pio test -e native``
(firmware/coordinator/test/test_contract.cpp), which parses the SAME ``valid/``/``warn/`` fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from eunomia_contracts import release, sidecar, sync_delta, telemetry_event
from eunomia_contracts.interfaces import CaptureDevicePort, CoordinatorPort

HERE = Path(__file__).resolve().parent
SCHEMA_DIR = HERE.parent / "_generated" / "jsonschema"
FIXTURES = HERE / "fixtures"

# entity module -> (its JSON Schema file base, its shipped stdlib validate_full)
ENTITIES = {
    "sidecar": ("eunomia-sidecar", sidecar.validate_full),
    "release": ("eunomia-release", release.validate_full),
    "telemetry_event": ("eunomia-telemetry-event", telemetry_event.validate_full),
    "sync_delta": ("eunomia-sync-delta", sync_delta.validate_full),
}


def _js_valid(entity: str, obj: dict) -> bool:
    base = ENTITIES[entity][0]
    schema = json.loads((SCHEMA_DIR / f"{base}.schema.json").read_text())
    return jsonschema.Draft202012Validator(schema).is_valid(obj)


def _validate_full(entity: str, obj: dict) -> tuple[list[str], list[str]]:
    return ENTITIES[entity][1](obj)


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _cases(bucket: str) -> list:
    out = []
    for entity in ENTITIES:
        directory = FIXTURES / entity / bucket
        if directory.exists():
            for path in sorted(directory.glob("*.json")):
                out.append(pytest.param(entity, path, id=f"{entity}/{path.name}"))
    return out


@pytest.mark.parametrize("entity,path", _cases("valid"))
def test_valid_accepted_by_both(entity: str, path: Path) -> None:
    obj = _load(path)
    assert _js_valid(entity, obj), f"{path.name}: jsonschema rejected a valid fixture"
    hard, _warnings = _validate_full(entity, obj)
    assert hard == [], f"{path.name}: stdlib hard errors on a valid fixture: {hard}"


@pytest.mark.parametrize("entity,path", _cases("invalid"))
def test_invalid_rejected_by_both(entity: str, path: Path) -> None:
    obj = _load(path)
    assert not _js_valid(entity, obj), (
        f"{path.name}: jsonschema accepted an invalid fixture"
    )
    hard, _warnings = _validate_full(entity, obj)
    assert hard != [], f"{path.name}: stdlib accepted an invalid fixture"


@pytest.mark.parametrize("entity,path", _cases("warn"))
def test_warn_is_valid_with_warnings(entity: str, path: Path) -> None:
    obj = _load(path)
    hard, warnings = _validate_full(entity, obj)
    assert hard == [], f"{path.name}: warn fixture produced HARD errors: {hard}"
    assert warnings, (
        f"{path.name}: warn fixture produced no warnings (severity split not exercised)"
    )


@pytest.mark.parametrize("entity,path", _cases("semantic_invalid"))
def test_semantic_invalid_overlay_only(entity: str, path: Path) -> None:
    """jsonschema accepts (structurally fine); the overlay's cross-field rule hard-rejects."""
    obj = _load(path)
    assert _js_valid(entity, obj), (
        f"{path.name}: should be structurally valid for jsonschema"
    )
    hard, _warnings = _validate_full(entity, obj)
    assert hard != [], (
        f"{path.name}: overlay should hard-reject the cross-field violation"
    )


def test_warn_field_downgrade_distinguishes_hard_from_warn() -> None:
    """The headline: a malformed WARN field is a jsonschema structural error but only a WARNING."""
    obj = _load(FIXTURES / "sidecar" / "warn" / "malformed_warn_field.json")
    assert not _js_valid("sidecar", obj), (
        "jsonschema should flag the warn-field type error"
    )
    hard, warnings = _validate_full("sidecar", obj)
    assert hard == [], (
        "a malformed WARN field must NOT be a hard failure (the downgrade)"
    )
    assert any("episode_ordinal" in w for w in warnings), (
        "the warn-field problem must be surfaced"
    )


def test_fully_populated_record_has_no_warnings() -> None:
    """A fully-populated valid record is clean on BOTH channels (no spurious warnings)."""
    hard, warnings = _validate_full(
        "sidecar", _load(FIXTURES / "sidecar" / "valid" / "full.json")
    )
    assert hard == [] and warnings == [], (
        f"expected clean, got hard={hard} warnings={warnings}"
    )


def test_validate_matches_validate_full_hard_channel() -> None:
    """The shipped validate() (hard-only) equals validate_full()[0] across every fixture."""
    for entity, (_base, _vf) in ENTITIES.items():
        for path in sorted((FIXTURES / entity).rglob("*.json")):
            obj = _load(path)
            hard_only = {
                "sidecar": sidecar,
                "release": release,
                "telemetry_event": telemetry_event,
                "sync_delta": sync_delta,
            }[entity].validate(obj)
            assert hard_only == _validate_full(entity, obj)[0], (
                f"{entity}/{path.name}: validate disagrees"
            )


# ---- interface ports (Run 0c): the generated Python Protocol is implementable ----
# The ``: CoordinatorPort = …`` / ``: CaptureDevicePort = …`` annotated assignments below are the
# mypy STRUCTURAL-CONFORMANCE assertions (verified by the `mypy .` gate, not at runtime). The C++
# abstract header's implementability is proven separately by `pio test -e native`
# (firmware/coordinator/test/test_contract.cpp). The two artifacts come from ONE source
# (interfaces/ports.iface.yaml), so the codegen-drift gate is the cross-language in-sync proof.


class _MockCoordinator:
    def mint_episode_id(self) -> str:
        return "00000000-0000-4000-8000-000000000000"

    def trigger(self, cameras: set[str]) -> bool:
        return len(cameras) == 2

    def read_clip_filename(self, camera: str) -> str:
        return f"VID_{camera}.insv"

    def write_sidecar(self, camera: str, record: sidecar.Sidecar) -> None: ...

    def detect_drop(self) -> set[str]:
        return set()

    def flush_telemetry(self) -> None: ...


class _MockCaptureDevice:
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def read_back_filename(self) -> str:
        return "VID_00.insv"

    def get_state(self) -> str:
        return "idle"

    def set_profile(self, profile: str) -> None: ...

    def write_sidecar(self, record: sidecar.Sidecar) -> None: ...


def test_coordinator_port_satisfied_by_mock() -> None:
    port: CoordinatorPort = _MockCoordinator()  # mypy: structural conformance
    assert port.trigger({"left", "right"}) is True
    assert port.detect_drop() == set()
    port.write_sidecar("left", sidecar.Sidecar())


def test_capture_device_port_satisfied_by_mock() -> None:
    device: CaptureDevicePort = _MockCaptureDevice()  # mypy: structural conformance
    assert device.read_back_filename().endswith(".insv")
    assert device.get_state() == "idle"
    device.set_profile("3K/100")
