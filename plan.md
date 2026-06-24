# Run 0c (plan-only) — `contracts/operational/` + `contracts/interfaces/`

> **Status: APPROVED — split confirmed; implementing 0c (interfaces) only.** All open questions are
> resolved with Mo's annotations: **LEAD-OQ-A → (C)** the separate `generate_interfaces.py`
> mini-emitter (closed type vocabulary held — a type outside the set is a STOP-and-flag, not an IDL
> extension); **LEAD-OQ-B → SPLIT, interfaces-first** — **0c = interfaces** (this run: the mini-emitter
> + `ports.iface.yaml` + the two generated artifacts + conformance/compile/type-check proof);
> **0d = the operational model** (held; OQ-3/4/5/6/9/10/11/12 pre-approved above carry into 0d's plan).
> **OQ-7 → the generated `Sidecar` / `const eunomia::Sidecar&` for `write_sidecar`'s record param
> (not dict). OQ-8 → sibling `make codegen` commands; single drift gate covers both.**
> (This replaces the merged Run 0b plan, which lives in git history at `201c0d5`.)
>
> Authority read for this plan: `docs/CONTRACT.md` §3 (operational model) + §1.6/§7 (seams, episode-id),
> `docs/DECISION_REGISTER.md` (B-8, B-9, A-2, C-9..C-12, the 2026-06-24 spot-check block, the 0b
> carry-forwards), `docs/SPEC.md` §1.6/§1.7 (the two ports), §3.2–§3.6; and the as-built 0b machinery
> (`contracts/codegen/generate.py`, the field-DSL YAMLs, `_semantics.py`, `test_conformance.py`).

---

## 1. Summary

**What this run produces** (the two areas 0b deferred):

- **`contracts/operational/`** — the event-sourced operational model (CONTRACT §3): nine entity
  schemas (`person`, `hardware_unit`, `kit`, `calibration`, `task`, `session`, `capture_stack`,
  `footage_reference`, `episode`) as **record-shaped schemas reusing the 0b field-DSL + hybrid
  validator unchanged**, plus the append-only **event/lifecycle** representation, plus the §3 rules
  (identity precedence §3.3, crosswalk/retargeting §3.4, task precedence §3.5, the dual-signal join
  §3.6) encoded as **typed fields + documentation** (and `_semantics` overlay only where a rule is a
  single-record cross-field check) — **not** as an enforced join. As-of resolution is encoded
  *temporally* (validity ranges + event `as_of`); the resolver/materializer is a later run.
- **`contracts/interfaces/`** — `CoordinatorPort` + `CaptureDevicePort` as explicit interface
  definitions emitted to a **C++ abstract header + a Python `Protocol`**, per the representation chosen
  in **LEAD-OQ-A**.
- **Conformance** — fixtures (valid/invalid/warn[/semantic_invalid]) for every operational entity
  through the same hybrid validator; an interface in-sync proof; the drift gate stays green.

**What it defers** (restated in §10): no module logic (no firmware state machine, no
ingest/identity/join/QC/edge/console code); the join/precedence/as-of **implementation**; the
spot-check tuning values (N%, N-day, watermark); the firmware-vs-ingest resolution of the
sidecar-shape divergence; how Hermes consumes the contract.

---

## 2. ⭐ The two lead open questions (assess + recommend; Mo decides at annotation)

### LEAD-OQ-A — How does the generator represent an INTERFACE?

`CoordinatorPort`/`CaptureDevicePort` are **operation signatures** (`mint_episode_id() -> uuid`,
`trigger(cameras) -> ack`, `read_clip_filename(camera) -> str`, `write_sidecar(camera, record)`,
`detect_drop() -> set[camera]`, `flush_telemetry()`; and start/stop/read-filename/get-state/set-profile/
write-sidecar for the device). They **do not fit the field-list DSL** the 0b generator uses for records
— there is no hard/warn field surface, no JSON Schema target (an interface is not a data record), and
the artifacts are kind-different (a C++ pure-virtual class vs a Python `Protocol`). The 0b carry-forward
flagged this verbatim: *"0c's interface (operation-signature) shape is the real codegen STOP-and-flag
line — signatures don't fit the field-DSL at all; reconsider the codegen approach there."*

| Option | What it is | Pro | Con |
|---|---|---|---|
| **(A)** Extend `generate.py` with a signature IDL | Second source shape + signature emitters inside the record generator | Interfaces stay "generated, single-source" like records | Grows the **record** generator into a second type system — **exactly the STOP-and-flag line**. Disfavored. |
| **(B)** Hand-write both artifacts | A C++ abstract header + a Python `Protocol`, by hand, no codegen | Zero generator complexity; honest that the field-DSL doesn't fit; interfaces are small + rarely change | **No drift guard** — the two language artifacts are kept in sync by discipline only; they live outside the "one source → targets" model (silent cross-language drift is the cardinal sin this whole spine exists to prevent) |
| **(C)** A **separate, tiny interface mini-emitter** | One small signature-YAML → a **dedicated** emitter (NOT `generate.py`) → C++ abstract header + Python `Protocol`, both committed + drift-gated | Preserves the project's defining no-silent-drift property for the interface artifacts; **honors STOP-and-flag as written** (it guards `generate.py` from becoming a framework — a *separate* bounded emitter for a genuinely different artifact does not touch the record generator); signature surface is tiny + fixed (2 ports, ~12 ops) so the emitter stays ~80–120 lines | It *is* new generator code (one more emitter) and a second source shape exists in the tree — but **isolated**, not entangled with records |

**Recommendation: (C) — a separate interface mini-emitter** (`contracts/codegen/generate_interfaces.py`),
single signature-YAML source → **two** targets (C++ abstract header + Python `Protocol`; **no** JSON
Schema — interfaces aren't records). Reasoning:

- The spine's entire reason for existing is *no silent drift between cross-language producers/consumers*
  (D-2, D-4). `CoordinatorPort` has a C++ implementer (firmware) and a Python parallel (the harness /
  a future non-ESP32 coordinator, SPEC §1.6). (B) abandons the drift guard for precisely the artifact
  where drift is most expensive; (C) keeps it "for free" (one source → both).
- The STOP-and-flag rule guards **`generate.py`** (the record/field-DSL path) from becoming a framework.
  (A) violates it by folding a second shape into that path. (C) does **not** grow `generate.py` at all —
  it stays records-only; the signature shape lives in its own bounded emitter. That is the opposite of
  framework-creep.
- The wiring sidesteps the 0b mypy-from-root constraint (`generate.py` docstring OQ-8: an intra-`codegen`
  import breaks `mypy .`-from-root under the no-config gate): the mini-emitter is a **sibling top-level
  script**, *not* imported by `generate.py`. `make codegen` runs both scripts sequentially; the single
  `git diff --exit-code contracts/_generated` drift gate already covers both (both write into
  `_generated/`). No intra-`codegen` import ⇒ no mypy resolution issue.

**Honest fallback for annotation:** if Mo judges a generator unjustified for ~12 rarely-changing
operations, fall back to **(B) hand-write + a cross-language parity test** (a Python test that
string-parses the C++ header's method declarations and compares the operation set + arity to the Python
`Protocol`'s, via `typing`/`inspect`) — that recovers *most* of the drift guard without an emitter, at
the cost of a hackier test. **(A) is not recommended.** The concrete design for (C) is in §5.

### LEAD-OQ-B — One run, or split (0c / 0d)?

Encoding the full §3 model (9 entities + the event representation + as-of + the join rules as
types+docs + per-entity fixtures) **and** the interfaces is a lot, and they are **two different shapes
of work**: operational = familiar field-DSL records (settled 0b machinery); interfaces = the genuinely
new emitter. They have **no contract-level dependency on each other** (episode references operational
entities by id; the ports are firmware seams; the sync-delta stub waits on the *operational* schemas,
not the ports).

**Recommendation: SPLIT, interfaces-first** — **0c = interfaces**, **0d = the operational model** —
reasoned on the same shape/urgency/generator-cost/reviewability axes 0b used:

- **Urgency** → interfaces-first. `CoordinatorPort` defines the swappable-transport seam the firmware's
  port-based architecture is built on, and **firmware is a near-term run** (BUILD_PLAN phase 3). The
  operational model unblocks ingest/edge (later phases). Nothing is blocked-and-bleeding on the
  operational schemas today (0b left the sync-delta `entity`/`payload` deliberately opaque, no gate is
  red).
- **Generator cost** → isolate the new machinery first. 0c lands + drift-gates the new mini-emitter in a
  small, low-blast-radius PR; the larger operational PR (0d) then rides on a settled toolchain and reuses
  the untouched record generator.
- **Reviewability** → two focused PRs beat one PR that mixes a signature emitter with 9 record entities +
  rules-as-docs. (0b split operational+interfaces out of the record surface for exactly this reason.)

**Alternative (one run):** lower coordination overhead; both areas fit conceptually under "the two
deferred areas." Defensible if Mo prefers fewer runs — the plan below is **written to support either**:
its two halves (Part A: interfaces §4.3+§5; Part B: operational §4.1–§4.2+§4.4) map cleanly onto 0c/0d
if split, or combine into one run if not.

> The rest of this plan covers **both** areas in full so it stands as a one-run plan; if split is
> chosen, "0c" = the interfaces half and "0d" = the operational half.

---

## 3. The `contracts/` tree after this run (annotated)

```
contracts/
├── operational/                              [Part B — was a 0b stub README]
│   ├── README.md                             (rewrite: stub → real)
│   ├── eunomia-person.schema.yaml            NEW   (§3.1 person; jsonschema+python)
│   ├── eunomia-hardware-unit.schema.yaml     NEW   (§3.1 hardware_unit + status enum)
│   ├── eunomia-kit.schema.yaml               NEW   (§3.1 kit; time-bound binding)
│   ├── eunomia-calibration.schema.yaml       NEW   (§3.1 calibration; scope enum, C-11)
│   ├── eunomia-task.schema.yaml              NEW   (§3.1 task; versioned prompt)
│   ├── eunomia-session.schema.yaml           NEW   (§3.1 session; fob_session_id)
│   ├── eunomia-capture-stack.schema.yaml     NEW   (§3.1 capture_stack, B-9)
│   ├── eunomia-footage-reference.schema.yaml NEW   (§3.1 footage_reference, A-2 + spot-check hold)
│   ├── eunomia-episode.schema.yaml           NEW   (§3.2 episode — the join point)
│   └── eunomia-operational-event.schema.yaml NEW?  (append-only lifecycle event; see OQ-3/OQ-4)
├── interfaces/                               [Part A — was a 0b stub README]
│   ├── README.md                             (rewrite: stub → real)
│   └── ports.iface.yaml                      NEW   (the signature source; LEAD-OQ-A option C)
├── codegen/
│   ├── generate.py                           UNCHANGED (records only; stays ~358 lines)
│   ├── generate_interfaces.py                NEW   (the mini-emitter; LEAD-OQ-A option C)
│   └── templates/
│       ├── header.h.tmpl / detail.h.tmpl / semantics.py.tmpl   UNCHANGED
│       ├── port.h.tmpl                        NEW   (C++ abstract-header template, fills per port)
│       └── protocol.py.tmpl                   NEW   (Python Protocol template)
├── events/
│   └── eunomia-sync-delta.schema.yaml        EDIT? (entity enum / payload tightening — OQ-9; with 0d)
├── _generated/                               (all regenerated by `make codegen`; committed, drift-gated)
│   ├── cpp/
│   │   ├── eunomia_coordinator_port.h         NEW   (generated abstract header)
│   │   └── eunomia_capture_device_port.h      NEW
│   ├── python/eunomia_contracts/
│   │   ├── person.py … episode.py             NEW   (dataclass + tables + validate/validate_full)
│   │   ├── operational_event.py               NEW?  (OQ-3/OQ-4)
│   │   ├── interfaces.py                       NEW   (the Python Protocols)
│   │   ├── _semantics.py                       EDIT  (add operational cross-field rules; OQ-11)
│   │   └── __init__.py                          regen (records only; interfaces imported by submodule, OQ-7)
│   └── jsonschema/
│       └── eunomia-person.schema.json …        NEW   (operational entities only; interfaces have none)
└── conformance/
    ├── fixtures/<entity>/{valid,invalid,warn[,semantic_invalid]}/   NEW per operational entity
    └── test_conformance.py                     EDIT  (ENTITIES dict + interface-sync test)
```

Everything else under `contracts/` (sidecar/, release/, the 0b generated targets) is **untouched**.

---

## 4. Per-area plan

> Field-level detail is **not re-typed** here (CONTRACT §3 is authority). Each entity below names its
> source file, the CONTRACT/decision reference, the key fields/enums/cross-field rules, and any
> generator-shape concern. Hard/warn rationale follows the 0b judgment call (HARD = corruption makes the
> record unsafe to use as an identity/join anchor; everything else WARN/nullable) and is annotated per
> entity for review.

### 4.1 The operational entities (Part B) — record-shaped, reuse the 0b DSL

| Entity / file | Encodes (CONTRACT §) | Key fields · enums | Cross-field / shape notes |
|---|---|---|---|
| **person** `eunomia-person.schema.yaml` | §3.1 person (B-8); SPEC §3.2.1 | `person_id` (HARD), name/handle, `status` enum `active\|offboarded`, onboarded/offboarded dates, site(s) | Decoupled from kit (binding lives on `kit`/`session`, not here). Employment lifecycle = events (OQ-3). |
| **hardware_unit** `…hardware-unit…` | §3.1 (B-9, R-2); SPEC §3.2.2/§3.3 | `unit_id` (HARD), `type` enum `fob\|camera\|sd\|gripper`, serials (`body_serial`, `insv_serial` IAQEB…, MAC), `batch_id`, `hardware_version`, `status` enum `received→provisioned→deployed→faulted→retired`, current `kit_id`, camera `side` | **Serials immutable + crosswalk key, NEVER decide kit** (§3.3) — documented. Status *value* is single-record-checkable; **transition legality is multi-record → docs + the event log (OQ-4), not a single-record rule**. Lifecycle events: OQ-4. |
| **kit** `eunomia-kit.schema.yaml` | §3.1; SPEC §3.2.2 | `kit_id` (HARD); a **time-bound binding** of {left-cam unit, right-cam unit, fob unit} with `effective_from`/`effective_to` (OQ-6) | Camera→side is a property of the unit binding (NAND), not the kit. Spares = pre-bound side-typed units. |
| **calibration** `…calibration…` | §3.1 (C-11) | `calibration_id`, `scope` enum `none\|fleet\|per_camera`, `camera_serial`, validity range, heavy data (intrinsics/distortion/method/captured_at) | Optional entity; `calibration_id` nullable on episode. Which world we're in is **data (scope), not structure**. |
| **task** `eunomia-task.schema.yaml` | §3.1/§3.5; SPEC §3.2.3 | `task_id` (HARD), `task_name`, `prompt`, `rotation_id`, `station_id`; structured attrs (category, bimanual, expected_duration, difficulty) | **Versioned** — a prompt change is a new version; episodes resolve prompt **as-of recorded_at** (OQ-6). Carries only task fields, never identity. |
| **session** `eunomia-session.schema.yaml` | §3.1; SPEC §3.2.1 | `session_id` (HARD), `person_id`, `kit_id`, `site_id`, `station_id`, **`fob_session_id`** (random per fob boot — fob-swap key), signed_in/out, `task_id`, pause tracking | Open/close = events (OQ-3). The time-series that makes churn/throughput queryable. |
| **capture_stack** `…capture-stack…` | §3.1 (B-9) | `capture_stack_id` (HARD), `modality` enum `umi\|teleop`, camera model/fw, fob board/fw, gripper hw, SD model, coordinator sw version | Reference-by-id from episode (don't bloat episodes). Firmware update = a new stack version / `unit_firmware_updated` event (resolvable as-of). |
| **footage_reference** `…footage-reference…` | §3.1 (A-2) + the 2026-06-24 spot-check block | `episode_id` (HARD), `footage_state` enum `on_card→on_styx→shipped→on_hades→purged`, `locations`, optional `hash`; **spot-check hold** fields (OQ-5): `spot_check_selected`, `selection_method` enum `qc_sample\|manual_pull`, `rendered_on_hades_at`, `purge_eligible_at` | **Must express the held-purge** — see §4.2 + OQ-5. Tuning values (N%, N-day, watermark) are OUT of scope (§8 OPEN). Note `purged` (CONTRACT §3) vs `purged_from_styx` (A-2) naming — CONTRACT §3 wins; flagged. |
| **episode** `eunomia-episode.schema.yaml` | §3.2 — **the join point** | `episode_id` (UUIDv4, HARD), `display_id` (WARN, derived), `bimanual_episode_id`, `episode_ordinal`, `global_episode_seq` (HARD); references resolved as-of `recorded_at`: `person_id`, `kit_id`+`side`, `task_id`, `calibration_id`, `capture_stack_id`, `session_id`; `recorded_at`/`ingested_at`; state `paired`/`void`+`void_reason`/`needs_review`/`archive`/`recording_suspect`; `pairing_method` enum `episode_id\|ordinal_join\|needs_review` + `pairing_anomaly` (C-12); embeds/refs a `footage_reference` | `void⇒void_reason` cross-field rule mirrors release (OQ-11). The references are stored here; **resolution as-of recorded_at is what ingest does** (later run). |

**Shape budget (important):** every entity stays within the **existing DSL** — top-level scalars +
**one** level of nested objects + scalar arrays (`items:<type>`). No entity is allowed to force
array-of-objects or 2-level nesting (which would grow the generator). Where the model wants a
repeating sub-structure (e.g. a unit's lifecycle history, a kit's multiple bindings over time, multiple
footage `locations`), it is modeled as **a separate append-only event/binding record referenced by id**
(OQ-4), **not** an embedded object array. If any entity genuinely cannot be expressed this way, that is
a STOP-and-flag → raised as an OQ, not silently extended.

**Targets:** operational entities are **`[jsonschema, python]`** only — firmware never reads the
operational model (it writes the sidecar + emits telemetry). The C++ flat-bag emitter is **untouched**
(OQ-10).

### 4.2 Event-sourcing, as-of resolution, and the footage hold

- **Event-sourced representation (OQ-3).** Each entity above is the **current-state (materialized-view)
  record**. The append-only **event log** is represented by (a) the existing **`eunomia-sync-delta`
  envelope** as the generic upsert/delete transport (tightened so `entity` is the set of operational
  entity names and `payload` is documented to validate against the entity schema — OQ-9), plus (b) a
  first-class **`operational-event`** record where a lifecycle carries its own fields beyond the entity
  snapshot (hardware-unit status transitions with `reason`+related refs; person onboard/offboard;
  session open/close; `unit_firmware_updated`; calibration recorded; task version bump). The
  **fold/materializer is NOT implemented** — 0c/0d defines the types and documents the derivation.
- **As-of resolution (OQ-6).** Encoded *temporally* at the type level: time-bound bindings carry
  explicit validity ranges (`effective_from` / nullable `effective_to` = open/current) — kit↔person,
  kit↔units, calibration validity, task version validity; events carry `as_of`. Episode carries
  `recorded_at`. The **rule** ("an episode resolves its references against the binding true at
  `recorded_at`") is documented; the **resolver runs at ingest = later run**.
- **The footage held-purge (OQ-5).** `footage_reference` expresses the spot-check semantics from the
  2026-06-24 decision: keep until **(a) `rendered_on_hades_at` is set AND (b) the N-day window elapses,
  whichever is LONGER** → `purge_eligible_at`; `spot_check_selected` + `selection_method` mark *why*
  it's held; the Styx watermark is an **operational threshold (config) documented as a bounding
  override**, its value deferred (§8). The faithfulness check (§ when implemented) will confirm the
  lifecycle can express held-purge / N-day / watermark.

### 4.3 The §3 rules — types + documentation, NOT enforced single-record validation

The join/precedence/as-of logic is **multi-entity, join-time** — not validatable on one record (the
honest-scope position 0b established). Encoded as **typed fields + prose in the entity READMEs/schema
comments**, with `_semantics` used **only** where a rule is genuinely a single-record cross-field check:

| Rule (CONTRACT §) | How 0c/0d encodes it | Single-record `_semantics` rule? |
|---|---|---|
| **Identity precedence** §3.3 (kit←fob, side←NAND, operator←roster, station+prompt←fob trigger; serials never decide) | Typed reference fields on `episode` + prose; precedence is applied by the ingest resolver (later) | No (multi-entity) |
| **Crosswalk + serial retargeting + kit aliases** §3.4 | `insv_serial`/`body_serial` on `hardware_unit` as the crosswalk key; alias mapping documented | No (multi-entity) |
| **Task precedence** §3.5 (NAND → SD → none) | `task_source` enum already on the sidecar; documented on `task`/`episode` | No |
| **Dual-signal join** §3.6 (ordinal spine + duration guardrail; tiebreaks `ordinal_slip`/`board_swap`/`clock_suspect`/`needs_review`; phantom-press gate `sent==2`; block-labeling; void-by-flag) | `pairing_method` + `pairing_anomaly` on `episode` (C-12); tiebreak names + the gate documented | No (the join itself is a later run) |
| **Void requires reason** §4.1/§3.2 | — | **Yes** — `episode.void⇒void_reason` mirrors the release rule, hand-written in `_semantics` keyed by the episode schema id (OQ-11) |
| **Footage hold consistency** (OQ-5) | — | **Yes (candidate)** — `spot_check_selected ⇒ selection_method present`; flagged for review |

### 4.4 Conformance — extend the harness (records) + prove interface sync

- **Operational entities:** per entity, fixtures in `valid/`, `invalid/`, `warn/` (and
  `semantic_invalid/` for episode's void rule + footage's hold rule), run through the **same hybrid
  validator** — real `jsonschema` Draft 2020-12 for structure + the stdlib `_semantics` overlay for the
  hard-vs-warn split + cross-field rules. Mechanically: add each entity to the `ENTITIES` dict in
  `test_conformance.py`; the existing parametrized `valid/invalid/warn/semantic_invalid` test bodies
  pick them up with no new test logic (only the dict + the `validate`-parity map grow).
- **Interface sync proof (per LEAD-OQ-A):**
  - **If (C) generated:** the in-sync proof *is* the drift gate — both the C++ header and the Python
    `Protocol` come from one `ports.iface.yaml`, so `make codegen && git diff --exit-code
    contracts/_generated` proves they cannot drift. Plus: the generated C++ abstract header must
    **compile in `pio test -e native`** (add an `#include` + a trivial mock implementer that overrides
    the pure-virtuals — proves the header is implementable), and the generated Python `Protocol` is
    under `mypy .` already (add a tiny mock class asserted to satisfy it, mypy-checked).
  - **If (B) hand-written fallback:** show the C++ header builds and the `Protocol` type-checks, and
    state plainly there is no codegen guard (discipline + the optional parity test only).

---

## 5. The interface-representation design (LEAD-OQ-A → option C, concretely)

**Source — `contracts/interfaces/ports.iface.yaml`** (a *separate shape* from the field-DSL): a list of
ports, each with a doc string and a list of operations; each operation has `name`, `params`
(name+type), `returns` (type), `doc`. A tiny fixed **type vocabulary** maps to each language:

| IDL type | C++ | Python |
|---|---|---|
| `uuid` / `str` / `filename` | `std::string` | `str` |
| `ack` | `bool` (or a small struct — OQ) | `bool` |
| `camera` | an enum/id (`std::string`) | `str` |
| `set[camera]` | `std::vector<std::string>` | `set[str]` |
| `record` (sidecar) | `const eunomia::Sidecar&` | `Sidecar` (or `dict` — OQ-7) |
| `state` | enum | `str`/`Enum` |
| `profile` | descriptor (`std::string`) | `str` |
| `void` | `void` | `None` |

**The operations (sourced from CONTRACT §1.6 / SPEC §1.6 / MODULE_MAP):**

*CoordinatorPort* — `mint_episode_id() -> uuid`; `trigger(cameras) -> ack` (serialized, near-simultaneous;
the phantom-press gate `sent==2`; **no per-take arm** — discardd holds video mode);
`read_clip_filename(camera) -> filename`; `write_sidecar(camera, record) -> void`;
`detect_drop() -> set[camera]` (at the L2/network-association layer, **not** OSC polling);
`flush_telemetry() -> void` (idle-gap god's-view events).

*CaptureDevicePort* — `start() -> void`; `stop() -> void`; `read_back_filename() -> filename`;
`get_state() -> state`; `set_profile(profile) -> void`; `write_sidecar(record) -> void`.

**Emitted artifacts (one source → two targets; no JSON Schema):**

- `contracts/_generated/cpp/eunomia_coordinator_port.h` + `…_capture_device_port.h` — a pure-virtual
  abstract class per port (`virtual <ret> <op>(<params>) = 0; … virtual ~Port() = default;`), filled
  from `templates/port.h.tmpl`. Must compile in the native test.
- `contracts/_generated/python/eunomia_contracts/interfaces.py` — a `typing.Protocol` per port (method
  signatures with type hints, `...` bodies), filled from `templates/protocol.py.tmpl`. Ruff-clean as
  emitted; mypy-clean.

**Kept in sync / drift-checked:**

- The mini-emitter `contracts/codegen/generate_interfaces.py` is a **sibling top-level script** (NOT
  imported by `generate.py` — avoids the mypy-from-root issue, `generate.py` docstring OQ-8). `make
  codegen` runs **both** scripts; the existing `git diff --exit-code contracts/_generated` covers both
  outputs. Same source → both targets ⇒ they cannot drift.
- `interfaces.py` is **not** added to the generated `__init__.py` (which `generate.py` builds from the
  record specs only) — consumers `from eunomia_contracts.interfaces import CoordinatorPort`. This keeps
  the two emitters fully decoupled (OQ-7).

---

## 6. Codegen + generator-budget impact

| Area | Generator impact | Budget verdict |
|---|---|---|
| **Operational records** | **None to `generate.py`** if every entity stays within the existing DSL (1-level nesting + scalar arrays; repeating structures → separate event/binding records, §4.1). Cross-field rules are hand-written in `_semantics` (OQ-3 boundary), keyed by schema id — same pattern as the release void rule. | Record-shaped → **cheap.** `generate.py` stays ~358 lines. |
| **Interfaces** | A **new** `generate_interfaces.py` (~80–120 lines: parse the signature YAML, fill two templates) + two templates. **`generate.py` is not touched.** | The real new machinery — but **isolated**; the record generator does **not** become a framework. STOP-and-flag **honored**. |

**If implementation reveals an entity needs array-of-objects or 2-level nesting** (a generator
extension), that is the STOP-and-flag trigger → stop and raise it, do not grow the DSL silently.

---

## 7. Conformance plan (summary)

- **Per operational entity:** `valid/` (real `jsonschema` accepts + stdlib hard==[]), `invalid/`
  (both reject), `warn/` (hard==[] with warnings — exercises the severity split), and
  `semantic_invalid/` for `episode` (void without reason) + `footage_reference` (selected without
  method). `test_conformance.py` grows by the `ENTITIES` dict + the hard-only parity map only.
- **Interfaces (option C):** drift gate = the in-sync proof; C++ header compiles + is mock-implemented in
  `pio test -e native`; Python `Protocol` is mypy-checked + structurally satisfied by a mock. (Option B
  fallback: build/type-check only + a stated no-guard caveat + optional parity test.)

---

## 8. Gate + drift impact

- **The 5 Python gates stay byte-identical** (`uv run pytest` → `ruff check .` → `ruff format --check
  .` → `mypy .` → `lint-imports`, on tool defaults — there remains **no** `[tool.ruff]`/`[tool.mypy]`
  section). New generated Python (entity modules + `interfaces.py`) must be ruff-format-clean **as
  emitted**; the existing `make codegen` step already runs `ruff format contracts/_generated/python`,
  so the drift gate stays meaningful.
- **No new dev/runtime deps expected.** `jsonschema`/`types-jsonschema` already present (0b); the
  mini-emitter uses PyYAML (already pinned in `contracts/codegen/requirements.txt`) + stdlib; the
  shipped validator stays pure-stdlib. **To confirm at implement** (state plainly if any dep is added).
- **import-linter unchanged.** New modules live under `eunomia_contracts` (intra-package). The forbidden
  contract (`eunomia_contracts` must not import `eunomia_bench_harness`) still holds. If `interfaces.py`
  types `write_sidecar`'s param as the generated `Sidecar` dataclass, that is an intra-`eunomia_contracts`
  import (allowed); `dict` avoids it entirely (OQ-7).
- **`testpaths` already includes `contracts`** → new fixtures + conformance params are auto-collected.
- **C++ gates:** `clang-format` runs on **hand-written** firmware only (generated headers are exempt but
  must compile); `pio test -e native` gains the port-header compile/mock if interfaces are in this run.

---

## 9. Open questions (numbered; options + recommendation)

- **OQ-1 = LEAD-OQ-A** (interface representation). **Rec: (C)** separate mini-emitter; **(B)** the
  honest fallback; **(A)** not recommended. (§2, §5.)
- **OQ-2 = LEAD-OQ-B** (one run vs split). **Rec: split, interfaces-first** (0c = interfaces, 0d =
  operational). (§2.)
- **OQ-3 — Event-log representation.** (a) current-state records + tightened sync-delta envelope + a
  first-class `operational-event` record; (b) current-state records only + envelope (no dedicated event
  record); (c) full per-entity event schemas. **Rec: (a)** — minimal + reuses 0b; the dedicated event
  record exists only where a lifecycle carries its own fields. Fold/materializer = later run.
- **OQ-4 — Lifecycle history shape.** Embedded array-of-objects on the entity (⇒ **DSL extension /
  STOP-and-flag**) vs a **separate append-only event record** (telemetry-style discriminator, fits the
  existing DSL). **Rec: separate event record — no generator change.**
- **OQ-5 — `footage_reference` held-purge fields.** **Rec:** `footage_state` enum +
  `spot_check_selected` + `selection_method` enum + `rendered_on_hades_at` + `purge_eligible_at`
  (= max(rendered-on-hades, N-day window)); the watermark threshold + N%/N-day **values stay OUT of
  scope** (§8 OPEN / tuning). Resolve the `purged` vs `purged_from_styx` name (CONTRACT §3 = `purged`).
- **OQ-6 — As-of / validity ranges.** Explicit `effective_from`/nullable `effective_to` on time-bound
  bindings (kit↔person, kit↔units, calibration, task version) + event `as_of`. **Rec: yes**; the
  resolver is a later run.
- **OQ-7 — `interfaces.py` export + sidecar param typing.** **Rec:** keep interfaces **out** of the
  generated `__init__` (decoupled emitters; import by submodule path); type `write_sidecar`'s record as
  the generated `Sidecar` dataclass (precise; intra-package import allowed) **or** `dict` (fully
  decoupled). Lean precise; flag for Mo.
- **OQ-8 — Mini-emitter wiring.** Run `generate.py` then `generate_interfaces.py` as **sibling commands**
  in `make codegen` (no intra-`codegen` import → no mypy-from-root breakage). **Rec: yes** — single
  drift gate covers both.
- **OQ-9 — Tighten the 0b `sync-delta` stub.** Make `entity` an enum of operational entity names +
  document `payload` against the entity schemas. **Caveat:** an enum on a previously-open string is a
  **narrowing**, not additive (CONTRACT §5) — so either bump `sync-delta` to `/v2`, or express the
  entity set as a **WARN-level `_semantics` check** (structurally still an open string, additive-safe).
  **Rec: the WARN-level check** (keeps v1 additive) unless Mo wants the version bump; lands with 0d.
- **OQ-10 — Operational C++ target.** **Rec: none** — operational entities are `[jsonschema, python]`;
  firmware never reads them. C++ flat-bag emitter untouched.
- **OQ-11 — Operational `_semantics` cross-field rules.** Add `episode.void⇒void_reason` (mirror
  release) and the footage hold-consistency rule, hand-written + keyed by schema id. **Rec: yes** (the
  only single-record rules; everything else is multi-entity → docs).
- **OQ-12 — `pairing_method`/`pairing_anomaly` placement (C-12).** Already on release; **Rec:** also on
  `episode` (pairing is decided there before it's frozen into release).

---

## 10. What this run deliberately does NOT do (restated)

- **No module logic** — no firmware state machine, no ingest/identity/join/QC implementation, no
  edge/store, no consoles. This is the **contract** (types + schema + interface definitions + documented
  rules), not its consumers.
- **No join / precedence / as-of resolution *implementation*** — those are later runs. 0c/0d defines the
  types and documents the rules.
- **No substrate scripts, no web stack, no Hermes-side cleaning code.**
- **Does not pick** the Hermes contract-consumption mechanism, the spot-check tuning values (N%, N-day,
  watermark), or the firmware-vs-ingest resolution of the **sidecar-shape divergence**. On that
  divergence (0b carry-forward): the operational `episode` **joins the sidecar by `episode_id`**, not by
  its physical nesting — it references sidecar **fields by logical name** (`episode_id`,
  `global_episode_seq`, `side`, `kit_id`, …), so the operational model does **not** assume the nested vs
  flat shape. The divergence stays visible and is resolved in the firmware run or by ingest tolerance,
  **not here**.

---

Plan ready for annotation — I have not implemented anything.
