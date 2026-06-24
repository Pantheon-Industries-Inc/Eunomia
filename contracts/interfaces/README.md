# `contracts/interfaces/` — the hardware seams

The hardware swap-points as explicit interface definitions, so a board/camera swap is a new
implementation of the same port and nothing upstream changes (the adapt-not-rebuild seam). These are
**operation signatures, not records** — a different shape than the `contracts/*/…schema.yaml` field-DSL.

- **CoordinatorPort** — mint the episode id, trigger both cameras serialized, read back the clip
  filename, write the sidecar, detect a camera drop (at the network-association layer), flush
  telemetry. (The fob does NOT arm per take — the on-camera agent holds video mode.)
- **CaptureDevicePort** — start, stop, read-back-filename, get-state, set-profile, write-sidecar.

Authoritative description: `docs/CONTRACT.md` §1.6 / `docs/SPEC.md` §1.6 / `docs/MODULE_MAP.md`.

## How they're built (Run 0c — LEAD-OQ-A → option C)

One neutral signature source → **two** targets (no JSON Schema; an interface is not a data record):

- **Source:** `ports.iface.yaml` — a list of ports, each with operations (`name`, `params`, `returns`,
  `doc`).
- **Emitter:** `contracts/codegen/generate_interfaces.py` — a **separate** mini-emitter, NOT the record
  generator `generate.py`. Folding signatures into the record generator would grow it into a second
  type system (the STOP-and-flag line); a bounded, isolated emitter for a genuinely different artifact
  is the opposite of framework-creep. It runs as a **sibling** `make codegen` command (after
  `generate.py`), never imported by it (an intra-`codegen` import breaks `mypy .`-from-root).
- **Targets:** `_generated/cpp/eunomia_coordinator_port.h` + `…_capture_device_port.h` (pure-virtual
  abstract classes) and `_generated/python/eunomia_contracts/interfaces.py` (`typing.Protocol`s).
- **In sync by construction:** one source → both targets, so the single `make drift`
  (`git diff --exit-code contracts/_generated`) gate is the cross-language sync proof — they cannot
  drift. The C++ header's implementability is proven by `pio test -e native`
  (`firmware/coordinator/test/test_contract.cpp`); the Python Protocol's by a mypy-checked mock in
  `contracts/conformance/test_conformance.py`.

### The closed type vocabulary (held boundary)

An operation type MUST be one of: `uuid` · `str` · `filename` · `ack` · `camera` · `set[camera]` ·
`record` · `state` · `profile` · `void`. The emitter maps this **fixed** set to each language; it is
not a parser for an open type grammar. A type outside the set is a **STOP-and-flag** (the emitter
raises) — raise an OQ, do **not** extend the IDL. (`record` resolves to the contract's `Sidecar`
type — the generated dataclass / `const eunomia::Sidecar&` — the one type-safety link between a port
and the record it writes.)
