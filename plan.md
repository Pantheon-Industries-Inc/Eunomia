# Run 0d — `contracts/operational/`: the operational model

> **Status: APPROVED — implementing.** Mo annotated 2026-06-24: **OQ-A → (2)** (hard enum only for
> DOMAIN-closed axes; open-string + WARN-check for today-closed/growth-prone axes), **OQ-B → APPROVED**
> (calibration = queryable scalars + opaque blob; footage `locations` = scalar array of strings; the
> matrix / per-location-object cases remain named STOP-and-flag lines), **OQ-C → APPROVED** (one
> polymorphic `operational-event` with an `event_type` discriminator + opaque payload; placed in
> `contracts/events/`), **OQ-D → (1)** (the `session` IS the kit↔person binding + a roster
> `operational-event`; no 10th entity). The pre-approved set (OQ-3/4/5/6/9/10/11/12) is encoded as
> decided. §9 below records each resolution.
>
> Same discipline as 0a/0b/0c: implement → run gates → report + STOP for go-ahead (do not merge or
> force-push). 0d fills the **one remaining contract stub** (`contracts/operational/`); after it,
> `contracts/` is fully poured.
>
> Authority read for this plan: `docs/CONTRACT.md` **§3** (the operational model — wins on any
> disagreement) + §4/§7; `docs/DECISION_REGISTER.md` (B-8, B-9, A-2, C-9/C-10/C-11/C-12, R-2, the
> 2026-06-24 spot-check block, the post-0b/0c run-status block with the carried OQs); `docs/SPEC.md`
> §3.2–§3.6; and the as-built machinery I REUSE unchanged — `contracts/codegen/generate.py`
> (358-line record DSL, **not grown**), `templates/semantics.py.tmpl` (the hand-written overlay),
> `contracts/conformance/test_conformance.py` (the hybrid validator + parametrized buckets), the 0b
> record schemas as the field-DSL pattern.

---

## 1. Summary

**What 0d produces:**

- **The 9 operational entities (CONTRACT §3.1–§3.2)** as record-shaped
  `contracts/operational/eunomia-<entity>.schema.yaml`, reusing the **0b field-DSL + the Option-C
  hybrid validator unchanged**: `person`, `hardware_unit`, `kit`, `calibration`, `task`, `session`,
  `capture_stack`, `footage_reference`, `episode` (the join point). Targets **`[jsonschema, python]`**
  only — no C++ (OQ-10).
- **The event/lifecycle representation (OQ-3)** — the entity records ARE the current-state
  (materialized-view) records; the append-only log is (a) the existing **`eunomia-sync-delta`**
  envelope as the generic upsert/delete transport (with the OQ-9 tightening), plus (b) ONE
  first-class **`eunomia-operational-event`** record where a lifecycle carries fields beyond the
  entity snapshot. **The fold/materializer is NOT implemented** — 0d defines the types + documents the
  derivation.
- **As-of resolution (OQ-6)** — encoded *temporally* as validity-range fields (`effective_from` /
  nullable `effective_to`) on time-bound bindings + `as_of` on events + `recorded_at` on episode. The
  resolution **rule** is documented; the **resolver runs at ingest = a later run**.
- **The §3 rules as types + documentation** — identity precedence (§3.3), crosswalk + serial
  retargeting (§3.4), task precedence (§3.5), the dual-signal join (§3.6) are **join-time,
  multi-entity** logic → encoded as **typed fields + prose** in entity READMEs/schema comments. The
  `_semantics` overlay carries **only the two single-record cross-field rules** (OQ-11).
- **The one `events/` tightening (OQ-9)** — the sync-delta `entity` value-set becomes a **WARN-level
  `_semantics` check**, NOT a hard enum (a hard enum is a §5-violating narrowing). `entity` stays an
  open string structurally = additive-safe.
- **Conformance** — `valid/`, `invalid/`, `warn/` (and `semantic_invalid/` for `episode` +
  `footage_reference`) fixtures per entity through the same hybrid validator; `ENTITIES` dict + the
  validate-parity map + the imports grow; the drift gate stays green.

**What 0d defers (restated in §10):** no module logic (no firmware/ingest/edge/console code); the
join/precedence/as-of **implementation**; the spot-check tuning values (N%, N-day, watermark); the
firmware-vs-ingest resolution of the sidecar-shape divergence; how Hermes consumes the contract.

**Why fast:** this is **record-shaped reuse of settled 0b machinery** + the held decisions. The only
*new* code is hand-written `_semantics` logic (2 hard rules + 1 warn rule) — no generator growth, no
new emitter (0c's `generate_interfaces.py` is done and out of scope).

---

## 2. The `contracts/` tree after 0d (annotated: NEW / EDIT / UNCHANGED)

```
contracts/
├── operational/                                  [was a 0b/0c stub README]
│   ├── README.md                                 REWRITE (stub → real)
│   ├── eunomia-person.schema.yaml                NEW   (§3.1 person; B-8)
│   ├── eunomia-hardware-unit.schema.yaml         NEW   (§3.1 hardware_unit; B-9, R-2, §3.4 crosswalk)
│   ├── eunomia-kit.schema.yaml                   NEW   (§3.1 kit; time-bound binding, OQ-6)
│   ├── eunomia-calibration.schema.yaml           NEW   (§3.1 calibration; scope enum, C-11)
│   ├── eunomia-task.schema.yaml                  NEW   (§3.1/§3.5 task; versioned prompt, OQ-6)
│   ├── eunomia-session.schema.yaml              NEW   (§3.1 session; fob_session_id)
│   ├── eunomia-capture-stack.schema.yaml         NEW   (§3.1 capture_stack; B-9)
│   ├── eunomia-footage-reference.schema.yaml     NEW   (§3.1 footage_reference; A-2 + OQ-5 hold)
│   └── eunomia-episode.schema.yaml               NEW   (§3.2 episode — the join point; C-12, OQ-11/12)
├── events/
│   ├── README.md                                 EDIT  (note: sync-delta entity now WARN-checked, 0d)
│   ├── eunomia-sync-delta.schema.yaml            EDIT  (OQ-9: refresh stale "in 0c" comments;
│   │                                                    STRUCTURALLY UNCHANGED — entity stays open string)
│   ├── eunomia-telemetry-event.schema.yaml       UNCHANGED
│   └── eunomia-operational-event.schema.yaml     NEW   (OQ-3; placement per OQ-C — see §9)
├── codegen/
│   ├── generate.py                               EDIT  (1-line conditional `field` import — bugfix, NOT growth; records only, ~360 lines)
│   ├── generate_interfaces.py                    UNCHANGED  (0c mini-emitter; out of scope)
│   ├── requirements.txt                          UNCHANGED  (PyYAML already pinned)
│   └── templates/
│       ├── semantics.py.tmpl                     EDIT  (OQ-11: 2 hard rules; OQ-9: a warn-rule registry)
│       └── header/detail/port/protocol/*.tmpl    UNCHANGED
├── _generated/                                   (ALL regenerated by `make codegen`; committed + drift-gated)
│   ├── cpp/                                       UNCHANGED  (no operational C++ — OQ-10)
│   ├── python/eunomia_contracts/
│   │   ├── person.py … episode.py                 NEW   (10 modules incl. operational_event.py)
│   │   ├── _semantics.py                          REGEN (re-vendored from the edited template)
│   │   ├── __init__.py                            REGEN (now also imports the operational entities)
│   │   └── sidecar/release/sync_delta/telemetry_event/interfaces.py  UNCHANGED
│   └── jsonschema/
│       ├── eunomia-person.schema.json …           NEW   (operational entities + operational-event)
│       └── eunomia-sync-delta.schema.json         REGEN (description-comment refresh only)
└── conformance/
    ├── fixtures/<entity>/{valid,invalid,warn[,semantic_invalid]}/   NEW per operational entity
    │   └── fixtures/sync_delta/warn/unknown_entity.json             NEW (exercises the OQ-9 warn check)
    └── test_conformance.py                        EDIT  (ENTITIES dict + parity map + imports only)
```

Everything else under `contracts/` (sidecar/, release/, the C++ targets, the 0c interfaces) is
**untouched**. The generator picks up the new YAMLs automatically (`SOURCES = glob("*/*.schema.yaml")`
in `generate.py`). **`generate.py` received exactly ONE 1-line edit** (during implement, not foreseen
in the original plan): import `field` from `dataclasses` only when an object/array field uses it. 0d
introduced the first **scalar-only** entities (kit/task/session/capture_stack/episode); every 0b entity
had a collection field, so the unconditional `field` import was never unused before — these new entities
exposed an `F401 unused-import` that `ruff check` flags. The fix is a bugfix, **not growth**: the DSL,
the emitters, and **every existing 0b generated output stay byte-identical** (verified — only the 5 new
scalar-only modules get the shorter import). This is the run's lead deviation (see the report). (The
`generate.py` line-31 comment "operational/interfaces are 0c" remains harmlessly stale.)

---

## 3. Per-entity plan

> Field-level detail is **not re-typed** (CONTRACT §3 is the authority). Each entity names its source
> file, the CONTRACT/decision reference, the key fields/enums, the hard/warn split + rationale, and
> any cross-field/shape note. **Every entity carries the standard top-level `schema` field** (hard,
> `enum: [eunomia-<entity>/v1]`) like all 0b records. **Hard/warn rule (the 0b judgment, applied
> per-entity):** HARD = corruption makes the record unsafe **as an identity/join anchor**; everything
> else is WARN / nullable (recoverable, surfaced in triage, non-blocking). Enum value-sets marked
> "(OQ-A)" depend on the open question in §9 (hard-enum vs open-string + warn-check).

| Entity / file | CONTRACT § + decision | Key fields · enums | HARD set + rationale | Cross-field / shape note |
|---|---|---|---|---|
| **person** `eunomia-person.schema.yaml` | §3.1 (B-8); SPEC §3.2 | `person_id`; name; `role` (OQ-A); `status` enum `active\|offboarded` (OQ-A); `onboarded_at`, `offboarded_at` (nullable); `site_ids` (scalar array) | **HARD:** `schema`, `person_id` (the only identity anchor). Decoupled from kit (binding lives on session + events, not here). Everything else WARN/nullable. | Employment lifecycle = `operational-event` records (OQ-3/4), never embedded. `onboarded_at`/`offboarded_at` = a person validity range (OQ-6). |
| **hardware_unit** `…hardware-unit…` | §3.1 (B-9, R-2), §3.4; SPEC §3.2/§3.3 | `unit_id`; `type` `fob\|camera\|sd\|gripper` (OQ-A); `body_serial`, `insv_serial` (IAQEB…), `mac` (nullable); `batch_id`, `order_id`, `hardware_version`; `status` `received\|provisioned\|deployed\|faulted\|retired` (OQ-A); current `kit_id`, camera `side` `left\|right` (omitted for non-cameras — NOT nullable; a nullable enum rejects `null` structurally); a `provisioning` nested object (MAC/AP/IP/fw — 1 level) | **HARD:** `schema`, `unit_id`, `type` (the discriminator). Serials/provisioning facts WARN/nullable (recoverable; null on an un-provisioned unit). | **Serials are immutable + the §3.4 crosswalk key + NEVER decide kit** — documented in the README/comments, NOT a single-record rule. Status *value* checkable; **transition legality is multi-record → docs + the event log (OQ-4)**. Lifecycle history = `operational-event` records. `provisioning` is ONE nesting level (like the sidecar `provenance` group) ✓. |
| **kit** `eunomia-kit.schema.yaml` | §3.1; SPEC §3.2.2 | `kit_id`; current binding (scalars): `left_cam_unit_id`, `right_cam_unit_id`, `fob_unit_id`; `effective_from`, `effective_to` (nullable = open) | **HARD:** `schema`, `kit_id`. The binding fields are WARN/nullable — a kit may exist before/between bindings; an incomplete binding surfaces in review, it does not invalidate the kit. | Camera→side is a property of the unit binding (NAND), not the kit. **Binding history over time = separate append-only binding/`operational-event` records (OQ-4)** — the kit record holds only the CURRENT binding (scalars). Spares = pre-bound side-typed units. |
| **calibration** `…calibration…` | §3.1 (C-11) | `calibration_id`; `scope` enum `none\|fleet\|per_camera`; `camera_serial` (nullable for none/fleet); `method`, `captured_at`; `effective_from`/`effective_to`; heavy intrinsics (see **OQ-B**) | **HARD:** `schema`, `calibration_id`, `scope` (the discriminator that says which world we're in). Everything else WARN/nullable. | Optional entity; `calibration_id` nullable on episode. "Which world" is **data (scope), not structure** (C-11). **Heavy intrinsics shape is OQ-B** (decompose to scalars + scalar arrays, or an opaque `object` blob — NOT a matrix/array-of-arrays). |
| **task** `eunomia-task.schema.yaml` | §3.1/§3.5; SPEC §3.2.3 | `task_id`; `task_name`, `prompt`, `rotation_id`, `station_id`; `version` (int); `category`, `bimanual` (bool), `expected_duration`; `effective_from`/`effective_to` | **HARD:** `schema`, `task_id`. `prompt`/`task_name`/`version` are WARN (content, not the anchor; resolved as-of). | **Versioned** — a prompt change is a new version; episodes resolve prompt **as-of `recorded_at`** (OQ-6). Carries ONLY task fields, never identity. `task_source` enum (`nand_staged\|sd_assignment\|none`, §3.5) already lives on the sidecar — documented here, not duplicated as a rule. |
| **session** `eunomia-session.schema.yaml` | §3.1; SPEC §3.2.1 | `session_id`; `person_id`, `kit_id`, `site_id`, `station_id`; **`fob_session_id`** (random per fob boot — the fob-swap key); `signed_in_at`, `signed_out_at` (nullable); `task_id`; `pause_count` (int), `total_pause_ms` (number) | **HARD:** `schema`, `session_id`. `person_id`/`kit_id`/`fob_session_id` WARN (resolvable; load-bearing for the join but the session's own anchor is `session_id`). | Open/close = `operational-event` records (OQ-3). The session IS the (person, kit) time-bound binding window (carries both ids + the range) — see **OQ-D**. Pause tracking as scalars (count + total), NOT an array-of-objects (per-pause detail → events) ✓. |
| **capture_stack** `…capture-stack…` | §3.1 (B-9) | `capture_stack_id`; `modality` enum `umi\|teleop`; `camera_model`, `camera_fw`, `fob_board`, `fob_fw`, `gripper_hw`, `sd_model`, `coordinator_sw`; `version` | **HARD:** `schema`, `capture_stack_id`. The stack fields WARN (forensic provenance; reference-by-id from episode). | Referenced by id from episode (don't bloat episodes — B-9). A firmware update = a new stack version / `unit_firmware_updated` `operational-event` (resolvable as-of). `modality` enum value-set per OQ-A (`umi\|teleop` is bounded → lean hard-enum). |
| **footage_reference** `…footage-reference…` | §3.1 (A-2) + the 2026-06-24 spot-check block | `episode_id` (the key); `footage_state` enum `on_card\|on_styx\|shipped\|on_hades\|purged`; `locations` (see **OQ-B**); `hash` (nullable); **OQ-5 hold:** `spot_check_selected` (bool), `selection_method` enum `qc_sample\|manual_pull` (omitted when not selected — NOT nullable; absence, not `null`), `rendered_on_hades_at` (nullable), `purge_eligible_at` (nullable) | **HARD:** `schema`, `episode_id` (the key — keyed by episode, A-2), `footage_state` (the lifecycle discriminator; a footage_reference with no state is unusable). Everything else WARN/nullable. | **Must express the held-purge** (§4.2 + OQ-5): `purge_eligible_at` = max(`rendered_on_hades_at`, the N-day window); the Styx watermark is a documented bounding override (config; value deferred, §8). **CROSS-FIELD RULE (OQ-11, hard):** `spot_check_selected ⇒ selection_method` present. **Name = `purged`** (CONTRACT §3) not `purged_from_styx` (A-2) — CONTRACT wins. `locations` shape = OQ-B. |
| **episode** `eunomia-episode.schema.yaml` | §3.2 — **the join point**; C-12, OQ-11/12 | `episode_id` (UUIDv4 join key), `display_id` (warn, DERIVED), `bimanual_episode_id`, `episode_ordinal`, `global_episode_seq`; references (as-of `recorded_at`): `person_id`, `kit_id`+`side`, `task_id`, `calibration_id` (nullable), `capture_stack_id` (nullable), `session_id`, `station_id`; `recorded_at`, `ingested_at` (nullable); state `paired`/`void`+`void_reason`/`needs_review`/`archive`/`recording_suspect`; **OQ-12 pairing:** `pairing_method` enum `episode_id\|ordinal_join\|needs_review`, `pairing_anomaly` (bool) | **HARD:** `schema`, `episode_id`, `global_episode_seq`, `kit_id` (non-empty), `side` (non-empty, enum), `station_id`, `task_id`, `session_id`, `recorded_at`. **`ingested_at` is WARN/nullable** (the operational episode exists at record time; ingest fills `ingested_at` later — distinct from `release`, where it is HARD). | **CROSS-FIELD RULE (OQ-11, hard):** `void ⇒ void_reason` (mirrors the release rule). **References stored here; as-of resolution is what ingest does (later run).** **Episode REFERENCES the footage_reference by shared `episode_id` — does NOT embed it** (footage state mutates post-record; embedding would force episode mutation). Episode joins the **sidecar by `episode_id`, by logical field name** — shape-divergence-safe (§6 / carry-forward). |

**Shape verdict:** see §6. 7 of 9 entities are trivially within the DSL; `calibration` and
`footage_reference` have a structured-data edge → **OQ-B** (resolved in-DSL by decompose/opaque, with
STOP-and-flag named as the boundary).

---

## 4. The event / as-of plan (OQ-3, OQ-6, OQ-5)

**4.1 Event-sourcing (OQ-3 — DECIDED).** Three layers, all reuse 0b machinery:

1. **Current-state records** = the 9 entity schemas above (the materialized-view shape the consoles
   read). The **fold/materializer is NOT implemented** — 0d defines the types + documents that current
   state is a view over the event log (B-8).
2. **The generic upsert/delete transport** = the existing **`eunomia-sync-delta`** envelope
   (`{schema, delta_seq, emitted_at, entity, op∈upsert|delete, entity_id, as_of, payload}`), with the
   OQ-9 tightening (§4.4). `payload` stays an opaque object validated against the entity schema at the
   fold (documented; not enforced here).
3. **A first-class `eunomia-operational-event` record** — added ONLY because some lifecycles carry
   fields beyond the entity snapshot: hardware-unit status transitions (with `reason` + related refs),
   person onboard/offboard, session open/close, `unit_firmware_updated`, calibration recorded, task
   version bump. **Shape (see OQ-C):** ONE polymorphic record with an `event_type` discriminator enum
   + common scalars (`entity`, `entity_id`, `as_of`, `reason` nullable, related-ref scalars) + an
   opaque `payload` object — mirroring the `telemetry-event` polymorphic-discriminator pattern, so the
   generator stays lean (no per-event conditional rules).

**4.2 Lifecycle history shape (OQ-4 — THE load-bearing constraint, DECIDED).** Every repeating
sub-structure (a unit's lifecycle history, a kit's bindings over time, multiple footage locations) is
a **separate append-only event/binding record referenced by id — NEVER an embedded object array.**
This is what keeps every entity inside the existing DSL (top-level scalars + ONE nested object level +
scalar arrays) and the `generate.py` DSL/emitters un-grown. **If implementation reveals any entity needs an
array-of-objects or 2-level nesting, that is a STOP-and-flag → raise it, do NOT silently extend the
DSL.** (The 0d analog of 0c's closed-vocabulary boundary.)

**4.3 As-of resolution (OQ-6 — DECIDED).** Encoded *temporally* at the type level:
- Validity ranges `effective_from` / nullable `effective_to` (= open/current) on the time-bound
  bindings: **kit↔units** (on `kit`), **kit↔person** (on `session`; see OQ-D), **calibration
  validity** (on `calibration`), **task-version validity** (on `task`). Person carries
  `onboarded_at`/`offboarded_at`.
- Events carry `as_of`; episode carries `recorded_at`.
- The **rule** — "an episode resolves its references against the binding true at `recorded_at`" — is
  **documented** in the episode README + schema comments. The **resolver runs at ingest = a later
  run.**

**4.4 The footage held-purge (OQ-5 — DECIDED).** `footage_reference` expresses the 2026-06-24
spot-check semantics: keep until **(a) `rendered_on_hades_at` is set AND (b) the N-day window elapses,
whichever is LONGER** → `purge_eligible_at`; `spot_check_selected` + `selection_method`
(`qc_sample|manual_pull`) mark *why* it is held; the Styx watermark is a documented config bounding
override. The N%/N-day/watermark **values stay OUT of scope** (tuning, §8). Faithfulness check at
implement: the lifecycle expresses held-purge / N-day / watermark.

---

## 5. The §3 rules — types + documentation, NOT enforced single-record validation

The join / precedence / as-of logic is **multi-entity, join-time** — not validatable on one record
(the honest-scope position 0b/0c established). Encoded as **typed fields + prose** in the entity
READMEs / schema comments; `_semantics` carries **only** the two genuine single-record cross-field
checks (OQ-11).

| Rule (CONTRACT §) | How 0d encodes it | Single-record `_semantics` rule? |
|---|---|---|
| **Identity precedence** §3.3 (kit←fob, side←NAND, operator←roster, station+prompt←fob trigger; serials never decide) | Typed reference fields on `episode` + prose; precedence applied by the ingest resolver (later run) | **No** (multi-entity) |
| **Crosswalk + serial retargeting + kit aliases** §3.4 | `insv_serial`/`body_serial` on `hardware_unit` as the immutable crosswalk key; retargeting + alias mapping documented in the README | **No** (multi-entity) |
| **Task precedence** §3.5 (NAND → SD → none) | `task_source` enum (already on the sidecar) documented on `task`/`episode`; the winner is recorded, not re-derived | **No** |
| **Dual-signal join** §3.6 (ordinal spine + duration guardrail; tiebreaks `ordinal_slip`/`board_swap`/`clock_suspect`/`needs_review`; phantom-press gate `sent==2`; block-labeling; void-by-flag) | `pairing_method` + `pairing_anomaly` on `episode` (C-12, OQ-12); tiebreak names + the gate documented; the join itself is a later run | **No** |
| **Void requires reason** §4.1/§3.2 | — | **YES** — `episode.void ⇒ void_reason`, hand-written in `_semantics`, keyed by the episode schema id (OQ-11; mirrors the release rule) |
| **Footage hold consistency** (OQ-5) | — | **YES** — `footage_reference.spot_check_selected ⇒ selection_method` present, keyed by the footage schema id (OQ-11) |

---

## 6. Shape-budget check (the OQ-4 boundary, per entity)

**The DSL admits:** top-level scalars · ONE level of nested object (`fields:[…]`) · scalar arrays
(`items:<scalar>`). It does **NOT** admit array-of-objects or 2-level nesting (confirmed in
`generate.py`: `emit_dataclass` only emits sub-dataclasses for top-level objects; arrays map to a bare
`list` with a scalar `items`). Repeating structures → separate event/binding records (OQ-4).

| Entity | Within DSL? | Why |
|---|---|---|
| person | ✅ | scalars + one scalar array (`site_ids`) |
| hardware_unit | ✅ | scalars + ONE nested object (`provisioning`); lifecycle history → events |
| kit | ✅ | all scalars (current binding); binding history → records |
| calibration | ⚠️ → **OQ-B** | scalars + `scope`/validity fit; the **intrinsics matrix** is the only risk — resolve by decompose-to-scalars-+-scalar-arrays OR an opaque `object` blob; a 3×3 matrix / array-of-matrices would be array-of-arrays = **STOP-and-flag** |
| task | ✅ | all scalars |
| session | ✅ | scalars (pause tracking = count + total, NOT per-pause objects) |
| capture_stack | ✅ | all scalars |
| footage_reference | ⚠️ → **OQ-B** | scalars + the OQ-5 hold fields fit; `locations` is the only risk — resolve as a **scalar array of strings**; structured per-location `{tier, path, verified_at}` would be array-of-objects = **STOP-and-flag** |
| episode | ✅ | all scalars (references footage_reference by id, does NOT embed it) |
| operational-event | ✅ | scalars + `event_type` enum + an opaque `payload` object (no nesting) — mirrors `sync-delta`/`telemetry-event` |

**Verdict:** with OQ-B resolved as recommended (decompose / scalar-array / opaque-object), **every
entity stays within the existing DSL and `generate.py` does not grow.** The two ⚠️ entities are flagged
now precisely so the STOP-and-flag boundary is honored at implement, not silently crossed.

---

## 7. Conformance plan

- **Per operational entity (10 incl. operational-event):** fixtures in `valid/` (real `jsonschema`
  Draft 2020-12 accepts + stdlib `hard == []`), `invalid/` (both reject — a missing hard field or a
  bad enum), `warn/` (a `minimal_hard_only` record: `hard == []` **with** warnings — exercises the
  severity split). Plus `semantic_invalid/` for **`episode`** (void without reason) and
  **`footage_reference`** (selected without method) — `jsonschema` accepts (structurally fine), the
  overlay hard-rejects the cross-field violation.
- **The OQ-9 warn check** gets a **new** `sync_delta/warn/unknown_entity.json` (`entity: "gizmo"`):
  `hard == []` (entity stays an open string, non-empty) **with** a warning (value not in the known
  operational set). The existing sync_delta valid/warn fixtures already use real entity names
  (`episode`/`hardware_unit`/`person`) — **verified, so they pass cleanly with no change**; the
  `empty_entity` invalid fixture stays a HARD reject (non_empty).
- **`test_conformance.py` growth (only):** add each entity to the **`ENTITIES`** dict
  (`"<entity>": ("eunomia-<entity>", <module>.validate_full)`), add it to the **validate-parity map**
  in `test_validate_matches_validate_full_hard_channel`, and add the module **imports**. The
  parametrized `valid/invalid/warn/semantic_invalid` test bodies pick the new entities up via
  `_cases()` — **no new test logic.** `testpaths` already includes `contracts`, so fixtures
  auto-collect. The 0c interface-port tests are untouched.

---

## 8. Gate + drift impact

- **The 5 Hermes Python gates stay byte-identical** (`uv run pytest` → `ruff check .` →
  `ruff format --check .` → `mypy .` → `lint-imports`, on tool defaults — no `[tool.ruff]`/`[tool.mypy]`
  added). New generated Python must be ruff-format-clean **as emitted**; `make codegen` already runs
  `ruff format contracts/_generated/python`, so the drift gate stays meaningful.
- **No new deps.** `jsonschema`/`types-jsonschema` already dev-pinned (0b); the shipped validator
  stays **pure-stdlib**; PyYAML already pinned for codegen. (Confirm at implement; state plainly if
  any dep is added — none expected.)
- **import-linter unchanged.** All new modules live under `eunomia_contracts` (intra-package); the
  forbidden contract (`eunomia_contracts` imports no other `eunomia_*`) still holds.
- **`generate.py` carries ONE 1-line bugfix** (conditional `field` import, see §2) and
  `generate_interfaces.py` is untouched — the DSL/emitters are otherwise unchanged and **every existing
  0b generated output is byte-identical**. The new entities ride the existing glob; the only
  hand-written *logic* is in `templates/semantics.py.tmpl` (OQ-11 two hard rules + OQ-9 warn-rule
  registry), which is **re-vendored** into `_generated/.../_semantics.py` by `make codegen` — editing
  the *template* does not edit the *generator*.
- **C++ gates unaffected** — no operational C++ target (OQ-10); `clang-format`/`pio test -e native`
  run on the unchanged firmware + the unchanged generated headers.
- **The one `events/` change (OQ-9)** is additive-safe: `entity` stays an open string; only a
  WARN-level value-set check + stale-comment refresh. No version bump (no narrowing). The known set is
  hand-coded in `_semantics` as the 9 current-state entity names.

---

## 9. Open questions — RESOLVED at annotation (2026-06-24)

> OQ-3/4/5/6/9/10/11/12 were pre-approved (see §1/§4). The four genuinely-new ones below are now
> resolved by Mo's notes; recorded here as the implemented decisions.

**OQ-A — Hard-enum vs open-string + WARN-check for the new vocabularies. → RESOLVED (2).** The test is
**"closed by the physics of the domain, or just by today's list?"** — because a hard enum can only be
*added to* additively (§5), a value that should have been allowed becomes a hard break.
- **HARD enum (domain-closed):** `episode.side`/`hardware_unit.side` (`left|right` — two arms),
  `calibration.scope` (`none|fleet|per_camera` — the calibration model), `capture_stack.modality`
  (`umi|teleop`), `footage_reference.footage_state`, `footage_reference.selection_method`,
  `sync-delta.op`, and `episode.pairing_method` (`episode_id|ordinal_join|needs_review`) — **but
  `pairing_method` is the hard enum MOST likely to need a future additive value (a new pairing
  strategy); eyes open** (noted in the episode schema comment).
- **OPEN string + WARN-check (today-closed / growth-prone):** `hardware_unit.type`,
  `hardware_unit.status`, `person.role`, `person.status`, `operational-event.event_type` (the most
  growth-prone — every new lifecycle adds one). These carry **no `enum:` in the YAML** (so the
  generated JSON Schema stays an open string = additive-safe, no §5 narrowing) + a **hand-written
  WARN-level value-set check** in `_semantics` (the OQ-9 pattern), keyed by schema id.

**OQ-B — Calibration intrinsics + footage `locations`. → RESOLVED (in-DSL).**
- **calibration:** a few queryable scalars + a scalar array (`distortion_coeffs`) + an **opaque
  `object` blob** (`intrinsics`, type `object`, no `fields`) for the heavy data — because the
  operational store only needs `scope` + validity + `camera_serial` + a reference; the full intrinsics
  matrix is consumed by the **Hermes-side** render from `camera_intrinsics.json`, not queried
  operationally. (Heavy data lives where it's used — not dodging the DSL.)
- **footage `locations`:** a **scalar array of strings** (`tier:path`).
- **The two STOP-and-flag lines stay named + honored:** a 3×3 matrix / array-of-matrices for
  calibration, and structured per-location objects for footage — **do not silently cross them**.

**OQ-C — `operational-event` shape + placement. → RESOLVED.** ONE polymorphic record with an
`event_type` discriminator + opaque `payload` (mirror `telemetry-event` — keeps the generator lean,
no per-event conditional rules). Placed in **`contracts/events/`** (it is an event record; `events/`
already holds the operational transport `sync-delta`; the glob is location-agnostic).

**OQ-D — Where the kit↔person binding lives. → RESOLVED (1).** The **`session`** entity IS the
kit↔person binding (it already carries `person_id` + `kit_id` + the `signed_in_at`/`signed_out_at`
window), plus a roster-level `operational-event` for resolution outside a session window. **No 10th
entity.** This models kit↔person as inherently shift-scoped — correct for UMI collection (operators
are assigned per shift). (Option (2), a standing kit→person assignment independent of shifts, is not
the case here.)

---

## 10. What 0d deliberately does NOT do (restated)

- **No module logic** — no firmware state machine, no ingest/identity/join/QC implementation, no
  edge/store, no consoles. 0d is the *contract* (types + schema + documented rules), not its consumers.
- **No join / precedence / as-of resolution IMPLEMENTATION** — later runs. 0d defines types + docs.
- **No DSL growth** — if an entity needs array-of-objects or 2-level nesting, STOP-and-flag (OQ-4 /
  OQ-B). No new generator machinery; `generate.py` stays records-only (only a 1-line conditional-import
  bugfix, §2 — no DSL/emitter growth); the 0c interface emitter is out of scope.
- **No substrate scripts, no web stack, no Hermes-side cleaning/render code.**
- **Does not pick** the Hermes contract-consumption mechanism, the spot-check tuning values (N%,
  N-day, watermark), or the firmware-vs-ingest resolution of the **sidecar-shape divergence**. On that
  divergence (carry-forward): the operational `episode` **joins the sidecar by `episode_id`** and
  references sidecar fields **by logical name** (`episode_id`, `global_episode_seq`, `side`, `kit_id`,
  …) — so the operational model does **not** assume the nested-vs-flat shape. The divergence stays
  visible and is resolved in the firmware run or by ingest tolerance, **not here**.

---

Plan ready for annotation — I have not implemented anything.
