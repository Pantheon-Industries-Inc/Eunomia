# `contracts/sidecar/` — the on-card schema (`eunomia-sidecar`)

**Filled in Run 0b.** What the coordinator writes per episode onto each camera's SD card at capture —
the primary, loss-resilient record (the label rides on the card). Carries the hard-vs-warn field
rules and the two-axis versioning (a `schema` string for parsers + a writer-owned
`record_format_version` int for forensic build-scoping).

Authoritative definition: `docs/CONTRACT.md` §2. Encoded here as the neutral source + codegen targets
in 0b, against the harness proven in 0a.
