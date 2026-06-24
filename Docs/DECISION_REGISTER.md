# X3 Capture — Decision Register & Learnings

> **Platform name: Eunomia.** This capture-program platform is called **Eunomia** (the on-site
> operational store + consoles + the capture contract). It is distinct from **Hermes** (the
> analytical data platform / system-of-record on Hades that ingests Eunomia's contract). Where
> earlier notes say "the edge store" or "this repo," read Eunomia.

A running log of decisions, the reasoning behind them, and open questions. Modeled on the
Hermes Register: this is the single source of truth for *why* things are the way they are.
When a decision here is folded into the spec / schema / ADR, it's tagged [FOLDED] with the
target doc. Until then it lives here as the authority.

Format per entry: **ID · title** — decision, why, alternatives rejected, status.

---

## ✅ UNIFICATION MANDATE (Eunomia replaces Layer 0/1/2 with one clean version)

**D-11 · Trigger generation — RESOLVED (the BLE-vs-OSC confusion, settled).** Two generations
exist: (1) **BLE fob = what Mexico runs TODAY** (current production; Eric's operator-from-fob-log,
the `legacy/` tablet/Pi labeling, BLE re-pair-on-swap were written against this). (2) **WiFi-OSC
= what we SPECced and are BUILDING** (fob hosts the 2.4 GHz AP, serialized OSC, telnet sidecar —
our clean coordinator). The repo calling "WiFi-OSC legacy" refers to their OLD tablet/Pi WiFi
path, a DIFFERENT implementation than our clean one — our spec is the NEW WiFi-OSC coordinator,
forward-looking, not a revival. Implication for mining their code:
  • **Modality-independent learnings PORT FORWARD**: identity crosswalk (IAQEB↔body serial),
    the dual-signal join, pairing/void, QC, the metadata schema, block-level labeling, the
    file-splitting risk, deletes-as-void-by-flag.
  • **BLE-transport-specific bits** (BLE pairing, fob-log as the ONLY operator source, BLE
    re-pair) are current-Mexico reference, NOT what Eunomia's coordinator implements.
  • **MIGRATION REALITY (flagged, not silent):** Mexico runs BLE today; Eunomia builds WiFi-OSC.
    So either Mexico switches to WiFi-OSC fobs when Eunomia ships, or the coordinator supports both
    transports for a transition. Real question for later; affects rollout. Status: locked.

**D-12 · Substrate: PORT into Eunomia without forcing Sean to redo setup.** Goal: one repo (no
separate-repo tracking). Constraint: Sean must not redo server setup if the Mexico box arrives
before Eunomia is done. Resolution — separate "setup CONFIG" from "setup EXECUTION," port both in,
keep the interface identical:
  • Port the Styx substrate (the machine-specific calibrated config — Sipolar bank/physical maps,
    ZFS pool name, host facts — AND the install scripts/udev/systemd) INTO Eunomia.
  • Eunomia ADOPTS the existing Styx config files as-is (same paths, same ZFS/Sipolar/mkfs
    contracts); its installer is a SUPERSET that is **idempotent** — if the substrate is already
    set up (Sean ran the `styx/` install), Eunomia detects it and does NOT redo it, only layers the
    unified software on top.
  • Eunomia honors the EXACT substrate interface the current `styx/` scripts use (`/mnt/robot-pool/
    umi`, the Sipolar resolution algorithm, the udev trigger, status-file locations) — so its
    ingest drops onto a Sean-prepared box with zero re-setup, regardless of how setup was done.
  • Do NOT change the substrate's interface or config FORMAT (that's what protects Sean); absorbing
    it is safe, improving it later is a deliberate coordinated change.
  • The earlier "substrate-interface doc" becomes a **substrate-ADOPTION spec**: what the host
    provides, the config Eunomia inherits unchanged, how the install is idempotent over a
    set-up box. This unblocks Sean to deploy anytime + lets Eunomia slot in. Status: locked.

**Decided with Victor + Eric:** Eunomia is the **clean, unified replacement** for the whole
capture/ingest/identity/QC/ops level — NOT a layer that fits beside their existing code. The
current 3-layer split (Victor's Layer 0 in `data`, Eric's Layer 1/2 in `x3_root`) is
battle-hardened code that solved real bugs but is spread over many messy files. Eunomia converges
all of it — PLUS the flows + consoles we've specced — into one coherent, well-architected system.

**How to treat their existing code:**
- It is **reference for patterns + learnings** (each fix solved a real bug — honor the lesson).
- Where a piece is **already clean + optimized → use/copy it** directly.
- Otherwise → **re-architect cleanly** in Eunomia, keeping the hard-won constraints, dropping the
  file-sprawl. (Same philosophy as "learn from Victor's firmware, don't copy the battle scars,"
  and the same move Hermes made vs. scattered data handling.)
- `INGESTION_CONTRACT.md`, `METADATA_SCHEMA.md`, `fleet.yaml`, the ingest/QC scripts → become the
  SURVEY/learnings layer that informs Eunomia's clean design.

**This DISSOLVES the earlier "conflicts" (now reference material, not constraints):**
- **D-9 (identity = Eunomia) UN-SUSPENDED, reframed:** Eunomia IS the unified identity owner; the
  rich fleet.yaml fields (insv_serial, ble_mac, calibration, the IAQEB↔body-serial crosswalk,
  kit→operator binding) are ABSORBED into Eunomia's clean operational model. The crosswalk-bootstrap
  idea (co-locate both serials on a card → learn the mapping) is a good pattern to keep.
- **C-12 / SEAM 3:** ADOPT their **dual-signal join** as the design (ordinal spine + clock-
  independent DURATION guardrail + named failure tiebreaks: ordinal_slip / board_swap /
  clock_suspect / needs_review). It's better than our single-signal version. Implemented cleanly
  IN Eunomia (not handed to a separate workstream). Supersedes the earlier C-12.
- **B-9 (capture-stack):** reconcile with `kit_version` + the registry's per-camera fields — all
  absorbed into Eunomia's clean provenance model.

**Boundaries that STILL hold:**
- **D-8 (Styx substrate):** Eunomia unifies the *software/behavior*, but the immovable host
  substrate (ZFS, Sipolar port mapping, udev plumbing) stays Styx's; Eunomia's unified ingest
  honors the substrate interface. Unify the code ≠ rewrite the host setup.
- **Eunomia ↔ Hermes (D-3/D-4):** unchanged. Eunomia is the on-site capture+ops+ingest system;
  Hermes (Hades, separate repo) is the analytical system-of-record that ingests Eunomia's contract.
  (Note: Eric's Layer-2 "release metadata" is now produced by EUNOMIA, and Hermes consumes it.)

### Open questions the contract ANSWERED (keep — these are facts to build on)
- **Operator (current topology):** from the FOB trigger log (camera never sees an assignment in
  BLE mode); kit_id+side always on-card from NAND (`PANTHEON/camera.json`).
- **Identity crosswalk key:** the long `IAQEB…` .insv serial (always present, even un-provisioned).
- **Block-level labeling insight:** an operator runs ONE task back-to-back for ~2 hrs, so labels
  are constant across a block → the join's per-take precision only matters for delete/void + edge
  pairing, not labels. (Big simplifier for the join design.)
- **Deletes = void-by-flag** (the fob delete log is the authority for intent; instant-delete is a
  card-space optimization, NOT a correctness requirement).

### STILL OPEN / URGENT (factual input needed to design the clean coordinator)
- ~~BLE vs WiFi-OSC~~ **RESOLVED (see D-11 below).**

### ⭐ The WiFi-OSC rig WORKS TODAY (HANDOFF_2026-06-23) — the build target is PROVEN
Victor validated the specced WiFi-OSC system end-to-end on the rig 2026-06-23. This is the
reference Eunomia's coordinator is the clean version OF.
- **Working reference fob source:** `ble_bridge/esp32-fob-wifi/` (synced to 3.8.3), `src/main.cpp`.
  (NOT `ble_bridge/esp32-fob/` — that's the OLD BLE fob, fw 2.1.0.)
- **THE TWO RULES (confirmed):** (1) ZERO background OSC — single-threaded cherokee crashes on
  concurrent OSC; fob discovery is L2-only (`esp_netif_get_sta_list`); OSC only at GRABAR/DETENER
  under `wifiLock`. (2) **discardd locks video mode; the fob does NOT arm per take.**
- **CORRECTION to our invariant:** we had "arm-before-start" (fw 3.7.0). CURRENT design (3.8.0+)
  DROPPED per-take arm because **discardd continuously re-asserts video mode camera-side**. The fob
  fires startCapture DIRECTLY; recording DEPENDS on discardd on every card. → Eunomia follows the
  discardd-locks-mode model (arm-before-start = fallback understanding, not live design).
- **discardd DOES do OSC** (re-asserts video mode every ~20–40s) — mild tension with "zero bg OSC";
  suspect if mid-take disconnects return. The re-assert cadence is a tuning parameter.
- **Fire-and-forget OSC confirmed** (`oscSendNoWait`); filename via telnet ls; camera clock poison.
- **⭐ Live-label-at-capture is the TARGET; the order-join is the FALLBACK.** discardd stamps
  `VID_<ts>_<seq>.pantheon.json` (station/task/episode/seq/record_settings) onto the SD AT CAPTURE
  (coordinator injects the per-take label, telnet-writes it). So `trigger_join.py` (our C-12 / SEAM
  3) is the SHIPPING FALLBACK for the BLE world; in the WiFi-OSC target, labels ride live and the
  join matters far less (delete/void + pairing edges). → Eunomia: live-label primary; dual-signal
  join as robustness fallback. Enables COLLECT-ANYWHERE (operators at home) — nothing needs office WiFi.
- **DESCARTAR = void+keep** (soft delete — voids but keeps the clip).
- **R-1 latency fix-path:** ~3s start delay + imperfect sync + cosmetic double-flash trace to the X3
  re-initializing its capture pipeline at startCapture. Proper fix = PRE-ARM via discardd's ambashell
  path (camera-side, Eric's) — OSC prearm DEAD on X3 1.1.6. R-1's latency is camera-side; the fob
  touch-ack/robustness portion is still ours.
- **§12 custom-hardware wishlist (→ hardware findings doc):** nearly every problem came from not
  owning the camera fw/API. Wishlist: dual-radio coordinator (cameras + office/LTE uplink), a
  concurrency-safe camera control API, native per-clip metadata API, real RTC. "Don't build a 360
  camera from scratch unless 360+FlowState stabilization is a hard requirement."

### The hardware-verification gate (merge into our bench plan)
Eric/Victor's UNVERIFIED on-cam assumptions, to fold into the bench test plan (several are
GATE-LOAD-adjacent): 2-hr 3K/100 thermal survival; **file-splitting of a 2-hr take (most likely
desync source — does firmware auto-segment? inflates episode count vs fob starts)**; capture-mode
retention without an agent; instant-delete actually removes on-card; NAND episode_seq monotonic
across SD/battery swaps; IAQEB serial reliably in every .insv.

## LEARNINGS from Eric's Layer 1/2 code (pipeline/) — patterns to carry into Eunomia's clean design

Read 2026-06-23: `pantheon_sidecar_schema.py`, `trigger_join.py`, `fleet_registry.py`,
`qc_score.py` (+ the WiFi-OSC handoff). The reusable PATTERNS (the clean design should keep these,
re-architected, not copy the file-sprawl):

**Sidecar schema + versioning (pantheon_sidecar_schema.py — the single most useful file):**
- On-card sidecar = `pantheon-x3-sidecar/v2`. **Hard-required identity** (corruption = unsafe to
  ingest): camera_id, kit_id, side, operator_id, station_id, task_id, task_name, session_id,
  episode_id, rotation_id; +v2: prompt, task_source; +top-level: schema, timestamp, seq,
  files.back, global_episode_seq. **The ONLY non-empty requirements are kit_id + side** (canonical
  naming + L/R pairing). **Warn-only** (consumed downstream, recoverable): episode_ordinal,
  calibration_id, record_settings, mount, assignment_source, bimanual_episode_id, site_id, fob_id,
  fob_build, camera_firmware, stop_reason, kit_version.
- **⭐ Two orthogonal version axes (ADOPT THIS):** the `schema` STRING tells a PARSER which fields
  to expect (semver, ADDITIVE — v1 files still validate under v2); `record_format_version` is a
  monotonic INT owned by the WRITER (discardd) that bumps when the captured-record format changes,
  so a bug tied to a firmware/fob/format build is scoped + quarantined BY QUERY, not a backfill.
  This IS our B-9 capture-stack provenance, already built — fold it in.
- **Hard-vs-warn validation (ADOPT):** loud field-level failures for ingest-unsafe fields;
  warnings for recoverable-but-consumed fields. Maps onto our conformance gate. Pure-stdlib (runs
  in the cam-side + ingest python with no deps).
- `bimanual_episode_id` = fob-injected, written to BOTH cams' current_assignment.env before
  startCapture, discardd-stamped → pairs the two cams with NO order-join (✓ live-label primary).
- `trigger_extra` / preserve-unknown-fields across schema bumps (forward-compat discipline).

**The join (trigger_join.py — the dual-signal join, 1534 lines):**
- Trigger-box log = `pantheon-trigger-episode/v1`: {schema, event:start|stop|delete, kit_id,
  fob_session_id, ordinal, wallclock, ms (fob uptime monotonic), station, prompt, cams[], sent,
  total}. The fob's event log shape — relevant to the contract's event model.
- **TWO ordinals, distinct roles (important):** NAND `global_episode_seq` (camera-side, swap-proof)
  = the PRIMARY ORDERING key; the fob `ordinal` = the LABEL-join source. They stay independent
  (a fob swap keeps global_seq continuous; de-dup keyed on (kit_id, fob_session_id, ordinal)).
- **`sent`/`total` phantom-press gate (= our R-1 robustness, enforced at source):** a START is
  refused (no ordinal advance, button locked) unless both cams acked (sent==2). sent==0 → dropped
  (phantom_start, non-blocking); sent==1 → kept-but-needs_review (oneside_start, orphan voided).
- **Delete = void-by-flag** with global_seq-gap detection to tell "clip wiped" vs "clip survived"
  (✓ our void-by-flag). Timing ALWAYS from fob NTP; camera clock never used.
- **Pairing (x3_pair.py) — robustness patterns to KEEP:** fleet.yaml gives three resolution maps:
  serial (body_serial/camera_id/insv_serial → kit/side; **RETARGETS a stale sidecar kit_id by the
  immutable serial**), kit_alias (**stale_kit_id → real_kit_id, applied to BOTH sidecar AND fob
  log** — handles provisioning-era kit renames), operator (kit_id → person). Pair L+R sharing the
  SAME fob ordinal after grouping by NAND identity. Idempotent rebuild with stage caches (audio-
  sync/trim/QC results carry forward); symlinks, never copies the raw fisheye. _00_ only (the SBS
  file); never resolve a _10_ as the front clip (it's the old dual-fisheye back stream).

**Identity (fleet_registry.py — what Eunomia's identity layer is the clean version of):**
- `fleet.yaml` holds **IDENTITY ONLY — never WiFi PSKs** (those in gitignored cameras.env). KEEP
  this secrets-separation principle.
- NAND identity keys (discardd reads from /pref/pantheon_camera.env): camera_id, kit_id, side,
  mount, calibration_id, operator_id, operator_name. So operator CAN be NAND kit-bound (the
  fixed binding) in addition to the fob-log source → cross-check, mismatch = needs_review.
- **Identity belongs in NAND; an SD camera.env carrying identity is a mislabel HAZARD** → flag/
  quarantine. Three registry jobs: provision (serial→NAND env), SD-mislabel check, ingest guard
  (cross-check burned identity vs registry, quarantine mismatch). = Eunomia's identity/provisioning
  console + ingest validation.
- **IAQEB crosswalk:** `IAQEB[A-Z0-9]{8,12}`, scan first+last 8MB of the .insv (don't slurp the
  whole multi-GB file); learn_crosswalk co-locates both serials on a card to bootstrap the mapping.

**QC (qc_score.py):**
- **No closed taxonomy** — QC returns whichever flags fire; **thresholds in a config dict so a new
  site retunes without code edits**. ADOPT: QC flags are an OPEN set in the contract, not a fixed
  enum; thresholds are config.
- **Default to "ok"** (a flag is the exception; a normal episode trips nothing). Cohort-relative
  flags (too_slow, ood) only fire WITH cohort stats (never guess a population from one episode).
- Flags (from the IMU the X3 already embeds — zero extra capture cost): idle/frequent_pause,
  freefall/drop, too_slow, ood, tiny-misfire, shake, saturation/clipping, excess-jerk. Maps to the
  schema's qc_flags / quality_flags / quality_score / quality_reasons (open flags + weighted score
  + per-flag reasons). Pure-stdlib.

**LESSONS.md — contract-critical data-semantics (modality-INDEPENDENT, apply to Eunomia regardless of trigger):**
- **⭐ The SD card is NOT a unit — never scope anything per-card.** `global_episode_seq` (camera
  NAND) + fob ordinal (NVS) are monotonic + CONTINUOUS across card/battery swaps + reboots — they
  do NOT reset. A drained card is just a contiguous gseq SLICE. The join is GLOBAL per (kit, side),
  run idempotently over the FULL accumulated set, re-run as each card lands. (Was mis-modeled twice
  as "card = session" — it is NOT.) → Eunomia's operational model: episodes belong to a continuous
  per-(kit,side) sequence, not to cards; ingest is idempotent + global, not per-card.
- **⭐ The .insv/.mp4 extension flip:** the X3 writes ONE file per 360 take and flips the container
  extension per-take (byte-identical), never both. ALWAYS glob BOTH. (files.back in the sidecar.)
- **⭐ 3K/100 SBS layout:** both lenses in one frame — LEFT half = FRONT (operator/selfie), RIGHT
  half = BACK (workspace). USE THE BACK/RIGHT HALF ONLY; never train on the front half
  (sbs_workspace_half=right). Critical data-semantics fact for the contract + consumers.
- **⭐ NEVER pair/identify by ingest folder or camera timestamp — both poison.** Pair by each clip's
  OWN sidecar identity (kit_id/side from NAND), L+R sharing the same fob ordinal; REFUSE to pair
  across inconsistent kit_ids rather than mis-pair. A kit's two cams MUST report a consistent
  kit_id + correct side or they never pair.
- **Identity load-order (override hazard, precise):** config.env → /pref/pantheon_camera.env (NAND)
  → camera.env (SD) → current_assignment.env. An SD camera.env OVERRIDES NAND — production SDs must
  NEVER carry one (mislabel hazard; fleet_registry validate-sd flags it).
- **Trim = camera-IMU ready-pose onset** (s2b_start_trim.py), NOT a fob-duration cut. Relevant to
  what episode boundaries mean downstream.
- **Audio post-sync is THE alignment** (sub-ms via cross-correlation); trigger-time <1ms impossible
  without genlock. Audio-slate click per START → exact + infinite-scale, no WiFi. Fills the
  cross-cam offset (sync_offset_ms/sync_confidence) downstream.
- **The no-SD trap (= our recording_suspect need):** a start can pass every check and save NOTHING
  (no/full SD card — the cam beeps + never records, no reliable pre-start SD telemetry). The fob's
  only proof a cam truly recorded is the rec-confirm edge; the BLE fob arms a background watcher
  (both cams must confirm within ~4s or it VOIDS the optimistically-advanced ordinal + flashes
  REVISA SD). → Eunomia's coordinator needs the same did-it-actually-record confirmation +
  recording_suspect flag (our WiFi-OSC equivalent = the STOP-time clip-grew check).
- **100-kit isolation:** per-kit SSID (primary) + per-kit PSK (recommended at scale) + macAllowed()
  runtime allowlist (cmd=lockcams, allow_n>=2). → fleet-scale + security (deferred items).

(BLE-only material — RTL8761B radio, re-advertise-on-connect, wake-beacon, supervision timeouts,
the GATT table, L2CAP raw-HVN trigger, marker-clip delete, ~29s reconnect — is CURRENT-MEXICO
reference, replaced by the WiFi-OSC target; relevant only to the eventual migration, not Eunomia's design.)

**IDENTITY_FLOW.md — the current identity MODEL + task precedence (contract-relevant):**
- **Current model collapses `kit # == operator ID == rig #`** (one operator owns one kit, identity
  fully camera-NAND-resident, zero operator action). → Eunomia should GENERALIZE this: keep person
  and kit as SEPARATE entities with a time-bound binding (event-sourced per B-8); "kit==operator"
  is just the degenerate case. This is where the clean design IMPROVES on the rigid current model
  (an operator may use different kits over time; person history must be hardware-independent —
  matches the spec's person_id decoupling). HR record comes from Rippling; roster is kit-based.
- **Task/prompt precedence (encode in contract):** NAND `/pref/pantheon_current_task.env`
  (task-only, survives SD swaps) → overridden by SD `current_assignment.env` (live push) → else
  none → order-join supplies it. `task_source` ∈ {nand_staged, sd_assignment, none}.
- **Clean separation principle (KEEP):** identity env carries ONLY identity; task env carries ONLY
  task — never mixed.
- **⚠ episode_id RECONCILIATION NEEDED:** the as-built current id is STRUCTURED —
  `<session_id>_<counter>` = `<YYYYMMDD>_<operator>_<station>_<NNNNNN>`, pairing rule
  `left.episode_id == right.episode_id`. Our C-9 decided UUIDv4 + structured fields alongside. Both
  have merit (structured = human-debuggable; UUID = provisioning-robust). DECIDE explicitly in the
  contract design — don't silently pick. (Leaning: keep our UUIDv4 as the pairing key per C-9, with
  the structured fields as the alongside metadata — but acknowledge the as-built uses the structured
  form directly.)
- GPS-metadata-channel encoding (ordinal/station/prompt-hash packed into the .insv GPS track) is a
  clever BLE-only live-label hack — NOT needed for WiFi-OSC (telnet writes the sidecar directly).
  Reference only.

**UMI_LIFECYCLE.md — the end-to-end blueprint (the best single ref for Eunomia's flows + consoles):**
- **⭐ Identity precedence (THE contract the join obeys):** `kit_id` ← FOB (device bound to the
  kit; a camera can be swapped, the fob can't be confused which kit it is); `side` ← CAMERA NAND
  (physical property); `operator` ← roster keyed by kit (kit→operator binding); `station` + `prompt`
  ← FOB trigger log (captured at press time = ground truth of where the operator was). Serials are
  provenance, NEVER decide the kit. → Eunomia's operational model + join must encode this precedence.
- **Failure-handling model (= our walkthrough scenarios, canonical):**
  • One cam drops → GRABAR LOCKS at <2 cams (can't start a one-sided take); wait for 2/2.
  • Camera swap → side-typed pooled spares (correct side pre-burned in NAND + in fleet.yaml + MAC
    in the fob allowlist) → swap is POWER-ON, zero field re-provisioning (kit from fob, side from
    NAND spare keep labeling correct).
  • Fob swap → pre-provisioned spare fobs per kit; ordinal continuity via server-seeded high-water
    mark (best-effort) + **`fob_session_id`** disambiguation (the REAL correctness guarantee: ingest
    keys on (kit_id, fob_session_id, ordinal)); camera global_episode_seq = continuous ordering
    anchor across the swap.
  • Bad take → DESCARTAR → instant-delete on-camera. • Need lead → LLAMAR → logged 3× (fob+
    receiver+dash), bell ~4s, honest status (notified vs saved).
  • Design principle: hardware failures degrade to "flag for review (needs_review)", NEVER to
    "silently wrong data."
- **⭐ R-1 enabler + extensions (fold into R-1):** the fob's Wi-Fi I/O runs on a **dedicated core-0
  task (wifiTask, pinned core 0; UI loop + touch on core 1)** fed by a fire-and-forget job queue —
  so the UI NEVER stalls on network. THIS is the architecture that makes instant touch-ack possible.
  Plus: feedback drawn BEFORE any network; ~125Hz touch sampling; **durable ordinal** (log line to
  flash BEFORE the NVS counter advances). Proposed UX (all = R-1): full-screen color state (green
  idle/red recording/grey locked), take counter + GUARDADO/DESCARTADO toast, **haptic/audio tick on
  a registered press**, persistent status ribbon (CAMS 2/2, battery, unsent-log count).
- **Ops/deploy reality (consoles + Styx boundary):** ONE real dashboard on Pluto :5074; the ingest
  receiver :5075 is the ONLY public-facing service (Tailscale Funnel, token-gated, the fob talks
  ONLY to it); assignment state in x3_state.json + operator_roster.yaml. "A missing thing is usually
  a DATA-feed gap, not a missing UI"; never write NETWORK_ROLE (soft-brick); tokens in the plist.
- **Provisioning steps (provisioning console + R-2):** (1) register camera in fleet.yaml
  (body_serial/kit_id/side/mount); (2) burn NAND env GENERATED from the registry (deploy_preflight
  checks agreement); (3) bulk SD flash (format + oncam/discardd payload — NO identity on SD); (4)
  provision fob over USB serial into NVS (kit, op, allow=MAC allowlist incl. spares, wifi,
  upload_url/token). Camera clock = UTC at provisioning (provenance + ordering-fallback ONLY).
- **CORRECTION (capture settings):** KEEP BOTH lenses (front _00_ carries the IMU; back reports
  "unsupported" for IMU) — KILL_FRONT_SENSOR=0. SUPERSEDES the single-lens-back optimization. The
  locked mode RES_3008_1504P100 IS the 2:1 dual-fisheye 360 frame (both lenses in the _00_ file).
- Genlock R&D is archived (genlock_rnd/), NOT production — audio post-sync is the alignment.

**ingest_orchestrator.py — scale + orchestration patterns (for Eunomia's ingest module):**
- Built for **~100 kits/hr, parallel + idempotent**. One worker per kit-dump (ProcessPoolExecutor);
  `.state/<kit>__<dump>.done` markers skip on re-run; ingest is file-level idempotent (hardlink
  samefile skip) so a crashed batch just resumes. Hardlinks, never copies; footage never moved/deleted.
- **Staging layout contract:** incoming/<kit_id>/<dump_id>/ (DCIM + sidecars; **dir name is a HINT,
  the sidecar identity verified vs registry is the AUTHORITY**), trigger_logs/ (per-kit fob logs,
  auto-paired by kit_id at join), out/<kit_id>/<dump_id>/ (per-dump, no cross-worker contention),
  .state/ (idempotency markers).
- **Throughput knob = IMU extraction** (~1-2s telemetry parse per .insv front lens); --imu-rate
  lowers JSON size, --no-imu = footage-only fast path. W=14 on 16-core clears >100 dumps/hr.
- **Two-phase label fold-back** (because the order-join is GLOBAL): per-dump workers run LABEL-LESS,
  then ONE full-tree join → JoinedEpisodes → fold_labels_into_outputs merges labels back on
  (kit_id, side, camera_clock, seq). Idempotent: re-derives from pristine JoinedEpisode.identity,
  never the decorated file, so labels never compound. (In the WiFi-OSC target this matters less —
  labels ride live on the sidecar — but the idempotent-orchestration + staging patterns transfer.)

**x3_audio_sync.py + the umi_clean boundary (scope question):**
- Cross-cam alignment = cross-correlation of the two wrist cams' audio → sub-frame start offset.
  Sign: lag_s>0 → LEFT earlier → skip lag_s of LEFT; score_ratio >20 solid, 5-15 ok, <5 unreliable.
  Maps to the schema's sync_offset_ms / sync_confidence (deferred-null-at-ingest; score_ratio = the
  confidence). REUSES a canonical core (data/umi_clean/stages/s2_audio_sync) — "re-deriving the sign
  has burned us before" → DRY/shared-core principle.
- **⚠ SCOPE QUESTION (flag for the contract/module map):** there is a separate **`data/umi_clean/`
  cleaning pipeline** (s2_audio_sync, s2b_start_trim, render-to-flat-mp4, etc.) that the X3 pipeline
  imports from. This is the DOWNSTREAM cleaning/processing layer (trim/sync/render → training data),
  distinct from the ingest/identity/QC layer Eunomia is unifying. DECIDE: does Eunomia ALSO absorb
  umi_clean (the cleaning stages), or does cleaning stay separate / move to the Hermes side? Leaning:
  Eunomia owns capture + ingest + identity + QC + ops + the live consoles; the heavy cleaning/render
  (trim, audio-sync, de-fisheye render) is a downstream concern that could be Hermes-side or a
  separate stage Eunomia feeds. Not Run-0-blocking, but the module map needs a clear line here.

**DEPLOY_SCALE_PLAN.md — scale/ops model + the front-lens reconciliation:**
- **⭐ Front-lens lifecycle (reconciles "keep both" vs "back-only"):** discardd KEEPS the front
  `_00_` lens on-card (DELETE_FRONT_AFTER_KEEP=0) because it's the ONLY IMU source (the _10_ back +
  discardd's "gyro" OSC probes are NOT a usable motion stream) → ingest EXTRACTS the IMU from it
  (--extract-imu) → ingest DROPS the front from the TRAINING OUTPUT (--drop-front). So: ingested
  data keeps the front until IMU is pulled; TRAINING data is back-half-only. Front _00_ (~600MB)
  survives on SD until offload. DELETE_FRONT_AFTER_KEEP=1 kills the QC feature → MUST stay 0.
- **Exception-based QA (the god's-view principle):** a lead oversees ~16 operators = ~32 wrist
  cams; live-feed monitoring doesn't scale (+ BLE kits have no live preview). QC flags bad takes
  AFTER recording; the dashboard surfaces WHICH operators need attention (flagged rate, camera
  offline, short day, low SD/battery). Lead reviews the small flagged set, not 32 streams. →
  Eunomia's god's-view = exception-first, not live-monitoring.
- **Registry match precedence (sharper):** serial → camera_id/alias → ble_mac → (kit_id, side). A
  cam whose NAND CAMERA_ID is still the wlan-MAC fallback but whose kit+side are right is ACCEPTED
  (don't quarantine good data); a genuine cross-wire → quarantine to _needs_review/. Registry
  self-validates (no dup serials/camera_ids/(kit,side), valid sides, complete L+R per kit).
- **Scale path:** `add-kit` = one command per kit (rejects dups, validates before write);
  `deploy_preflight.py` = the single "is the fleet deployable right now?" gate. One versioned
  registry file. Fobs have no SD → `fob_log_pull.py` ships logs by serial dump at the depot →
  trigger_logs/, or end-of-shift Wi-Fi POST.
- **The four legs (the system's spine):** (1) authoritative identity (fleet registry), (2) the QC
  feed (IMU extraction → flags), (3) parallel idempotent ingest (~100 kits/hr), (4) a field trigger
  box that scales (the fob). Eunomia unifies all four cleanly.

**INGEST_RUNBOOK.md — operational lessons (for Eunomia's ingest + quarantine handling):**
- **The ingest is TWO idempotent commands:** station_ingest.py (build staging view from the pool,
  SYMLINK not copy, land fob logs, resolve kit_id from the SIDECAR not the folder, flag operator/
  side mismatches) → ingest_orchestrator.py (join + QC + label + pair/void). Outputs: labels.jsonl,
  label_warnings.jsonl, voided.jsonl, .state/ markers. Nothing moves/deletes footage; deletes are
  void-by-flag; a labeling problem only flips needs_review.
- **Quarantine-rescue pattern:** when Layer 0 can't map a card's IAQEB serial to kit/side (factory-
  reset/unprovisioned cam), it parks the WHOLE card in `<date>/quarantine/<IMPORT_ID>/` — footage
  intact, just stranded. Recover by teaching the registry the serial (learn-crosswalk) then re-run
  with --rescue-quarantine. **NEVER guess L/R** (a wrong serial→side map silently swaps wrists). →
  Eunomia's quarantine handling: park-whole-card-intact + registry-driven rescue, never guess identity.
- **⭐ camera_map drift = the 2026-06-18 incident** (map hand-edited → missed a site's cameras →
  auto-added with SIDE BACKWARDS). FIX: identity-map deployment is a **NON-DESTRUCTIVE MERGE**
  (fleet.yaml authoritative for side+presence, preserves all other cameras), run on a timer that
  pushes only on drift WITH a backup — never a destructive overwrite. → strong principle for
  Eunomia: identity/config deployment is merge-with-drift-detection-and-backup, not overwrite.

**MEXICO_DEPLOY_RUNBOOK.md — deploy gates + provisioning sequence (for the bench plan + provisioning console):**
- **Deployment gates (map to Eunomia's bench + hardware-verification gate):** Gate 1 (per-cam:
  correct CAMERA_ID/SIDE + discardd running + record_mode_verify); Gate 2 (fob isolation: allow_n>=2,
  kit cams auto-reconnect after power-cycle, foreign camera REJECTED); Gate 3 (one end-to-end:
  paired + labeled + timestamped + sidecars written + actual .insv = 3K/100 + FlowState OFF — the
  ground-truth "will all footage be perfect" check); Gate 4 (dashboard shows live activity); Gate 5
  (50-fob same-room cross-talk test, before scale not before first deploy).
- **Ship-gate pattern (`ship_gate.py`):** exit 0 = SHIP; FAILs unless allow_n==2 + kit set + fw
  matches deployment fw (+ --require-time for NTP). "The only thing that blocks an unprovisioned
  (allow-all) fob from shipping." → Eunomia: a hard per-kit pre-deploy gate.
- **Camera config pins (burned at provision):** STANDBY_DURATION_S=0 (never auto-sleep),
  DELETE_FRONT_AFTER_KEEP=0 (keep front for IMU), 3K/100 SBS operator-non-changeable, NETWORK_ROLE
  EMPTY (soft-brick avoidance). Confirms the capture-settings invariants.
- **Per-shift:** each fob NTP-syncs once on boot (ship_gate --require-time) — confirms C-10.
- **Hard don'ts (operational safety):** agent NEVER switches the Mac Wi-Fi; never factory-reset a
  working camera (wipes NAND + SD); never hand-edit camera_map.json (use the merge tool); never ship
  a fob with allow_n==0; never touch camera Wi-Fi from discardd/bootup (soft-brick).
- **Confirms the umi_clean boundary (the scope question above):** the autonomous chain is card →
  drain (umi-pluto-* timers) → cron x3-clean-autorun → umi_clean (pair/sync/IMU-trim) → fob_overlay
  (labels+void+dashboard_ready) → dashboard_pair_render (back-only flat paired) → :5074 dashboard.
  The cleaning/render is a DISTINCT downstream layer from ingest — reinforces "decide Eunomia's line
  vs umi_clean."

**STATUS: the full x3-capture-kit learning set has now been read** (contracts, the WiFi-OSC handoff,
schema/join/registry/QC/pair/orchestrator/audio-sync/video-QC code, LESSONS, IDENTITY_FLOW,
FIRMWARE_FINDINGS, UMI_LIFECYCLE, DEPLOY_SCALE_PLAN, INGEST_RUNBOOK, MEXICO_DEPLOY_RUNBOOK) plus the
Styx substrate (data repo). Remaining unread = low-value-for-contract (dashboards' internals,
marker_codec, gps_meta, the two older HANDOFFs, genlock_rnd).

**DELIVERABLE DONE: `x3_platform_contract.md`** — the first-principles platform-input contract
(sidecar §2 + operational model §3 + release metadata §4 + two-axis versioning §5 + conformance §6).
Folds all 23 decisions + the learnings. BOTH contract decisions now RESOLVED: DECIDED-1 (episode_id =
**A′**: UUIDv4 pairing key + derived `display_id` composite, never-a-key) and DECIDED-2 (Eunomia
**FEEDS** the downstream cleaning/render layer — it is Hermes-side; includes a pointer table of where
each downstream piece lives today, flagged for the Hermes handoff).

**DELIVERABLE DONE: spec fold** — `x3_capture_system_spec.md` folded to Eunomia: retitled +
unification framing; WiFi-OSC marked PROVEN end-to-end (build target); the discardd-locks-mode
correction applied everywhere (§1.3, §1.7, EDGE-SETTINGS, F-CAP-04, the network-jobs list; GATE-ARM
voided → new GATE-DISCARDD-MODE + GATE-LIVE-LABEL); §3 data-model now POINTS at the contract as
authority (no longer duplicates it); episode_id → A′; RTC reframed as planned/not-present per C-10
(fob-NTP-authoritative + monotonic-offline); capture-format corrected to dual-fisheye SBS +
front-lens-IMU lifecycle; §3.6 + QC reframed for DECIDED-2 (cleaning Hermes-side) + the two
deterministic QC stages; §7 bench folded (WiFi-OSC proven + merged hardware-verification + deploy
gates).

**DELIVERABLE DONE: module map v3** — `x3_module_map.md` (drops the "v2" suffix; supersedes
`x3_module_map_v2.md`). Eunomia-named, clean. New top-level modules: `ingest/` (identity + join + QC
+ release + orchestrator — the unified successor to the scattered pipeline) and `substrate/` (the
ported host floor, interface frozen to the existing on-site deploy). `contracts/` now has sidecar +
operational + release + interfaces + events. Identity absorbed into `ingest/identity/`; the
dual-signal join in `ingest/join/`; the two QC stages in `ingest/qc/`; capture-stack + calibration
entities in `contracts/operational/`; gods-view = exception-first console; the fed-not-owned cleaning
boundary spelled out. Build order uses plain phase names (Foundation → bench harness → coordinator +
camera-image → ingest/edge/consoles), not internal run labels.

**DELIVERABLE DONE: de-jargon pass** — all internal shorthand codes (the C-/D-/B-/A-/R- decision
codes, the DECIDED-/OPEN- anchors, the A′/A/B option letters, the "Run 0/A/B/C" labels) REMOVED from
every doc others read: the contract, the spec, the module map, the hardware findings, the bench plan,
CONTRIBUTING. Each is now plain English ("the episode-id decision", "the substrate-port decision",
"the Foundation phase", etc.). **CONVENTION GOING FORWARD: the shared docs stay code-free; the codes
live ONLY in THIS register** (our internal working log). When folding anything new into a shared doc,
translate the code to plain English.

**DECISION — bench reframed to build-and-try (2026-06-23).** Victor reported his latest firmware ran
**>1 hr continuous with no battery or thermal issue** → the load/thermal/battery gate (the only one
that could change the HARDWARE) is treated as settled by his run; no separate soak campaign. The
remaining gates are reframed: (a) the correctness behaviors (file-splitting, NAND-seq across swaps,
stop-tightness, telemetry-not-in-take, serial presence) are **built to handle by construction and
validated on the FIRST REAL captures, fix-if-it-fails** — safe because the design degrades VISIBLY +
NON-DESTRUCTIVELY (every failure surfaces as `recording_suspect` / `needs_review` / a count mismatch,
never silently-wrong data, so a field miss is caught + quarantined, never a re-fix of lost data);
(b) two induced-failure checks kept (silent-stop → recording_suspect; no-SD start) because a clean
run can't trigger them — minutes, not days; (c) **the one true pre-deploy gate is the per-kit ship
gate** (correct provisioning + fob isolation), not a soak. Victor is away → can't ask him for a while;
build-and-try is the agreed path. ONE question for Victor when back (non-blocking): was his hour-long
recording one file or did it split? (Pre-answers the file-splitting gate for free.)
`x3_bench_test_plan.md` rewritten to this frame.

NEXT: Run 0 (the Foundation phase).

## Already decided (this session)

**D-1 · Repo scope** — One monorepo holds the WHOLE capture-program system: firmware
(coordinator + camera-image), tooling (bench-harness), edge (on-site store + sync), consoles
(the 5 UIs), and contracts. Why: the person wants all parts in one place. Cost acknowledged:
spans 3 stacks (C++/Python/web) under one roof; boundary discipline carries the weight.
Status: locked.

**D-2 · Contract spine** — `contracts/` is language-neutral, versioned (semver), the source of
truth; everything depends on it and nothing on each other's internals. Enforced by a
cross-language conformance gate (firmware-emitted + harness-parsed + console-written all
validate against one JSON Schema). Why: it's the Hermes "schema is the contract" pattern,
instantiated polyglot. Status: locked.

**D-3 · Data topology** — A small operational-metadata store on STYX (on-site, Mexico): live,
ground-teams read/write, survives WAN outage (edge-authoritative). Periodically syncs metadata
to a HADES backup (SF). Footage takes a SEPARATE drain→ship path (Victor's Layer 0), NOT the
metadata sync. Hermes (separate repo, Hades) is the analytical system-of-record and ingests the
same contract. Why: footage is huge (drain it so Styx doesn't fill); metadata is tiny and useful
live on the ground. Status: locked; sync cadence/conflict-policy to be designed when built.

**D-4 · Anti-drift process** — The contract is versioned; a contract change is its own reviewed
PR with a version bump + changelog; Hermes pins a version; bumping the pin is a deliberate
Hermes-side PR. Why: prevents the silent schema drift seen between Hermes and `athena`.
Status: locked; consumption mechanism (package vs submodule vs vendored) still open.

**D-5 · Build order** — Run 0 (Foundation, serial) → Run A (bench-harness) → GATE-LOAD verdict
vs Victor's proven firmware → Run B (firmware) + Run C (camera-image) in parallel → edge +
consoles later. Parallel only where modules are truly independent. Why: get the SoftAP hardware
verdict before the firmware's radio layer is sunk cost. Status: locked.

**D-6 · Build to end-state** — Modules are built to their real end-state shape (no throwaway
stubs), with the firmware's radio/transport layer factored as swappable (the GATE-LOAD hedge).
Why: the person wants the whole system built ASAP, cleanly. Status: locked.

**D-7 · Harness two-layer design** — bench-harness = a thin real serial/telnet IO shell + a
hardware-free core that replays recorded logs (testable + CI-able with no rig). Why: the
"no code only one machine can run" rule. Status: locked.

---

## DECIDED THIS PASS (Run-0-blocking design items)

**C-9 · episode_id construction** — RESOLVED as **A′** (2026-06-23, in the platform contract). The
pairing/join key `episode_id` is a **UUIDv4**, minted by the fob at START, written identically to
both cameras' sidecars (that's the pairing), and is the ONLY key anything joins/pairs on.
**REFINEMENT (A′):** a **`display_id`** composite (`<YYYYMMDD>_<operator>_<station>_<NNNNNN>`, the
as-built structured form) is COMPUTED + stored ALONGSIDE, clearly marked DERIVED — the human
debugging handle, NEVER a join key (so a wrong/changed field in it is cosmetic, not a corrupted
key). The underlying structured components (site_id, kit_id, fob_id, seq, recorded_at, operator,
station) also remain separate queryable fields. `bimanual_episode_id` stays the fob-injected shared
L/R id (pairs the two wrist cams of ONE take; distinct from episode_id which identifies the take).
Why A′ over plain-A (UUID + columns) / B (structured-as-id): keeps the UUID's robustness +
"resolve don't bake" consistency, recovers B's human readability without its fragility, makes the
readable handle first-class. Ordering still comes from global_episode_seq + recorded_at, never the
id. Small migration from as-built (fob already stamps the composite fields; now also emits a UUID).
Status: LOCKED (A′). [target: contracts/sidecar + contracts/operational]

**C-10 · Time model (no RTC yet)** — There is NO RTC in the current hardware; the fob relies on
connectivity for absolute time. The model degrades honestly:
  • online (NTP-synced): `recorded_at` = real wallclock, `time_confidence = ntp_synced`.
  • offline, no RTC: `recorded_at` = best-effort (last-known-sync + uptime delta),
    `time_confidence = unsynced_monotonic`; ordering is carried by a per-fob monotonic `seq`
    (which IS the ordinal) plus `uptime_ms` for offset reconstruction.
  • landing reconstructs absolute time for offline episodes once the fob reconnects (next sync
    establishes the offset; in-between episodes placed by monotonic offsets).
Camera time is NEVER stored (it's poison). Fields: `recorded_at`, `time_confidence`, `seq`,
`uptime_ms`. RTC-ready: when RTCs arrive, add an `rtc_freewheel` confidence level — no schema
change. Why: without an RTC the monotonic counter is the ONLY thing that makes offline episodes
orderable; confidence travels with the data so downstream knows what to trust. Operational
consequence flagged: a fully-offline fob has unreliable absolute time (and unreliable god's-view
"when") until it syncs. Status: locked. [target: contracts/sidecar]

**C-11 · Calibration (modeled for an undecided future)** — Calibration is NOT yet decided: Eric
is testing whether one calibration done on a single camera and applied fleet-wide is good enough
(watching SLAM error); the outcome could be per-camera, fleet-style, or none. The contract
ACCOMMODATES all three rather than committing:
  • `camera_serial` — ALWAYS on the sidecar (physical identity; what any calibration model
    resolves through; costs nothing).
  • `calibration_id` — nullable/optional reference on the episode.
  • Calibration is an optional first-class entity in `contracts/operational/` with a `scope`
    field (`none` | `fleet` | `per_camera`) + validity ranges; the heavy data (intrinsics,
    distortion, stitch params, captured_at, method) lives in the entity, not on the card.
  Which world we're in is DATA (scope + whether ids are populated), not structure — so when Eric
  reports back we set data, not re-cut the schema. Why: model the axis of uncertainty as a value,
  not a structure. Operational flag: pilot cameras are currently uncalibrated — fine under
  `scope=none`. Status: locked. [target: contracts/sidecar + contracts/operational]

**A-2 · Edge/ship data split** — The edge store (on Styx) holds operational metadata PLUS a
footage-reference entity per episode carrying a `footage_state` lifecycle
(`on_card` → `on_styx` → `shipped` → `on_hades` → `purged_from_styx`) + current location(s).
The footage BYTES and drain mechanics stay Victor's Layer 0; the drain REPORTS state transitions
into the edge store. Footage is safe to purge from Styx once `footage_state ≥ on_hades` verified.
Why: the ground teams' key question is "is this footage safely off the card so I can reuse it?" —
belongs where they already look; stays tiny (reference + enum + path). Alternatives rejected:
metadata-only (two systems to join); full content-addressed tracking (over-engineered). Contract
implication: a footage-reference shape (episode_id → {state, locations, hash?}). Status: locked.
[target: contracts/operational; interface: drain → edge state-transition report]

**C-12 · Ordinal-join reconciliation** — Primary pairing = `episode_id` (same UUID both arms).
Missing on an arm (write failed) → fallback: Nth START on fob F ↔ Nth episode from F by per-fob
`seq`; count mismatch → `needs_review`. **Landing ALWAYS cross-checks episode_id pairing against
the ordinal when both are present; disagreement → `pairing_anomaly` flag → review.** The
cross-check is FREE (landing-side compute on data it already has — NOT a manual verification gate,
NOT "plug in every fob"): clean agreement passes through with zero human step; only a detected
disagreement is flagged. Why: silent mis-pairing (a wrong-but-present id pairing the wrong arms,
flowing into training data) is a bad failure and the cross-check costs nothing to catch it.
Contract implication: `pairing_method` field (`episode_id` | `ordinal_join` | `needs_review`) +
a `pairing_anomaly` flag. Status: locked (revised from strict — cross-check restored as
detection, since it's free and silent failure is unacceptable). [target: contracts/operational]

**B-8 · Operational lifecycle = EVENT-SOURCED** — Lifecycle entities (person, hardware-unit,
calibration, task-menu-version, session) are APPEND-ONLY EVENTS (`unit_provisioned`,
`unit_deployed`, `unit_faulted`, `person_onboarded`, `person_qualified`, `person_offboarded`, …);
current state is a MATERIALIZED VIEW (fold events). Static entities stay plain records. An
episode's references resolve AS-OF its `recorded_at`. Why: the spec's attribution model is as-of
bindings (inherently temporal) — event-sourcing does this naturally, mutable records badly
("attribute to the operator's qualification AT THE TIME"; "which calibration was in effect when
shot"; "offboarding revokes access, keeps history"). Matches Hermes append-only/derive-on-read;
makes backfill clean (append a correcting event, never mutate). Cost (current-state) solved by
materialized views; storage negligible. Alternatives rejected: mutable records (loses history,
breaks as-of); hybrid (drift). CLOSES A SPEC GAP (spec named entities + as-of bindings but not
how state-over-time is represented). Status: locked. [target: contracts/operational + ADR-0001]

---

**B-9 · Capture-stack provenance** — Every episode records WHICH capture stack produced it, so
the platform is filterable by hardware/firmware/modality. Representation: a registered
**`capture_stack` entity** in `contracts/operational/` (a versioned combination: `modality` +
camera model + camera fw version + fob board type + fob fw version + UMI gripper hw version + SD
model + coordinator/Eunomia sw version), referenced by **`capture_stack_id`**. Each EPISODE
carries `capture_stack_id` + the per-episode varying **serials** (`camera_serial` ×2, `fob_id`,
`kit_id`, `calibration_id`). Heavy version details live in the registry, NOT on every episode
(reference-by-id, like calibration C-11). Why: filterable ("episodes with camera fw ≥ X", "UMI on
gripper v2") via a registry join, without bloating millions of episodes, and correctable/backfillable.
  • **Modality** is a first-class field, values **`umi` | `teleop`** (only these two for now; the
    field exists so teleop slots in later with no schema change). Eunomia today is always `umi`.
  • **Where provenance comes from:** AUTOMATIC by default + PREFILLED, with a supervisor
    confirm-every-day responsibility. Sources: coordinator/Eunomia sw + fob fw = build-time/
    self-reported (the fob already emits `FOB_BUILD`); camera fw = fob reads once at session start
    (single allowed telnet read) or provisioning-time fallback; camera model/board/SD/gripper hw =
    provisioning-time, recorded against serials in the registry; calibration = C-11. The fob
    assembles the current `capture_stack_id` automatically at session start; a **console at
    start-of-day prefills the resolved stack and the supervisor MUST check + confirm it daily**
    (catches un-sensable changes like a gripper swap). Robust-by-default (correct even if the
    confirm is skipped), with the daily confirm as the accountability/override step.
  • Event-sourced (B-8): a firmware update = a new stack version / `unit_firmware_updated` event,
    so "what stack was in effect when this episode was shot" is always answerable as-of.
  Status: locked. [target: contracts/operational + contracts/sidecar + ADR-0001; console:
  start-of-day stack-confirm in `consoles/site-setup` or `workforce`]

**D-8 · Eunomia ↔ Styx boundary (by mutability, not by data-type)** — The line is "would I
change this by re-cabling/re-imaging the server, or by pushing new code?":
  • **Styx = immovable host substrate** — ZFS pool, the Sipolar 20-slot port mapping (bank-local
    + current-physical maps), udev rules, systemd plumbing, boot-disk safety. "How this particular
    server is wired." Changes rarely, hands-on only. Owned/set up via the `Pantheon-Industries-Inc/
    data` → `styx/` folder. Sean sets this up when the Mexico server arrives.
  • **Eunomia = all deployable behavior** — the drain LOGIC, ingest LOGIC, routing, the QA +
    ingest-status dashboards, the operational store, the consoles, the contract. The clean,
    unifying version of the software that runs on the substrate.
  • **The substrate interface is itself a contract**: if Eunomia replaces a Styx script/dashboard
    it MUST honor the substrate seam — udev triggers ingest, writes land in the ZFS pool path, the
    Sipolar slot-resolution maps/algorithm are used, the status-JSON location/shape is preserved,
    camera_map location. Changing a dashboard means rewiring its backend to these.
  • **Do NOT change**: ZFS, Sipolar port mapping, the server setup substrate. **CAN change**: the
    drain/ingest scripts, dashboards, routing logic (with backend rewired).
  Why: don't disturb the working/deploying substrate (Victor's, battle-tested); unify the
  changeable software in one clean repo. Status: locked. [target: ADR-0001 + a Styx↔Eunomia
  boundary/substrate-interface doc]

**D-9 · Identity source of truth = Eunomia** — Serial→side/operator identity is deployable
data (a pushable file, not a ZFS/Sipolar fact), so by D-8 it belongs in Eunomia's operational
model. Styx's `camera_map.json` becomes a PROJECTION/consumer of Eunomia's identity, not an
independent source. One source of truth; Styx's ingest derives what it needs from Eunomia. Why:
two systems independently claiming identity is exactly the drift we're avoiding. Status: locked.
[target: contracts/operational]

**D-10 · Deconfliction plan (Sean's Mexico setup vs. unfinished Eunomia)** — RISK: Sean deploys
Styx-substrate from the `styx/` folder before Eunomia is done → conflicts. MITIGATION: Styx is a
REPLICA OF PLUTO (already set up in SF), so we test/resolve conflicts in SF first. Plan:
  1. Write the Styx↔Eunomia substrate-interface doc NOW (what Eunomia depends on from the host:
     ZFS path, Sipolar resolution, udev trigger contract, status-JSON shape, camera_map location).
  2. Sean deploys the substrate as-is (stable, not what Eunomia changes) → unblocked.
  3. Eunomia replaces behavior (scripts/dashboards) incrementally, tested against Pluto-SF first,
     so the rewiring is proven before it reaches Mexico.
  4. Keep Victor (current scripts/fw), Sean (Mexico deploy), Eric (L1/2 ingest), Mo (Eunomia +
     Hermes) in the loop via the written boundary doc.
  Status: plan agreed; substrate-interface doc is the next concrete artifact.

**D-11 · Trigger mechanism: BLE is CURRENT, WiFi-OSC is the BUILD TARGET** — Mexico runs the BLE
fob TODAY; the WiFi-OSC design we specced is what Eunomia BUILDS (forward direction). No doc
contradiction — both true at different times (README = current BLE deployment; fob firmware
binary = the forward WiFi/OSC path). Implications: (a) Eunomia's coordinator is built around the
**specced WiFi-OSC design** (fob hosts AP, serialized OSC, telnet sidecar) — that's the target;
(b) BLE specifics in Victor's/Eric's code are CURRENT-MEXICO REFERENCE, not what we reproduce —
only the modality-independent learnings transfer (identity, dual-signal join, pairing/void, QC,
schema, block-labeling); (c) there is a future MIGRATION in Mexico from BLE-today → WiFi-OSC-
Eunomia — an operational transition, not a design blocker, but noted so it isn't forgotten.
Status: locked. [target: SPEC.md — confirm the WiFi-OSC trigger is the build target; note BLE as
current-state reference]

**D-12 · Substrate: PORT into Eunomia's repo, freeze its interface to Sean's deployment** — Goal:
ONE repo (no separate-repo tracking) WITHOUT forcing Sean to redo setup if the Mexico server
arrives before Eunomia ships. Resolution: the Styx substrate (ZFS, Sipolar maps, udev, systemd
plumbing, install scripts) LIVES IN the Eunomia repo as a distinct, clearly-bounded substrate
component that is INTERFACE-COMPATIBLE with what Sean deploys from the current `styx/` folder.
Eunomia *contains* the substrate definition but does NOT change its shape/config/layout — so a
setup Sean already did stays valid. "What Sean deployed" is a compatibility constraint the in-repo
version must honor; any real substrate change is deliberate + communicated, never a surprise that
breaks his box. Refines D-8 (the substrate boundary still exists, but it's vendored into the
monorepo rather than living in a separate repo). The earlier "substrate-interface doc" becomes
"the substrate component's frozen interface" within Eunomia. Status: locked. [target: ADR-0001 +
module map: a `substrate/` (or `host/`) component in the Eunomia repo]

**R-2 · Provisioning data capture** (build in provisioning console + operational model). Victor +
Mo agree: at PROVISIONING, capture everything later flows will need to CONNECT TO and IDENTIFY a
device — camera serial, MAC, camera WiFi/AP details, assigned IP scheme, kit/side, fob id,
firmware versions, calibration ref. Recorded against the serial in the operational model. Why:
makes downstream flows far easier (god's-view connecting to a kit, unit swap, re-provisioning,
the B-9 capture-stack resolution) because identity/connection facts already exist. Folds into B-9
(provenance-at-provisioning) + the provisioning console + the `unit` entity. Status: captured.

## REQUIREMENTS captured (build in their run; not Run-0-blocking)

**R-1 · Fob button feedback + input robustness** (build in Run B, `firmware/coordinator/ui/` +
`core/`). From Victor: there's a delay between pressing START/STOP and the action completing, and
the operator can't tell whether the fob *registered the touch* or *missed it* (resistive screen) —
so they re-tap, which can inject a spurious toggle and corrupt a take. Design:
  • **Instant touch-ack** — the moment a press registers (before any OSC fires), the button
    visually flips (color/pressed style). Answers "did it hear me?" immediately, decoupled from
    the slower "did the action finish?".
  • **Working state** — during arm→start / stop→finalize, the button shows a working style
    (spinner / "INICIANDO…") that reads as don't-tap.
  • **Done state** — settles to RECording / stopped when the action actually completes.
  • **Lockout (UI)** — the button ignores taps during the working state.
  • **ROBUSTNESS (core, non-negotiable)** — even if taps get through (fast taps before lockout,
    queued touch events, a held/spamming press, a malfunctioning screen), the coordinator STATE
    MACHINE must never act on a second trigger mid-sequence: START is valid only from `idle`;
    from `arming`/`starting`/`recording`/`stopping`, further inputs are dropped or
    coalesced, never double-fired. Spamming the screen must be harmless by design, not just hidden
    by the UI. Why: protection in two layers — UI makes it look locked, core GUARANTEES no
    spurious action regardless of input. Lives entirely in the `ui/` + `core/` layers (validates
    the swappable-UI seam). Status: captured; fold into spec at next doc pass.

## OPEN — deferred to later runs (NOT Run-0-blocking; revisit at the relevant run)

These do not change the frozen contract shape or the module boundaries, so they don't block
Foundation. Each is tagged with when it should be resolved.

- **Edge-sync cadence / conflict policy / Hades-backup shape** → when `edge/sync` is built.
- **Footage retention on Styx + Styx→Hades transfer integrity** (how we KNOW footage arrived
  intact before freeing Styx space — ties to A-2's `on_hades` verified state) → drain/ship design.
- **WAN-outage behavior for ground teams** (what consoles can/can't do offline) → console design.
- **How Hermes consumes the contract** — published package vs git submodule vs vendored-with-
  version-stamp (versioning discipline is locked in D-4; the mechanism isn't) → before the Hermes adapter.
- **⚠ HERMES HANDOFF — the downstream cleaning/render integration (DECIDED-2):** Eunomia FEEDS the
  cleaning/render layer (audio-sync, IMU start-trim, de-fisheye back-only render, dataset assembly);
  it lives Hermes-side. When the Hermes integration is scoped, FLAG these pieces with exactly where
  to find the code to integrate. Starting map (in the contract's DECIDED-2 pointer table): audio-sync
  core `data/umi_clean/stages/s2_audio_sync.py` (SHARED — keep one core); start-trim
  `s2b_start_trim.py`; run builder `pipeline/x3_pair.py` + `data/umi_clean`; render
  `pipeline/dashboard_pair_render.py`; label/void overlay `pipeline/fob_overlay.py`; the autonomous
  chain `pipeline/deploy/x3-clean-autorun.sh`. BOUNDARY: IMU extraction (`insv_to_imu_json.py` +
  `qc_from_imu.py`) stays on the EUNOMIA/ingest side (QC + trim input); front lens dropped from
  training output AFTER extraction. → revisit at Hermes integration time.
- **QC check definitions + thresholds** (the spec has the hook, not the checks) → post-processing design.
- **Discard/quarantine end-to-end semantics** (on-card discard → does it ship? get deleted?
  reviewed?) → pipeline design.
- **Backfill mechanics** (the event-sourced model from B-8 makes this clean; the operational
  surface for it is still a design) → pipeline / console design.
- **Provisioning-at-scale path** (zero-touch from kit_id); **site-config distribution + updates**
  (task-menu versioning, how a fob pulls new config); **fleet firmware updates** across ~1000
  fobs; **multi-site** (is Mexico the only Styx, or many?) → fleet-ops design.
- **Web stack choice** for consoles (and whether real-time `gods-view` differs) → before consoles run.
- **Console auth/access model** (who can fault a unit, offboard a person, change site config);
  **console offline behavior** → before consoles run.
- **Secrets/credentials distribution** (site WiFi passwords, endpoints); **metadata-sync auth**
  (can a rogue device write to the edge store / emit telemetry?); **PII handling** (operator
  names on cards + in the store — privacy/retention) → security pass.
- **Per-field schema name reconciliation** — BLOCKED on Victor's files + per-field decisions
  (see `x3_schema_reconciliation.md`). This DOES feed Run 0 (the frozen field names), so it's the
  one open item that gates Foundation — but it's a naming reconciliation, not a design decision.

## Known, chosen gaps (accepted tradeoffs, recorded so they're not surprises later)

- **C-10**: a fully-offline fob (no RTC) has unreliable absolute time + unreliable god's-view
  "when" until it syncs. Accepted; resolved when RTCs are added (model already RTC-ready).
