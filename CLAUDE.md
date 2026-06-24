# Eunomia

Eunomia is the clean, unified replacement for the whole on-site capture + ingest + identity + QC + ops
level — the convergence of two existing codebases (the card-drain/ops side and the ingest/identity/QC
pipeline) plus the specced flows + consoles, into one polyglot monorepo (C++ firmware, Python
services/ingest/tooling, a web console stack, the ported host substrate, the cross-cutting contracts).
It produces the release metadata the **Hermes** analytical platform (separate repo, on Hades) ingests,
and FEEDS the downstream cleaning/render layer (Hermes-side, not part of Eunomia).

## The dependency law

**Everything depends only on `contracts/`.** `contracts/` imports nothing. A console never imports
firmware; firmware never imports a service. Enforced by import-linter (Python) + the cross-language
conformance gate (anything emitting/consuming the data validates against the generated JSON Schema).

## Where things live

- `contracts/` — the spine: the versioned, language-neutral data + interface definitions. Codegen
  emits **one source, three targets** (C++ header / Python type / JSON Schema). `contracts/_generated/`
  is generated + committed — **never hand-edit it**; edit the source and run `make codegen`.
- `firmware/` (C++/ESP32) · `ingest/` · `edge/` · `consoles/` · `substrate/` (frozen) · `tooling/`.
  Each module's README states its single responsibility + dependency rule.
- `docs/` — the authority docs. `docs/CONTRACT.md` is the data-model spine; `docs/MODULE_MAP.md` is
  the structure authority; `docs/SPEC.md` is the long-form lifecycle; `docs/DECISION_REGISTER.md` is
  the decisions + open questions; `docs/BUILD_PLAN.md` is the phase sequence + current scope;
  `docs/adr/0001-architecture.md` is this architecture. (These are large — read by path on demand.)

## Conventions

@docs/CONTRIBUTING.md

## Gates (local == CI == Hermes)

Run `make gates`. Blocking: the five Python gates (`uv run pytest` → `ruff check .` →
`ruff format --check .` → `mypy .` → `lint-imports`, in that order, on tool defaults), the C++
`clang-format --dry-run -Werror` + the off-target `pio test -e native`, the cross-language conformance
gate, and the codegen-drift gate (`make codegen && git diff --exit-code contracts/_generated`).
Non-blocking in Run 0a: the esp32 target build and `clang-tidy`.

The repo uses **uv** (Python 3.12, a workspace with per-package members) and **PlatformIO** (the ESP32
coordinator, with a `native` off-target test env). The contract is versioned: a contract change is its
own reviewed PR with a version bump + changelog; Hermes pins a version.

## Working agreement (plan-mode)

Plan before you implement. The cost of pausing is near zero; the cost of wrong edits is high. When a
decision is ambiguous, write the options into the plan as an open question rather than picking one
silently. Report what changed + the gate results and wait for the go-ahead before opening a PR; never
force-push `main`.
