# Run 0b — `contracts/`: encode the real Eunomia contract (PLAN)

> **Status: APPROVED — implementing.** All eight Open Questions are resolved (§9, with Mo's
> annotations folded in); OQ-3's data-vs-logic boundary is sharpened in §5.2/§6/§9. Authority for
> every field is `docs/CONTRACT.md`; where it and any other doc disagree, CONTRACT wins. (This
> replaces the merged Run 0a plan, which lives in git history at `ea31f9d`.)
>
> **Report-back scope (Mo's note):** the report's faithfulness check covers the **0b-scoped sections
> only** — §2 sidecar, §4 release, §5 versioning, and events — **not** §3 operational or the
> interfaces (those are 0c). Everything else in the report-back spec stands as written, including the
> merge-readiness evidence.

---

## 1. Summary

**What 0b produces:** the real Eunomia data contract poured through the 0a codegen + conformance
harness — replacing the throwaway `ping` proof. Concretely, the *record-shaped* contract surface:

- `contracts/sidecar/` — the on-card `eunomia-sidecar` record (CONTRACT §2), with the hard-vs-warn
  split, the only-two non-empty fields (`kit_id`+`side`), the v1-extra conditional, and the two-axis
  versioning fields.
- `contracts/release/` — the release-metadata record Hermes ingests (§4) — **the external contract
  surface** Hermes pins a version of.
- `contracts/events/` — the god's-view telemetry event(s) + the operational-sync delta (§3 events /
  §6). The `ping` proof graduates into a real telemetry event here.
- `contracts/` **two-axis versioning** (§5) made first-class: `schema` (string, parser-facing,
  drives conditional presence) ⊥ `record_format_version` (int, writer-owned, forensic).
- **The hybrid conformance validator** (the locked Option C): real `jsonschema` Draft 2020-12 for
  the structural layer + a pure-stdlib overlay for the hard-vs-warn severity split and the
  Eunomia-specific semantics. Wired into the conformance gate.
- **Hermetic codegen:** PyYAML pinned in a codegen dependency group (retires the 0a ephemeral
  `uv run --with pyyaml`).
- **Conformance extended, not replaced:** `valid/` + `invalid/` + **`warn/`** fixtures per entity;
  all three targets (JSON Schema via `jsonschema`, the Python type+validator, the C++ header) proven
  to agree; the codegen-drift gate still green on the committed tree.

**What 0b defers (see §2 — recommended split, and §10):** the full **operational model** (§3: the 9
event-sourced entities, as-of resolution, identity-precedence *logic*, crosswalk/serial-retargeting,
the dual-signal join *rules-as-logic*) and the **interfaces** (`CoordinatorPort` / `CaptureDevicePort`
— a different, non-record shape) are recommended to move to **Run 0c**. 0b encodes everything the
coordinator *writes* and Hermes *ingests*; 0c encodes the operational *store* and the hardware *seams*.

**What 0b never does:** any module logic (no firmware state machine, no ingest/identity/join/QC
implementation, no edge/console code), no substrate scripts, no web stack, no Hermes-side cleaning
code, and it does **not** pick the Hermes contract-consumption mechanism.

---

## 2. ⭐ FIRST OPEN QUESTION — ONE run, or split 0b / 0c?

Encoding all of §2–§6 **plus** the interfaces in a single run is a lot, and it is exactly the lot
that pressures the generator (requirement 3). My honest assessment is to **split**, and here is why.

**The two halves separate cleanly by *shape*, *urgency*, and *generator cost*:**

| | **0b (recommend NOW)** | **0c (recommend NEXT)** |
|---|---|---|
| **Areas** | sidecar §2, release §4, events §3/§6, versioning §5, the hybrid validator, PyYAML pin, conformance | operational model §3 (9 entities, events, as-of), identity-precedence/crosswalk/join *logic*, interfaces |
| **Shape** | **records** — flat-ish JSON objects with fields. Fits the 0a field-list DSL with bounded extensions (enum, nullable, array, `minLength`, one conditional rule). | **a system model + operation signatures** — event-sourced entities with temporal resolution, *and* interfaces (method signatures, not data). A genuinely different shape than the record DSL. |
| **Urgency** | The coordinator **writes** the sidecar and **emits** events *now*; Hermes **pins** release *now*. The live external surface. | Consumed by ingest/identity/join + firmware ports — all **later runs** (Run B+). Not on any current critical path. |
| **Generator cost** | "more field-types" + **one** bounded conditional rule. Stays near the budget. | nesting/recursion for entity graphs + an interface-description format that does **not** fall out of the field DSL — the most likely STOP-and-flag trigger. |
| **Reviewability** | One coherent diff: "does the on-card/emitted/ingested record match the doc, and does hard-vs-warn work?" | One coherent diff: "is the operational store + the seams modeled right?" |

**Why the seam is real (not arbitrary):** the release record (§4) is the *frozen join* of sidecar +
operational. But release defines its **own** shape — denormalized frozen fields + **id references**
(`capture_stack_id`, `calibration_id`, `person_id`, `session_id`). It does **not** need the
operational entity *schemas* to exist in order to define itself; it needs only the id-reference
fields. So 0b can encode release's shape fully, and 0c encodes the entities those ids resolve to.
Identity precedence, crosswalk, and the dual-signal join are **join-time, multi-entity logic** — they
are not validatable on a single record anyway, so they belong with the operational model in 0c (as
typed entities + documented rules; the *implementation* that runs at ingest is a still-later run, per
the task's own out-of-scope note).

**Recommendation: SPLIT.** Run 0b = the record surface + the hybrid validator (this plan, §3–§8 as
written). Run 0c = operational model + interfaces. **Mo decides.** If Mo prefers ONE run, the plan
still holds — the operational + interfaces sections (§4.2, §4.4) are written so they can be pulled in —
but expect the generator to hit the STOP-and-flag line on the interface shape (§6, §9-OQ-1), which is
itself the signal to pause and reconsider codegen. The rest of this plan is written for the **split**
(0b) scope, with the deferred areas outlined so the decision is reversible.

---

## 3. The directory tree after 0b

Annotated: **`NEW`** = created in 0b · **`0a`** = built in 0a, reused · **`0a→0b`** = 0a file
modified · **`DEL`** = removed in 0b · **`0c`** = stays stubbed for the next run (README only).

```
contracts/
├── README.md                                   0a→0b  (drop the _proof row; note the hybrid validator)
├── pyproject.toml                              0a      (UNCHANGED — eunomia_contracts stays dependencies=[])
├── codegen/
│   ├── generate.py                             0a→0b  (driver + source manifest; per-target emitters — §6)
│   ├── emitters/  (jsonschema.py·python.py·cpp.py)  NEW?  (only if the monolith exceeds budget — §6, OQ-8 note)
│   ├── README.md                               0a→0b  (new invocation; the budget verdict)
│   └── templates/
│       ├── header.h.tmpl                        0a→0b  (string/enum members; nested left out — OQ-5)
│       └── module.py.tmpl                       0a→0b  (_HARD/_WARN tables, enum/non-empty/conditional checks)
├── _proof/                                      DEL     (ping graduates into events/ — §4.5)
│   └── ping.schema.yaml                         DEL
├── sidecar/
│   ├── eunomia-sidecar.schema.yaml              NEW     (CONTRACT §2 — the on-card record)
│   └── README.md                               0a→0b
├── release/
│   ├── eunomia-release.schema.yaml              NEW     (CONTRACT §4 — Hermes-pinned surface)
│   └── README.md                               0a→0b
├── events/
│   ├── eunomia-telemetry-event.schema.yaml      NEW     (started/stopped/camera-dropped/recording-suspect)
│   ├── eunomia-sync-delta.schema.yaml           NEW     (the operational-sync delta — §6)
│   └── README.md                               0a→0b
├── operational/   README.md                     0c      (stub; filled in 0c — §4.2)
├── interfaces/    README.md                     0c      (stub; filled in 0c — §4.4)
├── overlay/                                     NEW?    (the hand-written pure-stdlib semantics — placement OQ-3)
│   └── eunomia_overlay/ (…)
├── _generated/                                  0a→0b  (regenerated; ping artifacts replaced)
│   ├── cpp/        eunomia_sidecar.h · eunomia_telemetry_event.h          NEW  (firmware-relevant only — OQ-5)
│   │               eunomia_ping.h                                          DEL
│   ├── python/eunomia_contracts/  sidecar.py · release.py · events.py · __init__.py   NEW (ping.py DEL)
│   └── jsonschema/  eunomia-sidecar.schema.json · eunomia-release.schema.json
│                    eunomia-telemetry-event.schema.json · eunomia-sync-delta.schema.json   NEW (ping.* DEL)
└── conformance/
    ├── fixtures/
    │   ├── ping/                                DEL
    │   ├── sidecar/{valid,invalid,warn}/        NEW
    │   ├── release/{valid,invalid,warn}/        NEW
    │   └── events/{valid,invalid,warn}/         NEW
    └── test_conformance.py                      NEW (generalizes test_ping_conformance.py — uses jsonschema)

firmware/coordinator/
├── platformio.ini                              0a→0b  (EUNOMIA_FIXTURES_DIR → sidecar/events; include both headers)
└── test/test_contract.cpp                       NEW (generalizes test_ping_contract.cpp over the real headers)
```

---

## 4. Per-area plan

For each area: the source file(s), what it encodes (outline — fields referenced to CONTRACT, not
re-typed), and the decisions made.

### 4.1 `contracts/sidecar/` — `eunomia-sidecar` (CONTRACT §2) — **0b**

- **Source:** `sidecar/eunomia-sidecar.schema.yaml`, schema id `eunomia-sidecar/v1`.
- **Encodes (per §2.2, by group):** top-level HARD `schema`; top-level WARN `record_format_version`;
  `ordering` (`seq` HARD, `global_episode_seq` HARD); the `identity` group (HARD set: `camera_id`,
  `kit_id`, `side`, `operator_id`, `station_id`, `task_id`, `task_name`, `session_id`, `episode_id`
  (UUIDv4), `rotation_id`; the **only-two HARD-non-empty**: `kit_id`, `side`; v1-extra HARD `prompt`,
  `task_source`; WARN: `episode_ordinal`, `bimanual_episode_id`, `display_id` (derived, never-a-key),
  `calibration_id`, `record_settings`, `mount`, `assignment_source`); the `timing` object
  (`started_unix`/`stopped_unix`/`start_skew_ms`, `camera_clock` WARN provenance-only); `provenance`
  (all WARN: `camera_firmware`, `fob_id`, `fob_build`, `kit_version`, `site_id`, `modality`); the
  `outcome` group (`stop_reason` enum WARN, `archive` WARN, **net-new** `recording_suspect` WARN); the
  `files` group (`files.back` HARD pointer).
- **Decisions:** (a) `episode_id`=UUIDv4 pairing key, `display_id`=derived WARN never-a-key
  (CONTRACT §7 resolved); (b) `task_source` enum `nand_staged|sd_assignment|none`; `stop_reason` enum
  `operator|timer|card_full|battery|error|overheat`; `modality` enum `umi|teleop`; `side` enum
  `left|right`; (c) `kit_id`+`side` get `minLength:1` (the only non-empty rule); (d) the v1-extra
  conditional (`prompt`,`task_source` required when `schema` declares v1+) — OQ-4.
- **OQ-2 confirm result (the as-built was reached at `~/Desktop/Pantheon/X3_Capture_Kit/`).** The
  proven writer `pantheon-x3-sidecar/v2` nests **`identity` as an object** (not just `timing`+`files`),
  stores `seq` as a zero-padded **string**, and carries a top-level camera-derived `timestamp`. This
  **revises** my OQ-2 sketch. Reconciliation (CONTRACT wins; CONTRACT §2 explicitly "cleans namespacing
  of the field groups"): encode the §2.2 groups as **nested objects** — `identity`(HARD),
  `timing`(WARN), `provenance`(WARN), `outcome`(WARN), `files`(HARD) — with `schema`,
  `record_format_version`, `seq`, `global_episode_seq` as **top-level scalars**. Judgment calls flagged
  in the report's faithfulness check: (i) `provenance`/`outcome` nested per CONTRACT's clean-namespacing
  (the as-built scattered these under `identity`/top-level); (ii) `seq` encoded **numeric** per CONTRACT
  "(numeric)" — the as-built used a zero-padded string; (iii) **no** top-level `timestamp` — CONTRACT
  drops camera-clock-derived time as poison (the as-built had a hard `timestamp`). Firmware needs the
  C++ target here (it *writes* the sidecar) — scoped per OQ-5.

### 4.2 `contracts/operational/` — event-sourced model (CONTRACT §3) — **recommend 0c** (outlined)

If pulled into 0b, this encodes the 9 entities (`person`, `hardware_unit` (order→batch→unit→
lifecycle), `kit`, `calibration` (scope `none|fleet|per_camera`), `task`, `session` (`fob_session_id`),
`capture_stack`, `footage_reference` (`on_card→on_styx→shipped→on_hades→purged`), and `episode` (the
join point, §3.2)) as typed entities + append-only event records, plus the documented rules: identity
precedence (§3.3), crosswalk + serial-retargeting (§3.4), task precedence (§3.5), dual-signal join
(§3.6). **What becomes what:** the *entities/events* → schema; the *enums* (scope, footage_state,
pairing_method) → schema; **identity precedence, crosswalk, retargeting, the join tiebreaks → typed
fields + documentation only** (they are join-time, multi-entity logic — not single-record-validatable;
the *implementation* is a later run). This area is the generator's nesting/graph stressor and is on no
current critical path → **deferred to 0c (OQ-1).**

### 4.3 `contracts/release/` — release metadata (CONTRACT §4) — **0b**

- **Source:** `release/eunomia-release.schema.yaml`, schema id `eunomia-release/v1`.
- **Encodes (per §4.1, by group):** Identity (frozen) incl. the id references; Time (frozen:
  `recorded_at`, `camera_clock` provenance-only, `ingested_at`, `time_confidence` enum
  `ntp_synced|unsynced_monotonic`); Capture stack (frozen); QC (derived, **OPEN taxonomy** —
  `qc_flags` is an array of strings with **no enum lock**, `qc_reasons`, `qc_score`; plus status-only
  `probe_failed`/`decode_skipped`); Sync (deferred-null `sync_offset_ms`, `sync_confidence`); State
  (`paired`, `void`+`void_reason`, `needs_review`, `archive`, `recording_suspect`, `label_source`);
  Deferred-null-at-ingest (`human_label`, `task_completed`, the sync pair) → modeled **nullable**.
- **Decisions:** (a) **This is the external contract surface** — its `schema` string is what Hermes
  pins (§5); flagged as such in the README and the changelog. (b) `qc_flags` stays open (array of
  string, never an enum) — a closed taxonomy here would be a faithfulness bug. (c) deferred-null
  fields are `["null", T]` unions, present-but-null at ingest. (d) release references operational
  entities by **id only** — so it is fully encodable in 0b without the §3 entities existing yet (§2
  seam). No C++ target (Hermes/ingest are Python; firmware never touches release — OQ-5).

### 4.4 `contracts/interfaces/` — `CoordinatorPort` / `CaptureDevicePort` — **recommend 0c** (outlined)

These are **operation signatures, not records** — the 0a field-list DSL does not represent them. The
generator would need a neutral *interface-description* format emitted as a C++ abstract header + a
Python `Protocol`/ABC. That source-format choice does **not** fall out of the record DSL (it is a
different shape) → it is its own design question (**OQ-1** rolls this into the 0c split; if 0b must
include it, the interface-source format becomes a blocking sub-question and the generator would likely
trip STOP-and-flag). The README stays the 0c stub; the port surface is already sketched in
`contracts/interfaces/README.md`.

### 4.5 `contracts/events/` — telemetry + sync-delta (§3 events / §6) — **0b**

- **Sources:** `events/eunomia-telemetry-event.schema.yaml` (`eunomia-telemetry-event/v1`) and
  `events/eunomia-sync-delta.schema.yaml` (`eunomia-sync-delta/v1`).
- **Encodes:** the god's-view telemetry event (`started`/`stopped`/`camera-dropped`/
  `recording-suspect`) — modeled as **one record with an `event` enum discriminator + conditional
  fields**, mirroring the as-built `pantheon-trigger-episode/v1` `{event, kit_id, fob_session_id,
  ordinal, wallclock, ms, station, prompt, cams[], sent, total}` shape (BUILD_PLAN learnings) — and the
  operational-sync delta format used by `edge/sync/`. See **OQ-7** (one polymorphic event vs one
  source per type).
- **Decisions:** the `ping` proof **graduates** here: `_proof/ping.schema.yaml`, the generated
  `*ping*` artifacts, the `fixtures/ping/`, `test_ping_conformance.py`, the C++ `test_ping_contract.cpp`,
  and the `platformio.ini` `EUNOMIA_FIXTURES_DIR` path are all removed/repointed to the real event
  (enumerated in §3 tree + §8). Firmware needs the C++ target here (it *emits* telemetry).

### 4.6 Two-axis versioning (CONTRACT §5) — **0b, cross-cutting**

- `schema` (string, additive semver, parser-facing) and `record_format_version` (int, writer-owned,
  forensic) are encoded as first-class fields on the sidecar (and the release carries its own `schema`
  + the forensic handles). **The validator uses `schema` to know which fields to expect** — this is
  the conditional-presence machinery (the v1-extra hard set), realized as a JSON Schema `if/then` keyed
  on the `schema` string **and** mirrored in the stdlib validator (§5, OQ-4). Additive-only is enforced
  by discipline + the conformance rule that an older fixture must still validate under the current
  schema (a `warn/` fixture omitting a newer field stays valid).

### 4.7 Conformance — extend the harness (CONTRACT §6) — **0b** (full design in §5, §7)

---

## 5. The hybrid-validator design (the piece to scrutinize)

The locked **Option C** is two validators sharing one severity model. The key clarification: **JSON
Schema only knows valid/invalid; the hard-vs-warn *severity* is a second axis the overlay owns.**

### 5.1 The two validators (which is which)

| | **Shipped stdlib validator** | **Dev/CI hybrid conformance validator** |
|---|---|---|
| **Where it runs** | cam-side / ingest / edge — **in the field** | the CI conformance gate only |
| **Deps** | **pure-stdlib** (no `jsonschema`) | `jsonschema` (Draft 2020-12) + the stdlib overlay |
| **What it is** | generated `eunomia_contracts.<entity>.validate(obj)->hard_errors` and `validate_full(obj)->(hard_errors, warnings)` + the overlay | a dev harness in `conformance/` that validates fixtures against the emitted JSON Schema with the real lib, then applies the overlay |
| **Structural layer** | generated purpose-built field checks (types from `_HARD`/`_WARN` tables) — **not** a hand-rolled JSON-Schema interpreter | the **real `jsonschema` library** against `_generated/jsonschema/*.json` |

`jsonschema` lives in a **dev/validation dependency group only** (§8). It never enters
`contracts/pyproject.toml` (which stays `dependencies = []`), and the conformance test is **not** part
of the shipped `eunomia_contracts` wheel (the wheel packages only `_generated/python/eunomia_contracts`
[+ the overlay, OQ-3]). So the field validator stays pure-stdlib by construction.

The 0a hand-rolled stdlib schema-checker in `test_ping_conformance.py` (`_schema_errors`) is
**retired**: the CI structural layer is now the real `jsonschema` lib. The *shipped* validator stays
stdlib but is purpose-built (it checks the contract directly from generated tables), not a generic
JSON-Schema interpreter — that is the distinction the locked decision draws (it is why the shipped
validator won't "diverge silently on nested/enum/conditional fields").

### 5.2 What each layer covers

- **JSON Schema layer (emitted, Draft 2020-12, browser-validatable with ajv):** types, enums,
  nesting, nullable (`["null", T]`), arrays, required-vs-optional (`required` = the **hard** fields
  only), `minLength:1` (kit_id/side), and conditional presence (`if {schema matches v1+} then
  {required: [prompt, task_source]}`, OQ-4). **No custom dialect** in the structural layer — pure
  Draft 2020-12 so the consoles' ajv validates the same file.
- **stdlib overlay (pure-stdlib, the Eunomia semantics JSON Schema can't express) — OQ-3 sharp
  boundary: declarative-DATA is generated, actual LOGIC is hand-written.**
  1. **The hard-vs-warn severity split (generated DATA):** the partition is driven by a generated
     **severity table** (field-path → `hard|warn`, the `_HARD`/`_WARN` tables — pure data). A
     *missing* hard field or a *malformed* hard field → **hard error**. A *malformed warn field* (a
     structural type error on a warn path) → **downgraded to a warning**. A *missing warn field* →
     not an error (absence is surfaced as a triage advisory, not invalidating). This is the
     "warn-only downgrade." The enum value-sets, `minLength`, and the **one** conditional-presence
     rule are likewise generated as simple **table lookups**.
  2. **Bespoke cross-field rules (hand-written LOGIC, NOT generated):** anything that is real logic —
     a cross-field dependency like *`void == true ⇒ void_reason present & non-empty`* (release,
     grounded in §4.1 "void+void_reason") — is **hand-written in a small pure-stdlib overlay module**
     (`eunomia_contracts._semantics`, shipped in the contracts wheel). It is **not** emitted from a
     YAML rule-DSL: generating a severity table is safe data-driven codegen; generating arbitrary
     cross-field logic is a mini rules-engine and exactly what the generator-complexity STOP-and-flag
     is meant to catch (OQ-3). The hand-written overlay stays small and pure-stdlib.
  3. **Honest scope flag:** identity precedence / "camera-clock-is-poison" / the join tiebreaks are
     *join-time, multi-entity* rules — **not mechanically checkable on one record**. They are encoded
     as **typed fields + documentation** now; their enforcing logic is 0c/ingest. The overlay's
     mechanically-enforceable share in 0b is: the (generated) severity partition + enum/non-empty/
     conditional checks, plus the (hand-written) `void⇒void_reason` cross-field rule.

### 5.3 How hard-vs-warn shows in validator output

`validate(obj) -> list[str]` (hard errors only — the field-side go/no-go) and `validate_full(obj) ->
(hard_errors, warnings)`. A record with a malformed **warn** field returns `([], ["warn: <field> …"])`
→ **valid-with-warnings** (accepted, flagged). A record missing a **hard** field returns
`(["hard: missing <field>"], …)` → **rejected**. The conformance harness proves the shipped stdlib
verdict equals the `jsonschema`+overlay verdict on every fixture.

### 5.4 How `jsonschema` wires into the gate

`conformance/test_conformance.py` (run by the existing `uv run pytest`, gate #1): for each entity,
load `_generated/jsonschema/<entity>.schema.json`, build a `jsonschema` validator, and assert (a) it
accepts every `valid/` + `warn/` and rejects every `invalid/`; (b) the overlay classifies `warn/` as
valid-with-warnings and hard failures as rejected — including a fixture whose **only** problem is a
warn field (proving the downgrade); (c) the generated Python validator and the C++ header agree with
`jsonschema` on the structural layer. No new gate command — it rides the existing pytest gate (§8).

---

## 6. The codegen plan

- **Source manifest:** `generate.py` stops pointing at the single `_proof` file and iterates a
  manifest of `contracts/<area>/*.schema.yaml` sources → for each, emit the 3 targets (C++ only for
  firmware-relevant records — OQ-5). Output stays deterministic (sorted keys, no timestamps) so drift
  is meaningful.
- **DSL extensions needed (assessment against the ~150-line budget):**

  | Extension | Classification | Budget read |
  |---|---|---|
  | `enum` (scalar value set) | more field-types | cheap (a `TYPES`-style table + an `enum` key) |
  | `nullable` / `["null", T]` | more field-types | cheap |
  | `array of scalar` (qc_flags, cams[]) | more field-types | cheap |
  | `minLength:1` (non-empty) | a field attribute | cheap |
  | **conditional presence** (v1-extra hard set) | **one bounded rule**, not a field-type | a single declarative block (`conditional_required: {when_schema_min: 1, fields: […]}`) → JSON Schema `if/then` + a stdlib check. Borderline but **bounded to one rule** |
  | **nesting** (timing, files) | borderline | kept **shallow** (match as-built, OQ-2); one level, no general recursion |
  | **interfaces** (signatures) | **real complexity / different shape** | **does not fit** — the STOP-and-flag trigger → deferred to 0c (OQ-1) |

- **The STOP-and-flag verdict (the approved rule holds):** with the **split** (OQ-1), 0b's additions
  are "more field-types + one bounded conditional + shallow nesting" — they pressure the budget but do
  **not** require a framework. **Recommended structure to absorb the pressure without growing a
  monolith (OQ-8):** split `generate.py` into a thin driver + three per-target emitters
  (`emitters/{jsonschema,python,cpp}.py`) sharing one field-DSL parser (the BUILD_PLAN carry-forward
  #3). Each emitter stays individually obvious and small; the budget is read **per emitter**, not as
  one 150-line file. **If, while implementing, any single emitter needs real recursion / a real type
  system to handle the 0b records, I STOP and flag it in the report** rather than growing it — that
  pressure is the signal to reconsider codegen (a decision for Mo). The interface shape is already
  identified as over the line, hence the 0c split.
- **PyYAML pinning (hermetic codegen):** add a pinned **`codegen` dependency group** to the root
  `pyproject.toml` (`pyyaml>=6.0,<7.0`) and change `make codegen` from `uv run --no-project --with
  pyyaml …` to a pinned-group invocation. **Wrinkle (OQ-6):** codegen must still run *before* `uv sync`
  builds `eunomia-contracts` (its package *is* the generated tree) — so the invocation must install the
  group without building the project. Recommended: `uv run --no-project --only-group codegen python
  contracts/codegen/generate.py`, verified at implement-time to resolve the chicken-egg; fallback is a
  pinned `contracts/codegen/requirements.txt` via `--with-requirements`. CI installs this group before
  the drift gate.

---

## 7. Conformance fixtures plan

Per entity (sidecar, release, events), three fixture classes — the **`warn/`** class is new (the
severity split):

| Class | What it contains | Expected verdict |
|---|---|---|
| `valid/` | a full record + a minimal-hard-only record | `jsonschema` accepts; overlay → `([], [])` |
| `invalid/` | missing a hard field; **empty** `kit_id`/`side`; missing `schema`; wrong-typed hard field; v1 file missing `prompt`/`task_source` | `jsonschema` rejects; overlay → hard_errors ≠ [] |
| `warn/` | missing a warn field (e.g. `episode_ordinal`); **malformed** warn field (wrong type — the downgrade demo); `recording_suspect`/`archive` set | `jsonschema` *may* flag the malformed-warn structural error; overlay **downgrades** → `([], ["warn: …"])` = **valid-with-warnings** |

**Proving the three targets agree** (per entity, in `test_conformance.py`): (a) real `jsonschema`
accepts every `valid/`+`warn/`, rejects every `invalid/`; (b) the generated Python `validate_full`
returns the same accept/reject *and* the same hard-vs-warn partition (the shipped stdlib validator does
not diverge from the canonical schema); (c) the C++ header parses the same `valid/`+`warn/` fixtures
(structural subset it owns — OQ-5) via `pio test -e native`. Per-entity accept/reject/warn counts go in
the report. The **malformed-warn fixture is the headline demo** the report calls out (warn-vs-hard
working). The codegen-drift gate must stay green on the committed tree.

---

## 8. Gate + drift impact

**The 5 Hermes Python gates stay byte-identical in command and order** — confirmed:

```
uv run pytest  →  uv run ruff check .  →  uv run ruff format --check .  →  uv run mypy .  →  uv run lint-imports
```

What changes (none of it alters those 5 command strings):

| Change | Detail |
|---|---|
| New dev dep | `jsonschema>=4.0,<5.0` in a dev/validation group; likely `types-jsonschema` too so `mypy .` stays clean (flag/verify) |
| Codegen invocation | `make codegen` → pinned `codegen` group (§6, OQ-6); CI installs it before `make drift` |
| `make codegen` produces more files | `_generated/{cpp,python,jsonschema}` gain the real entities, lose the `ping` ones; **`make drift` (codegen && git diff --exit-code _generated) must be 0** |
| pytest scope | `conformance/test_conformance.py` replaces `test_ping_conformance.py`; uses `jsonschema`; still under `testpaths=["contracts","tooling"]` |
| C++ gate | `pio test -e native` now builds `test_contract.cpp` over the real headers; `platformio.ini` `EUNOMIA_FIXTURES_DIR` repointed; **still blocking**. esp32 target + clang-tidy **stay non-blocking** in 0b |
| import-linter | `eunomia_contracts` still "imports nothing internal"; if the overlay is a separate package (OQ-3) it is added to `root_packages` with its own forbidden/independence contract; otherwise unchanged |
| ruff/format | generated output **and** the hand-written overlay + conformance test must be ruff- and ruff-format-clean as emitted/written |

`contracts/pyproject.toml` stays `dependencies = []` (pure-stdlib shipped validator). No new blocking
gates; the hybrid validator rides the existing pytest gate.

---

## 9. Open Questions — ALL RESOLVED (Mo's annotations folded in)

**OQ-1 — ONE run or split? → RESOLVED: SPLIT (A).** 0b = record surface + hybrid validator; 0c =
operational model + interfaces. The release-via-id-references seam is the cut. Sequencing note: 0b
unblocks firmware *starting* (sidecar + events C++ headers it writes/emits); 0c unblocks firmware's
*port-based* structure (Coordinator/CaptureDevice ports = the swappable-transport seam).

**OQ-2 — sidecar JSON shape → RESOLVED: match the as-built nesting, reconciled to CONTRACT's clean
groups.** Confirmed against the reachable as-built (§4.1): `identity` is nested too (not just
`timing`+`files`). Encode the §2.2 groups as nested objects (`identity`/`timing`/`provenance`/
`outcome`/`files`) + top-level scalars (`schema`/`record_format_version`/`seq`/`global_episode_seq`).
Generator nesting stays **one level, no recursion**. Judgment calls (provenance/outcome nesting, `seq`
numeric, no `timestamp`) flagged in §4.1 + the report.

**OQ-3 — overlay placement → RESOLVED: (A) with a SHARP boundary.** Declarative-in-source is limited to
what is essentially **DATA** — the severity table (field→hard|warn), enum value-sets, `minLength`, and
the **one** conditional-presence rule — all generated into simple **table lookups**. Anything that is
actual **LOGIC** (cross-field rules like `void ⇒ void_reason`) is **hand-written** in the small
pure-stdlib overlay module (`eunomia_contracts._semantics`), **NOT** generated from a YAML rule-DSL
(generating arbitrary cross-field logic is a mini rules-engine — the STOP-and-flag target). The
hand-written overlay stays small + pure-stdlib and ships in the contracts wheel.

**OQ-4 — v1-extra conditional → RESOLVED: (A) semver pattern.** `^eunomia-sidecar/v[1-9][0-9]*$` ⇒
require the v1-extra hard set, in `if/then`; the stdlib side parses the int and applies `>= 1`.

**OQ-5 — C++ target scope → RESOLVED: (A).** C++ emitted only for firmware-relevant records (sidecar +
events), scoped to struct + serialize + flat scalar/string parse, **no nested parse**. Release +
(0c) operational are Python+JSON-Schema only. The C++ structural-subset scope is stated honestly in
the conformance report.

**OQ-6 — PyYAML codegen invocation → RESOLVED: (A, fallback B).** `uv run --no-project --only-group
codegen …`; verify it resolves a group without building the project (the chicken-egg). Fallback: pinned
`contracts/codegen/requirements.txt` via `--with-requirements`. Requirement (pinned, hermetic,
CI-installed-before-drift) is fixed; incantation confirmed at implement-time.

**OQ-7 — events shape → RESOLVED: (A).** One polymorphic telemetry-event record with an `event` enum
discriminator + conditional fields, mirroring `pantheon-trigger-episode/v1`. Sync-delta is its own
source.

**OQ-8 — generator structure → RESOLVED: (B if the monolith crosses ~150 lines while staying
obvious).** Driver + `emitters/{jsonschema,python,cpp}` sharing one field-DSL parser; budget read **per
emitter**. STOP-and-flag still governs real-complexity growth in any single emitter.

---

## 10. What 0b deliberately does NOT do (restated)

- **No module logic** — no firmware trigger state machine, no ingest/identity/join/QC implementation,
  no edge/store, no consoles. 0b is the *contract*, not its consumers. The dual-signal join's *rules*
  are encoded (as types + documentation; in 0c with the operational model) — the join *implementation*
  that runs at ingest is a later run.
- **No substrate scripts, no web stack, no Hermes-side cleaning code.**
- **Does not pick the Hermes contract-consumption mechanism** (package vs submodule vs vendored) — 0b
  just makes `release/` the clean, pinned surface.
- **Recommended-deferred to 0c (OQ-1):** the full operational model (§3 entities/events/as-of, the
  precedence/crosswalk/join *logic*) and the interfaces (`CoordinatorPort`/`CaptureDevicePort`).
- **Does not grow the generator into a framework** — if the 0b records push any emitter into real
  complexity, the run STOPS and flags rather than absorbing it (§6).

---

Plan ready for annotation — I have not implemented anything.
