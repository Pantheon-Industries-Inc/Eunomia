# `contracts/events/` — telemetry events + operational-sync delta + operational lifecycle events

**Filled in Run 0b; extended in Run 0d.** Three event/envelope records:

- `eunomia-telemetry-event.schema.yaml` — the god's-view live event (started / stopped /
  camera-dropped / recording-suspect) consumed by `consoles/gods-view/`. (Run 0b.)
- `eunomia-sync-delta.schema.yaml` — the edge→Hades operational-metadata sync envelope (generic
  upsert/delete transport) used by `edge/sync/`. (Run 0b; **Run 0d OQ-9**: `entity` stays an open
  string — additive-safe — and is WARN-checked against the §3 operational entity set in `_semantics`,
  NOT a hard enum, which would be a §5-violating narrowing.)
- `eunomia-operational-event.schema.yaml` — the append-only operational **lifecycle** event
  (polymorphic by `event_type`, opaque `payload`), the first-class log record where a lifecycle carries
  fields beyond the entity snapshot (CONTRACT §3, B-8/B-9; **Run 0d OQ-3/OQ-C**). It lives here (with
  the operational transport) rather than in `operational/`, which holds the current-state entities.

Authoritative description: `docs/MODULE_MAP.md` (`contracts/events/`) + `docs/CONTRACT.md`. (The Run
0a `ping` proof in `contracts/_proof/` is an *event-shaped* throwaway; it is not a real event and was
deleted in 0b.)
