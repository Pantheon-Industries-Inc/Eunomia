# Run 0e — operational-model extensions (plan-of-record)

Plan-only run, then implemented on Mo's `NOTE:` annotations. `contracts/` **code only** — no UI,
firmware, console, or SPEC/CONTRACT doc edits. Every new entity is operational/console/ingest-side,
**additive and non-breaking to the firmware-facing wire types** (the sidecar + the C++ targets are
untouched; `contracts/_generated/cpp/` is byte-identical).

## Scope landed (A–E)

**A. Station registry — NEW entity `eunomia-station/v1`** (`contracts/operational/`). A registered,
site-scoped, first-class station (until 0e, `station_id` was only a string field). Anchor `station_id`
is the per-site number-as-string the card carries; `site_id` (HARD) scopes it. **Global identity /
uniqueness / resolution = `(site_id, station_id)`** — a documented cross-record allocation property
(the allocator never re-issues a retired pair), not a single-record rule. `status` is an OPEN string,
WARN-checked vs `{active, retired}` (OQ-A); `retired_at` is the retire-not-reuse marker.
- Per NOTE: `station_number` dropped (it equals `station_id`, the number the card carries); `site_id`
  HARD. The existing sidecar/episode `station_id` semantics (a bare per-site string the card carries)
  are consistent with this — no conflict to flag.

**B. Task catalog — versioning + variants + rotation.** `task` already carries `version` +
`effective_from/to` + `rotation_id`; prompt variants are modeled as **rows sharing `task_id`,
differing by `rotation_id`** (in-DSL; no array-of-objects). Natural key `(task_id, version,
rotation_id)`. The episode now **pins all three**: added `task_version` + `rotation_id` to
`eunomia-episode/v1` (warn/nullable; resolved + stored at ingest, like `capture_stack_id`) so a catalog
edit never retroactively changes a past episode. `task.station_id` flagged **legacy / non-authoritative**
(superseded by C; kept additive per §5).

**C. Task→station assignment — NEW entity `eunomia-task-station-assignment/v1`** (`contracts/operational/`).
Append-only, time-ranged. Anchor `assignment_id`. **`site_id` + `station_id` + `effective_from` are HARD**
(the resolution key + the record's essence); `effective_to` nullable (null = open/current). Resolution
(documented, runs at ingest): `(site_id, station_id, timestamp)` → the row whose
`[effective_from, effective_to)` contains the timestamp; latest `effective_from` wins. The dynamic
replacement for the hardcoded `stations.yaml`.
- Per NOTE §4.5: `effective_from` is HARD — a deliberate divergence from the nullable `effective_from`
  on kit/task/calibration (an assignment is event-like, not slowly-varying).
- Ingest note (NOT built here): the resolver can cross-check the card's stamped `task_id` against the
  resolved assignment to catch a stale boot-mapping.

**D. Provision profile — extend `hardware_unit`** (additive, warn/nullable): `camera_id` (the LOGICAL,
registry-allocated, globally-unique, unchanging, retire-not-reuse id; the explicit `body_serial`↔
`camera_id` crosswalk on one record), `fob_id`, `board` (per-fob profile), `mount` (promoted from
sidecar-only). camera_id uniqueness + retire-not-reuse = cross-record allocation property (schema models
the shape, the console owns the allocation). The optional `type==camera ⇒ warn-if-camera_id-absent` was
**left out**: the DSL `conditional` is schema-version-gated (makes a field HARD when `schema` is v1+),
not field-value-gated — so it can't express this; a hand-written `_semantics` rule is the only path and
the NOTE said leave-if-not-cheap-in-the-DSL.

**E. Event-sourced hardware-config history / `capture_stack`** (additive, warn/nullable): added
`kit_id` + `effective_from`/`effective_to` so the per-kit config is time-ranged + reconstructable as-of
("kit 42: gripper v2→v3 @ date"). New operational-event types in the WARN known-set (additive;
`event_type` stays an open string): `kit_config_changed` (a gripper swap, no reflash),
`capture_stack_registered`, `station_registered`, `station_retired`, `task_assignment_created`,
`task_assignment_ended`, `camera_id_allocated`, `camera_id_retired`. **Reconcile = no-op in code**: the
sidecar carries the components (not a `capture_stack_id`) and the episode's `capture_stack_id` is
warn/nullable (resolved + stored at ingest) — already correct; only the B-9 prose was stale, documented
in the capture_stack header.

## Hand-written (non-generated) edits

- `contracts/codegen/templates/semantics.py.tmpl`: `station` + `task_station_assignment` added to
  `_OPERATIONAL_ENTITIES`; the 8 new `event_type`s added to `_OPERATIONAL_EVENT_TYPES`; new
  `_STATION_STATUSES` + `_station_vocab` WARN-check wired into `_CROSS_FIELD_WARN["eunomia-station/v1"]`.
- `contracts/conformance/test_conformance.py`: imports, `ENTITIES` map, and the validate-parity dict.
- 8 new fixtures (station + assignment: valid / warn / invalid; one demonstrates `effective_from` HARD).
- `contracts/operational/README.md`: entity table 9 → 11.

## Codegen impact

New `_generated` jsonschema + python for the 2 new entities; regenerated jsonschema + python for the 4
edited entities + `_semantics.py` + `__init__.py`. **`contracts/_generated/cpp/` is byte-identical** —
the only cpp targets are sidecar / telemetry_event / the ports, none touched.

## Gates (all green)

- Python: `pytest` (83), `ruff check`, `ruff format --check`, `mypy`, `lint-imports`.
- Codegen-drift: zero (deterministic; staged tree == freshly-regenerated output).
- C++: `clang-format`, `pio test -e native`, `pio run -e esp32`, `pio run -e cyd`, `clang-tidy`
  (0 user findings), camera-image checksum stub.

## Register decisions this run implements (mark folded; register unchanged by this run)

- "Task-setup flow" (2026-06-25) → A, B, C.
- "Boot-uplink … provision profile" thread 2 (2026-06-25) → D (resolves the open "camera_id
  registry-allocated + never-reused" decision — modeled).
- "Boot-uplink …" thread 3 + "Daily hardware-setup" (B-9) → E.
- The "FOLD-IN RECONCILE" (capture_stack_id resolved-at-ingest) → E (confirmed already-satisfied).
- "Post-F3 sequencing" Run-0e scope + "Run 0e revised → pure contract CODE".
