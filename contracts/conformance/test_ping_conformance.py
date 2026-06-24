"""Cross-target conformance test for the Run 0a ``ping`` codegen proof.

Proves the three generated targets agree on the SAME golden fixtures:
  * the generated JSON Schema accepts every ``valid/`` and rejects every ``invalid/``;
  * the generated Python validator (``eunomia_contracts.validate``) agrees with the
    schema on each fixture.

The C++ target is exercised separately by ``pio test -e native``
(firmware/coordinator/test/test_ping_contract.cpp), which parses the SAME fixtures
with the generated header. The conformance gate is the conjunction of this test and
that native test.
"""

from __future__ import annotations

import json
from pathlib import Path

from eunomia_contracts import validate

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parent
SCHEMA = json.loads(
    (CONTRACTS / "_generated" / "jsonschema" / "ping.schema.json").read_text()
)
FIXTURES = HERE / "fixtures" / "ping"

# JSON Schema type -> the Python type(s) a value of that type must be.
_JSON_TO_PY: dict[str, object] = {
    "integer": int,
    "number": (int, float),
    "string": str,
    "boolean": bool,
}


def _schema_errors(obj: dict) -> list[str]:
    """Apply the generated JSON Schema (the subset we emit) using only the stdlib.

    Reads the generated schema artifact (not the source) so this genuinely tests the
    emitted JSON Schema target, not a re-derivation of it.
    """
    errors: list[str] = []
    for field in SCHEMA.get("required", []):
        if field not in obj:
            errors.append(f"missing required: {field}")
    for name, spec in SCHEMA.get("properties", {}).items():
        if name not in obj:
            continue
        value = obj[name]
        expected = _JSON_TO_PY[spec["type"]]
        # In JSON Schema a bool is NOT a valid integer/number (unlike Python's bool<int).
        if isinstance(value, bool) and spec["type"] in ("integer", "number"):
            errors.append(f"type: {name}")
        elif not isinstance(value, expected):  # type: ignore[arg-type]
            errors.append(f"type: {name}")
    return errors


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_valid_fixtures_pass_schema_and_validator() -> None:
    files = sorted((FIXTURES / "valid").glob("*.json"))
    assert files, "no valid fixtures found"
    for f in files:
        obj = _load(f)
        assert _schema_errors(obj) == [], (
            f"{f.name}: JSON Schema rejected a valid fixture"
        )
        assert validate(obj) == [], (
            f"{f.name}: Python validator rejected a valid fixture"
        )


def test_invalid_fixtures_fail_schema_and_validator() -> None:
    files = sorted((FIXTURES / "invalid").glob("*.json"))
    assert files, "no invalid fixtures found"
    for f in files:
        obj = _load(f)
        assert _schema_errors(obj), f"{f.name}: JSON Schema accepted an invalid fixture"
        assert validate(obj), f"{f.name}: Python validator accepted an invalid fixture"


def test_schema_and_validator_agree() -> None:
    for sub in ("valid", "invalid"):
        for f in sorted((FIXTURES / sub).glob("*.json")):
            obj = _load(f)
            assert bool(_schema_errors(obj)) == bool(validate(obj)), (
                f"{f.name}: targets disagree"
            )
