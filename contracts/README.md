# `contracts/` — the spine

**Single responsibility:** the canonical, language-neutral, **versioned** definition of every piece
of Eunomia data and every hardware interface. This repo is the source of truth.

**Dependency rule:** `contracts/` **imports nothing** internal. Everything else depends on it; it
depends on no other module. (Enforced for Python by import-linter — `eunomia_contracts` is the
forbidden-from-importing-anything-internal spine; for C++/firmware by the include structure + the
conformance gate.)

**One source, three targets.** Each schema is authored once as a language-neutral source and
`contracts/codegen/` emits three consumables: a **C++ header** (firmware), a **Python type + a
pure-stdlib validator** (tooling/ingest/services), and a **JSON Schema** (the cross-language
conformance gate + web validation). See `codegen/README.md`.

**Versioning discipline** (CONTRACT §5): two orthogonal axes — a `schema` string (additive semver,
tells a parser which fields to expect) and a writer-owned `record_format_version` int (forensic
build-scoping). A contract change is its own reviewed PR with a version bump + changelog; Hermes pins
a version, so drift is a visible version gap, never silent.

## Layout

| Path | What lives here |
|---|---|
| `codegen/` | the generator (neutral source → C++/Python/JSON Schema) + templates + the pinned codegen deps |
| `_generated/` | committed, drift-gated codegen outputs (`cpp/`, `python/`, `jsonschema/`) — **do not hand-edit** |
| `conformance/` | golden fixtures (`valid/`·`invalid/`·`warn/`·`semantic_invalid/`) + the hybrid conformance test |
| `sidecar/` | the on-card `eunomia-sidecar` schema (CONTRACT §2) — **encoded in 0b** |
| `release/` | the release metadata Hermes pins + ingests (CONTRACT §4) — **encoded in 0b** |
| `events/` | the telemetry-event schema + the operational-sync delta — **encoded in 0b** |
| `operational/` | the event-sourced operational model (CONTRACT §3) — **deferred to 0c** (plan.md OQ-1) |
| `interfaces/` | the hardware seams (CoordinatorPort, CaptureDevicePort) — **deferred to 0c** (plan.md OQ-1) |

> **The validator (CONTRACT §6, Run 0b Option C — hybrid).** Two validators share one severity model.
> The SHIPPED one is `eunomia_contracts.<entity>.validate` / `validate_full` — pure-stdlib (no deps),
> runs cam-side / in ingest / on the edge; it applies the generated hard/warn tables + the hand-written
> cross-field rules in `_semantics`. The DEV/CI HYBRID one (`conformance/test_conformance.py`) uses the
> real `jsonschema` library (Draft 2020-12) for the structural layer + the same overlay for severity.
> `jsonschema` is dev-only and never ships.
