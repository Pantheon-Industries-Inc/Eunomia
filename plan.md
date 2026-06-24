# Run 0a — Eunomia Foundation: Implementation Plan (PLAN ONLY, rev 2)

**Status:** revised per your annotations. Every OQ-1…OQ-14 note is folded into the body; §6 is now the
resolution record (no open questions remain — two tiny Hermes-mirror confirmations flagged at the end
of §6). Still **not implemented** — awaiting "implement".

---

## 0. What I found in the repo (read-first results + discrepancies)

I read `Docs/CONTRACT.md`, `Docs/MODULE_MAP.md`, and the Run-0-blocking decisions in
`Docs/DECISION_REGISTER.md` in full, and skimmed `SPEC.md`, `VALIDATION_PLAN.md`,
`HARDWARE_FINDINGS.md`. Three things differ from what the run prompt assumed — resolved as step 1 of
implementation:

| Prompt expected | Actually in repo | Plan (approved) |
|---|---|---|
| `docs/` (lowercase) | **`Docs/`** (capital D), git-tracked | Rename to `docs/` via the two-step case-only `git mv` on this case-insensitive FS (OQ-1). Needed so the CLAUDE.md `@docs/...` import + the ADR path resolve on case-sensitive CI. |
| `docs/CONTRIBUTING.md` | **absent** | Author it in 0a from the conventions stated in the run prompt's "Execution environment" section + MODULE_MAP §docs — **stated conventions only, nothing invented** (OQ-2). |
| `docs/REGISTER.md` | named **`DECISION_REGISTER.md`** | Keep the longer name; it *is* MODULE_MAP §docs's "decision register". No rename (OQ-9). |

The six source docs are all present (no `_incoming/`). All **8 modules** named in the prompt match
`MODULE_MAP.md` exactly: `contracts/ firmware/ ingest/ edge/ consoles/ substrate/ tooling/ docs/`.
Branch is `Mzcassim/lima` — not renamed. No `.claude/` or `.github/` yet.

> **Overarching constraint (OQ-4):** the Python toolchain **mirrors Hermes exactly** — version
> bounds, gate commands + order, defaults-only ruff/mypy, pytest config, CI shape, and package
> naming. The specifics are baked into §3.2, §4, and the CI plan below. This is the explicit
> "match Hermes" requirement, so where this plan and Hermes ever disagree, Hermes wins.

---

## 1. Summary

Run 0a stands up the **skeleton + gates + substrate placeholder + conventions** for the Eunomia
monorepo: the 8 top-level modules from `MODULE_MAP.md` (each with a one-responsibility README), the
two polyglot build shells (a `uv` Python 3.12 workspace that **mirrors Hermes exactly** and a
PlatformIO ESP32 coordinator project), per-language gates plus a cross-language conformance gate wired
identically for local and CI (and identical to Hermes for the five Python gates), and deterministic
`.claude/` enforcement (auto-format + secret-block hooks, a `reviewer` subagent, a lean
navigation-map `CLAUDE.md`). Its load-bearing piece is the **codegen proof**: ONE trivial `ping` event
encoded once as a language-neutral YAML source, with a small (<~150-line) hand-written generator
emitting a C++ header, a Python type, and a JSON Schema, exercised end-to-end by a conformance test —
proving "one source, three targets" before the real contract is poured in. Run 0a deliberately does
**not** encode the real contract (that is 0b), write any firmware/ingest/edge/console logic, or copy
real substrate scripts. The whole point is a *known-good harness* the next run fills against.

---

## 2. The directory tree (one line per entry)

> `(existing)` = already in repo · `(NEW)` = created in 0a · `[0b]` = placeholder/README only in 0a,
> filled later · `[gen]` = generated, committed, drift-gated.

```
eunomia/                              # repo root ($CONDUCTOR_ROOT_PATH / $CLAUDE_PROJECT_DIR)
├── plan.md                          (existing) this plan
├── README.md                        (NEW) one screen: what Eunomia is · run the gates · plan-mode workflow
├── CLAUDE.md                        (NEW) lean root agent guide (~100 lines, navigation map)
├── .gitignore                       (NEW) python + platformio + uv + secrets (_generated/ is COMMITTED, not ignored)
├── .python-version                  (NEW) 3.12  (pins, mirrors Hermes)
├── pyproject.toml                   (NEW) thin root meta-package "eunomia": uv workspace members,
│                                          [dependency-groups] dev (exact Hermes bounds), [tool.pytest.ini_options],
│                                          [tool.importlinter] — and NO [tool.ruff]/[tool.mypy] (defaults, like Hermes)
├── uv.lock                          (NEW) committed lockfile
├── Makefile                         (NEW) gate entrypoints — local == CI == Hermes (verbatim uv-run commands)
├── .clang-format                    (NEW) C++ format config
├── .clang-tidy                      (NEW) C++ lint config (non-blocking in 0a)
│
├── .github/workflows/ci.yml         (NEW) ONE gates job mirroring Hermes + additional cpp/conformance/codegen-drift steps
│
├── .claude/
│   ├── settings.json                (NEW) two hooks (see §5) — NO commit-guard hook in 0a
│   ├── hooks/
│   │   ├── format-edited.sh         (NEW) PostToolUse: ruff format / clang-format -i the edited file
│   │   └── block-secrets.sh         (NEW) PreToolUse: exit 2 to block .env / key-material reads+writes
│   ├── agents/
│   │   ├── reviewer.md              (NEW, ~30 ln) diffs work-done vs plan/spec, reports discrepancies
│   │   └── contract-conformance.md  (NEW, optional) checks emitters/consumers vs the generated JSON Schema [for 0b]
│   ├── skills/
│   │   ├── codegen/SKILL.md         (NEW) how to add/regenerate a contract + the drift gate
│   │   └── gates/SKILL.md           (NEW) how to run/debug each gate locally
│   └── rules/
│       ├── contracts.md             (NEW) never hand-edit _generated/; edit the source + regenerate
│       ├── firmware.md              (NEW) core/ stays pure + off-target testable; transport/ui swappable
│       └── substrate.md             (NEW) interface FROZEN; non-destructive merge only
│
├── docs/                            (renamed from Docs/) design + conventions
│   ├── CONTRACT.md                  (existing) data-model spine
│   ├── MODULE_MAP.md                (existing) structure authority
│   ├── SPEC.md                      (existing) long-form lifecycle
│   ├── DECISION_REGISTER.md         (existing) decisions + open questions
│   ├── HARDWARE_FINDINGS.md         (existing) background
│   ├── VALIDATION_PLAN.md           (existing) bench/validation plan
│   ├── CONTRIBUTING.md              (NEW) git/PR/agent conventions (stated-only) — @-imported by CLAUDE.md
│   ├── BUILD_PLAN.md                (NEW) thin: phase sequence + current scope = Run 0a (mirrors Hermes's docs/BUILD_PLAN.md)
│   └── adr/0001-architecture.md     (NEW) the architecture decision record (outline §3.8; full at impl)
│
├── contracts/                       THE SPINE — imports nothing. "one source, three targets."
│   ├── README.md                    (NEW) responsibility + "imports nothing" dependency rule
│   ├── pyproject.toml               (NEW) dist `eunomia-contracts` / import `eunomia_contracts` (types + stdlib validator)
│   ├── codegen/
│   │   ├── generate.py              (NEW) the generator (<~150 lines of obvious code): neutral YAML → C++/Python/JSON Schema
│   │   └── README.md                (NEW) source format · targets · how invoked · drift gate · the <150-line / stop-and-flag rule
│   ├── _proof/ping.schema.yaml      (NEW) the ONE tiny 2-field neutral-source example (throwaway; 0b replaces)
│   ├── _generated/                  [gen] codegen outputs — COMMITTED + drift-gated
│   │   ├── cpp/eunomia_ping.h       [gen] header-only struct + parse/serialize (no deps, off-target safe)
│   │   ├── python/eunomia_contracts/{__init__.py,ping.py}  [gen] dataclass + validate()
│   │   └── jsonschema/ping.schema.json                     [gen] the conformance-gate schema
│   ├── conformance/
│   │   ├── fixtures/ping/valid/*.json    (NEW) golden valid records
│   │   ├── fixtures/ping/invalid/*.json  (NEW) golden invalid records
│   │   └── test_ping_conformance.py      (NEW) py-side cross-target conformance test (collected by pytest)
│   ├── sidecar/README.md            [0b] on-card schema area
│   ├── operational/README.md        [0b] event-sourced entities area
│   ├── release/README.md            [0b] release-metadata area (what Hermes pins)
│   ├── interfaces/README.md         [0b] CoordinatorPort / CaptureDevicePort
│   └── events/README.md             [0b] telemetry-event + op-sync-delta area
│
├── firmware/                        C++ / PlatformIO, ESP32  (outside the Python import-linter; boundary = include structure + conformance gate)
│   ├── README.md                    (NEW) responsibility + dependency rule
│   ├── coordinator/
│   │   ├── platformio.ini           (NEW) env:esp32 (target, non-blocking in 0a) + env:native (off-target host tests, blocking)
│   │   ├── src/main.cpp             (NEW) placeholder shell only
│   │   ├── core/README.md           [0b] pure, hardware-free, off-target testable (implements CoordinatorPort)
│   │   ├── transport/README.md      [0b] swappable WiFi-AP/OSC/telnet layer
│   │   ├── ui/README.md             [0b] swappable touchscreen layer
│   │   └── test/test_ping_contract.cpp  (NEW) off-target host test: parse golden fixtures via the generated header
│   └── camera-image/
│       ├── README.md                (NEW) reproducible packaging of a stock binary + on-camera agent; checksum-verified
│       └── checksum_gate.py         (NEW) stub: verify packaged binary vs recorded checksum (no-op until built)
│
├── ingest/                          Python — dirs + READMEs only in 0a (joins the workspace in its own run)
│   └── README.md  identity/README.md  join/README.md  qc/README.md  release/README.md  orchestrator/README.md   [all 0b]
│
├── edge/                            Python — dirs + READMEs only in 0a
│   └── README.md  store/README.md  sync/README.md  api/README.md                                                 [all 0b]
│
├── consoles/                        web stack — dirs + READMEs only in 0a (no stack chosen — OQ-14)
│   └── README.md  _shared/README.md  site-setup/README.md  provisioning/README.md
│       inventory/README.md  workforce/README.md  gods-view/README.md                                            [all 0b]
│
├── substrate/                       ported host substrate — interface FROZEN
│   └── README.md                    (NEW) frozen-interface statement + where Styx config gets vendored (no real scripts in 0a)
│
└── tooling/                         Python engineering tooling
    ├── README.md                    (NEW) responsibility + dependency rule
    └── bench-harness/
        ├── pyproject.toml           (NEW) dist `eunomia-bench-harness` / import `eunomia_bench_harness` (shell)
        ├── README.md                (NEW) two layers: thin real serial/telnet IO + hardware-free replay core
        └── src/                     (NEW) placeholder
```

---

## 3. Per-area plan

### 3.1 Repo skeleton (8 modules + per-module READMEs)
Create the tree above. Each module gets a short `README.md` stating **its single responsibility** and
**its dependency rule** ("depends only on `contracts/`"), lifted faithfully from `MODULE_MAP.md`.
Submodule READMEs carry the one-line role from the map. `ingest/ edge/ consoles/` are directories +
READMEs only (no Python packages in 0a — they become workspace members in their own runs).

### 3.2 Polyglot workspace shells — Python mirrors Hermes EXACTLY (OQ-4)
- **Root `pyproject.toml`** — a **thin root meta-package** named `eunomia` (no real code; real code in
  workspace members), with:
  - `requires-python = ">=3.12"` (uncapped, like Hermes); `.python-version` pins `3.12`; uv-managed.
  - `[tool.uv.workspace] members = ["contracts", "tooling/bench-harness"]` (grows as packages land).
  - `[dependency-groups] dev = ["pytest>=8.0,<9.0", "ruff>=0.10,<0.20", "mypy>=1.10,<2.0",
    "import-linter>=2.0,<3.0"]` — **these exact bounds**.
  - `[tool.pytest.ini_options]`: `python_files = ["test_*.py"]`, `addopts = "-ra -q"`,
    `testpaths` analogous to Hermes's `["tests","packages"]` adapted to Eunomia's top-level members →
    `["contracts", "tooling"]` in 0a (the conformance test lives at `contracts/conformance/`; grows as
    members are added). No `pythonpath` in 0a (no shared fixtures yet); add `pythonpath =
    ["tests/support"]` when shared fixtures appear (Hermes form).
  - `[tool.importlinter]` — see §3.4.
  - **NO `[tool.ruff]` and NO `[tool.mypy]` sections, and no separate ruff/mypy config file.** Both run
    on **defaults**, exactly like Hermes. No invented rule selections or strictness flags.
- **Member packages** — naming mirrors `hermes-<name>`/`hermes_<name>`:
  - `contracts/pyproject.toml` → dist `eunomia-contracts`, import `eunomia_contracts` (the generated
    types + the pure-stdlib validator; the "contract root", analogous to `hermes_schema`).
  - `tooling/bench-harness/pyproject.toml` → dist `eunomia-bench-harness`, import
    `eunomia_bench_harness` (shell only in 0a).
  - `uv.lock` committed; `uv sync --frozen --all-packages` is the install.
- **C++ (PlatformIO, ESP32):** `firmware/coordinator/platformio.ini` with `[env:esp32]` (target board)
  and `[env:native]` (platform = native) for the **off-target host tests** (the requirement that
  `core/` is testable with no hardware). `src/main.cpp` is a shell; `test/test_ping_contract.cpp` is
  the host-build test (doubles as the codegen C++ proof, §3.3). The native env includes the generated
  header via `build_flags = -I${PROJECT_DIR}/../../contracts/_generated/cpp`.

### 3.3 Stub `contracts/` + codegen proof  ← **the load-bearing 0a deliverable**
**The example:** a trivial 2-field `ping` event (e.g. `seq:int`, `sent_unix:number`) — illustrative,
throwaway, replaced by the real schemas in 0b. Lives at `contracts/_proof/ping.schema.yaml` (OQ-5).

**The mechanism (one source → three targets), choice A (OQ-10):**
1. **Source of truth:** one language-neutral **YAML** spec (a tiny field-list DSL: name, type,
   required/warn).
2. **Generator:** `contracts/codegen/generate.py` — a **small hand-written generator, kept under ~150
   lines of obvious code**. If it ever starts needing real complexity (e.g. nested types, the
   interface ports, conditional validation), I **STOP and flag** rather than growing it — I do not
   reach for protobuf/JSON-Schema-as-source, because the contract's pure-stdlib hard-vs-warn semantics
   + the hardware interface ports don't map cleanly onto them. It emits into `contracts/_generated/`
   (committed):
   - `cpp/eunomia_ping.h` — header-only `struct` + parse/serialize, **no deps, off-target compilable**.
   - `python/eunomia_contracts/ping.py` — a dataclass + `validate(obj) -> hard_errors` /
     `validate_full(obj) -> (errors, warnings)` (pure-stdlib, the CONTRACT §6 hard-vs-warn shape).
   - `jsonschema/ping.schema.json` — the JSON Schema for the conformance gate (+ later web validation).
3. **Invocation:** `make codegen` (→ `uv run python contracts/codegen/generate.py`). CI runs it then
   asserts a clean `git diff` — the **codegen-drift gate** (OQ-6: artifacts committed + kept in sync).
4. **Proof of correctness — the conformance harness:** golden fixtures under
   `contracts/conformance/fixtures/ping/{valid,invalid}/`. `test_ping_conformance.py` (collected by the
   normal `pytest` gate) checks all three targets agree: (a) the JSON Schema accepts every `valid/` and
   rejects every `invalid/`; (b) the generated Python type round-trips the valid ones and `validate()`
   rejects the invalid ones; (c) the C++ host test (`firmware/.../test_ping_contract.cpp`, via
   `pio test -e native`) parses the same fixtures with the generated header and agrees. End-to-end
   "one source, three targets, all consistent."

### 3.4 Gates — five Python gates VERBATIM Hermes; C++ + cross-cutting added (OQ-7/OQ-11/OQ-13)
Every gate is a Makefile target; CI calls the **same** commands so local == CI == Hermes.
- **Python (exact Hermes commands, exact Hermes order):**
  `uv run pytest` → `uv run ruff check .` → `uv run ruff format --check .` → `uv run mypy .` →
  `uv run lint-imports`. All five **blocking**.
- **C++:** `pio run -e esp32` (target build — **present but NON-blocking in 0a**, flips to blocking
  when `coordinator/core/` lands), `pio test -e native` (off-target build+test — **blocking**),
  `clang-format --dry-run -Werror` (**blocking**), `clang-tidy` (**NON-blocking in 0a**).
- **Cross-cutting:** the conformance gate (the Python half is already inside `uv run pytest`; the C++
  half is `pio test -e native` — the gate is their conjunction, **blocking**); the **codegen-drift**
  gate (`make codegen && git diff --exit-code contracts/_generated`, **blocking**); the **camera-image
  checksum gate stub** (`firmware/camera-image/checksum_gate.py` — no-op pass in 0a, becomes blocking
  when camera-image is built).
- **import-linter (Hermes pattern, OQ-11):** config in `[tool.importlinter]` (root pyproject).
  `root_packages = ["eunomia_contracts", "eunomia_bench_harness"]`. Contracts in 0a:
  - a `forbidden` contract making **`eunomia_contracts` import nothing internal** (source
    `eunomia_contracts`, forbidden `eunomia_bench_harness` + every future `eunomia_*`) — the
    contract-root rule, analogous to `hermes_schema`;
  - every other package may import `eunomia_contracts` **only** (in 0a, `eunomia_bench_harness` has no
    other internal package to import — the rule pre-exists for when they're added).
  - A `layers` contract is **reserved** for when an internal pipeline ordering exists to declare (e.g.
    ingest's `identity → join → qc → release`); none is declared in 0a.
  - **`firmware/` is C++ — outside the Python import-linter.** Its boundary is the include structure
    (`-I .../_generated/cpp` only; no upstream includes) + the conformance gate.

### 3.5 Deterministic enforcement via hooks (OQ-8: NO commit-guard in 0a)
In `.claude/settings.json`, scripts in `.claude/hooks/` referenced via `$CLAUDE_PROJECT_DIR`:
- **PostToolUse** (matcher `Edit|Write`) → `format-edited.sh`: `ruff format` for `.py`,
  `clang-format -i` for C/C++ — formatting never relies on the agent remembering. Non-blocking.
- **PreToolUse** (matcher on file tools + `Bash`) → `block-secrets.sh`: **exit 2 to block** any
  read/write of secrets (`.env`, `*.pem`, `*.key`, a credentials store). The only reliable hard block
  per the docs; CONTRACT §2.3 forbids PSKs/secrets in the repo or on the card.
- **The commit-guard hook is OMITTED in 0a — CI is the real gate.**

### 3.6 Lean root `CLAUDE.md` (~100 lines / <~2,500 tokens)
A navigation map written as **factual statements** (never out-of-band commands): what Eunomia is; the
dependency law in one line; the gate commands (`make gates`); the plan-mode working agreement.
Rarely-needed knowledge → `.claude/skills/*/SKILL.md`; path-scoped rules → `.claude/rules/*.md`.
**`@`-imports (OQ-12, (b)):** `@`-import **only** the short `docs/CONTRIBUTING.md`; reference
`CONTRACT.md` / `MODULE_MAP.md` / `SPEC.md` by **plain path** (read-on-demand) so the lean budget holds.

### 3.7 `.claude/agents/` subagents (~30 lines each)
- **`reviewer.md`** (required): read-only; diffs work-done against `plan.md` / `SPEC.md` and reports
  discrepancies. Used to check 0a's implementation against this plan.
- **`contract-conformance.md`** (optional, for 0b): validates an emitter/consumer against the
  generated JSON Schema + golden fixtures.

### 3.8 ADR — `docs/adr/0001-architecture.md` (outline now, written at implementation)
Captures *this* architecture from the locked decisions:
1. **Context** — the unification mandate: converge `data`/Styx Layer 0 + `x3-capture-kit` Layer 1/2 +
   the specced flows/consoles into one clean monorepo.
2. one polyglot monorepo (C++ firmware / Python services / web consoles).
3. contract-as-spine + the dependency law (everything depends only on `contracts/`), enforced by the
   per-language import-boundary check + the cross-language conformance gate.
4. data topology — edge-authoritative event-sourced operational store on-site (B-8, A-2) + the
   analytical system-of-record downstream (Hermes pins + ingests the release record).
5. Eunomia FEEDS the cleaning/render layer (Hermes-side, on Hades) — shared audio-sync core, not
   duplicated (CONTRACT §7).
6. substrate ported-but-frozen (D-8/D-12) — interface-compatible, idempotent installer,
   non-destructive merge.
7. two-axis versioning + anti-drift (CONTRACT §5).
8. consequences · alternatives · status. Cross-references C-9..C-12, B-8, B-9, D-8..D-12.

### 3.9 Misc — `.gitignore`, root `README.md`, lockfiles
- `.gitignore`: Python (`__pycache__/`, `.venv/`, `*.egg-info/`, `.mypy_cache/`, `.ruff_cache/`,
  `.pytest_cache/`), PlatformIO (`.pio/`), secrets (`.env`, `*.pem`, `*.key`, `credentials/`).
  **`contracts/_generated/` is NOT ignored — it is committed** (OQ-6).
- root `README.md`: one screen — what Eunomia is + `make gates` + the plan-mode workflow.
- lockfiles: `uv.lock` committed; PlatformIO pins versions inline in `platformio.ini`.

---

## 4. The gate matrix

| Gate | Language | Command (Makefile target) | Blocking? | Runs where |
|---|---|---|---|---|
| Unit tests | Python | `uv run pytest` | **yes** | local + CI |
| Lint | Python | `uv run ruff check .` | **yes** | local + CI |
| Format check | Python | `uv run ruff format --check .` | **yes** | local + CI |
| Types | Python | `uv run mypy .` | **yes** | local + CI |
| Import boundary | Python | `uv run lint-imports` | **yes** | local + CI |
| Build (target) | C++ | `pio run -e esp32` | **no in 0a** → blocking when `core/` lands | local + CI |
| Build + test (off-target) | C++ | `pio test -e native` | **yes** | local + CI |
| Format check | C++ | `clang-format --dry-run -Werror` | **yes** | local + CI |
| Static analysis | C++ | `clang-tidy` | **no in 0a** | local + CI |
| **Conformance** | cross | `uv run pytest` (py+schema) ∧ `pio test -e native` (cpp) | **yes** | local + CI |
| **Codegen drift** | cross | `make codegen && git diff --exit-code contracts/_generated` | **yes** | local + CI |
| Camera-image checksum | cross | `python firmware/camera-image/checksum_gate.py` | stub/no-op in 0a; blocking later | local + CI |

The five Python rows are **byte-for-byte the Hermes gates, in Hermes order**. `make gates` runs all
blocking gates.

**CI (`.github/workflows/ci.yml`) — mirrors Hermes:** ONE `gates` job on `ubuntu-latest`:
`astral-sh/setup-uv@v5` (`enable-cache: true`) → `uv python install 3.12` → `uv sync --frozen
--all-packages` → the **five Python gate steps in the order above** (identical to Hermes). The C++,
conformance, and codegen-drift checks are **additional steps/jobs** (a separate `cpp` job with the
PlatformIO + clang toolchain, and a codegen-drift step), so the five Python gates stay identical to
Hermes.

---

## 5. The hooks plan

| Event | Matcher | What it does | Blocks? |
|---|---|---|---|
| PostToolUse | `Edit\|Write` | `format-edited.sh`: `ruff format <file>` for `.py`; `clang-format -i <file>` for `.c/.cpp/.h/.hpp`; no-op otherwise | no (formats only) |
| PreToolUse | `Read\|Edit\|Write\|Bash` | `block-secrets.sh`: if the target path matches `.env`, `*.pem`, `*.key`, `*credentials*`, **exit 2** to block | **yes (exit 2)** |

Commit-guard hook **omitted** in 0a (OQ-8). All hook scripts live in `.claude/hooks/`, invoked with
`$CLAUDE_PROJECT_DIR`-prefixed paths.

---

## 6. Resolution record (your annotations, folded in)

| OQ | Decision | Where applied |
|---|---|---|
| OQ-1 | (a) rename `Docs/` → `docs/`, two-step case-only `git mv` | §0, §2 |
| OQ-2 | (a) author `CONTRIBUTING.md` from stated conventions only | §0, §2, §3.6 |
| OQ-3 | (a) thin `docs/BUILD_PLAN.md`, scope = Run 0a; **mirror Hermes's `docs/BUILD_PLAN.md`** | §2 |
| OQ-4 | (a) **mirror Hermes Python toolchain exactly** — version bounds, gate order, defaults-only ruff/mypy, pytest config, CI shape, `eunomia-<name>`/`eunomia_<name>` naming | §3.2, §4, CI plan |
| OQ-5 | (a) stub at `contracts/_proof/ping.*`, throwaway | §2, §3.3 |
| OQ-6 | (a) commit `_generated/` + codegen-drift gate | §2, §3.3, §3.9, §4 |
| OQ-7 | Makefile, with the **verbatim Hermes `uv run` commands** | §3.4, §4 |
| OQ-8 | (a) **omit** the commit-guard hook in 0a | §2, §3.5, §5 |
| OQ-9 | (a) keep `DECISION_REGISTER.md`, no rename | §0 |
| OQ-10 | A — neutral YAML + small hand-written generator, **<~150 lines, stop-and-flag if it needs real complexity** | §3.3 |
| OQ-11 | Hermes import-linter pattern: `root_packages` = every import name; `forbidden` so `eunomia_contracts` imports nothing internal; others import it only; `layers` reserved; firmware is C++/out of scope | §3.4 |
| OQ-12 | (b) `@`-import only `CONTRIBUTING.md`; others by path | §3.6 |
| OQ-13 | **split** — native build+test blocking; esp32 target build present but non-blocking in 0a (flip when `core/` lands); clang-tidy non-blocking in 0a | §3.2, §3.4, §4 |
| OQ-14 | `consoles/` dirs + READMEs only, no web stack chosen | §2, §3.1 |

**Two small Hermes-mirror confirmations** (I chose a faithful adaptation; correct me if Hermes
differs):
1. **`testpaths`** — Hermes's `["tests","packages"]` adapts to Eunomia's *top-level* members as
   `["contracts","tooling"]` in 0a (no `packages/` parent dir, no top-level `tests/` in 0a). If Hermes
   actually nests members under `packages/`, I'll match that layout instead.
2. **import-linter config location** — I put `[tool.importlinter]` in the **root `pyproject.toml`**
   (import-linter needs config to do anything; this is the one tool that *does* get a config block,
   unlike ruff/mypy). If Hermes keeps a separate `.importlinter`/`setup.cfg`, I'll match that file.

---

## 7. What Run 0a deliberately does NOT do (boundary on record)

- **Does NOT encode the real contract** into `contracts/sidecar|operational|release|interfaces|events/`
  — that is **Run 0b**. Only the throwaway `ping` stub goes in now, to prove the codegen harness.
- **Does NOT write any** firmware logic (no trigger state machine, transport, or UI), ingest logic,
  edge/store logic, or console code. Only build shells + READMEs + the codegen/conformance proof.
- **Does NOT copy real substrate scripts.** `substrate/` gets its directory + frozen-interface README +
  a statement of where the existing Styx host config *will* be vendored (unchanged) — but no ZFS /
  Sipolar / udev / systemd scripts are copied in 0a (none are present in the repo to vendor).
- **Does NOT pick** the web stack, edge-sync policy, the Hermes contract-consumption mechanism, console
  auth/PII handling, or QC thresholds — all explicitly deferred (CONTRACT §8, MODULE_MAP open-Qs).
- **Does NOT** open a PR, force-push, or merge. Per conventions: report gate results + a change summary
  and wait for your go-ahead first.

---

Plan ready for annotation — I have not implemented anything.
