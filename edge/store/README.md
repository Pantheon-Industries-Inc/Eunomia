# `edge/store/`

**Filled in its own run.** The operational store — persists the `contracts/operational/` model,
event-sourced (append-only events + materialized current-state views). The consoles write through it;
it is the live system of record on the ground, edge-authoritative (survives a WAN outage).
