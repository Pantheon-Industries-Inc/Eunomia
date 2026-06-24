# `contracts/events/` — telemetry events + operational-sync delta

**Filled in Run 0b.** The god's-view telemetry event schema (started / stopped / camera-dropped /
recording-suspect) consumed by `consoles/gods-view/`, and the operational-sync delta format used by
`edge/sync/`.

Authoritative description: `docs/MODULE_MAP.md` (`contracts/events/`) + `docs/CONTRACT.md`. (The Run
0a `ping` proof in `contracts/_proof/` is an *event-shaped* throwaway; it is not a real event and is
deleted in 0b.)
