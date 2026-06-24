# Eunomia

The clean, unified on-site **capture → ingest → identity → QC → ops** system: one polyglot monorepo
(C++ ESP32 firmware, Python services/ingest/tooling, a web console stack, the ported host substrate,
and the cross-cutting contracts). Eunomia produces the release metadata the **Hermes** analytical
platform ingests, and feeds the downstream cleaning/render layer (Hermes-side).

The one rule that makes it modular: **everything depends only on `contracts/`** (the versioned,
language-neutral spine). Codegen turns one source into three targets — a C++ header, a Python type,
and a JSON Schema — so every stack consumes the same definition.

## Layout

| Module | Responsibility |
|---|---|
| `contracts/` | the spine — versioned data + interface definitions; codegen (one source → three targets) |
| `firmware/` | the kit (C++ / PlatformIO, ESP32): the fob coordinator + the camera-image packaging |
| `ingest/` | identity, QC, dual-signal join, and the release record (Python) |
| `edge/` | the on-site, edge-authoritative operational store + sync + API |
| `consoles/` | the operator/supervisor/HQ UIs (web; each a separately-deployable island) |
| `substrate/` | the ported host substrate (ZFS / card-reader / udev / systemd) — **interface frozen** |
| `tooling/` | engineering tooling (the bench harness) |
| `docs/` | the authority docs (contract, module map, spec, decisions, build plan, ADR) |

## Run the gates

```sh
make gates          # all blocking gates (python + cpp + codegen-drift), local == CI == Hermes
make gates-python   # uv run pytest -> ruff check . -> ruff format --check . -> mypy . -> lint-imports
make gates-cpp      # clang-format + the off-target `pio test -e native` + the checksum stub
make codegen        # regenerate contracts/_generated from the neutral source
make drift          # codegen + assert contracts/_generated is unchanged
```

Prereqs: [`uv`](https://docs.astral.sh/uv/) (Python 3.12, managed), `clang-format`, and
[PlatformIO](https://platformio.org/) (`pio`). `uv sync --all-packages` installs the workspace.
The esp32 target build + `clang-tidy` are present but **non-blocking** in the Foundation run.

## How we work (plan-mode)

Plan before implementing; the cost of pausing is near zero, the cost of wrong edits is high. Ambiguity
becomes an open question in the plan, not a silent choice. Report what changed + the gate results and
wait for the go-ahead before opening a PR. See `docs/CONTRIBUTING.md` and `CLAUDE.md`.
