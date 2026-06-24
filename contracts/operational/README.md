# `contracts/operational/` — the event-sourced operational model

**Deferred to Run 0c (split decision, plan.md OQ-1).** Run 0b encodes the *record surface* (sidecar +
release + events) + the hybrid validator; the operational *store* model lands in 0c. The append-only
event model with materialized current-state views: person
(decoupled from kit), hardware-unit (order→batch→unit→lifecycle), kit, calibration (a scoped optional
entity — none/fleet/per-camera), task, session, capture-stack (registered provenance),
footage-reference (on-card→on-styx→shipped→on-hades→purged), and episode (the join point). Episode
references resolve **as-of `recorded_at`**.

Authoritative definition: `docs/CONTRACT.md` §3 (+ decisions B-8, B-9, A-2, C-9..C-12).
