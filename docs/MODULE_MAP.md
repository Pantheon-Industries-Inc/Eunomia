# Eunomia — Module & Boundary Map

This is the structure the Foundation phase will scaffold and freeze. It holds the **whole Eunomia
system** in one monorepo: the embedded coordinator firmware, the bench/test tooling, the camera-image
builder, the on-site operational store + its consoles, the ingest pipeline, the ported host substrate,
and the cross-cutting contracts. It is polyglot (C++ firmware, Python tooling/services/ingest, a web
UI stack).

**What Eunomia is:** the clean, unified replacement for the whole on-site capture + ingest + identity
+ QC + ops level — the convergence of the two existing battle-hardened codebases (the card-drain/ops
side in the `data` repo, and the ingest/identity/QC pipeline in `x3-capture-kit`) plus the flows and
consoles we specced, into one coherent system. Eunomia produces the release metadata the **Hermes**
analytical platform (a separate repo, on Hades) ingests, and FEEDS the downstream cleaning/render
layer (which is Hermes-side, not part of Eunomia).

**The design goal that drives everything: abstraction sufficient that we adapt instead of rebuild.**
Three swap-points must each be cheap to change:
1. **Hardware** (board or camera) → changes one adapter, not the tree.
2. **A UI** (any console) → changes one app, touches nothing else.
3. **A process** (a flow/policy) → changes service logic behind a stable interface.
The map is organized so each lives behind a seam.

---

## The one rule that makes it modular: everything bends to the CONTRACT

```
                          ┌───────────────────────┐
                          │      contracts/        │  ← THE SPINE
                          │  (versioned, neutral)  │     imports nothing
                          └───────────┬───────────┘
   ┌──────────┬──────────┬───────────┼───────────┬──────────┬──────────┐
   ▼          ▼          ▼           ▼           ▼          ▼          ▼
firmware/   ingest/    edge/      consoles/   tooling/  substrate/  (Hermes —
(the kit) (identity+  (on-site   (the UIs)   (bench    (ported,    separate repo,
           QC+join+    store +                harness)  frozen      ingests the
           release)    sync)                            interface)  contract)
```

Every box depends on `contracts/` and **on nothing else of each other's internals**. A console never
imports firmware; firmware never imports a service; the harness never imports ingest. The only shared
language between them is the contract. This is the boundary discipline carried over from Hermes —
enforced by an **import boundary check** (per-language) plus a **cross-language conformance gate**
(anything that emits or consumes the data validates against the one schema).

The authoritative definition of the data lives in `x3_platform_contract.md`; `contracts/` below is
the machine-readable encoding of it.

---

## `contracts/` — the spine (authored here; this repo is the source of truth)

The canonical definition of every piece of data and every hardware interface. Language-neutral,
**versioned**, with codegen so each stack consumes the *same* source.

- `contracts/sidecar/` — the on-card schema (`eunomia-sidecar`): what the coordinator writes per
  episode onto the card, the hard-vs-warn field rules, the two-axis versioning (a `schema` string for
  parsers + a writer-owned format-version integer for forensic build-scoping).
- `contracts/operational/` — the event-sourced operational model: person (decoupled from kit),
  hardware-unit (order→batch→unit→lifecycle), kit, calibration (a scoped optional entity so
  none/fleet/per-camera all fit), task, session, capture-stack (the registered provenance entity),
  footage-reference (the on-card→on-site→shipped→on-Hades→purged lifecycle), and episode (the join
  point). This is the identity + context model the consoles read/write and the ingest resolves against.
- `contracts/release/` — the release metadata: the per-episode record Eunomia emits for Hermes to
  ingest (the join of sidecar + operational model, frozen at ingest, plus the derived QC/sync/pairing
  fields). **This is the platform-input contract Hermes pins a version of.**
- `contracts/interfaces/` — the hardware seams as explicit interface definitions:
  - **CoordinatorPort** — mint the episode id, trigger both cameras serialized, read back the clip
    filename, write the sidecar, detect a camera drop (at the network-association layer), flush
    telemetry. (The fob's contract; recording depends on the on-camera agent holding video mode, so
    the coordinator does NOT arm per take.)
  - **CaptureDevicePort** — start, stop, read-back-filename, get-state, set-profile, write-sidecar.
  These are *why* a hardware swap is cheap: firmware implements a port; a new board/camera is a new
  implementation of the same port, nothing upstream changes.
- `contracts/events/` — the god's-view telemetry event schema (started / stopped / camera-dropped /
  recording-suspect) and the operational-sync delta format.
- codegen → emits C++ headers (firmware), Python types (tooling/ingest/services), JSON Schema (the
  conformance gate + web validation). **One source, three targets.**

Versioning discipline: a contract change is its own reviewed PR with a version bump + changelog;
Hermes pins a version; bumping the pin is a deliberate PR on the Hermes side, so drift is visible (a
version gap), never silent. Identity/config deployment is always a non-destructive merge (with
drift-detection + backup), never a destructive overwrite.

---

## `firmware/` — the kit (C++ / PlatformIO, ESP32)

- `firmware/coordinator/` — the fob coordinator. Built to its real end-state shape, but structured so
  the **radio/transport layer is one swappable module** (the load-test hedge: if the SoftAP proves
  marginal under sustained load, you replace `transport/`, not the trigger logic).
  - `core/` — the trigger state machine, episode/ordinal logic, sidecar assembly, the phantom-press
    guarantee (a take only starts when both cameras have acknowledged; spamming is harmless by
    design), the instant touch-acknowledgement UI state machine. **Pure, off-target testable,
    hardware-free.** Implements `CoordinatorPort`. The network worker runs on a dedicated core so the
    UI never stalls; the durable ordinal is written to flash before the counter advances.
  - `transport/` — the WiFi-AP hosting + OSC client (fire-and-forget) + telnet client. The
    hardware-coupled, swappable layer. Single serialized OSC client, no background polling.
  - `ui/` — the touchscreen screens (the display). Swappable without touching `core/`. Full-screen
    color state, take counter, action toast, haptic/audio tick on a registered press.
- `firmware/camera-image/` — the camera-image build tool (NOT firmware we author; a reproducible
  **packaging** of a stock binary + the on-camera agent that holds capture mode and writes the
  per-clip sidecar). Core + CLI today, callable by the provisioning console later. Checksum-verified.

Why this is adapt-not-rebuild: change the board → new `transport/` + maybe `ui/`; `core/` and the
contracts are untouched. Change the camera → a new `CaptureDevicePort` implementation; `core/` untouched.

---

## `ingest/` — identity, QC, join, and the release record (Python, runs on the ingest host)

The clean, unified successor to the scattered ingest/identity/QC code. Turns drained cards (the DCIM
tree + the on-card sidecars + the fob trigger log) into labeled, QC'd, paired release records.

- `ingest/identity/` — the unified identity owner (absorbs the old registry): the immutable-serial
  crosswalk (the long camera serial embedded in every clip is the always-present key), serial
  retargeting (a stale-labeled clip is corrected by its immutable serial), kit aliases, and the
  identity-precedence rule (kit from the fob, side from the camera, operator from the roster binding,
  station/prompt from the fob log — serials are provenance and never decide the kit). A mismatch sets
  needs-review, never overwrites.
- `ingest/join/` — the dual-signal join (the robustness fallback; live-label is the primary path):
  the camera's swap-proof ordinal as the ordering spine + the fob ordinal as the label source, with a
  clock-independent duration guardrail and named failure tiebreaks (ordinal-slip / board-swap /
  clock-suspect / needs-review). Deletes are void-by-flag with gap detection. Pairs left+right by the
  shared episode id.
- `ingest/qc/` — the two deterministic QC stages (open-taxonomy, config thresholds, default-ok): IMU
  motion-QC (from the IMU the camera embeds, extracted here from the front lens) + video/container-QC.
  Writes flags + reasons + a cohort-relative score into the release record. (A learned/VLM stage is a
  separate future concern.)
- `ingest/release/` — assembles + emits the release record (the `contracts/release/` shape) for
  Hermes; resolves the operational model as-of the recording time; freezes the join.
- `ingest/orchestrator/` — the parallel, idempotent runner (one worker per card-dump; per-dump
  done-markers; hardlinks, never copies; the staging-tree contract). Built for ~100 kits/hr; the IMU
  extraction is the throughput knob.

**Boundary (fed, not owned):** the heavy downstream cleaning/render — audio cross-correlation sync,
IMU start-trim, de-fisheye back-only render, dataset assembly — is NOT here. Eunomia FEEDS it; it
lives on the Hermes side (on Hades, where the compute is). The audio-sync core is shared code, not
duplicated. The integration map of where each downstream piece lives today is in the platform
contract (the cleaning-boundary decision), flagged for the Hermes handoff. IMU *extraction* stays
here (it is the QC + trim input); the front lens is dropped from the training output after extraction.

---

## `edge/` — the on-site operational store + sync (Python service, runs on-site)

The small operational-metadata store the **ground teams read/write live**. Tiny (kilobytes/episode),
**topology-agnostic (Postgres via DSN); authoritative-location TBD pending the infra team** (Run S1).

- `edge/store/` — the operational store (persists the `contracts/operational/` model as current-state
  records + an append-only event log). The consoles write through this; it's the live system of record
  on the ground.
- `edge/sync/` — periodic replication of the metadata to a Hades backup (an intentional design when
  we build it: cadence, conflict policy, edge-authoritative confirmation). Footage does NOT go here —
  footage takes the separate drain→ship path. This syncs only the small metadata.
- `edge/api/` — a stable internal API the consoles call (so a console never touches the store
  directly — the process/logic lives here behind an interface; change a *process* → change here, not
  the UIs).

Boundary note: `edge/` and Hermes both implement a store, but for different masters — `edge/` is the
live on-site store; Hermes (separate repo) is the analytical system-of-record that ingests the same
contract. They share the contract, not code.

---

## `consoles/` — the operator/supervisor/HQ UIs (web stack; each an island)

Each console is an independent app that talks ONLY to `edge/api/` and knows ONLY the contract.
Changing or replacing one touches nothing else.

- `consoles/site-setup/` — HQ: site WiFi + telemetry endpoint + task-menu (the config the fob pulls).
- `consoles/provisioning/` — bench flash/assign UI; calls the `camera-image` core; captures the
  provisioning facts (serial, MAC, AP/WiFi, IP scheme, kit/side, fob id, firmware versions,
  calibration ref) against the unit; runs the per-kit ship-gate (isolation locked + identity set +
  firmware match) before a kit can ship.
- `consoles/inventory/` — receiving (receipt capture), box-scan, periodic count.
- `consoles/workforce/` — onboarding, qualify, offboard, observations, **fault-logging** (where a
  faulted unit's failure mode is captured).
- `consoles/gods-view/` — the live ops dashboard (consumes `contracts/events/`). Exception-first
  (healthy operators stay quiet; problems surface) — not live video, which doesn't scale to ~32 wrist
  cameras per lead. Shows recording/connected/flagged-rate/battery/SD + the help-call inbox.

A shared `consoles/_shared/` (common components + the contract-typed client) so the apps don't
reinvent it — but they remain separately deployable islands.

---

## `substrate/` — the ported host substrate (runs the on-site box; interface frozen)

The immovable host layer the on-site ingest box needs — ZFS pool, the multi-slot card-reader
port-mapping, the udev plumbing, the systemd units, the install scripts. **Ported into this repo so
there is no separate-repo tracking, but its shape/config/layout is FROZEN to match what the on-site
operator already deploys** — a setup done from the existing folder stays valid; Eunomia contains the
substrate definition but does not change it. Any real substrate change is deliberate + communicated,
never a surprise that breaks a running box. The drain/route/wipe *behavior* is Eunomia's (it lives in
`ingest/` + a drain module); the substrate is just the host floor it runs on, exposed through a frozen
interface.

---

## `tooling/` — engineering tooling (Python)

- `tooling/bench-harness/` — runs the gates against a rig. **Two layers**: a thin real serial/telnet
  IO shell + a hardware-free core that replays recorded logs (so it's testable and CI-able with no
  rig). Built early; the first thing run against the proven firmware for the load-test verdict.

---

## `docs/` — design + conventions (mirrors the Hermes doc system, scaled down)

- A lean root agent guide (root-only — no per-module ones for a project this size), the build plan
  (the phase sequence + current scope), the system spec, **the platform contract** (the data-model
  authority), the bench test plan, the contributing guide, an architecture decision record, and the
  decision register (decisions + open questions).

---

## The build order (dependency-driven; parallel only where truly independent)

1. **Foundation** (serial, alone): repo skeleton + frozen `contracts/` + conventions + the
   architecture decision record + per-language gates + the ported substrate (adopting the existing
   config as-is). This is the spine everything else builds on.
2. **Bench harness** (after Foundation) → run the load-test gate against the proven firmware for the
   hardware verdict.
3. **Coordinator firmware** and **camera-image** in parallel (independent; separate worktrees), the
   coordinator proceeding with the SoftAP verdict known. (The camera-image needs the existing recipe.)
4. **ingest / edge / consoles** — built after the capture edge is proven (their own phases; the
   consoles can parallelize among themselves since each is an island). Revisit this map after Foundation.

---

## Open questions to resolve (flagged, not decided)

1. **Web stack choice** for the consoles (and whether the gods-view, which is more real-time, shares
   it or differs). Affects `consoles/_shared/`.
2. **edge/sync replication policy** — cadence, conflict resolution, edge-authoritative confirmation,
   the Hades backup shape. (Be intentional when we get there.)
3. **How Hermes consumes the contract** — published package vs git submodule vs vendored-with-
   version-stamp. (Versioning discipline is locked; the mechanism isn't.)
4. **The exact ingest↔downstream-cleaning seam on the Hermes side** — what Eunomia hands over and in
   what form (the release record + footage references is the handoff; the precise interface is part
   of the Hermes handoff, with the integration map already in the contract).
5. **Console auth/access + secrets/PII handling** — deferred to the console design.
