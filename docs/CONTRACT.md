# Eunomia — Platform-Input Contract (First-Principles Design)

**Status:** design draft for review. This is the SPINE document: the data contract every other
Eunomia component depends on. It is written from first principles — sources, consumer needs, then
optimal structure — using the as-built `pantheon-x3-sidecar/v2` + `pantheon-episode-meta/v1` and our
own spec as **inputs and reality-checks, not as the definition**.

**Companion docs:** `x3_decision_register.md` (the 23 decisions + the full learnings this folds in);
`x3_capture_system_spec.md` (the long-form lifecycle — will be folded to reference THIS doc in a
later pass); `x3_hardware_findings.md`; `x3_bench_test_plan.md`.

**What Eunomia is (the frame for this contract):** Eunomia is the clean, unified replacement for the
whole on-site capture + ingest + identity + QC + ops level — the convergence of Victor's Layer 0
(`data`/Styx) and Eric's Layer 1/2 (`x3-capture-kit/pipeline`), plus the flows and consoles we
specced, into one coherent system. Their battle-hardened code is the SURVEY/learnings layer; where
it is already clean we copy, otherwise we re-architect cleanly keeping the hard-won constraints.
Eunomia sits on the immovable Styx host substrate (ported into the repo, interface frozen — the substrate-port decision)
and produces the release metadata the **Hermes** analytical platform consumes (Hermes is a separate
repo, on Hades).

---

## 0. How to read this contract

The contract has three layers, each a section below:

- **§2 The on-card sidecar** — what discardd writes next to each clip at capture. This is the
  primary, authoritative, loss-resilient record. The label rides on the card.
- **§3 The operational model** — the event-sourced entities (person, hardware-unit, kit,
  calibration, task, session, capture-stack) that give every clip its full identity and that the
  consoles read/write. This is the queryable store on Styx.
- **§4 The release metadata** — what Eunomia emits per episode for Hermes to ingest (the clean
  successor to `pantheon-episode-meta/v1`).

Plus: **§1** the first-principles derivation (why the shape is what it is); **§5** the two-axis
versioning model; **§6** the validation/conformance contract; **§7** the resolved decisions
(the episode-id key, and the cleaning-layer boundary); **§8**
what this deliberately defers.

A note on the relationship between the three layers: the **sidecar is the source of truth for an
episode's self-description**; the **operational model is the source of truth for identity and
context** (who/what/where, resolved as-of the recording time); the **release metadata is the
join of the two**, frozen at ingest, plus the derived QC/sync/pairing fields. Nothing downstream
re-derives identity from serials or folders — it flows sidecar + operational-model → release.

---

## 1. First principles: sources, consumers, then structure

### 1.1 The sources (what produces data, now and later)

The contract must hold for more than today's rig. The sources, in order of how grounded they are:

- **UMI handheld (today, the rig this is built for):** two Insta360 X3 wrist cameras per kit + an
  ESP32 fob coordinator. One operator runs ONE task back-to-back for ~2 hrs (the block-labeling
  property). The fob triggers both cameras over WiFi-OSC and writes the label onto each card at
  capture (the proven 2026-06-23 rig). This is the concrete source the sidecar schema is shaped by.
- **Teleop (next):** robot-collected demonstrations (e.g. YAM↔YAM). Different hardware, different
  action space, but the SAME need for episode identity, provenance, QC, and a release record. The
  contract carries a `modality` field (`umi` | `teleop`) so both fit one schema (the capture-stack-provenance decision).
- **Sim (later) + internet-scale (separate path):** out of scope for the on-card sidecar (no card),
  but the operational model's episode/release entities must not assume a physical card exists.

The design rule from this: **the on-card sidecar is UMI-specific by nature** (it is literally a file
on a camera's SD card); **the operational model and the release metadata are modality-general** and
must accommodate teleop/sim with no schema break.

### 1.2 The consumers (what downstream needs, which is what the schema must serve)

A schema is the filter on every question that can ever be asked of the data. The consumers:

- **Training (the point of all of it):** needs paired, time-aligned, clean episodes with reliable
  identity (which kit, which operator-cohort, which task/prompt), the correct video half (back/
  workspace), the IMU stream, and the calibration to undistort. Needs to FILTER by capture stack
  (exclude episodes from a known-bad firmware/format build) without a re-ingest.
- **QC + triage (Calix's surface):** needs an OPEN set of quality flags + reasons + a score, the
  pairing/void/needs_review state, and enough provenance to know WHY a take is suspect.
- **Ops / god's-view (live):** needs near-real-time per-operator/per-kit status (recording, cams
  connected, flagged-rate, battery/SD, help calls) — exception-first, not live video.
- **The platform (Hermes, analytical):** needs a stable, versioned release record it can pin and
  ingest, with clean lifecycle timestamps and a forensic handle on the producing build.
- **Forensics / debugging (everyone, after an incident):** needs to scope a bug to the exact
  capture build that produced an episode and bulk-invalidate by query, not by backfill.

### 1.3 The structure that falls out

From sources + consumers, the optimal structure is three layers with a strict information flow:

```
   CAPTURE TIME RESOLVED AS-OF recorded_at FROZEN AT INGEST
   ┌─────────────────┐ ┌───────────────────────────┐ ┌────────────────────┐
   │ on-card sidecar │ ──────▶ │ operational model │ ─────▶ │ release metadata │
   │ (§2) │ identity│ (event-sourced entities) │ join │ (§4, for Hermes) │
   │ self-describes │ context │ (§3) │ + QC │ │
   │ the episode │ │ who/what/where/which-cal │ +sync │ │
   └─────────────────┘ └───────────────────────────┘ └────────────────────┘
        authority for authority for the join of the two,
        episode self-desc identity + context + derived fields
```

Three invariants that this structure must guarantee (each is a hard-won lesson):

- **I-1 Loss resilience.** The episode's self-description is on the card at capture (sidecar), so a
  dead fob / dropped network after a take never orphans footage. (LESSONS: the label rides on the card.)
- **I-2 No silent mislabel.** Identity flows from authoritative sources with a fixed precedence; any
  disagreement sets `needs_review`, never silently overwrites. (INGESTION_CONTRACT + UMI_LIFECYCLE.)
- **I-3 Forensic scoping by query.** Every episode records the capture build that produced it, so a
  bad build is excluded by a query, never a re-ingest/backfill. (pantheon_sidecar_schema: record_format_version.)

---

## 2. The on-card sidecar (`eunomia-sidecar`)

**What it is:** one JSON file per episode, written by discardd onto each camera's SD card in the
same folder as the clip, at capture, named to bind to the clip. It is the primary record.

**Heritage:** this is the clean successor to `pantheon-x3-sidecar/v2`. We keep its field model and
its hard-vs-warn discipline almost entirely (it is already well-designed); the changes are (a) clean
namespacing of the field groups, (b) the two-axis versioning made explicit (§5), (c) `modality` for
teleop-generality, (d) the open decisions in §7.

### 2.1 Filename + binding

- Clip: `VID_<ts>_<lens>_<seq>.{insv|mp4}` (the X3 writes ONE file per take and FLIPS the container
  extension per-take — glob BOTH; `_00_` is the SBS dual-fisheye file we use, never `_10_`).
- Sidecar: `VID_<ts>_<seq>.eunomia.json` (binds by `<ts>_<seq>` to the clip; tolerant of the
  extension flip).
- **`files.back`** records the actual clip file the sidecar describes (the hard-required pointer).

### 2.2 Field groups (the record)

The sidecar is organized into named groups. **Hard-required** = corruption makes the file unsafe to
ingest (validation fails). **Warn** = consumed downstream, recoverable, absence is surfaced in triage
but does not invalidate. (This hard-vs-warn split is adopted directly from the as-built validator.)

**`schema` (top-level, HARD)** — the schema identifier string, e.g. `eunomia-sidecar/v1`. Tells a
parser which fields to expect. Additive semver: new fields are added, never renamed, so older files
still validate. (§5.)

**`record_format_version` (top-level INT, WARN)** — monotonic, owned by the WRITER (discardd), bumps
when the captured-record FORMAT changes (new field group, changed timing semantic). The forensic
handle: scope a bad build by query (§5, I-3). Warn-only so older cards keep validating.

**`identity` group:**
- HARD: `camera_id`, `kit_id`, `side`, `operator_id`, `station_id`, `task_id`, `task_name`,
  `session_id`, `episode_id`, `rotation_id`. (`episode_id` = the fob-minted **UUIDv4** pairing/join
  key, written identically to both arms — see the episode-id decision.)
- HARD-non-empty (the ONLY two): `kit_id`, `side` (they decide canonical naming + L/R pairing).
- v1-extra HARD (present when the file declares v1+): `prompt`, `task_source`
  (`nand_staged`|`sd_assignment`|`none` — where the task came from; see §3.6 precedence).
- WARN: `episode_ordinal` (the fob label ordinal), `bimanual_episode_id` (the fob-injected shared
  L/R pairing id — written to BOTH cams before startCapture, lets ingest pair with NO order-join;
  distinct from `episode_id` — it pairs the two wrist cams of ONE take), `display_id` (DERIVED,
  never-a-key: the human-readable `<YYYYMMDD>_<operator>_<station>_<NNNNNN>` composite for debugging
  — see the episode-id decision), `calibration_id`, `record_settings`, `mount`, `assignment_source`.

**`timing` group (top-level `timing` object):**
- Per-camera `started_unix` / `stopped_unix` (discardd derives them from the clip file).
- `start_skew_ms` — the fob-measured cross-cam start skew (the at-capture inter-arm-skew prior).
- `camera_clock` (WARN, provenance-only — the X3 has no RTC, its clock is POISON: never used for
  ordering or labeling, decoration only).
- NOTE: authoritative episode TIME comes from the fob NTP wallclock via the operational model /
  trigger record, NOT from the camera clock. (the time-model decision.)

**`ordering` group:**
- `seq` (top-level, HARD) — the per-card filename seq counter (numeric).
- `global_episode_seq` (top-level, HARD) — the NAND swap-proof monotonic ordinal, the PRIMARY
  ordering spine, continuous across SD/battery swaps (the card is NOT a unit). Distinct from the fob
  `episode_ordinal` (the label source). Two ordinals, two roles. (trigger_join.)

**`provenance` / capture-stack group (all WARN, the forensic identity — = the capture-stack-provenance decision):**
- `camera_firmware` (the Insta360 fw, self-read by discardd), `fob_id`, `fob_build`, `kit_version`
  (the discardd fw), `site_id`. Plus `modality` (`umi`|`teleop`). These + `record_format_version`
  are how a consumer filters by the exact producing build.

**`outcome` group:**
- `stop_reason` (WARN: `operator`|`timer`|`card_full`|`battery`|`error`|`overheat`) — WHY the take
  ended (distinct from completeness flags, which say WHAT is missing).
- `archive` (0/1, WARN) — the operator marked this take DESCARTAR = a SOFT discard (void+keep). The
  footage is KEPT on-card; ingest routes `archive==1` to the archive bucket, not the training set, so
  we retain a record of exactly what was discarded.
- `recording_suspect` (0/1, WARN — NET-NEW, our addition): the coordinator could not confirm the
  clip actually grew/recorded (the no-SD trap: a start can pass every check and save nothing on a
  full/absent SD). The WiFi-OSC equivalent of the BLE rec=1 watcher. Surfaces "did it actually record."

**`files` group:**
- `files.back` (HARD) — the clip file the sidecar describes.

### 2.3 What is NOT in the sidecar (and why)

- **No WiFi PSKs / secrets.** Identity-only, never credentials (fleet_registry principle). PSKs live
  in a gitignored credentials store, never on the card, never in the sidecar.
- **No QC verdict.** QC is computed at INGEST from the IMU + video (§4), not on-card (the camera has
  no telemetry parser, and QC is cohort-relative). The sidecar carries the inputs (timing, settings);
  the release record carries the verdict.
- **No absolute "authoritative" time from the camera.** Camera clock is provenance-only (the time-model decision).
- **No mutation of the video.** The sidecar is a COMPANION file; the `.insv`/`.mp4` is never
  re-encoded (the gyro/FlowState trailer must stay intact; ingest never runs ffmpeg on the master).

---

## 3. The operational model (event-sourced)

**What it is:** the queryable store of identity + context that lives on Styx (edge-authoritative,
survives WAN outage), that the consoles read/write, and that resolves every clip's full identity.
This is the clean, unified successor to `fleet.yaml` + `operator_roster.yaml` + `x3_state.json` +
the scattered env files — one coherent model.

**Why event-sourced (the event-sourcing decision):** people change roles, cameras get swapped, calibrations get redone,
task menus change, kits get re-assigned. An episode recorded last Tuesday must resolve against the
identity/binding that was true LAST TUESDAY, not today's. So the store is **append-only events**
(person hired, unit provisioned, unit assigned to kit, calibration recorded, task added, session
opened…) with **materialized current-state views** for the consoles, and **episode references
resolve as-of `recorded_at`**. The degenerate "current state" is always a view over the event log.

### 3.1 The entities

**`person`** — the human operator (and leads). Sourced from HR (Rippling). Carries `person_id`,
name, role, employment lifecycle events. **Decoupled from kit** (this is the key generalization over
the current `kit==operator==rig` model): a person is bound to a kit over a TIME RANGE, not
identically. The current "one operator owns one kit" is just the degenerate case where the binding
is stable and 1:1.

**`hardware_unit`** — any physical device with a lifecycle: a camera body, a fob, an SD card, a
gripper. Modeled with the order→batch→unit→lifecycle structure (the provisioning-capture requirement): a unit has an immutable
identity (e.g. camera `body_serial` + the long `insv_serial` `IAQEB[A-Z0-9]{8,12}`; fob id; SD
model), provisioning facts (MAC, AP/WiFi details, assigned IP scheme, fw versions), and lifecycle
events (provisioned, assigned, retired). **Serials are immutable and are the crosswalk key; they
NEVER decide the kit** (identity precedence, §3.5).

**`kit`** — the logical unit an operator carries: a binding of {a LEFT camera unit, a RIGHT camera
unit, a fob unit} over a time range, with a `kit_id`. Camera→side is a property of the unit's
binding (burned to NAND), not of the kit. Spares are side-typed units pre-bound and allow-listed so
a swap is power-on.

**`calibration`** — an OPTIONAL entity with a `scope` field (`none`|`fleet`|`per_camera`), so
none/fleet-wide/per-unit ALL fit with no schema change (the calibration-as-scoped-entity decision). `camera_serial` is always on the
card; `calibration_id` is nullable and references this entity when present. (Eric is testing one
fleet-wide calibration; per-unit is the rigorous target for fisheye.)

**`task`** — the task menu: `task_id`, `task_name`, `prompt`, `rotation_id`, `station_id`. Versioned
(a prompt can change; episodes resolve the prompt as-of recording). Carries ONLY task fields, never
identity (the clean separation principle).

**`session`** — a shift / a block of capture for a (person, kit) over a time window. Carries
`session_id`, the fob `fob_session_id` (random per fob boot — the fob-swap disambiguation key), open/
close events, pause tracking.

**`capture_stack`** — the registered provenance entity (the capture-stack-provenance decision): a `capture_stack_id` resolving to
{modality, camera model, camera fw, fob board, fob fw, UMI gripper hw, SD model, coordinator sw}.
Every episode records its `capture_stack_id` + the per-unit serials; the field is automatic +
prefilled with a supervisor daily confirm. (Matches the as-built `record_format_version`/kit_version
intent, made into a first-class entity.)

**`footage_reference`** — the lifecycle of an episode's bytes (the footage-lifecycle decision): `footage_state` ∈
`on_card → on_styx → shipped → on_hades → purged`. Drain reports transitions; safe-to-purge only
once `on_hades` is verified. Decouples "we have the metadata" from "where the bytes are."

### 3.2 The episode (the join point)

**`episode`** — the central record. NOT owned by a card (the card is NOT a unit; episodes belong to
a continuous per-(kit,side) sequence by `global_episode_seq`). Carries:
- `episode_id` (the UUIDv4 pairing/join key), `display_id` (derived, human-readable,
  never-a-key), `bimanual_episode_id` (the shared L/R id), `episode_ordinal` (fob label),
  `global_episode_seq` (ordering spine).
- References (resolved as-of `recorded_at`): `person_id`, `kit_id`+`side`, `task_id`,
  `calibration_id`, `capture_stack_id`, `session_id`.
- Lifecycle timestamps: `recorded_at` (fob NTP wallclock, authoritative) vs `ingested_at` (distinct —
  the explicit-lifecycle-timestamps decision).
- State: `paired`, `void`+`void_reason`, `needs_review`, `archive`, `recording_suspect`.
- A `footage_reference`.

### 3.3 Identity precedence (THE rule the join obeys — I-2)

Resolved per episode, fixed precedence, mismatch → `needs_review` (never overwrite):
- `kit_id` ← the FOB (the device bound to the kit; a camera can be swapped, the fob can't be
  confused which kit it is).
- `side` ← the CAMERA NAND (physical property of the body + mount).
- `operator`/`person_id` ← the roster binding keyed by kit (kit→person as-of recorded_at), cross-
  checked against the fob log's operator if present.
- `station` + `prompt` ← the FOB trigger record for that exact episode (ground truth of where the
  operator was at press time).
- **Serials (body/insv/camera_id) are PROVENANCE; they NEVER decide the kit.** They are the
  immutable crosswalk for retargeting a stale-labeled clip and for the IAQEB bootstrap.

### 3.4 The crosswalk + serial retargeting (robustness patterns kept)

- The long `IAQEB…` .insv serial is ALWAYS present (even on an un-provisioned camera) and is the
  crosswalk key carrying body_serial + camera_id + kit/side. Learned for free by co-locating both
  serials on one provisioned card (scan first+last 8MB of the .insv, don't slurp it whole).
- **Serial retargeting:** a clip carrying a STALE sidecar `kit_id` is corrected by its IMMUTABLE
  serial (a provisioning-era kit rename doesn't poison the data).
- **Kit aliases:** `stale_kit_id → real_kit_id`, applied to BOTH the sidecar AND the fob trigger
  record, so a fob still tagged a scrapped kit anchors correctly.

### 3.5 Task precedence (where the prompt comes from)

NAND `pantheon_current_task.env` (task-only, survives SD swaps) → overridden by SD
`current_assignment.env` (live push) → else `none` → the order-join supplies station/prompt at
ingest. `task_source` records which won. (IDENTITY_FLOW.)

### 3.6 The dual-signal join (the robustness fallback — the dual-signal-join decision, adopted from SEAM 3)

In the WiFi-OSC target, the label rides on the card LIVE, so the order-join is the FALLBACK, not the
primary path. But it is kept as the robustness mechanism (and it is the primary path for any
BLE/legacy data). The model (adopted from `trigger_join.py`, which is better than our original the dual-signal-join decision):
- **PRIMARY spine:** ordinal/count — the camera `global_episode_seq` (ordering) aligned to the fob
  `episode_ordinal` (label). For dense identical takes this is the only per-take discriminator.
- **GUARDRAIL:** coarse time + per-episode DURATION (frame-count/fps, CLOCK-INDEPENDENT; never
  absolute camera time, never the ~2s inter-take idle gap). Detects/repairs ordinal desync.
- **Failure tiebreaks (named):** `ordinal_slip` (phantom/missed start — time re-anchors),
  `board_swap` (counter reset — stitch by continuous segment + wallclock), `clock_suspect` (camera
  clock jump — ordinal holds), `needs_review` (both fail — flag, don't guess).
- **Phantom-press gate (= the fob-feedback/robustness requirement, enforced at source):** a START is refused (no ordinal advance) unless
  both cams acked (`sent==2`). `sent==0` → dropped (phantom_start); `sent==1` → kept-but-needs_review
  (one-sided orphan voided).
- **Block-level labeling simplifier:** one operator runs one task ~2 hrs, so labels are constant
  across the block → per-take precision only matters for delete/void + edge pairing, not labels.
- **Deletes = void-by-flag** with `global_episode_seq`-gap detection ("clip wiped" vs "clip
  survived"); instant-delete is a card-space optimization, NOT a correctness requirement.

---

## 4. The release metadata (what Hermes ingests)

**What it is:** what Eunomia emits per episode for the Hermes analytical platform to ingest — the
clean successor to `pantheon-episode-meta/v1`. It is the JOIN of the sidecar (§2) + the operational
model (§3) resolved as-of `recorded_at`, FROZEN at ingest, PLUS the derived fields (QC, sync,
pairing). Hermes pins a version of this and ingests it (the data-topology decision/the anti-drift decision).

### 4.1 Fields (grouped; populated at ingest unless noted)

- **Identity (frozen):** `episode_id` (UUIDv4 pairing key), `display_id` (derived human handle),
  `bimanual_episode_id`, `episode_ordinal`, `global_episode_seq`, `kit_id`, `side`, `camera_id`
  (+ body/insv serials as provenance), `person_id`+name, `station_id`, `task_id`+name, `prompt`,
  `rotation_id`, `session_id`.
- **Time (frozen):** `recorded_at` (fob NTP, authoritative), `camera_clock` (provenance-only),
  `ingested_at`. `time_confidence` ∈ `ntp_synced`|`unsynced_monotonic` (RTC-ready, the time-model decision).
- **Capture stack (frozen):** `capture_stack_id`, `modality` (`umi`|`teleop`), `camera_firmware`,
  `fob_id`+`fob_build`, `kit_version`, `record_format_version`, `record_settings` (3K/100, FlowState
  off, audio-on), `site_id`, `calibration_id`.
- **QC (derived at ingest, OPEN taxonomy):** `qc_flags` (open set), `qc_reasons`, `qc_score`
  (cohort-relative, default-ok). TWO deterministic stages feed it: IMU motion-QC (idle/frequent_pause/
  freefall/too_slow/ood/tiny/shake/saturation/jerk — from the IMU the X3 embeds) + video/container-QC
  (clip_too_short/missing_audio/dark/blank/dropped_frames/lr_desync). A VLM stage is separate/future.
  Status-only (not quality): `probe_failed`, `decode_skipped`.
- **Sync (derived, deferred-null-at-ingest):** `sync_offset_ms`, `sync_confidence` (the audio
  cross-correlation `score_ratio`: >20 solid, 5–15 ok, <5 unreliable). The cross-cam alignment is
  audio post-sync (the ground truth); trigger-time <1ms is impossible (no genlock).
- **State:** `paired`, `void`+`void_reason`, `needs_review`, `archive`, `recording_suspect`,
  `label_source`. **Promotion gates on the `void` FLAG, never a directory** (a clip's bytes location
  is independent of its void state).
- **Deferred-null-at-ingest (filled later):** `human_label`, `task_completed`, and the sync pair above.

### 4.2 The data-semantics the release carries (for training consumers)

- The usable video is the **BACK/RIGHT half** of the 3K/100 SBS frame (left half = front/selfie;
  use back only — `sbs_workspace_half=right`).
- The **IMU** comes from the FRONT `_00_` lens (the back reports "unsupported"); the front is kept
  through ingest for IMU extraction, then dropped from the training output (back-only training).
- Only **PAIRED** (left+right) non-void episodes are training/QA-able.

---

## 5. The two-axis versioning model (adopted from the as-built validator)

Two ORTHOGONAL version axes, because they answer different questions:

- **`schema` (STRING, e.g. `eunomia-sidecar/v1`)** — tells a PARSER which fields to expect.
  **Additive semver:** new fields are ADDED, never renamed; older files still validate under a newer
  schema (v1 files validate under a v2 parser). Owned by the contract; a change is its own reviewed
  PR with a version bump + changelog (the versioned-contract decision/the anti-drift decision).
- **`record_format_version` (monotonic INT)** — tells a FORENSIC query which capture BUILD produced
  an episode, so a bug tied to a firmware/fob/format build is scoped + quarantined BY QUERY, not a
  backfill. Owned by the WRITER (discardd). Warn-only so older cards keep validating.

The same two-axis discipline applies to the release metadata (a `schema` string Hermes pins +
the carried `record_format_version`/`capture_stack_id` for forensic scoping).

**Anti-drift (the anti-drift decision):** the contract is the single source of truth; Hermes pins a version; every
contract change is a reviewed PR with a version bump + changelog; consumers never silently track HEAD.

---

## 6. Validation + conformance (the enforcement contract)

- **Hard-vs-warn validation** (adopted directly): HARD errors INVALIDATE a record (the fields whose
  corruption makes it unsafe to ingest); WARNINGS flag downstream-consumed-but-recoverable fields,
  surfaced loudly in triage, non-blocking. A pure-stdlib validator (runs in the cam-side + ingest
  python with no deps) — `validate(obj) -> hard_errors`, `validate_full(obj) -> (errors, warnings)`.
- **The cross-language conformance gate (the versioned-contract decision):** the contract spine is language-neutral
  (`contracts/`: JSON Schema + interface markdown + codegen to C++ headers / Python types / JSON
  Schema). A cross-language conformance gate is the boundary check: the fob's emitted JSON, the
  ingest's parser, and Hermes's reader are all pinned to the same contract version and tested against
  golden fixtures (the as-built `test_fob_contract.py` pattern, generalized).
- **Identity/config deployment is a NON-DESTRUCTIVE MERGE** (the 2026-06-18 camera_map incident
  lesson): the registry/map is deployed by merge-with-drift-detection-and-backup, never a destructive
  overwrite. The authoritative source wins on side+presence; other entries are preserved.

---

## 7. Resolved decisions (the episode-id key, and the cleaning-layer boundary)

### RESOLVED — `episode_id` = UUIDv4 pairing key + a derived `display_id` composite

**Decision (locked):** `episode_id` is a **UUIDv4** minted by the fob at START and written
identically to both arms' sidecars — it is the opaque, collision-free PAIRING + JOIN key, and the
ONLY key anything joins/pairs on. A **`display_id`** composite (`<YYYYMMDD>_<operator>_<station>_
<NNNNNN>`, the as-built structured form) is COMPUTED and stored ALONGSIDE, clearly marked DERIVED —
it is the human-readable handle for debugging/eyeballing a card, and is NEVER a join key. The
underlying descriptive fields (site/kit/fob_session/ordinal/recorded_at/operator/station) also
remain their own queryable columns.

**Why this (vs. a bare UUID with no readable handle, vs. using the structured composite itself as the key):**
- Keeps the UUID's robustness: identical on both arms (fob writes the same bytes), collision-free,
  immune to a wrong/changed resolved field (operator/station can be a mislabel) — consistent with
  the contract's "resolve, don't bake" identity precedence (§3.3). The join NEVER depends on a baked
  identity string.
- Recovers B's readability WITHOUT B's fragility: humans debug by `display_id` (instant "what
  episode is this"), but if a field in it is wrong it's a COSMETIC label, not a corrupted key. Makes
  the readable handle first-class (rather than reassembling it from separate columns).
- Ordering still comes from `global_episode_seq` + `recorded_at`, NEVER the id (the `display_id`'s
  date prefix is not used for ordering — that would invite the camera-clock mis-ordering the join
  guards against).

**Contract consequences (applied below):** `episode_id` (UUIDv4) is the hard-required pairing key;
`display_id` is a WARN, derived, never-a-key field carried on the sidecar identity group + the
episode entity + the release record. `bimanual_episode_id` remains the fob-injected shared L/R id
(distinct from `episode_id`: it pairs the two wrist cams of ONE take; `episode_id` identifies the
take). Small migration from as-built (the fob already stamps every field in the composite; it now
also emits a UUID, and pairing keys on the UUID).

### RESOLVED — Eunomia FEEDS the cleaning/render layer; it is downstream (Hermes-side)

**Decision (locked):** Eunomia owns **capture + ingest + identity + QC + ops + the live consoles**,
and EMITS the release record (§4) + the raw footage references. The heavy downstream cleaning/render
(audio-sync, IMU start-trim, de-fisheye render to flat back-only mp4, dataset assembly) is NOT
absorbed into Eunomia — it is a **downstream stage Eunomia feeds**, living on the Hermes side (on
Hades, where the compute already is). The audio-sync CORE is shared code (the DRY lesson), so "feed"
does NOT mean "duplicate" — Eunomia and the downstream stage import the same sign-verified core.

**Why feed (rather than absorb the cleaning layer, or split it):** keeps Eunomia focused on the on-site capture→ingest→identity→QC→
ops path (its coherent scope); puts the heavy compute (de-fisheye render, audio xcorr over full
clips) with the training-data platform on the box built for it; avoids Eunomia sprawling into
training-data engineering. The seam is clean because the release record (§4) + footage_reference
(§3.1) are exactly the handoff: Eunomia says "here is the labeled, QC'd, paired episode and where its
bytes are," and the downstream stage cleans/renders/assembles from there.

**⚠ HANDOFF REQUIREMENT (Mo, when you get to Hermes):** the heavier pieces that will live in Hermes
must be FLAGGED at that point as part of the Hermes handoff — including EXACTLY where to find the
existing code to integrate. The pointer table below is the starting map (from the repo read); confirm
+ extend it when the Hermes integration is scoped. These are REFERENCE implementations to integrate/
re-architect cleanly on the Hermes side, not Eunomia modules.

**Downstream pieces (where they live today — the integration map):**

| Downstream concern | Where it lives today | Notes for the Hermes-side handoff |
|---|---|---|
| Audio cross-cam sync (the SHARED core) | `data/umi_clean/stages/s2_audio_sync.py` (canonical, sign-verified); X3 wrapper `pipeline/x3_audio_sync.py` | The core is shared — Eunomia's QC `lr_desync` + the downstream sync both call it. Keep ONE core. |
| IMU start-trim (ready-pose onset) | `data/umi_clean/stages/s2b_start_trim.py` | Trim = camera-IMU ready-pose onset, NOT a fob-duration cut. Needs the IMU (front-lens) Eunomia extracts. |
| The umi_clean run builder / pairing→clean entry | `pipeline/x3_pair.py` (builds a umi_clean run dir) + `data/umi_clean/` (bootstrap_umi_clean → the stages) | x3_pair groups by NAND identity + fob ordinal, symlinks raw, emits manifest. The clean pipeline runs on that. |
| De-fisheye / back-only flat render | `pipeline/dashboard_pair_render.py` (back-only flat paired render) + `data/umi_clean` render stage | Reads fisheye, writes NEW mp4s; raw fisheye NEVER deleted/overwritten. Back/right half only. |
| Label/void overlay onto cleaned episodes | `pipeline/fob_overlay.py` | Applies fob labels + void + `dashboard_ready` to the cleaned run (post-ingest). |
| The autonomous clean→dashboard chain (orchestration) | pluto cron `pipeline/deploy/x3-clean-autorun.sh` → bootstrap_umi_clean → umi_clean → fob_overlay → dashboard_pair_render | The whole downstream chain, flock'd + idempotent. The model for the Hermes-side stage. |
| IMU extraction (the seam — Eunomia SIDE) | `pipeline/insv_to_imu_json.py` (+ `qc_from_imu.py` unit conversion) | NOTE: IMU extraction stays on the EUNOMIA/ingest side (it's the QC input + the trim input); the front lens is dropped from the training output AFTER extraction. This is the boundary line. |

(The intrinsics/SBS-half config the render reads: the data repo's `camera_intrinsics.json` /
`camera_intrinsics` with `sbs_workspace_half=right`.)

---

## 8. Deliberately deferred (visible, not forgotten)

These are out of scope for THIS contract but tracked (see the register's OPEN section): edge-sync
cadence/conflict + the Hades-backup shape; footage retention + Styx→Hades transfer integrity;
WAN-outage console behavior; exactly how Hermes consumes the contract (package vs submodule vs
vendored); QC thresholds (config, per-site retune); discard/quarantine end-to-end mechanics; backfill
mechanics; provisioning-at-scale + site-config distribution + fleet firmware updates + multi-site; the
web stack choice; console auth/access; secrets/PII handling. The downstream cleaning/render boundary
is now resolved (§7: Eunomia feeds it); its Hermes-side integration (the pointer table in §7)
is flagged for the Hermes handoff, not built here. The time-model known gap (a fully-offline
fob has unreliable absolute time + god's-view "when" until sync) stands until RTCs are added.

---

## Appendix A — decisions folded into this contract

This contract folds: the episode-id decision (episode_id — RESOLVED as A′: UUIDv4 pairing key + derived `display_id`
composite), the time-model decision (time model), the calibration-as-scoped-entity decision (calibration as optional scoped entity), the dual-signal-join decision (dual-signal join, upgraded to SEAM-3's model), the footage-lifecycle decision (footage_reference
lifecycle), the event-sourcing decision (event-sourced operational model), the capture-stack-provenance decision (capture-stack provenance), the versioned-contract decision/the anti-drift decision (versioned
contract + conformance gate + anti-drift), and the identity-ownership of the unification mandate
(Eunomia owns identity; fleet.yaml's fields absorbed). It encodes the learnings: two-axis versioning,
hard-vs-warn, the two-ordinal model, open-taxonomy QC (two deterministic stages), identity precedence
(kit←fob/side←NAND/operator←roster/serials-never-decide), card-is-not-a-unit, the .insv flip, the SBS
back-half + front-lens-IMU lifecycle, the IAQEB crosswalk + serial-retargeting + aliases, audio
post-sync, the no-SD trap (`recording_suspect`), non-destructive-merge deployment, and the
live-label-primary / join-fallback architecture.
