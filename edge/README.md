# `edge/` — the on-site operational store + sync (Python service, runs on-site)

**Single responsibility:** the small operational-metadata store the ground teams read/write live.
Tiny (kilobytes/episode), local, **survives a WAN outage** (edge-authoritative).

**Dependency rule:** depends only on `contracts/`. The consoles talk to `edge/api/`, never to the
store directly.

**Boundary:** `edge/` and Hermes both implement a store but for different masters — `edge/` is the
live on-site store; Hermes (separate repo) is the analytical system-of-record that ingests the same
contract. They share the contract, not code. Footage does NOT flow through here — only the small
metadata (footage takes the separate drain→ship path).

## Layout (READMEs only in 0a)

| Path | Responsibility |
|---|---|
| `store/` | the operational store (persists the `contracts/operational/` model, event-sourced). The live on-ground system of record. |
| `sync/` | periodic replication of the metadata to a Hades backup (cadence/conflict policy designed when built). Metadata only. |
| `api/` | a stable internal API the consoles call — the process/logic lives here behind an interface (change a *process* → change here, not the UIs). |
