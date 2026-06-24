# `contracts/operational/` — the event-sourced operational model

**Single responsibility:** the queryable store of identity + context (CONTRACT §3) — the
current-state (materialized-view) records every clip's full identity resolves against. The clean,
unified successor to `fleet.yaml` + `operator_roster.yaml` + `x3_state.json` + the scattered env files.

**Dependency rule:** like all of `contracts/`, this area imports nothing internal — it IS the spine.
Targets are **`[jsonschema, python]`** only; **firmware never reads the operational model** (it writes
the sidecar + emits telemetry), so there is no C++ target (decision OQ-10).

## The nine entities (CONTRACT §3.1–§3.2)

| File | Entity | Anchor (HARD) | Notes |
|---|---|---|---|
| `eunomia-person.schema.yaml` | person | `person_id` | Decoupled from kit; lifecycle = events (B-8). |
| `eunomia-hardware-unit.schema.yaml` | hardware_unit | `unit_id` | Serials immutable + the §3.4 crosswalk key, **never decide kit** (§3.3). |
| `eunomia-kit.schema.yaml` | kit | `kit_id` | A time-bound binding of {left-cam, right-cam, fob} units. |
| `eunomia-calibration.schema.yaml` | calibration | `calibration_id` | Optional; `scope` none/fleet/per_camera (C-11). |
| `eunomia-task.schema.yaml` | task | `task_id` | Versioned prompt; resolved as-of recording (§3.5). |
| `eunomia-session.schema.yaml` | session | `session_id` | The kit↔person binding (OQ-D) + `fob_session_id`. |
| `eunomia-capture-stack.schema.yaml` | capture_stack | `capture_stack_id` | Registered provenance, referenced by id (B-9). |
| `eunomia-footage-reference.schema.yaml` | footage_reference | `episode_id` | Byte lifecycle on_card→…→purged + the spot-check held-purge (A-2, OQ-5). |
| `eunomia-episode.schema.yaml` | episode | `episode_id` | **The join point** (§3.2); references resolve as-of `recorded_at`. |

## How the model is built (Run 0d)

- **Record-shaped reuse of the 0b machinery.** Each entity is a field-DSL YAML through the same
  generator + the Option-C hybrid validator (real `jsonschema` for structure + the stdlib `_semantics`
  overlay for the hard-vs-warn split + cross-field rules). The generator did **not** grow.
- **Event-sourcing (OQ-3, B-8).** These records are the **materialized current-state views**; the
  append-only log is the `eunomia-sync-delta` envelope (generic upsert/delete) + the first-class
  `eunomia-operational-event` record (in `contracts/events/`) where a lifecycle carries its own fields.
  The fold/materializer is **not** implemented — 0d defines the types + documents the derivation.
- **As-of resolution (OQ-6).** Time-bound bindings carry `effective_from` / nullable `effective_to`;
  events carry `as_of`; the episode carries `recorded_at`. The rule — "an episode resolves its
  references against the binding true at `recorded_at`" — is **documented**; the resolver runs at
  ingest (a later run).
- **The §3 rules are types + docs, not enforced single-record validation.** Identity precedence
  (§3.3), the crosswalk + serial retargeting (§3.4), task precedence (§3.5), and the dual-signal join
  (§3.6) are **join-time, multi-entity** logic, encoded as typed fields + prose. The only single-record
  `_semantics` rules are `episode.void ⇒ void_reason` and
  `footage_reference.spot_check_selected ⇒ selection_method` (OQ-11).
- **The shape budget (OQ-4).** Every entity stays within the DSL — top-level scalars, ONE nested
  object level, scalar arrays. Repeating sub-structures (a unit's lifecycle, a kit's bindings over
  time) are **separate event/binding records referenced by id**, never embedded object arrays. The two
  structured-data edges resolve in-DSL (OQ-B): calibration heavy intrinsics → an opaque `object` blob
  (consumed Hermes-side); footage `locations` → a scalar array of strings.

**Never hand-edit `contracts/_generated/`** — edit the YAML source here and run `make codegen`.
Authoritative definition: `docs/CONTRACT.md` §3 (+ decisions B-8, B-9, A-2, C-9..C-12, R-2, the
2026-06-24 spot-check block).
