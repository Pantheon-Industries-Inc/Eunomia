# `edge/sync/`

**Filled in its own run.** Periodic replication of the operational metadata to a Hades backup — an
intentional design when we build it (cadence, conflict policy, edge-authoritative confirmation, the
Hades backup shape; MODULE_MAP open-Q 2). Footage does NOT go here (it takes the separate drain→ship
path); this syncs only the small metadata.
