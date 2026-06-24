---
name: gates
description: How to run and debug the Eunomia gates locally (Python, C++, conformance, codegen-drift). Use when a gate is red or before reporting a run done.
---

# Running the gates

`make gates` runs every **blocking** gate. Local == CI == Hermes.

## The blocking gates

| Gate | Command | Debug tip |
|---|---|---|
| Python (5, in order) | `uv run pytest` → `uv run ruff check .` → `uv run ruff format --check .` → `uv run mypy .` → `uv run lint-imports` | These are the verbatim Hermes commands; run on tool DEFAULTS (no `[tool.ruff]`/`[tool.mypy]`). `ruff format .` auto-fixes formatting. |
| C++ format | `clang-format --dry-run -Werror <firmware files>` | `clang-format -i <file>` to auto-fix. Generated headers are exempt. |
| C++ off-target | `pio test -e native -d firmware/coordinator` | The host build + Unity tests; no hardware (the one-machine rule). Doubles as the C++ conformance proof. |
| Conformance | `uv run pytest` (Python+schema) ∧ `pio test -e native` (C++) | Both validate the SAME golden fixtures against the generated contract. |
| Codegen drift | `make drift` | If red: someone edited `contracts/_generated/` by hand, or changed the source without `make codegen`. Run `make codegen` and commit. |

## Non-blocking in Run 0a (OQ-13)

- `pio run -e esp32 -d firmware/coordinator` (the target build) — `make gates-cpp-nonblocking`.
- `clang-tidy` (configured in `.clang-tidy`).

Both flip to blocking when `firmware/coordinator/core/` lands.

## Setup

`uv sync --all-packages` (Python 3.12 workspace). C++ needs `clang-format` + PlatformIO (`pio`); the
`native` platform + Unity download on first `pio test`.
