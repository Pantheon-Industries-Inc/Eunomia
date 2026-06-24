# ADR-0001 — Eunomia architecture

- **Status:** Accepted (Run 0a, Foundation)
- **Context docs:** `docs/CONTRACT.md` (the data spine), `docs/MODULE_MAP.md` (the structure),
  `docs/DECISION_REGISTER.md` (the decisions this folds: C-9..C-12, B-8, B-9, A-2, D-8..D-12, R-2).

## Context

Eunomia is the clean, **unified replacement** for the whole on-site capture + ingest + identity + QC +
ops level — the convergence of two battle-hardened codebases (the card-drain/ops side in the `data`
repo / Styx Layer 0, and the ingest/identity/QC pipeline in `x3-capture-kit` Layer 1/2) **plus** the
flows and consoles we specced, into one coherent system. Their code is the SURVEY/learnings layer:
where it is already clean we copy, otherwise we re-architect cleanly keeping the hard-won constraints.
Eunomia produces the release metadata the **Hermes** analytical platform (separate repo, on Hades)
ingests, and FEEDS the downstream cleaning/render layer (Hermes-side).

## Decisions

1. **One polyglot monorepo.** The whole system lives in one repo: C++ firmware, Python
   tooling/services/ingest, a web console stack, the ported host substrate, and the cross-cutting
   contracts. No separate-repo tracking. The design goal driving the layout: abstraction sufficient
   that we **adapt instead of rebuild** — three swap-points (hardware, a UI, a process) each behind a
   seam.

2. **Contract-as-spine + the dependency law.** `contracts/` is the versioned, language-neutral
   definition of every piece of data and every hardware interface. **Everything depends only on
   `contracts/`; it imports nothing.** A console never imports firmware; firmware never imports a
   service. Enforced by a per-language import-boundary check (import-linter for Python;
   `eunomia_contracts` is the spine) **plus** a cross-language conformance gate (anything emitting/
   consuming the data validates against the one generated JSON Schema). Codegen emits **one source,
   three targets** (C++ header / Python type / JSON Schema).

3. **Event-sourced operational model** (B-8). The identity + context entities (person, hardware-unit,
   kit, calibration, task, session, capture-stack, footage-reference, episode) are append-only events
   with materialized current-state views; an episode's references resolve **as-of `recorded_at`**.
   This is what makes attribution temporally correct and backfill clean (append a correcting event,
   never mutate).

4. **Data topology: edge-authoritative + analytical system-of-record downstream** (A-2, anti-drift).
   The on-site operational store (`edge/`) is the live, edge-authoritative system of record (survives
   a WAN outage; footage tracked by a `footage_reference` lifecycle). The release record is emitted to
   Hermes, the **analytical** system-of-record, which **pins a version** and ingests it. Drift is a
   visible version gap, never silent.

5. **Eunomia FEEDS the cleaning/render layer; it does not own it** (CONTRACT §7). Eunomia owns
   capture + ingest + identity + QC + ops + the live consoles, and emits the release record + footage
   references. The heavy downstream cleaning/render (audio-sync, IMU start-trim, de-fisheye back-only
   render, dataset assembly) is a downstream stage on the Hermes side. The audio-sync **core is shared
   code, not duplicated** ("feed" ≠ "duplicate"). IMU *extraction* stays on the Eunomia/ingest side.

6. **Substrate ported-but-frozen** (D-8 / D-12). The Styx host substrate (ZFS, Sipolar port mapping,
   udev, systemd, install scripts) is vendored into the repo **interface-frozen** to the existing
   deploy: Eunomia contains the substrate definition but does not change its shape/config/layout, and
   its installer is an idempotent superset. Identity is owned by Eunomia; Styx's `camera_map` becomes
   a projection (D-9). This unblocks the on-site deploy without forcing a re-setup.

7. **Two-axis versioning + anti-drift** (CONTRACT §5). A `schema` string (additive semver; tells a
   parser which fields to expect) and a writer-owned `record_format_version` int (forensic
   build-scoping by query, never a backfill). A contract change is its own reviewed PR with a version
   bump + changelog.

## Consequences

- A hardware swap changes one adapter (a port implementation), a UI swap changes one app, a process
  swap changes service logic behind `edge/api/` — none cascade.
- The contract is the single coordination point across four languages/stacks; the conformance gate is
  the boundary check that keeps them honest.
- The contract is the highest-leverage, highest-blast-radius surface — hence Run 0a proves the codegen
  pipeline end-to-end on a trivial example *before* the real schemas are poured in (Run 0b).

## Alternatives considered

- **Layer beside the existing code** (keep the 3-layer split) — rejected: perpetuates the file-sprawl
  the unification mandate exists to fix.
- **Separate repos per component** — rejected: separate-repo tracking is the coordination cost we are
  removing; the contract + conformance gate give modularity without it.
- **Absorb the cleaning/render layer** — rejected: puts heavy training-data compute where the capture
  system lives; the release record + footage_reference are a clean handoff seam instead.
- **Substrate in a separate repo / mutable in-repo** — rejected: would risk breaking a running on-site
  box; frozen-interface vendoring protects the existing deploy.
