# Contributing to Eunomia

> Authored in Run 0a from the conventions stated for this project. It encodes those conventions only —
> nothing invented. The git/PR/agent rules below are the working agreement.

## Git conventions

- **Bracket commit tags** — every commit subject starts with one of:
  `[FEAT]` · `[FIX]` · `[REFACTOR]` · `[CHORE]` · `[DOCS]` · `[TEST]`.
- **Branch prefixes** — `mzcassim/…` for Mo's branches; `agent/<run>-…` for an agent run's work
  (e.g. `agent/0a-foundation`).
- **Report before opening a PR** — summarize what changed + the gate results and **wait for the
  go-ahead** before opening the PR.
- **Squash-merge** — PRs land as a single squashed commit.
- **Never force-push `main`.**

## The one-machine rule

When only one device/rig is available, the **default target is the mock/host path** — real hardware
is never assumed by a test. (The firmware core is hardware-free and host-testable via
`pio test -e native`.)

## Gates

Run everything with `make gates`. Local == CI. The blocking gates:

- **Python** (verbatim, in order): `uv run pytest` → `uv run ruff check .` →
  `uv run ruff format --check .` → `uv run mypy .` → `uv run lint-imports`.
- **C++**: `clang-format --dry-run -Werror`, the off-target build + unit test (`pio test -e native`).
- **Cross-language**: the **conformance gate** (everything emitting/consuming the data validates
  against the generated JSON Schema + golden fixtures) and the **codegen-drift** gate
  (`make codegen && git diff --exit-code contracts/_generated`).
- **esp32 target build — now BLOCKING** (Run F1, OQ-13): flipped on when `firmware/coordinator/core/`
  landed (core/ is pure C++17 and must cross-compile for the ESP32 it will run on; built under
  `-fno-exceptions -fno-rtti`). **`clang-tidy` stays non-blocking** until `transport/`/`ui/` land (F2).

The dependency law — **everything depends only on `contracts/`** — is enforced by the per-language
import-boundary check (import-linter for Python) plus the cross-language conformance gate.

The contract is versioned (CONTRACT §5): a contract change is its own reviewed PR with a version bump
+ changelog; consumers (Hermes) pin a version and never silently track HEAD.

## Execution environment

- Runs under **Conductor** on a git worktree. The repo root is `$CONDUCTOR_ROOT_PATH`; hook scripts
  use `$CLAUDE_PROJECT_DIR`. Agent shells are detectable via the `CLAUDECODE` / `CLAUDE_CODE` env vars.
- Deterministic enforcement lives in `.claude/` (hooks), not prose — see `.claude/settings.json`.
