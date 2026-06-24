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
| `codegen/` | the generator (neutral source → C++/Python/JSON Schema) + the drift gate |
| `_proof/` | **Run 0a only** — a throwaway `ping` example proving the pipeline. 0b deletes it. |
| `_generated/` | committed, drift-gated codegen outputs (`cpp/`, `python/`, `jsonschema/`) — **do not hand-edit** |
| `conformance/` | golden fixtures + the cross-target conformance test |
| `sidecar/` | the on-card `eunomia-sidecar` schema (CONTRACT §2) — **filled in 0b** |
| `operational/` | the event-sourced operational model (CONTRACT §3) — **filled in 0b** |
| `release/` | the release metadata Hermes pins + ingests (CONTRACT §4) — **filled in 0b** |
| `interfaces/` | the hardware seams (CoordinatorPort, CaptureDevicePort) — **filled in 0b** |
| `events/` | the telemetry-event schema + the operational-sync delta — **filled in 0b** |

> Run 0a stands up the stub + the proven codegen harness only. The real schemas are poured in 0b
> against this known-good harness.
