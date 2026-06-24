# Eunomia — UMI Capture System Specification & Lifecycle

**Status:** working draft, folded to the Eunomia unification (2026-06-23). The WiFi-OSC architecture
this describes is **proven end-to-end on the rig** (Victor, 2026-06-23) — it is the BUILD TARGET, not
a proposal. Mexico runs the BLE fob TODAY; this WiFi-OSC design is what we are building (the BLE
specifics are current-state reference, not what Eunomia reproduces).

**What Eunomia is:** the clean, unified replacement for the whole on-site capture + ingest + identity
+ QC + ops level — the convergence of Victor's Layer 0 (`data`/Styx) and Eric's Layer 1/2
(`x3-capture-kit/pipeline`) plus the flows + consoles here, into one coherent system. Their battle-
hardened code is the SURVEY/learnings layer (copy where clean, re-architect otherwise, keep the
hard-won constraints). Eunomia sits on the immovable Styx host substrate (ported into the repo,
interface frozen) and produces the release metadata the **Hermes** analytical platform (separate
repo, on Hades) consumes. Eunomia FEEDS the downstream cleaning/render layer (audio-sync, trim,
de-fisheye render) — that layer is Hermes-side, not part of Eunomia (see the contract's the cleaning-boundary decision).

**Scope:** the complete lifecycle of bimanual UMI data collection — hardware procurement and
provisioning, operator onboarding, capture, drain, ingest, edge cases, offboarding.

**Data-model authority:** `x3_platform_contract.md` is the authoritative, versioned definition of
the sidecar, the operational model, the release metadata, and the two-axis versioning. §3 of THIS
document gives the rationale and points at the contract for field-level detail — **where this spec
and the contract disagree on the data model, the contract wins.** Decisions live in
`x3_decision_register.md`.

**Companion:** `x3_capture_system_flows.html` — a single interactive file with two synced views
(FLOWS and IPO graph). Every flow ID here (e.g. `F-CAP-03`) corresponds to a highlightable flow.

---

## 0. Reading guide

This document is the long-form lifecycle source of truth. It is organized as:

- **§1 Architecture** — the physical system and the one idea that shapes everything (the label rides
  on the card), plus the unification framing (Eunomia replaces Layer 0/1/2).
- **§2 Hardware** — the fob, the cameras, the (planned) RTC, and why.
- **§3 The data model** — RATIONALE only; `x3_platform_contract.md` is the authoritative definition
  of the sidecar, the operational model, the release metadata, and versioning. Where they disagree,
  the contract wins.
- **§4 Flows** — the full lifecycle, each step tagged with a flow ID synced to the HTML.
- **§5 Edge cases** — the failure register, each tagged.
- **§6 Open items** — decisions deliberately deferred (and now-resolved ones marked).
- **§7 Bench status** — what the proven WiFi-OSC rig has settled + the gates left before fleet buy.

A note on conventions: **flow IDs** are stable identifiers (`F-<area>-<n>`). Areas, in pipeline order, are `SRC` (raw sources), `PROV` (provisioning/inventory), `ONB` (operator onboarding), `CAP` (capture), `DRN` (drain at Styx), `SHIP` (raw transfer Styx→Hades), `PROC` (post-processing on Hades), `ING` (ingest into Hermes), `OPS` (god's-view/telemetry), `OFF` (offboarding), plus `EDGE` (edge cases). The same IDs appear as clickable, highlightable elements in the flows view and as nodes/edges in the IPO graph.

---

## 1. Architecture

### 1.1 The system in one paragraph

Each **kit** is two Insta360 X3 cameras (one filming the left arm, one the right) plus a **fob** — an ESP32-2432S028R touchscreen microcontroller. The cameras run custom firmware exposing a telnet root shell and the native OSC HTTP API. One camera (or the fob) hosts a 2.4 GHz WiFi network; the other camera and the fob join it. To record an episode, the operator presses START on the fob; the fob fires OSC `startCapture` at both cameras near-simultaneously, and on STOP fires `stopCapture`, reads back each clip's filename, and **writes a small JSON sidecar onto each camera's SD card, in the same folder as the clip it just recorded.** Footage never leaves the SD card over the network — the cards are physically drained at an on-site box (**Styx**, in Mexico), which verifies and mirrors the card contents (including the sidecars) into a clean raw pool. That raw pool is then transferred wholesale to **Hades** (the big compute server in SF), where **post-processing** runs — pairing the two arms by `episode_id`, audio-cross-correlation sync, quality checks, and derived artifacts — after which the **Hermes** data platform, also on Hades, ingests from the Hades-local pool. A near-real-time operational dashboard (**god's-view**) is fed by tiny event pings the fob emits between takes. The governing principle for *where* work runs: **raw stays where it lands and compute happens on Hades** — Styx is a dumb, reliable drain; everything derived is produced on the box we control in SF.

### 1.2 The one idea: the label rides on the card

The single most important property of this architecture, and the thing that distinguishes it from every earlier design: **the metadata that identifies an episode is written onto the SD card next to the footage, at capture time, by the fob, over telnet.**

Everything follows from this:

- **The label is primary; the order-join is the robustness fallback (not the primary path).**
  Earlier designs recorded the label on a separate channel (a coordinator-side manifest, or a token
  muxed into the video) and had to *reconcile* two asynchronous streams after the fact. In the
  WiFi-OSC target that reconciliation is no longer the primary mechanism — the label is physically
  co-located with the footage, written at capture, so the clip and its identity arrive together. The
  dual-signal order-join (§1.7, and the contract's §3.6) is KEPT as the robustness fallback (and is
  the primary path for any BLE/legacy data that lacked the live write), but in normal WiFi-OSC
  operation the label rides on the card and the join only repairs edges (delete/void, a missed
  write, a phantom press).
- **The two arms self-pair.** Both cameras' sidecars carry the same fob-minted `episode_id`. Left and right are paired by that shared key — not by timing, not by a manifest. (Earlier the schema had no shared key and a coordinator manifest was load-bearing for pairing; it no longer is.)
- **The video file is never modified.** The `.insv`/`.mp4` is a clean Insta360 file with its gyro/FlowState trailer intact. The label is a *companion* file, not a mutation. (This is why ingest must never re-encode with ffmpeg — see §3.6 and `EDGE` register.)
- **Identity survives loss of the network and loss of the fob.** Because the label is on the card, a fob that dies after a take is recorded does not orphan that footage — the sidecar is already written. The god's-view may not *hear* about it live, but the data is intact.

### 1.3 What the network is and is not for

The WiFi network exists for jobs between the fob and the cameras. The fob hosts a 2.4 GHz SoftAP (e.g. `PANTHEON-kit_<N>`, `192.168.42.1`, DHCP `.2–.6`); both cameras join it as stations. On that network:

1. **Presence — at L2 only.** The fob knows which cameras are present by reading its **own AP's association / DHCP table** (which stations are joined), *not* by asking the cameras anything. This is free and continuous and touches no camera service.
2. **Trigger — OSC, at trigger time only.** On START the fob sends `camera.startCapture` to each
   camera directly (NO per-take arm — discardd holds video mode, see §1.3 below); on STOP,
   `camera.stopCapture`. OSC is port 80, fire-and-forget. (discardd's periodic video-mode re-assert
   is the only other OSC, ~every 20–40s.)
3. **Read back the filename — via telnet `ls`, not OSC.** After STOP the fob recovers each clip's filename with `telnet ls -t` on the card's DCIM folder. (The OSC response body is unreliable on the X3 — see the hard rule below — so it is ignored.)
4. **Write the sidecar — telnet.** The fob opens a telnet root shell to each camera and writes the sidecar onto the card.

> **Hard rule (a fact about the X3, not a choice): exactly one serialized OSC client, no concurrent or background OSC, ever.** The X3's on-camera web server that answers OSC is single-threaded; two overlapping OSC requests crash it (and it then accepts TCP connections only to reset them, or returns the *previous* request's response). Therefore: presence is tracked at L2 (never by OSC polling); the trigger sends exactly one arm+start / one stop per camera, serialized under a mutex; and nothing — not the fob, not any on-camera supervisor, not a stray laptop on the AP — may poll OSC in the background. This single constraint shaped the whole working design; violating it is the difference between "records reliably" and "cameras mysteriously drop."

> **discardd locks video mode; the fob does NOT arm per take (X3 behavior, corrected 2026-06-23).**
> A freshly-booted camera refuses `startCapture` ("not in video mode") until video mode is set. In
> the current proven design, the on-camera **discardd** agent continuously re-asserts video mode
> (`RES_3008_1504P100`, `captureMode=video`) — so the fob fires `startCapture` DIRECTLY, with no
> per-take arm step. **Recording therefore DEPENDS on discardd running on every card.** (Earlier
> drafts had the fob send an arm before every start, from fw 3.7.0; 3.8.0+ dropped it because
> discardd holds the mode — keep the discardd-locks-mode model.) discardd's mode re-assert is the
> one allowed periodic OSC (every ~20–40s, a tuning parameter) — see the single-OSC rule above; if
> mid-take disconnects ever appear, this cadence is the first suspect.

The network is **not** a path for footage (that goes by card), and it is **not** continuously connected to anything else. The god's-view telemetry is a separate, occasional, low-priority use of the fob's single radio, strictly subordinate to the camera jobs above (§4.8, `F-OPS-*`).

### 1.4 The single-radio constraint (why telemetry is event-driven and queued)

The fob has **one** WiFi radio. While it is coordinating cameras it is on the camera network. To send a god's-view event it must briefly leave that network, reach the office/home WiFi, send, and rejoin — and rejoining is not instant (WiFi association takes hundreds of milliseconds to a couple of seconds).

This produces the **cardinal telemetry rule**, which the firmware must enforce and the bench must verify:

> **The fob never leaves the camera network while a take is open.** The radio's home state is the camera AP. Events (`started`, `stopped`, `camera_dropped`, `recording_suspect`) are *queued* and flushed only in the idle gap after a take has closed (both cameras stopped, sidecars written). Camera commands always have the radio; telemetry yields and queues; START is never blocked by a pending send.

The consequence is that the dashboard is **near-real-time, not live** — a `started` event typically arrives batched at the following STOP. This is acceptable: the god's-view answers "who is active, who is recording, who is stalled," for which state transitions at take granularity are the right resolution. What is *not* acceptable is a telemetry hop bleeding into a take and delaying a STOP — and the rule above makes that impossible by construction. (Earlier drafts incorrectly proposed sending `started` immediately at START, which would leave the fob off-network mid-take; that is explicitly wrong and is the bug this rule fixes.)

If even the post-take idle hop is judged too risky after bench testing, the zero-risk fallback is to flush events **only at sign-out / session boundaries** — no mid-session hops at all — at the cost of coarser dashboard freshness. Either way, footage and labels are on the card regardless, so telemetry behavior can never corrupt the dataset; the only thing at stake is dashboard freshness.

### 1.5 Pipeline topology — where each stage runs

The data makes one WAN hop and otherwise stays local to the box that owns its stage. The governing line is the **immutability boundary**: *raw stays where it lands; all derived work happens on Hades.*

```
  RAW SOURCES ON-SITE (Mexico) ┌──── one WAN hop ────┐ SF — Hades (big compute)
  ─────────── ──────────────── ───────────────────────
  fob UI (operator input) ┐ ┌ PROC (post-process) ┐
  UMI cameras (footage, ├─► CAPTURE ─► STYX (drain) ──── SHIP everything ─────────►─┤ · pair arms (episode_id) ├─► HERMES
    IMU, audio) │ · sidecar · verify │ · audio-sync │ (ingest,
  provisioning inputs ┘ on card (count+byte+readable) │ · QC / quality block │ on Hades)
    (serial→side, task #) (label · ledger-route │ · derived artifacts ┘
                                   meets · quarantine                            
                                   footage) = clean raw pool Hermes ingests from the
                                                                                          Hades-LOCAL pool, not Styx.
```

- **Styx (on-site):** the only work that *must* happen at the edge — get bytes off cards safely, verify the copy, route by the on-card ledger, quarantine bad cards. It produces a clean, verified raw pool and **renders nothing**. Keeping it free of derived/render work keeps the remote site reliable and easy to operate. Output contract: "these cards arrived intact and correctly attributed." *(Two non-rendering exceptions, both additive and both still "no compute": Styx (a) runs the Eunomia operational-store post-processing — identity/pairing/QC/the release record, which is metadata work, not video render — and (b) **retains a selected subset of raw episodes longer as a spot-check cache and hosts the spot-check dashboard as a view**, never a renderer — see §1.9.)*
- **SHIP (Styx → Hades):** the full raw pool (~200 GB/session) is transferred wholesale to Hades. **No Styx-side filtering for now** — everything ships; a triage/filter step on Styx can be added later to cut transfer volume (open item §6.7). This is the one WAN hop. *(Spot-check-selected episodes take a **priority lane** on this hop — fast-tracked ahead of the bulk — see §1.9.)*
- **Hades (SF):** all post-processing runs here as the `PROC` stage — pairing, audio-correlation sync, QC/quality-block computation, derived artifacts. This is "part of what we are building now," modeled as a **distinct stage between drain and ingest**, because pairing/sync/QC are pre-ingest transforms on raw, not the platform's job. **This is the single renderer** — spot-check footage is rendered here too, never re-rendered on Styx (§1.9), so there is exactly one render path and no version drift.
- **Hermes (on Hades):** the data platform ingests from the **Hades-local** pool after PROC, never across the wire from Styx. Matches the existing Option-C deploy flow (local dev → GitHub → Hades/Athena pulls).

### 1.6 Modularity — the hardware is an implementation detail behind two contracts

This document names specific hardware throughout (ESP32-2432S028R, Insta360 X3, `RES_3008_1504P100`, telnet, OSC). That is the *current* implementation, not the architecture. We will change boards and cameras as we scale, and the system must absorb that by swapping one component, not rewriting everything. **The build must therefore be written against two contracts, with the concrete hardware as a swappable driver behind each.** This is a note for the build phase, not a flow today — but it shapes how the code is structured.

**Contract A — the Coordinator.** Whatever the fob *is* (an ESP32 today, conceivably a phone or a different MCU tomorrow), it must: mint a globally-unique `episode_id`; trigger both capture devices near-simultaneously; read back each clip's identity; write the sidecar onto the capture medium; detect a capture-device drop; and flush god's-view events in the idle gap. The rest of the system depends only on those behaviors and on the sidecar contract (§3.1) — never on "it's an ESP32" or "it speaks telnet."

**Contract B — the Capture Device.** Whatever the camera *is*, the coordinator drives it through a small adapter exposing: start, stop, read-back-filename, get-state, set-profile, write-sidecar-file. Today that adapter is implemented with OSC + a telnet shell against the X3's hidcap firmware. A different camera = a different adapter implementing the same six operations. The capture *format* specifics (the `.insv`/`.mp4` extension flip, the embedded-gyro-trailer / never-ffmpeg rule, audio-as-sync-source) likewise belong to the device adapter and the PROC stage, not the pipeline.

**Where specifics are allowed to live.** Exactly one place per concern: the coordinator firmware build, the capture-device adapter, and the capture-profile registry. Site config (§2.5), the schema (§3), the drain (Styx), and the platform (Hermes) must contain **no** hardware-model assumptions. The litmus test: *swapping the board or the camera should touch the driver/adapter and the profile registry, and nothing in Styx, the schema, or Hermes.*

### 1.7 The trigger sequence, the two-write sidecar, and the ordinal-join backup

This is the heart of capture, refined against the working rig. Three things matter.

**The trigger sequence (serialized, one OSC client).** On **START** (`camStartAll`), holding the
WiFi mutex for the whole burst, one camera at a time spaced by a small gap (~150 ms): (1) telnet-
write the **identity sidecar** to the card; (2) `startCapture` **directly** — NO per-take arm, because
discardd holds the camera in video mode (see §1.3). On **STOP** (`camStopAll`): fire **both**
`stopCapture`s first (this avoids the stop-stagger artifact — see below), then per camera do the
telnet finalize: recover the clip filename via `ls -t`, confirm the clip grew, and write the
**outcome sidecar**. OSC is fire-and-forget (raw socket, send + flush + brief grace + close); the
response body is never read (the X3's OSC response is off-by-one and unreliable — §1.3). Recording
depends on discardd running on each card; if a camera is somehow not in video mode, `startCapture`
no-ops and the STOP-time clip-grew check catches it (`recording_suspect`).

> **Stop ordering (build it right):** if you instead fully finalize camera A (stop → wait → telnet) before stopping camera B, the two arms stop several seconds apart. Firing both stops first, then finalizing, keeps them tight. Starts are already tight. (A residual sub-2 s offset from the lack of genlock remains and is absorbed by audio-sync at PROC — that is normal, not a defect.)

**Two writes, two purposes (identity at START, outcome at STOP).** The identity sidecar (`episode_id`, `person_id`, `task_id`, `side`, `kit_id`, … — §3.1) is written **at START**, before the clip exists. This is deliberate and is the safer design: the moment a clip begins, its identity is already on the card, so a fob death mid-take cannot orphan an in-flight episode's identity. It also doubles as an implicit card-writable check (a failed write surfaces *before* recording). The START write describes "the assignment in effect on this card"; the **STOP** write binds it to the actual clip filename (recovered via telnet `ls`) and records the outcome (saved/discarded, timing, completeness). Pairing still keys on `episode_id`, identical on both arms.

**The ordinal-join backup (independent, self-bounding, on the fob).** Independently of the sidecars, the fob keeps a tiny append-at-START log: `episode_seq` + fob NTP wallclock + kit/fob id, a few bytes each. Downstream this provides a fail-safe pairing: the Nth fob-START matches the Nth camera episode, and a count mismatch routes to **needs-review** rather than silently mislabeling. It is the safety net for the case where a *sidecar write failed entirely*.
- **It must live on the fob, not the card** — a backup that shares the card's failure mode (a card-write failure would take out both the sidecar and the backup) is no backup. The fob is the independent medium.
- **It is a rolling ring buffer, bounded by design** — the fob keeps roughly the last **2 days** of episodes (expressed as *≥2× the expected drain cadence*, default ~2 days or a few hundred episodes, whichever bound hits first), dropping the oldest as new ones arrive. The window is sized to "how long footage sits on a card before it is drained, plus a day of cushion" — so if Hades/Hermes flags a problem the next morning, the backup is still there. Because it self-bounds, a fob that is **never** networked still never grows without limit. (If the fob *is* networked, the log may also be drained opportunistically in idle gaps for god's-view reconciliation — a bonus, not a requirement.)

### 1.8 Fob press feedback and spam-safety (why START/STOP can't be double-fired)

There is a **~3 s gap** between pressing START and recording actually beginning (the X3 re-initializes its capture pipeline on `startCapture` — a camera-side cost; the proper fix-path is a camera-side pre-arm, separate from this). On a **resistive** touchscreen an operator who can't tell whether the touch registered will **re-tap** — and a stray re-tap historically could inject a spurious toggle and corrupt a take. This is handled in two layers, and both are required:

- **The UI layer (makes it obvious + locks).** The moment a press registers — *before any OSC fires* — the button **flips visually** (an instant touch-ack), answering "did it hear me?" immediately, decoupled from the slower "did the action finish?". During the work (start→finalize) the button shows a **working** state that reads as don't-tap, and **ignores taps** (UI lockout). It settles to the recording / stopped state only when the action actually completes. Proposed presentation: a full-screen color state (idle / working / recording / locked), the take counter, a saved/discarded toast, and a haptic or audio tick on a registered press.
- **The core layer (guarantees it, regardless of input).** Even if taps get through — fast taps before lockout, queued touch events, a held or spamming press, a flaky screen — the coordinator **state machine never acts on a second trigger mid-sequence**: a START is valid **only from `idle`**; from `arming`/`starting`/`recording`/`stopping`, further inputs are dropped or coalesced, never double-fired. **Spamming the screen is harmless by design, not merely hidden by the UI.** This is the non-negotiable guarantee; the UI is the comfort on top of it.

This is enabled by the fob running its **network work on a dedicated core** so the UI never stalls while OSC is in flight (the instant touch-ack is only possible because the UI thread isn't blocked), and by writing the **durable ordinal to flash before the counter advances** so a crash/swap can't lose or reuse a number. Both layers live entirely in the coordinator's UI + core (they validate the swappable-UI seam — a different screen reimplements the UI layer against the same core guarantee). See the "impatient operator spams START" walkthrough for the step-by-step.

### 1.9 Spot-check — the fast feedback loop (and what it pins down about where work runs)

There is a **fast-feedback requirement** that sits alongside the bulk pipeline: managers in Mexico use
freshly-collected episodes to give operators feedback **the same day**, and founders/people in SF want
to spot-check new data **as soon after the SD drain as possible**. The bulk path (drain → ship
everything → PROC → ingest) is the *thorough* path; spot-check is the *fast* path, and it is
deliberately a **prioritized lane through the existing pipeline plus a view**, not a second processing
stack.

The shape, and the single constraint that determines it:

- **One renderer, never two — this is the load-bearing decision.** Spot-check footage is rendered by
  the **single Hermes renderer on Hades**, the same one that produces training data. It is **not**
  re-rendered on Styx. The reason is drift: two renderers (an on-site one and the Hades one) that fall
  out of version-sync would mean a manager signs off on a render that is *not* bit-for-bit what becomes
  the training clip — a silent correctness gap, exactly the class of error this whole system is built
  to avoid. One renderer means the manager sees the canonical artifact. (This keeps the
  §3.6 / cleaning-layer boundary intact — heavy render stays Hades-side; spot-check does not fork it.)
- **The priority lane is the speed mechanism.** Spot-check-selected episodes are **queued first and
  greedily fast-tracked Styx→Hades ahead of the bulk drain**, rendered by Hermes, and surfaced to the
  dashboard as each completes; the bulk follows. The loop is fast because it races **one** episode
  through, not the whole session.
- **Selection is both automatic and manual.** Eunomia auto-flags a QC sample (everything that lands
  `needs_review`, plus a random N% of clean episodes) and retains it; and a manager/founder can
  **manually pull** recent episodes by kit/operator/task from whatever is still present.
- **The dashboard already exists in prototype — Eunomia builds on it.** Victor's `umi-qa` (a FastAPI
  QA dashboard on port `:8090`) already does the spot-check job: it **samples** both ways (random
  auto-sample *and* filter by date/operator/episode/camera — the manual pull), **transcodes clips on
  demand into a bounded cache** (`/tmp`, 20 GB cap, 24h TTL — i.e. render-to-cache-then-flush, the same
  retention pattern one hop earlier), runs **automated QA** (health/detection/trajectory), and carries
  a full **human-review loop** (feedback, flagging, a review queue, and **per-operator scorecards** —
  exactly the manager-gives-operators-feedback workflow). It is **Tailscale-gated** (binds behind the
  tailnet, no port-forward) and reads footage from **Pluto** — the smaller R730 storage box in the SF
  office (NOT Hades; the prototype reads office-trial footage where it currently sits). So the as-built
  is the *steady-state* spot-check pattern: it runs against already-landed footage, reachable
  identically from Mexico and SF over the tailnet. In the Eunomia topology the canonical render lives
  on **Hades** (the ~2.4 PB datacenter tier); the dashboard prefers that and falls back to Styx-raw for
  the fresh window. Eunomia adopts this proven model rather than reinventing it.
- **What Eunomia adds is the fresh-window fast path.** The dashboard is **tailnet-reachable from
  anywhere** (Mexico + SF) and reads the **Hades** render in steady state — it does *not* need to
  physically run on Styx ("hosted in Mexico" really means "reachable fast from Mexico," which the
  tailnet already gives). The genuinely-new piece is: for an episode still in the **fresh window**
  (drained, fast-tracked, but not yet rendered on Hades), the dashboard **falls back to the raw
  footage still on Styx over the tailnet** — shrinking time-to-first-view below "wait for the normal
  drain." Steady state: prefer the Hades render. Fresh window: raw fisheye from Styx. One renderer
  (Hades) — the reviewer always eventually sees the canonical artifact, never a drifted re-render.
- **Retention + flush on Styx.** Styx is the smaller box (~360 TB) and video is heavy, so the
  spot-check raw footage is a **cache, not a home**. An episode's spot-check footage is kept on Styx
  until **(a) it is confirmed rendered on Hades AND (b) an N-day Mexico-viewing window has elapsed,
  whichever is longer**, then purged — with a **Styx space watermark** as a safety valve that flushes
  the oldest spot-check footage early if the box runs low. This is not a new mechanism: the
  footage-reference lifecycle (`on_card → on_styx → shipped → on_hades → purged`) already models it;
  spot-check simply **delays the purge** for selected episodes. Once an episode is rendered on Hades,
  its Styx copy is pure cache and deletes with nothing lost.

**Latency is a target to be measured, not a guarantee — and with a fast uplink it is render-bound,
not transfer-bound.** End-to-end "drained → spot-check episode rendered and viewable" is the drain
(already complete at drain time) + the Styx→Hades fast-track hop + the Hermes render. Victor reports a
**100 Gb card landing at Hades soon** and a hoped-for **10–100 Gb Mexico (Styx) uplink** (timing TBD).
At those speeds the transfer nearly vanishes from the budget — a ~1.8 GB (60s) episode is ~1.5s at
10 Gb/s, ~0.15s at 100 Gb/s — so once the uplink is live the loop is gated by the **render** (tens of
seconds for a short clip on a decent box), not the network. The thing to measure first is therefore
Athena's render-vs-realtime multiple, not the link. Until the Styx uplink is ready, a slower link
makes transfer the bottleneck (≈2.4 min for a 60s episode at 100 Mbps), so **uplink readiness is the
gating dependency** for the loop being genuinely fast. Working target: **a single spot-check episode
viewable within tens of seconds once the hardware lands; measure and iterate.**

**At scale, selectivity is what keeps it fast.** A fast uplink removes the transfer bottleneck but
does *not* make "render everything fast" possible — with many hundreds of episodes per session, the
render queue behind the priority lane is the ceiling, and the spot-check *cache* (not the bulk) is what
pressures the smaller 360 TB Styx box. The loop stays fast and Styx stays bounded **only because
spot-check is a bounded sample** (the QC sample + manual pulls), never the whole session. So the sample
rate, the N-day window, and the watermark are not mere tuning at scale — they are the levers that keep
the render queue and the Styx cache bounded. Size them conservatively.

**What this pins down.** Spot-check resolves the previously-fuzzy line between the tiers: the
**operational tier (Eunomia, on Styx)** owns *selection, retention, and the dashboard-as-view*; the
**analytical tier (Hermes, on Hades)** owns *the single renderer and the system of record*. The fast
loop is a prioritized path through the one pipeline plus a viewer — it adds no rendering to the
operational tier and introduces no second copy of the render code. (Tuning left open: the sample rate
N%, the N-day window, the watermark threshold, the fast-track transport, and the dashboard's exact
placement in the admin console — all design-time, not architecture.)


---

## 2. Hardware

### 2.1 The fob — ESP32-2432S028R ("Cheap Yellow Display" / CYD)

- **Why this board:** integrated 2.8" touchscreen (all operator input — sign-in, task confirmation, START/STOP/SAVE/DISCARD — on one part, no separate buttons/screen to wire), 2.4 GHz WiFi (the band the cameras are now flashed to), native USB for flashing and for the optional wired-host telemetry path, and ~$21 at fleet quantity. Self-contained: works identically in an office and (later) at a gig worker's home, because it carries no infrastructure assumptions.
- **One radio.** This is the defining constraint (§1.4). The board cannot be on two WiFi networks at once; this is why we did not pursue a second WiFi adapter, and why god's-view is event-driven over the one radio rather than a continuous stream.
- **Limited free GPIO.** The display and touch consume most pins; the RTC runs I²C on the genuinely-free GPIOs, assigned at firmware bring-up.

### 2.2 The cameras — Insta360 X3 (hidcap firmware)

- Flashed with custom firmware (`Insta360X3FW_hidcap.bin`): stock + passwordless-root telnet on :23 + native OSC on :80. A recovery image exists; flashing cannot brick the camera (separate recovery partition); `/pref` survives flashing.
- **Flashed to 2.4 GHz.** The X3 broadcasts 5 GHz by default; we have re-flashed the fleet cameras to 2.4 GHz. This removed the band wall that previously complicated coordinator selection (no device needs a 5 GHz radio).
- **Capture format (current, hardware-confirmed):** the locked `RES_3008_1504P100` (3K/100) is the
  **2:1 dual-fisheye 360 SBS** frame — both lenses in one `VID_..._00_.insv` per camera per episode
  (LEFT half = front/selfie + the IMU stream; RIGHT half = back/workspace; the container extension
  flips between `.insv` and `.mp4` per take — both must be globbed). **Training uses the BACK/right
  half only**; the front lens is kept on-card through ingest because it carries the IMU, then dropped
  from the training output at ingest (not on-cam). One `.lrv` proxy. **Audio is present and
  load-bearing** — cross-camera fine alignment is audio cross-correlation downstream (no genlock);
  audio must stay ON (muting breaks pairing). ~200 GB raw + ~10 GB LRV per session.
- **Keep cameras awake.** An idle X3 sleeps its OSC port; auto-power-off must be set to Never (asserted/verified by the fob via OSC options — see `EDGE-SETTINGS`).

### 2.3 The RTC — DS3231 (ZS-042 module) — PLANNED, not yet present (the time-model decision)

**Current state (the time-model decision): there is NO RTC yet.** The proven WiFi-OSC rig has no RTC; the fob's **NTP
wallclock is the authoritative episode time** when the fob has a network path, and when fully offline
the fob degrades to **monotonic** time (`seq` + `uptime_ms`), with landing reconstructing absolute
time on reconnect. `time_confidence` (`ntp_synced` | `unsynced_monotonic`) records which applied. The
camera clock is NEVER used (no RTC, jumps backward — poison). This is the design's known gap: a
fully-offline fob has unreliable absolute time + a god's-view "when" that firms up on sync.

**The DS3231 is the planned hardening** that closes that gap (it is RTC-ready by design):
- **Why:** the ESP32 has no battery-backed clock, so a fob that boots offline starts at epoch zero;
  the DS3231 holds accurate time (temperature-compensated, ~±2 ppm) across reboots/offline gaps,
  re-disciplined by NTP when networked. (DS1307 rejected — drifts, 5 V-fussy.)
- **Connection on the CYD:** I²C on spare GPIOs; the ZS-042 ships pre-soldered (four F-F jumpers).
- **Not load-bearing even when added.** It would not be used for cross-camera sync (audio does that)
  or L/R pairing (`episode_id` does that) — only to give offline episodes a reliable absolute
  timestamp + clean drain date-partitioning. Adding it flips `time_confidence` from
  `unsynced_monotonic` to a real clock without any schema change (the contract is RTC-ready).

### 2.4 Time-source summary

| Need | Source | Load-bearing? |
|---|---|---|
| Cross-camera fine sync | Audio cross-correlation (downstream cleaning stage) | Yes |
| Left/right arm pairing | `episode_id` (fob-minted UUIDv4) | Yes |
| Episode timestamp (authoritative) | **fob NTP wallclock** when networked; **monotonic** (`seq`+`uptime_ms`) when offline; absolute time reconstructed on reconnect | Yes (it IS `recorded_at`) |
| Episode timestamp when fully offline | monotonic; firms up on sync (`time_confidence`); DS3231 closes this gap when added | Known gap (the time-model decision) |
| Camera clock | NEVER used (no RTC, jumps backward — poison) | — |
| Drain date-partitioning | fob wallclock (DS3231 when added) | No |

Note: `recorded_at` is the fob NTP wallclock — authoritative, unlike the earlier framing that treated
the episode timestamp as mere provenance. (The camera clock is the provenance-only field.)

### 2.5 Site configuration & secrets (what can't be flashed in)

Some things a fob needs are **per-site, secret, or change over time**, so they cannot be baked into the firmware image at provisioning. These are managed as **Site Setup**, a one-time-per-site, high-trust step owned by HQ / the overall site manager (not the floor supervisor or operator).

- **What it holds:** the site Wi-Fi SSID **and password**; the god's-view telemetry endpoint (URL); `site_id`; time zone; and the **task menu** for the site (the number→name list the fob echoes back). As we scale, this is the natural "bring a new site online" surface.
- **Why a fob needs Wi-Fi at all — and the critical scoping:** the boards do **not** have a general live uplink to the server. The site Wi-Fi exists for exactly one purpose: so the fob can **flush god's-view events in the post-take idle gaps** (§1.4). It is telemetry plumbing only. The radio's home is the camera network during a take; it never holds site Wi-Fi while recording. Site config must be framed this way or it will wrongly imply a live data path that would jeopardize capture timing.
- **How it reaches the fob:** HQ enters and versions the config in a console; the fob pulls the current version on an idle-gap check-in. A spare fob brought in to replace a dead one therefore already has the site config (this is why the fob-death recovery is fast — see the fob-death flow).
- **Secrets handling (build note):** the Wi-Fi password and endpoint are secrets. They are entered once at HQ, transmitted to the fob over a trusted channel, and stored on the device — not printed, not in the sidecar, not in the schema. This is part of the "configuration & secrets" surface that, like the hardware drivers (§1.6), must not leak into Styx, the schema, or Hermes.

---

## 3. The data model

> **This section gives the RATIONALE; `x3_platform_contract.md` is the AUTHORITY.** The contract is
> the versioned, first-principles definition of the on-card sidecar (`eunomia-sidecar`), the
> event-sourced operational model, the release metadata Hermes ingests, and the two-axis versioning.
> This section explains *why* the model is shaped the way it is and how it threads through the
> lifecycle; for field-level detail, defer to the contract. **Where the two disagree, the contract
> wins.** The governing principle is unchanged: *put on the card only what must travel with the
> footage; everything else joins later by a key the card already carries.*

### 3.1 Tier 1 — the on-card sidecar (see contract §2)

Written by the fob to each camera's SD card, in the same folder as the clip. It lands in **two
writes** (§1.7): the **identity** fields at **START** (before the clip exists — so identity is on the
card the instant recording begins, and a fob death mid-take cannot orphan an in-flight episode), and
the **outcome** fields at **STOP** (binding to the actual clip filename recovered via telnet `ls`,
plus how the take ended). Once written, fields are immutable except the in-place status flags set
over telnet before drain (`archive`/`incomplete`/`recording_suspect`).

**The field model is defined authoritatively in contract §2.2.** Key points the lifecycle here
depends on:
- **Hard-required identity** (corruption = unsafe to ingest): `camera_id`, `kit_id`, `side`,
  `operator_id`, `station_id`, `task_id`, `task_name`, `session_id`, `episode_id`, `rotation_id`,
  `prompt`, `task_source`. **The ONLY hard-NON-EMPTY fields are `kit_id` + `side`** (they decide
  canonical naming + L/R pairing); everything else may be present-but-empty.
- **`episode_id`** = the fob-minted **UUIDv4** pairing key (the episode-id decision), written identically to both
  arms; **`display_id`** = the derived human-readable `<YYYYMMDD>_<operator>_<station>_<NNNNNN>`
  composite (never a join key); **`bimanual_episode_id`** = the fob-injected shared L/R id (pairs the
  two wrist cams of ONE take).
- **`recording_suspect`** (our net-new flag) = the STOP-time clip-grew check failed (the no-SD trap:
  a start can pass every check and save nothing); **`archive`** = DESCARTAR soft-discard (void+keep);
  **`stop_reason`** = why the take ended (incl. `overheat`).
- **Two-axis versioning** (contract §5): `schema` (string, additive semver — tells a parser which
  fields to expect) is ORTHOGONAL to `record_format_version` (writer-owned int — tells a forensic
  query which capture BUILD produced the episode, so a bad build is excluded by query, not backfill).
  *(This replaces the earlier single `landing_schema_version` field.)*
- **Ordering:** `global_episode_seq` (NAND, swap-proof, the PRIMARY ordering spine — the card is NOT
  a unit) is distinct from the fob `episode_ordinal` (the label source). Two ordinals, two roles.
- **Provenance / capture-stack** (contract §2.2, = the capture-stack-provenance decision): `camera_firmware`, `fob_id`, `fob_build`,
  `kit_version`, `site_id`, `modality` (`umi`|`teleop`) — the forensic identity of the producing build.

**Design notes (the rationale, kept):**
- Cost, batch, hardware version, operator history, task attributes, and quality results are
  **deliberately absent** from the sidecar — they join later through `camera_id`/`fob_id`/
  `person_id`/`task_id`/`episode_id`. This keeps the on-card write small and robust (every field is a
  chance for the telnet write to fail) and lets upstream facts (e.g. a batch's cost) be filled in
  *after* capture without touching the episode record.
- `archive`, `incomplete`, `recording_suspect` are the only fields mutated after first write, and
  only in place on the card before drain.
- **Filename binding:** the clip pointer (`files.back`) is filled at STOP from the telnet `ls -t`
  read, not the OSC response (unreliable — §1.3). The identity write at START precedes the clip's
  existence, so it describes the assignment in force; STOP binds it to the concrete file. Both the
  `.insv` and `.mp4` extensions are globbed (the X3 flips the container per take — `EDGE-EXTFLIP`).
- **Audio stays ON, both lenses kept through capture.** The sidecar's `record_settings` always
  reflects audio-on (audio is the cross-cam sync source — muting breaks pairing) and the locked
  3K/100 SBS mode; the front lens carries the IMU and is kept on-card (dropped from the *training
  output* at ingest, not on-cam — see contract §4.2 / hardware findings).

### 3.2 Tier 2 — the operational store (queryable model; see contract §3)

The entities below live in the operational store on Styx (edge-authoritative, survives WAN outage),
joined to episodes at ingest. They are what make the system *queryable* — the sidecar identifies an
episode; these entities describe everything *about* the people, hardware, tasks, and campaigns an
episode references. **Contract §3 is the authoritative model; two properties from it shape everything
below:**

- **Event-sourced (the event-sourcing decision).** The store is append-only events (person hired, unit provisioned, unit
  assigned to kit, calibration recorded, task added, session opened…) with materialized current-state
  views, and **episode references resolve as-of `recorded_at`** — so an episode recorded last Tuesday
  resolves against the identity/binding that was true *then*, not today's. The entity descriptions
  below are the current-state view; each is backed by its event log.
- **Person is DECOUPLED from kit.** The current Mexico model collapses `kit == operator == rig`;
  Eunomia generalizes this to a person bound to a kit over a TIME RANGE (the current 1:1 is just the
  degenerate case). A person's history is hardware-independent. (This is the main improvement over the
  rigid current model — contract §3.1, IDENTITY_FLOW.)

The entities (full definitions in contract §3.1): **person**, **hardware_unit** (order→batch→
unit→lifecycle, the provisioning-capture requirement), **kit** (a time-bound binding of L-cam + R-cam + fob units), **calibration**
(optional, with a `scope` field so none/fleet/per-camera all fit — the calibration-as-scoped-entity decision), **task**, **session** (with
the `fob_session_id` fob-swap disambiguation key), **capture_stack** (the registered provenance entity,
the capture-stack-provenance decision), **footage_reference** (the `on_card → on_styx → shipped → on_hades → purged` lifecycle, the footage-lifecycle decision),
and **episode** (the join point). The subsections below keep the rationale for the ones that warrant it.

#### 3.2.1 Person & Session (identity, onboarding, churn)

- **Person** — `person_id`, name/handle, date_onboarded, status (`active`/`offboarded`), date_offboarded, site(s). Supports "who collected this episode" and tenure-based queries.
- **Session / Attendance** — append-only, one row per sign-in: `session_id`, `person_id`, `site_id`, `station_id`, signed_in_at, signed_out_at, `task_id` for the session (task is chosen once at sign-in — §4.3), episode counts derivable by join. This time-series is what makes **churn and throughput** queryable: episodes-in-first-week-vs-month, per-operator-per-day throughput, 30-day churn, etc. Without Session as a first-class time-series, those questions are unanswerable; with it, they fall out of joins.

#### 3.2.2 Hardware: Order → Batch → HardwareUnit → LifecycleEvent, with Kit

This spine (specced in §4.1) is what makes hardware **fully traceable and costable, including retroactively**.

- **Order** — a procurement order: `order_id`, supplier, order_date, qty_ordered, unit_cost, currency, expected_arrival, status. *One order may arrive as several batches; some units may never arrive.*
- **Batch** — a delivery/lot under an order: `batch_id`, `order_id`, arrival_date, qty_received, `hardware_version` of what actually arrived, actual landed unit_cost (if it differs from the order). **Created and cost-corrected independently and late** — this is the entity that absorbs the volatility you flagged (prices vary per order, batches arrive weeks later, some never come).
- **HardwareUnit** — a single physical body: `unit_id`, `type` (`fob`/`camera`), serial/MAC, `batch_id` (→ cost & version), `hardware_version`, `status` (see §3.3), current `kit_id`, and for cameras the assigned `side`. The sidecar's `camera_serial`/`fob_id` join here.
- **HardwareLifecycleEvent** — append-only history: `unit_id`, `from_status`, `to_status`, timestamp, reason, related refs (the `episode_id` a fault interrupted, the `kit_id` deployed to, the `unit_id` swapped with). This log is the **backward-traceable lifecycle** (§3.3).
- **Kit** — the stable logical grouping (`kit_id`) that units attach to over time. A kit persists even as the physical bodies in it are swapped (a swap links old_unit → new_unit at the kit), so kit history is continuous.

**Cost** attaches at Order/Batch and joins down to any episode via `episode → unit (serial/fob_id) → batch → cost`. Because the join is resolved at query time, an episode collected today is automatically costed once its batch's cost lands next week — the episode record never changes. This is the "link now, enrich later" property. (A `batch_id` is the granular hook; the Order layer sits above it for partial/late shipments.)

#### 3.2.3 TaskDefinition (structured task attributes)

The sidecar carries only `task_id` + `task` string. A separate **TaskDefinition** table — maintained independently and joined into the data platform on `task_id` — carries structured attributes: `category`, `bimanual` (y/n), `expected_duration`, `difficulty`, and whatever else accrues. This keeps the card lean while making tasks richly queryable ("all pouring tasks across operators," "bimanual tasks only"). New attributes are added to TaskDefinition without touching any episode.

#### 3.2.4 Quality block (extensible, to be designed — see §6)

Each episode carries a **quality block** populated at ingest. Headline filter: `is_clean_episode` (bool). Beneath it, an **extensible** set of sub-flags for specific failure modes — `paired_complete`, `side_swap` (+ confidence), `duration_ok`, `settings_drift`, `audio_sync_ok`, `backfilled`, … — modeled as an open structure so adding a new check later does **not** migrate the schema. The capture/ingest flows expose the *hook* (episodes have a quality block); the specific checks and thresholds are an open item (§6.1), deliberately not over-specified now.

### 3.3 The `status` field and lifecycle traceability

A HardwareUnit's current state is a single, **mutually-exclusive** enum — exactly one value at a time:

```
received → provisioned → deployed → faulted → retired
                ↑___________________|
              (faulted → deployed on repair)
```

- **`received`** — arrived in a batch, not yet set up.
- **`provisioned`** — flashed, serial→side/kit assigned, ready to deploy.
- **`deployed`** — in active service at a site.
- **`faulted`** — broken, awaiting repair/RMA (may return to `deployed`).
- **`retired`** — permanently pulled.

Two guarantees, by construction:

1. **No contradictory states.** Because `status` is one field holding one value, a unit can never be (e.g.) both `provisioned` and `retired`. Downstream consumers read one unambiguous value. The legal transitions are enumerated; an illegal jump (e.g. `retired → deployed`) is rejected rather than written. "Is it provisioned?" = "status is `provisioned` or later."
2. **Full backward traceability.** `status` tells you only where a unit is *now*. The append-only **HardwareLifecycleEvent** log is the complete ordered history — received in this batch on this date, provisioned then, deployed to Santa Fe, faulted mid-`episode_id` X, repaired, redeployed, retired. Current state is the latest event's `to_status`; the trail backward is the whole list. So you get both "where is it now" (one clean field) and "the entire lifecycle" (the event log).

### 3.4 Why `site_id`, `station_id`, and `task_id` are three distinct fields

They feel entangled because one number typed at a bench has been doing double duty, but they answer different questions and cannot be reconstructed from each other if merged:

- **`site_id`** — the facility (`mx_santafe_office_1`). Cross-site comparison.
- **`station_id`** — the physical bench/position within a site. "How productive is bench 3." About *where / which hardware*.
- **`task_id`** — the activity performed (pour water into cup). "How much pouring data do we have." About *what work*.

A bench may run different tasks over time, and a task may run at multiple benches; a single conflated id cannot express that. All three are cheap to carry on the sidecar and impossible to recover later if collapsed — so they are kept separate.

### 3.5 `episode_id` — UUIDv4 pairing key + a derived `display_id` (the episode-id decision)

The `episode_id` is a **UUIDv4** minted by the fob at START and stamped identically into both
cameras' sidecars — the opaque, collision-free, globally-unique PAIRING + JOIN key, and the only key
anything pairs/joins on. It is immune to a wrong/changed resolved field (operator/station can be a
mislabel) and consistent with the identity-precedence rule that identity is *resolved*, not baked
into a key. A **`display_id`** composite (`<YYYYMMDD>_<operator>_<station>_<NNNNNN>`, the as-built
structured form) is computed and stored ALONGSIDE as the human-readable debugging handle — **never a
join key**, so a wrong field in it is cosmetic, not a corrupted key. (Contract the episode-id decision; this
resolves the former open §6.5.) Ordering comes from `global_episode_seq` + `recorded_at`, never the
id — the `display_id`'s date prefix is not used for ordering (that would invite camera-clock
mis-ordering).

### 3.6 Processing & ingest contract (what runs where, and what must never happen)

This is split across what Eunomia owns (ingest + identity + QC, producing the release record) and
the downstream cleaning/render layer (Hermes-side — the cleaning-boundary decision). The hard rules:

- **Eunomia owns ingest + identity + QC and EMITS the release record; cleaning/render is downstream
  (Hermes-side).** At ingest Eunomia resolves identity (the precedence rule), runs QC, pairs L/R by
  `episode_id`, voids/flags, and writes the release metadata (contract §4) + the footage reference.
  The heavy cleaning/render — audio cross-correlation sync, IMU start-trim, de-fisheye back-only
  render, dataset assembly — is a DOWNSTREAM stage that Eunomia FEEDS (it lives Hermes-side on Hades,
  where the compute is). The audio-sync CORE is shared code (not duplicated). (Contract the cleaning-boundary decision
  carries the integration map of where each downstream piece lives today.)
- **QC is two deterministic stages computed at ingest, open-taxonomy.** IMU motion-QC (idle/freefall/
  too_slow/ood/tiny/shake/saturation/jerk — from the IMU the X3 embeds, extracted on the Eunomia side
  from the front lens) + video/container-QC (clip_too_short/missing_audio/dark/blank/dropped_frames/
  lr_desync). Flags are an OPEN set with config thresholds (retune per-site, no code edit); default
  is "ok"; cohort-relative flags fire only with cohort stats. A VLM stage is separate/future.
  (Contract §4.1; supersedes the under-specified "Quality block populated at PROC" framing — the
  *hook* is the same, the checks are now defined.)
- **Join happens at ingest.** The release record resolves to Person/Session, Hardware (Order→Batch→
  Unit→Lifecycle, incl. retroactive cost), Task, calibration, capture_stack, `site_id`/`station_id` —
  all as-of `recorded_at`.
- **Never re-encode with ffmpeg, at any stage.** ffmpeg strips the Insta360 gyro/FlowState trailer
  and breaks stabilization. If a tag must be baked in for a downstream tool, use exiftool on a *copy*,
  never at capture, never on the original, never on the raw pool. The raw `.insv`/`.mp4` is never
  mutated. (See `EDGE-FFMPEG`.)
- **Completeness includes the sidecar.** An episode is complete only if every expected clip has its
  matching sidecar. A clip without a sidecar, or a sidecar without its clip, is quarantined
  (`EDGE-ORPHAN`). A card Layer-0 can't route is parked WHOLE in quarantine, footage intact, and
  rescued by teaching the registry the serial — never guess L/R.
- **Raw is immutable; promotion gates on the `void` FLAG, never a directory.** Styx and SHIP copy
  bytes only; the downstream stage produces derived artifacts *alongside* raw and never mutates it.
  A clip's bytes location is independent of its void/archive state.

---

## 4. Flows (full lifecycle)

Each step carries a flow ID synced to the HTML. Within each flow the **operational** action (what a human/device does) and the **data** effect (what is created/mutated/joined underneath) are given together — this operational/data pairing is exactly what the IPO graph renders, with the data journey as the spine and the operational action as the real-world annotation on each node.

### 4.0 Raw sources — `F-SRC-*`

The true origins of both the footage and its metadata. Everything downstream is a transform on these three streams; the IPO graph begins here.

- **`F-SRC-01` UMI camera capture.** *Op:* the two X3 cameras film the bimanual task — left arm and right arm — capturing 360 video, embedded IMU, and load-bearing audio. *Data:* the raw `.insv`/`.mp4` clips (+ `.lrv` proxy) on each camera's SD card. This is the primary payload; ~200 GB raw/session.
- **`F-SRC-02` Operator input (fob UI).** *Op:* the operator interacts with the fob touchscreen — sign-in, task confirmation, START/STOP/SAVE/DISCARD. *Data:* the metadata stream — `person_id`, `task_id`, `episode_id`, timestamps, side/kit — that becomes the sidecar. Converges with `F-SRC-01` at the sidecar write (`F-CAP-08`).
- **`F-SRC-03` Provisioning inputs.** *Op:* before capture, provisioning produced the serial→side(+kit) map; a manager prints the task number at the station. *Data:* the reference inputs that let the fob label arms (`side`) and resolve the task, and that Styx uses for ledger routing. Feeds capture and drain.


The hardware spine, from purchase to retirement. This is the lifecycle that the §3.2.2 entities fall out of.

- **`F-PROV-01` Order placed.** *Op:* procurement orders N units from a supplier at a unit cost on a date. *Data:* create **Order** (`order_id`, supplier, order_date, qty, unit_cost, currency, expected_arrival, status=`open`).
- **`F-PROV-02` Shipment arrives (possibly partial / late / never).** *Op:* a delivery lands; quantity and cost may differ from the order, and may arrive weeks later. *Data:* create **Batch** (`batch_id`, `order_id`, arrival_date, qty_received, `hardware_version`, actual landed unit_cost). Order status updated (`partially_received`/`received`). Batches may be created and **cost-corrected late** — episodes referencing these units cost-resolve automatically when the cost lands.
- **`F-PROV-03` Unit intake.** *Op:* each physical body is registered. *Data:* create **HardwareUnit** (`unit_id`, `type`, serial/MAC, `batch_id`, `hardware_version`, `status=received`). Lifecycle event `→received`.
- **`F-PROV-04` Provisioning.** *Op:* flash firmware (camera: hidcap + 2.4 GHz + capture profile + auto-power-off Never; fob: coordinator firmware), assign serial→`side`+`kit_id`, register the fob. *Data:* HardwareUnit `status: received→provisioned`; the **serial→side(+kit) map** is minted (consumed later by the fob to label arms and by Styx's ledger routing). Lifecycle event `→provisioned`.
- **`F-PROV-05` Deployment.** *Op:* unit assigned to a site/kit, goes live. *Data:* HardwareUnit `status: provisioned→deployed`, `site_id`/`kit_id` set. Lifecycle event `→deployed`.
- **`F-PROV-06` Fault.** *Op:* a unit breaks (camera dies mid-take — see `F-CAP-08`/`EDGE-CAMDROP`; fob won't boot; screen cracks). *Data:* HardwareUnit `status: deployed→faulted`; lifecycle event `→faulted` with reason and the interrupted `episode_id` if any. ("Episodes lost to faults" is queryable from these.)
- **`F-PROV-07` Repair / swap.** *Op:* unit repaired and redeployed, or swapped out and a replacement deployed to the same kit. *Data:* lifecycle event `faulted→deployed` (repair) **or** a swap linking `old_unit→new_unit` at the `kit_id` (kit history stays continuous across body changes).
- **`F-PROV-08` Retirement.** *Op:* unit permanently pulled. *Data:* HardwareUnit `status: →retired`; lifecycle event `→retired` with reason. Terminal.
- **`F-PROV-09` Cost attribution (continuous / retroactive).** *Op:* none — automatic. *Data:* any episode's cost resolves by join `episode → unit (serial/fob_id) → batch → cost`. Filling in a batch's cost later retro-costs all its episodes without touching episode records.

### 4.2 Operator onboarding — `F-ONB-*`

- **`F-ONB-01` Person created.** *Op:* a new operator is enrolled at a site. *Data:* create **Person** (`person_id`, date_onboarded, status=`active`, site).
- **`F-ONB-02` Credential set.** *Op:* operator is issued an id and sets/receives a PIN. *Data:* PIN→`person_id` binding stored (the fob resolves identity from this at sign-in).
- **`F-ONB-03` First sign-in.** *Op:* operator signs in on a fob for the first time. *Data:* first **Session** row; tenure clock effectively starts (date_onboarded is the anchor for first-week/first-month queries).

### 4.3 Capture — `F-CAP-*`

The core loop. Task is chosen **once at sign-in** for the whole session; the operator re-enters only on change.

- **`F-CAP-01` Sign-in.** *Op:* operator enters their **ID**, the fob shows who it is for confirmation ("¿eres tú? Ana Ramírez"), then asks for the **PIN**. A non-existent ID or wrong PIN is rejected on the device and nothing is written (see `EDGE-BADINPUT`). *Data:* on a correct PIN, resolve `person_id` and open a **Session** (`session_id`, `person_id`, `site_id`, `station_id`, signed_in_at).
- **`F-CAP-02` Task selection (once per session).** *Op:* operator types the task number printed at the station; **the fob echoes back the task name** and asks to confirm. A number not in the site task menu is rejected (the menu is the allow-list). *Data:* `task_id` (+ `task` string, `task_menu_version`) bound to the Session. A wrong-but-valid number shows obviously-wrong words → caught here, not at ingest.
- **`F-CAP-03` Camera connectivity check.** *Op:* fob confirms both cameras are **associated to its AP** (read from the L2 station table — no OSC). START is **blocked** unless both are present. *Data:* none persisted; gates the loop. *(A non-camera device on the AP can inflate the count — `EDGE-PHANTOM`.)*
- **`F-CAP-04` START.** *Op:* operator presses START; the fob **mints a UUIDv4 `episode_id`** (+ the
  derived `display_id`) and an `episode_ordinal`, then, serialized under the WiFi mutex, per camera:
  writes the **identity sidecar** to the card, then `startCapture` **directly** (no per-take arm —
  discardd holds video mode, §1.3). **No telemetry hop — the radio stays on the camera network;
  `started` is queued (§1.4).** *Data:* `episode_id` minted; identity sidecar on both cards; ordinal
  appended to the fob's ring-buffer backup (§1.7).
- **`F-CAP-05` Recording.** *Op:* the take runs. The fob watches **L2 association only** (which stations remain joined) — it does **not** poll OSC, which would crash the cameras (§1.3). *Data:* none persisted yet. *(A camera that stays associated but silently stops recording is the L2 blind spot — caught at STOP and ingest, `EDGE-SILENT-STOP`.)*
- **`F-CAP-06` Long-recording nudge (passive).** *Op:* past a threshold the fob gives a **passive** signal (beep/LED/on-screen banner). There is **no button and recording continues** — purely informational. *Data:* none.
- **`F-CAP-07` STOP.** *Op:* operator presses STOP; the fob fires **both** `stopCapture`s first (avoids the stop-stagger), then per camera recovers the clip filename via telnet `ls -t` and **checks the clip actually grew**. *Data:* clip basenames captured; a non-growing clip sets `recording_suspect` (`EDGE-SILENT-STOP`).
- **`F-CAP-08` Outcome sidecar write.** *Op:* the fob writes the **outcome sidecar** over telnet — binding the identity (written at START) to the actual clip filename and recording how the take ended. *Data:* the on-card label is now complete; episode identity has been durable since START regardless of fob state. (The OSC response body is never used — §1.3.)
- **`F-CAP-09` Save / Discard.** *Op:* operator chooses SAVE (default) or DISCARD. *Data:* on DISCARD the fob sets `discarded:true` + `discard_reason` in the sidecar over telnet — **the clip is kept** (quarantine, not shred). On SAVE, no change. *(On-camera, a daemon consumes the sidecar env and locks record mode; our spec defines the sidecar contract, not that daemon's internals — §1.6.)*
- **`F-CAP-10` Telemetry flush (post-take idle gap).** *Op:* the take now closed and the radio free, the fob hops once to the site WiFi, flushes the queued events (`started`, `stopped`, any `camera_dropped`, any `recording_suspect`), and returns to the camera AP. If there is no idle gap (back-to-back takes), events keep queuing. *Data:* god's-view state updated near-real-time (§4.8).
- **`F-CAP-11` Next episode or session end.** *Op:* loop back to `F-CAP-04` for the next take (same task), or the operator signs out. *Data:* on sign-out, Session `signed_out_at` set; any remaining queued events flushed.

### 4.4 Drain at Styx (on-site, Mexico) — `F-DRN-*`

The cards are physically brought to the on-site drain box. Styx does only edge-mandatory work; nothing derived.

- **`F-DRN-01` Card intake.** *Op:* a card is mounted at Styx. *Data:* an import is opened.
- **`F-DRN-02` Whole-card mirror.** *Op:* Styx rsyncs the entire card (minus macOS junk) into the raw pool, preserving the DCIM/ footage **and the sidecars** verbatim, under `…/<date>/import_<id>/operator_<op>/<side>/…`. *Data:* footage + sidecars land in the pool unchanged. (exiftool-never-ffmpeg applies downstream; the drain copies bytes only.)
- **`F-DRN-03` Ledger-first routing.** *Op:* Styx reads the on-card ledger (camera/side/operator/episode records) as the authoritative routing source; the serial→side map (from `F-SRC-03`) is a **fallback** for non-kit or incomplete-ledger cards. *Data:* card content routed to the correct site/operator/kit partitions.
- **`F-DRN-04` Verify gate.** *Op:* Styx confirms the copy before releasing the card. *Data:* **branch** — pass → the clean verified raw pool; fail → quarantine (`EDGE-ORPHAN`/unreadable). The gate must be hardened to count + byte equality + per-file readability (open item §6.2); today's weaker gate is a known gap.

### 4.5 Ship raw to Hades (Styx → Hades) — `F-SHIP-*`

The single WAN hop. The immutability boundary is here: nothing has been derived yet.

- **`F-SHIP-01` Transfer raw pool.** *Op:* the clean verified raw pool is transferred wholesale from Styx (Mexico) to Hades (SF). *Data:* the full raw pool (~200 GB/session) lands in a **Hades-local raw pool**, byte-identical. **No filtering for now** — everything ships (open item §6.7 covers a future Styx-side triage to cut volume). The raw pool on Hades is the immutable input to all post-processing.

### 4.6 Post-processing on Hades (SF) — `F-PROC-*`

All derived work. This is the stage "we are building now." It sits between drain and ingest because pairing/sync/QC are pre-ingest transforms on raw, not the platform's job. Raw is never mutated — PROC produces derived artifacts alongside it.

- **`F-PROC-01` Clip discovery.** *Op:* enumerate clips in the raw pool, globbing **both** `.insv` and `.mp4` (the extension flips non-deterministically — `EDGE-EXTFLIP`). *Data:* the set of clips + their sidecars to process.
- **`F-PROC-02` Read sidecar identity.** *Op:* read each clip's sidecar. *Data:* episode identity
  established from on-card metadata (parsed per the `schema` string; capture build scoped via
  `record_format_version`).
- **`F-PROC-03` Pair arms.** *Op:* match left and right by shared `episode_id`; if a sidecar is missing entirely, fall back to the **ordinal-join** (Nth fob-START ↔ Nth episode, §1.7). *Data:* **branch** — paired episode / `paired_incomplete` (one side, `EDGE-UNPAIRED`) / `needs_review` (ordinal count mismatch) / orphan (sidecar without clip or clip without sidecar, `EDGE-ORPHAN` → quarantine).
- **`F-PROC-04` Audio-sync.** *Op:* cross-correlate the two cameras' audio to compute fine inter-arm alignment (there is no genlock; the fob clock is not used for this). *Data:* derived sync offset (`audio_lag_s`) + a confidence (`audio_score_ratio`); low confidence flags `audio_sync_ok=false`.
- **`F-PROC-05` Quality evaluation.** *Op:* run the quality checks. *Data:* populate the extensible Quality block — `is_clean_episode` + sub-flags (`paired_complete`, `side_swap`+confidence, `duration_ok`, `settings_drift`, `audio_sync_ok`, `recording_suspect` (carried from the card — `EDGE-SILENT-STOP`), `backfilled`, …). **Branch** — clean vs. flagged vs. quarantine. (Specific checks/thresholds: open item §6.1.)
- **`F-PROC-06` Derived artifacts.** *Op:* generate proxies/derived outputs as needed, alongside the untouched raw. *Data:* derived artifacts in the Hades pool; raw `.insv` unchanged (gyro/FlowState trailer intact — `EDGE-FFMPEG`).

### 4.7 Ingest into Hermes (on Hades) — `F-ING-*`

Hermes ingests from the **Hades-local** post-processed pool — never across the wire from Styx.

- **`F-ING-01` Read processed episode.** *Op:* Hermes reads the paired, synced, quality-tagged episode from the Hades pool. *Data:* episode + its derived metadata presented for ingest.
- **`F-ING-02` Join operational model.** *Op:* resolve all references. *Data:* join Person/Session (who/when/tenure), Hardware (Order→Batch→Unit→Lifecycle, incl. cost — possibly retroactively), TaskDefinition (structured task attributes), `site_id`/`station_id`.
- **`F-ING-03` Commit.** *Op:* the episode enters Hermes as an immutable record with derived metrics. *Data:* queryable episode, fully joined.
- **`F-ING-04` Backfill.** *Op:* late-arriving facts (a batch's cost, a corrected task definition, a re-run quality check) update the joined model. *Data:* **cycle** — derived/joined values refresh; the immutable raw episode is untouched. Episodes touched this way carry the `backfilled` flag.

### 4.8 God's-view / telemetry — `F-OPS-*`

Near-real-time operational visibility, fed by the queued events (§1.4). Runs in parallel with the capture→drain→proc→ingest path, not in series.

- **`F-OPS-01` Event emission.** *Op:* in a post-take idle gap, the fob flushes queued events. *Data:* `started` / `stopped` / `camera_dropped` / `recording_suspect` pings, each tiny (kit, fob, person, episode count, battery, reason).
- **`F-OPS-02` Live state.** *Op:* the dashboard reflects who is recording / idle / stalled, episode counts per operator, per-kit battery. *Data:* near-real-time operational state.
- **`F-OPS-03` Camera-drop exception (L2-detected).** *Op:* when a camera **falls off the fob's AP** mid-take (the station leaves the L2 table — power/battery/WiFi death), the fob (alive, still on the camera network) stops the survivor and marks the episode `incomplete` locally; a `camera_dropped` event is flushed at the next idle gap. *Data:* the dashboard learns of the drop; the episode is flagged incomplete on the card. (`EDGE-CAMDROP`.)
- **`F-OPS-04` Silent-stop exception (the L2 blind spot).** *Op:* a camera that **stays associated but stops recording** cannot be seen at L2 and must not be probed by OSC. It is caught at STOP by the clip-grew check (`recording_suspect` set on the card) and surfaced on god's-view; at ingest the flag routes the episode to review. *Data:* `recording_suspect` flag → dashboard + ingest review. (`EDGE-SILENT-STOP`.)
- **`F-OPS-05` Fob-death detection (server-inferred).** *Op:* a dead fob sends nothing; the server detects a stuck-"recording" or stale heartbeat past a timeout and flags the kit. *Data:* staleness flag. (The one failure not self-reported — `EDGE-FOBDEATH`.)

### 4.9 Offboarding — `F-OFF-*`

- **`F-OFF-01` Operator offboarded.** *Op:* an operator leaves. *Data:* Person `status: active→offboarded`, date_offboarded set. Historical episodes/sessions remain attributed to `person_id` (churn/tenure queries depend on this).
- **`F-OFF-02` Hardware return.** *Op:* the operator's assigned hardware is returned. *Data:* HardwareUnit lifecycle events as appropriate (back to `provisioned` for redeployment, or `faulted`/`retired`).

---

## 5. Edge-case register — `EDGE-*`

Each is a known failure mode with the designed response. All share one property: **footage and label are on the card, so no edge case below loses data** unless the card itself is lost — they affect completeness, freshness, or attribution, which are recoverable.

- **`EDGE-CAMDROP` — a camera dies / falls off WiFi mid-take.** Detected live at **L2** — the camera's station leaves the fob's AP association table (`F-CAP-05`/`F-OPS-03`). Response: fob stops the survivor (don't keep rolling a one-armed take), sets `incomplete:true`+reason in the survivor's sidecar, emits `camera_dropped`. Footage kept; quarantined at ingest as `paired_incomplete`. *(Detection is L2-only because OSC polling crashes the camera — §1.3.)*
- **`EDGE-SILENT-STOP` — a camera stops recording but stays on WiFi.** The L2 blind spot: the station is still associated, so the fob sees nothing wrong at the WiFi layer, and it must not probe OSC (which would crash the camera). Caught instead at STOP by the clip-grew check (a clip that didn't grow / is implausibly small → `recording_suspect:true` on the card, `F-CAP-07`), surfaced on god's-view (`F-OPS-04`), and routed to review at ingest via the `recording_suspect` flag. This is a fact about the X3, not a bug we can engineer away — so it is a designed-for edge case, not a defect.
- **`EDGE-PHANTOM` — a non-camera on the fob AP inflates the camera count.** Presence is L2 (anything associated to the AP counts), and there is no OSC-free way to tell a stray laptop from a camera. A debugging machine left on the kit AP shows as an extra "camera"; a powered-off camera lingers in the table until it ages out. Mitigation: keep non-cameras off the kit AP; the fob uses a short inactivity timeout + liveness so powered-off cameras drop quickly. Operationally visible on the camera-check screen.
- **`EDGE-BADINPUT` — bad ID / wrong PIN / unknown task number at the fob.** Every fob entry point validates before it commits: an ID not on the site roster, a wrong PIN (counted, with lockout after several tries), or a task number not in the site menu are all rejected on the device. **Nothing is written** — no Session row opens until a correct PIN authenticates, and only menu task_ids can reach a sidecar. The operator simply retries.
- **`EDGE-FOBDEATH` — the fob dies mid-take.** A dead fob cannot self-report. Because the **identity sidecar is written at START** (§1.7), every clip that began recording already carries its identity on the card; only the in-flight take's *outcome* write is lost. The server infers the death from a stuck-"recording"/stale heartbeat past a timeout (`F-OPS-05`). A spare fob (pre-loaded with site config) re-fixes the network; the ordinal-join backup on the dead fob is lost, but the sidecars on the cards are the primary record. The orphaned cameras (no coordinator can STOP them) are handled at next sign-in / by the operator.
- **`EDGE-FFMPEG` — re-encoding breaks stabilization.** ffmpeg strips the Insta360 gyro/FlowState trailer. Hard rule: **never ffmpeg**; exiftool only, on a copy, at ingest, never on the original (§3.6).
- **`EDGE-ORPHAN` — clip without sidecar, or sidecar without clip.** Completeness requires both. Either alone is quarantined at ingest (`F-ING-02`/`F-DRN`). Causes: telnet sidecar write failed under a WiFi dip, or a clip glob missed the flipped `.insv`/`.mp4` extension.
- **`EDGE-UNPAIRED` — only one arm present.** Pairing by `episode_id` finds one side. Marked `paired_incomplete`; not discarded (the single side may still be usable / diagnostic).
- **`EDGE-EXTFLIP` — `.insv`/`.mp4` extension flips non-deterministically.** Both extensions must be globbed at clip discovery and sidecar matching. A glob that assumes one extension silently drops clips.
- **`EDGE-SETTINGS` — settings drift / camera not in video mode.** A freshly-booted X3 refuses
  `startCapture` until video mode is set, and profile settings can drift. In the current design the
  on-camera **discardd** agent continuously re-asserts the locked profile (3K/100, FlowState off,
  audio on, both lenses) whenever the camera is idle, so the fob does NOT arm per take (§1.3). If a
  camera is somehow not in video mode at START, `startCapture` no-ops and the STOP-time clip-grew
  check flags `recording_suspect`; `record_settings` is recorded per episode and a mismatch raises a
  `settings_drift`-class quality flag at QC.
- **`EDGE-SIDESWAP` — left/right mislabeled.** The serial→side map could be wrong, or a swap mis-recorded. A `side_swap` quality check (with confidence) flags suspected swaps at ingest; the map and lifecycle swap records are the ground truth to reconcile against.
- **`EDGE-TELNETFAIL` — sidecar write fails silently.** A WiFi dip during the telnet write could leave a clip without its sidecar. Mitigations: the write is retried; ingest treats a missing sidecar as `EDGE-ORPHAN` and quarantines rather than guessing. (Whether the fob keeps a local backup manifest to reconcile such cases is an open item, §6.3.)
- **`EDGE-CLOCK` — fob clock unsynced.** There is no RTC yet (the time-model decision): the fob NTP wallclock is the
  authoritative `recorded_at` when networked, and a fully-offline fob degrades to monotonic
  (`seq`+`uptime_ms`) with absolute time reconstructed on reconnect (`time_confidence` records which).
  Impact of an offline gap is the absolute-time firmness + drain date-partitioning only — **not** sync
  (audio) or pairing (`episode_id`). Recoverable by re-derivation on sync; the planned DS3231 closes
  the gap.
- **`EDGE-NOGAP` — back-to-back takes, no idle gap.** Telemetry events queue and the dashboard goes staler during a burst. No effect on data or sync. Resolves when a gap appears or at sign-out.
- **`EDGE-DISCARD-RECOVER` — a discarded clip is wanted back.** Because DISCARD only sets `discarded:true` (clip kept), a mistaken discard is recoverable at ingest by overriding the flag. Quarantine-not-shred exists precisely for this.

---

## 6. Open items (deliberately deferred, tracked here so they are not lost)

- **§6.1 Quality checks & thresholds.** The Quality block hook exists (`is_clean_episode` + extensible sub-flags), but the specific checks, thresholds, and the side-swap/audio-sync confidence methods are not yet designed. Modeled as an open structure so adding checks does not migrate the schema. Not blocking; revisit when QC is prioritized.
- **§6.2 Styx verify gate.** The drain's success gate must be hardened from the current weak check to a count + byte equality check and per-file readability (ffprobe-class) before declaring an import good. Known gap.
- **§6.3 Fob-local backup manifest.** Whether the fob should keep a local manifest of episodes/sidecars it wrote (to reconcile silent telnet-write failures, `EDGE-TELNETFAIL`) is undecided. Trade-off: extra robustness vs. more on-fob state.
- **§6.4 Procurement layer depth.** We model Order → Batch. Whether a higher layer (e.g. a multi-order procurement program) is needed is deferred; `batch_id` is the granular hook and Order covers partial/late shipments for now.
- **§6.5 `episode_id` construction — RESOLVED (the episode-id decision, A′).** `episode_id` = a UUIDv4 (the
  opaque pairing/join key) + a derived `display_id` composite stored alongside (the human handle,
  never a key). See §3.5 / contract the episode-id decision. No longer open.
- **§6.6 Telemetry freshness floor.** Default is post-take idle-gap flush; if the bench shows any sync risk, fall back to session-boundary-only flush. The choice is pending the bench result.
- **§6.7 Styx-side triage / pre-ship filtering.** For now the full raw pool ships from Styx to Hades unfiltered (`F-SHIP-01`). A future cheap triage on Styx (drop discarded clips / obvious orphans before the WAN hop) would cut transfer volume from Mexico, at the cost of a little more logic on the drain box. Deferred until transfer volume justifies it.
- **§6.8 Zero-touch camera provisioning.** Today a camera's fob assignment is written by hand at the bench (a per-camera config naming its kit/fob). The plan is to **derive it from the `kit_id` already burned during normal provisioning**, so a camera self-joins the right kit with no hand-step. The provisioning flow shows the zero-touch path as the design; the hand-write is the current-state fallback until the kit_id-derivation is wired.

---

## 7. Bench status (what Victor's working rig has proven, and what's left)

The WiFi-OSC system is **proven end-to-end on the rig** (Victor, 2026-06-23): the fob hosts the AP,
both cameras join, one GRABAR records both over OSC, discardd stamps a per-clip sidecar at capture,
clean DETENER, DESCARTAR (void+keep) works. The hard-won facts are folded into §1.3 and §1.7. The
reference fob source (`ble_bridge/esp32-fob-wifi/src/main.cpp`, fw 3.8.3) is what the clean Eunomia
fob build ports — keeping the constraints, not the battle-scar code (§1.6).

**Proven (treat as settled):**
- **`GATE-AP-JOIN` ✅** — X3s reliably STA-join the fob's own 2.4 GHz SoftAP and serve OSC + the
  telnet sidecar write.
- **`GATE-OSC-SERIAL` ✅** — the load-bearing rule: the X3's OSC server is single-threaded and **must**
  see exactly one serialized OSC client with no background polling; presence is tracked at L2. Now an
  architectural rule (§1.3), not an experiment.
- **`GATE-DISCARDD-MODE` ✅** — discardd locks video mode; the fob fires `startCapture` directly, NO
  per-take arm (§1.3). **This VOIDS the former `GATE-ARM`** (which had the fob arm before each start —
  that was the 3.7.0 model; 3.8.0+ dropped it).
- **`GATE-LIVE-LABEL` ✅** — discardd stamps a per-clip `VID_<ts>_<seq>.pantheon.json` sidecar at
  capture (the label rides on the card live); enables collect-anywhere. The order-join is the fallback.
- **Recording truth ✅** — clip-count / file-growth over telnet is the trustworthy "did it record"
  signal; the camera clock is not.

**Still to verify before fleet buy** — these merge our bench gates with Eric/Victor's hardware-
verification gate (the on-cam assumptions not yet hardware-confirmed):
1. **`GATE-LOAD`** — the board holds WiFi under sustained load (trigger + two-write sidecar +
   occasional telemetry) across a full shift without choking. (ESP32 SoftAP is marginal; low camera
   batteries cause drops — quantify the margin.) This is the GATE-LOAD verdict-vs-Victor's-binary step.
2. **`GATE-THERMAL`** — a 2-hr continuous 3K/100 take survives without hitting `TEMP_HIGH_SHUTDOWN`
   (the cam auto-stops at thermal limit — a real `stop_reason=overheat` source). Confirmed-readable
   via OSC temp keys.
3. **`GATE-FILE-SPLIT`** — does the firmware auto-segment a long (2-hr) take into multiple files? If
   so the camera episode count inflates vs fob starts and the count-reconcile must account for it.
   **Flagged as the most likely desync source for this workload.**
4. **`GATE-ORDER`** — the cardinal telemetry rule holds: with idle-gap telemetry on, START
   simultaneity and STOP latency are identical to telemetry off, including back-to-back takes.
5. **`GATE-STOP-TIGHT`** — the corrected stop sequence (fire both `stopCapture`s first, then finalize)
   brings the two arms' stop times close; the residual offset is within what audio-sync absorbs.
6. **`GATE-SILENT-STOP`** — the STOP-time clip-grew check catches a camera that stopped recording
   while staying associated (`EDGE-SILENT-STOP` / the no-SD trap → `recording_suspect`).
7. **`GATE-NAND-SEQ`** — NAND `global_episode_seq` is monotonic across SD/battery swaps (the ordering
   spine; the card is not a unit).
8. **`GATE-IAQEB`** — the `IAQEB…` serial is reliably present in every `.insv` (the crosswalk key).
9. **`GATE-INSTANT-DELETE`** — DESCARTAR instant-delete actually removes the take on-card (a card-space
   optimization; void-by-flag is the correctness path regardless).

Plus the deploy gates (from the Mexico runbook, for the provisioning console): per-cam identity +
discardd running (Gate 1); fob isolation `allow_n>=2` + foreign-camera-rejected (Gate 2); one
end-to-end paired+labeled+3K/100+FlowState-off capture (Gate 3); dashboard-live (Gate 4); 50-fob
cross-talk (Gate 5, before scale). The `ship_gate` (allow_n==2 + kit set + fw match + NTP) blocks any
un-isolated fob from shipping.

Once `GATE-LOAD` + the hardware-verification gates pass, the fleet build is unblocked. (Full gate
detail: `x3_bench_test_plan.md`, which the hardware-verification gate is being merged into.)
