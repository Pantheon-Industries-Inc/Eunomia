# `ingest/` — identity, QC, join, and the release record (Python)

**Single responsibility:** turn drained cards (the DCIM tree + on-card sidecars + the fob trigger
log) into labeled, QC'd, paired **release records**. The clean, unified successor to the scattered
ingest/identity/QC code. Runs on the ingest host.

**Dependency rule:** depends only on `contracts/`. Never imported by firmware, edge, consoles, or
tooling.

**Boundary (fed, not owned):** the heavy downstream cleaning/render (audio cross-correlation sync, IMU
start-trim, de-fisheye back-only render, dataset assembly) is **Hermes-side**, not here. Eunomia
FEEDS it. IMU *extraction* stays here (it is the QC + trim input); the front lens is dropped from the
training output after extraction. (CONTRACT §7.)

## Layout (all filled in their own run; READMEs only in 0a)

| Path | Responsibility |
|---|---|
| `identity/` | the unified identity owner: immutable-serial crosswalk, serial retargeting, kit aliases, identity precedence (kit←fob / side←NAND / operator←roster / serials-never-decide). A mismatch sets needs-review. |
| `join/` | the dual-signal join (ordinal spine + clock-independent duration guardrail + named tiebreaks), L/R pairing by shared episode id, deletes-as-void-by-flag. |
| `qc/` | the two deterministic QC stages (IMU motion-QC + video/container-QC), open taxonomy, cohort-relative score. |
| `release/` | assembles + emits the release record; resolves the operational model as-of recording time; freezes the join. |
| `orchestrator/` | the parallel, idempotent runner (one worker per card-dump, done-markers, hardlinks never copies). |

Built for ~100 kits/hr; the IMU extraction is the throughput knob.
