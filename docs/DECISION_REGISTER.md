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

**DELIVERABLE DONE: flows/IPO HTML faithful pass** — `x3_capture_system_flows.html` (the canonical
file; the build's older 77KB `x3_capture_system_flows.html` and `x3_walkthroughs2.html` are
superseded). Full pass to match the new architecture: title → "Eunomia" (title + brand only, body
component names kept per Mo); episode_id → UUIDv4 pairing key + display_id everywhere; per-take arm
REMOVED throughout (discardd holds video mode; startCapture direct); sidecar examples now carry the
two-axis versioning (schema + record_format_version), episode_ordinal, global_episode_seq,
operator_id; "no async join" reframed (live-label primary, order-join fallback); capture format →
dual-fisheye SBS + front-lens-IMU lifecycle; record_settings replaces capture_profile; QC → the two
deterministic stages. The Eunomia/Hermes split applied to the back-of-house: Eunomia owns
resolve+pair+QC and EMITS the release record, the heavy cleaning (audio-sync, de-fisheye) shown as the
Hermes-side layer it FEEDS. **IPO map reoriented to inputs → process → outputs** (Mo's ask): inputs
left, process spine middle, individual OUTPUTS broken out on the right edge (training clips · episode
record · cost/throughput/churn · quarantine), with I→P→O zone labels + rewritten map header. **Two new
flows integrated:** camera-overheat (stop_reason=overheat thermal stop) and fob-battery-swap
(global_episode_seq continuity, card-is-not-the-unit). Now 21 scenarios (was 19), 27 IPO nodes, 39
edges. Headless-rendered (jsdom): both views build, zero runtime errors.

**DELIVERABLE DONE: HTML gap-fill pass #2 + fob-feedback fold (2026-06-23).** Mo asked about the
START press-feedback flow and for a broader gap check. Done:
- **Fob press-feedback + spam-safety** — was missing from BOTH the HTML and the spec. Added two new
  fob screens (startidle green-idle, starting instant-ack/working/locked), split the capture
  walkthrough's single INICIAR step into instant-ack → working (mint/sidecar/startCapture, taps
  dropped) → GRABANDO, and added a dedicated edge-case scenario "Impatient operator spams START."
  **Folded into the spec as new §1.8** (UI instant-ack+working+lockout, plus the core guarantee that
  START is valid only from idle so spamming is harmless by design; enabled by the dedicated-core
  network task + durable-ordinal-to-flash). Resolves the register's R-1 "fold into spec" note.
- **Gap check (spec flows/edges vs HTML):** all 15 spec EDGE-* map to scenarios. Found provisioning
  thin vs the provisioning-capture requirement + calibration absent entirely despite being a
  first-class contract entity. **Added to provisioning** (now 8 steps): a unit-record capture step
  (body/.insv serial, MAC, AP/Wi-Fi, IP scheme, fob_id, firmware) + a per-camera calibration step,
  with two new console screens (provrecord, calibrate).
- **New hardware finding (Mo, on Victor's rig 2026-06-23):** cameras **self-restarted at ~30 min** of
  continuous recording (cause unpinned). Likely benign (real tasks are short), noted because it
  interacts with the count-reconcile (mid-take restart = multi-clip, handled like a split). Added as
  hardware-findings §1.8 with the thermal auto-stop + the open file-split question + a future-camera
  REQ for uninterrupted long recording + documented segmentation.

Now 24 scenarios (Edge cases 9), 52 fob/console screens, 27 IPO nodes. Headless-rendered: clean.

NEXT: Mo reviews the HTML + runs Run 0a (the Foundation phase).

**DELIVERABLE DONE: Run 0a Foundation — IMPLEMENTED + MERGED.** Plan-only → annotated (14 OQs +
2 confirmations resolved) → implemented on `Mzcassim/eunomia-run-0a-plan` → PR #1 to `main`
(github.com/Pantheon-Industries-Inc/Eunomia/pull/1) → CI green (gates + cpp jobs) → squash-merged via
Conductor. The repo skeleton (8 top-level modules), the uv Python 3.12 workspace mirroring Hermes
exactly (exact dep bounds, defaults-only ruff/mypy, the 5 gates in Hermes order, CI shape,
`eunomia-<name>`/`eunomia_<name>`, `[tool.importlinter]` in root pyproject), the PlatformIO ESP32
shell (native build+test blocking; esp32 target + clang-tidy non-blocking per OQ-13), the `.claude/`
tree (2 hooks — format + secret-block; commit-guard omitted; reviewer + contract-conformance agents;
codegen + gates skills; 3 rules), CI (`.github/workflows/ci.yml`), and the docs (lowercased
`Docs/`→`docs/` as clean R100 renames + new CONTRIBUTING.md, BUILD_PLAN.md, adr/0001-architecture.md)
all landed. **The load-bearing piece — the codegen harness — is proven:** ONE `ping` stub encoded
once → 3 targets (C++ header / Python type / JSON Schema); `make codegen && git diff --exit-code`
= 0 (committed `_generated/` byte-matches the generator); conformance shows all 3 targets agree on the
same fixtures (JSON Schema 2/2 accept + 2/2 reject, Python validate() same, C++ native test parses the
same files + round-trips). Generator slimmed to 130 lines via plain fill-templates (under the OQ-10
~150 budget; byte-identical output). `uv sync --frozen` confirmed resolving on a clean checkout (local
checkout-index + CI). Report-back format (real terminal tails, not claims) worked — keep it for 0b.

**DECIDED — Run 0b conformance validator = OPTION C (hybrid).** The real `contracts/` will validate
via **real JSON Schema (Draft 2020-12, the `jsonschema` library) for structure/types/enums/nesting**
+ a **thin stdlib overlay for the Eunomia-specific hard-vs-warn severity + the bespoke rules JSON
Schema can't express** (the precedence checks, warn-only downgrades). Rationale: 0a's stdlib
subset-checker was fine for 2 flat fields, but the real contract's nested entities + the two-axis
versioning + nullable-typed/enum/conditional fields are exactly where a hand-rolled validator goes
silently wrong — which violates the contract's own no-silent-mislabel invariant. Hand the hard,
error-prone structural validation to code that's already correct; keep only the Eunomia severity logic
in our own stdlib. The one new dependency (`jsonschema`) lives in the **validation/dev** group, NOT in
the shipped sidecar/edge validator (which stays pure-stdlib per CONTRACT §6 — purity matters where it
RUNS in the field, not in the CI gate). The emitted schema must be **spec-compliant Draft 2020-12** so
the consoles can validate browser-side (ajv) against the same file. Supersedes the BUILD_PLAN.md "Carry
into 0b" note (b). The other two 0b carry-forwards stand: pin PyYAML in a codegen dependency group
(hermetic regeneration vs the current `--with`); the ~150-line generator budget will be pressured by
the real schemas — STOP-and-flag (OQ-10) holds.

NEXT: Run 0b — encode the real `contracts/` from CONTRACT.md through the proven harness, with the
hybrid validator (Option C). Plan-only → annotate → implement, report-back + merge-readiness baked in.

**UPDATE (post-0b/0c, 2026-06-24) — run status:**
- **Run 0b — MERGED** (PR #2, squash `201c0d5`). The record surface: `contracts/sidecar/` +
  `release/` + `events/` + the two-axis versioning, through the 0a harness; the `ping` proof retired.
  The Option-C hybrid validator proven both directions on 33 fixtures (warn-field downgrade +
  `void⇒void_reason` semantic hard-reject). Shipped validator pure-stdlib; `jsonschema` dev-only.
  Generator 358 lines (flagged, accepted — more field-types + one bounded conditional + shallow
  nesting, NOT a framework; real cross-field logic hand-written in `_semantics`). 0b judgment calls
  ratified as carry-forwards (sidecar nested-shape-vs-rig, release hard/warn split → document into
  CONTRACT §4, telemetry strictness deferred).
- **Run 0c (interfaces half) — MERGED** (PR #3, squash `cc5c40f`). The two hardware seams
  (`CoordinatorPort` + `CaptureDevicePort`) as operation signatures → one `ports.iface.yaml` source →
  two targets (C++ pure-virtual abstract header + Python `typing.Protocol`; no JSON Schema — an
  interface isn't a record). **LEAD-OQ-A resolved = option C** (a SEPARATE `generate_interfaces.py`
  mini-emitter; `generate.py` byte-identical to 0b, so STOP-and-flag honored provably; sibling
  `make codegen` wiring, never imported — sidesteps the mypy-from-root constraint). **Closed type
  vocabulary HARD-ENFORCED** symmetrically in both emitters (`_check_return`/`_check_param`, raises
  `SystemExit` on a non-vocab type — the reviewer's catch, fixed before merge). The boundary that keeps
  C from degrading into A: the vocabulary is closed; a new type is a STOP-and-flag, not an IDL edit.
  OQ-7 = `record` → the generated `Sidecar`/`const eunomia::Sidecar&` (the one type-safety link).
  Proven in sync by the drift gate; C++ implementability via `pio test -e native` mock subclasses;
  Python conformance via a mypy-checked mock. **LEAD-OQ-B resolved = SPLIT, interfaces-first.**
- **Run 0d (operational model) — NEXT.** The §3 record-shaped entities (9) + the event/lifecycle
  representation + as-of + the §3 rules as types+docs (not enforced join). **Pre-approved OQs carried
  in `plan.md` + the annotations: OQ-3** (current-state records + tightened sync-delta envelope + a
  first-class operational-event record only where a lifecycle carries its own fields), **OQ-4** (THE
  watch-item: lifecycle history is a SEPARATE append-only event record, NEVER an embedded object array
  — this is what keeps every entity inside the existing DSL and `generate.py` un-grown; an
  array-of-objects/2-level-nesting need is a STOP-and-flag, not a silent DSL extension), **OQ-5**
  (footage_reference held-purge fields; tuning values out of scope; name = `purged`), **OQ-6**
  (validity ranges for as-of; resolver is a later run), **OQ-9** (tighten sync-delta `entity` as a
  WARN-level `_semantics` check, NOT a hard enum — a hard enum is a §5-violating narrowing; lands with
  0d), **OQ-10** (no operational C++ target), **OQ-11** (episode.void⇒void_reason + footage
  hold-consistency, the only single-record rules), **OQ-12** (pairing fields on episode too). 0d should
  move fast: record-shaped reuse of the settled 0b machinery + the held decisions.

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

## Decisions + carry-forwards added 2026-06-24 (post-0b)

**SPOT-CHECK / FAST-FEEDBACK ARCHITECTURE (DECIDED).** The fast feedback loop — managers in Mexico
(giving operators feedback) and founders in SF spot-checking freshly-collected data — is an
**Eunomia/Styx-side concern, NOT a Hermes/Hades critical-path concern.** Resolved design:

- **Base flow (unchanged, now explicit):** SD drain → Styx (Eunomia does the operational-store
  post-processing here: identity, pairing decisions, QC, the release record) → everything drains to
  Hades → Hermes ingests (analytical system-of-record + the heavy cleaning/render). Styx = on-site
  operational tier (Eunomia); Hades = analytical tier (Hermes).
- **ONE renderer, zero drift (the decisive constraint).** Spot-check footage is rendered by the
  **single Hermes renderer on Hades** — NOT re-rendered on Styx. Mo's drift concern is the argument:
  two renderers (Styx + Hades) that version-drift would mean a manager approves a render that isn't
  bit-for-bit what becomes training data — a silent correctness gap. One renderer = the manager sees
  the canonical artifact. **This keeps DECIDED-2 intact** (heavy cleaning stays Hermes-side); spot-check
  does NOT fork it.
- **Priority lane (the fast loop mechanism).** Spot-check-selected episodes are **queued first and
  greedily fast-tracked Styx→Hades ahead of the bulk drain**, rendered by Hermes, and pushed to the
  dashboard as they complete; the bulk drain follows. Racing ONE episode through, not the whole
  session, is what makes the loop fast.
- **Selection = BOTH** (Q1): Eunomia auto-flags a QC sample (everything `needs_review` + a random N%
  of clean) for retention AND a manual pull (manager/founder requests recent episodes by
  kit/operator/task) over whatever is still present.
- **Dashboard = hosted in Mexico** (a section of the supervisor admin console), but it is a **VIEW,
  not a renderer**: it **prefers the rendered episode on Hades** (fast, direct, once present) and
  **falls back to the raw footage still on Styx over the tailnet** only in the fresh window before the
  fast-track+render completes. Accessible identically from Mexico and SF (it references Hades). Honest
  tradeoff: in the fresh window the view is **raw fisheye over tailnet**; the clean flat render appears
  once Hades has it (the few-minutes target). This is the price of not duplicating the renderer — and
  given the drift concern, the right price.
- **Retention/flush on Styx:** keep spot-check raw footage until **(a) confirmed-rendered-on-Hades AND
  (b) an N-day Mexico-viewing window, whichever is LONGER**, then purge — bounded also by a **Styx
  space watermark** as a safety valve (Styx is the smaller ~360TB box; video is heavy). The
  footage_reference lifecycle (`on_card→on_styx→shipped→on_hades→purged`) already models this;
  spot-check just **delays the purge** for selected episodes. Mo's "send a copy to Hades up front so
  deletion is free" instinct IS the fast-track: once rendered on Hades, the Styx copy is pure cache and
  deletes with nothing lost.
- **LATENCY = a target with a measurement task, NOT a guarantee.** End-to-end "drained → spot-check
  episode rendered + viewable" = drain (already done at drain-time) + the Styx→Hades fast-track hop
  (network-bound) + the Hermes render (compute-bound on Hades/Athena, which is ordered-not-set-up).
  **UPDATE (Victor, 2026-06-24):** a **100 Gb card is coming to Hades soon**, and the Mexico/Styx
  uplink is hoped to be **10–100 Gb** (timing TBD). At those speeds the network hop nearly vanishes —
  a ~1.8 GB (60s) episode transfers in **~1.5s at 10 Gb/s, ~0.15s at 100 Gb/s**. So once the uplink +
  the Hades card are live, the loop is gated by the **Hermes render** (tens of seconds for a short
  clip on a decent box), NOT transfer. The bottleneck flips from network to compute. **Revised target:
  tens of seconds per spot-check episode once the hardware lands; measure and iterate** (the two
  things to measure: the actual effective Mexico→Hades throughput, and Athena's render-vs-realtime
  multiple — the latter now dominates). The queue-first design still applies. Until the uplink is
  ready, a slower link makes transfer the bottleneck (at 100 Mbps a 60s episode is ~2.4 min) — so the
  uplink readiness is the gating dependency for the fast loop being genuinely fast.
- **OPEN (deferred, design-time):** N% sample rate; the N-day window length; the Styx watermark
  threshold; the exact fast-track transport (priority queue mechanism); the dashboard's place within
  the supervisor admin console; the actual measured latency (needs Athena + the Mexico link). These
  are tuning/measurement, not architecture.
- **SCALING — "many many episodes" makes SELECTIVITY load-bearing (Mo, 2026-06-24).** A fast uplink
  removes the *transfer* bottleneck but does not make "render everything fast" possible. At fleet scale
  two pressures compound even with a 10–100 Gb link: (1) **render throughput becomes the ceiling** — if
  a session is hundreds of episodes and Athena renders each in tens of seconds, the queue *behind* the
  priority lane backs up; spot-check stays fast ONLY because it is a **bounded sample** (the QC sample +
  manual pulls), never the whole session. (2) **the Styx cache, not the bulk, fills the 360 TB box** —
  a fat uplink drains the bulk quickly, so it is the spot-check *retention* (the N-day window × the
  sample size) that pressures Styx storage. **Conclusion:** the sample-rate N%, the N-day window, and
  the watermark are NOT just tuning — at scale they are the levers that keep both the render queue and
  the Styx cache bounded. **Size them conservatively; "retain/render a large fraction" breaks the fast
  loop at scale.** The loop is fast *because* it is selective.

**HARDWARE UPDATE (Victor, 2026-06-24):** a **100 Gb card is coming to Hades soon** (the Hades-side
ingress). This effectively removes the **Hades ingress** from the latency equation — once data reaches
Hades the network is never the bottleneck there. The remaining unknown + real gate is the **Mexico
(Styx) uplink** (transfer OUT of Styx), whose timing/availability is TBD but "ideally pretty quick."
Net: end-to-end spot-check latency is bounded by `min(Mexico uplink, 100Gb Hades ingress)` =
effectively the Mexico uplink + the Hermes render. If the Mexico uplink is also fat, a single
spot-check episode is plausibly viewable in **well under a minute** (transfer in tens of seconds, render
in seconds-to-a-minute on a decent box). **The one thing to measure when Mexico is ready: the uplink
throughput** — Hades will not be the bottleneck. (Back-of-envelope: a 30–60s episode is ~0.9–1.8 GB
across two cameras; the render — pair+sync+de-fisheye back-half — is the smaller variable, ~15–60s on a
fast box.)

This resolves the previously-fuzzy Styx-vs-Hades / Eunomia-vs-Hermes split for the fast loop: the
operational tier (Eunomia/Styx) owns selection, retention, and the dashboard-as-view; the analytical
tier (Hermes/Hades) owns the single renderer and the system-of-record. Spot-check is a prioritized
path through the existing pipeline + a view, not new processing.

**PRIOR ART — `umi-qa` already exists; Eunomia BUILDS ON it, does not reinvent it (found 2026-06-24,
`data/umi-qa` on main, Victor + Claude).** A **FastAPI QA dashboard on port `:8090`** (the `:8090`
"Layer 2b QA viewer" from the learnings, now seen in full). What it already does — and how it maps to
the decisions above:
- **Selection both ways (validates Q1):** `random_video`/`random_clip` (auto-sample) AND `api_files`
  filtering by `date/episode/operator/camera` (manual pull). Exactly the both-modes selection decided.
- **Render-to-bounded-cache (validates the retention idea):** transcodes clips on demand with ffmpeg
  into `/tmp/umi-qa-clips`, capped at **20 GB** with a **24h TTL**. This IS "render-for-viewing into a
  bounded cache that flushes periodically" — our Styx retention is the same pattern one hop earlier.
- **Automated QA:** `health` + `detection` + `trajectory` modules run per episode.
- **Human-review loop (validates the manager-feedback use case):** feedback, flagging, a **review
  queue**, **per-operator scorecards**, recent-reviews — precisely the manager-gives-operators-feedback
  workflow.
- **Tailscale-gated, reads Hades footage:** binds `0.0.0.0` behind the tailnet (no port-forward, like
  the R730 dashboards), reads footage from `/mnt/robot-pool/umi-office-trials` (a **Pluto / R730**
  mount in the SF office — see the corrected hardware facts below; NOT Hades). **So the as-built runs ON Hades reading Hades-resident footage** — it is the *steady-state*
  spot-check, operating AFTER data has landed on Hades.
- **HARDWARE FACTS — corrected (Mo, 2026-06-24).** The `umi-qa` dashboard and the
  `data/hades-r730-dashboard` both run against the **R730**, which is **Pluto** — a *smaller* storage
  box in the **SF office** (`r730-storage`, Tailscale 100.119.90.17, mergerfs `/mnt/robot-pool` ~115T +
  a sensitive ZFS 3-way mirror ~17T; storage-health dashboard on `:8080`, copy-only discipline, never
  `--delete`). **This is NOT Hades.** **Hades** is the **datacenter** box — **~2.4 PB and being
  expanded** — the analytical system-of-record tier. So the as-built `umi-qa` currently reads footage
  from **Pluto** (`/mnt/robot-pool/umi-office-trials`), not Hades. (The repo folder is *named*
  `hades-r730-dashboard` but the server it targets is the R730/Pluto — a naming artifact, not Hades.)
  **Reconciliation for the Eunomia design:** the intended steady-state spot-check reads the **Hades**
  render (the 2.4 PB datacenter tier), per the topology; the *prototype* happens to run against Pluto
  today because that's where the office-trial footage currently sits. When Eunomia's pipeline lands,
  the dashboard points at Hades for the canonical render and falls back to **Styx** (Mexico) raw for
  the fresh window. "Athena" was a name previously recorded for a Hades-side compute box — its
  relationship to the 2.4 PB Hades store is still to be confirmed; treat Hades = the datacenter
  analytical tier and reconcile the specific machine names (Athena, the storage nodes) when that
  hardware is set up.

**RECONCILIATION — "hosted in Mexico" was really "reachable fast from Mexico."** The as-built `umi-qa`
is reached identically from Mexico + SF over the tailnet and reads Hades footage in steady state — it
does NOT physically run on Styx. Eunomia's genuinely-new contribution is the **fresh-window fast
path**: the priority-lane fast-track Styx→Hades + the Styx-raw tailnet fallback for episodes that have
NOT reached Hades yet (shrinking time-to-first-view below "wait for the normal drain"), plus folding
`umi-qa`'s selection/QA/review/scorecard model into the unified Eunomia system rather than a separate
Hades-side Flask app. So: the dashboard is **tailnet-reachable from anywhere** (Mexico + SF), reads
**Hades** footage in steady state, and reaches back to **Styx-raw only** for fresh-window episodes.
The "hosted in Mexico" instinct is satisfied by tailnet reachability — it need not physically run on
Styx. **Build-forward: adopt `umi-qa`'s proven model (sampling + bounded clip cache + review queue +
scorecards); add the fast-track lane + fresh-window fallback; unify it rather than leaving it a
separate app.**

**CARRY-FORWARD — sidecar contract shape vs the rig writer (from 0b).** Run 0b encoded the sidecar
with **nested clean-namespacing** (`identity`/`timing`/`provenance`/`outcome`/`files`) per CONTRACT §2,
overriding the as-built `pantheon-x3-sidecar/v2` which scattered provenance/outcome under
identity/top-level and used a zero-padded string `seq` + a top-level camera-clock timestamp. CONTRACT
won (clean namespacing; `seq` is int; no poison camera-clock timestamp). **Consequence:** the contract
sidecar shape now DIFFERS from what Victor's current discardd writer emits — the current rig output
will NOT validate as-is. **The firmware run (and/or 0c) must either (a) update the coordinator writer
to emit the nested contract shape, or (b) have ingest tolerate both the as-built flat shape and the
contract nested shape.** Log so it's not a surprise when firmware lands.

**CARRY-FORWARD — other 0b items (documentation, not 0a/0b fixes):**
- **Release hard/warn split** is currently implicit in the 0b schema (the agent's interpretation: hard
  = the join/identity/time keys Hermes needs; rest warn/nullable; `void⇒void_reason` hard). **Document
  this split back into CONTRACT §4** so it's explicit, not just encoded.
- **Telemetry per-event required fields** are modeled warn-optional in 0b (only the `event`
  discriminator is hard). **Future tightening** if per-event validation strictness is needed (would add
  N conditional rules — deliberately deferred to keep the generator lean).
- **Generator budget / interfaces:** 0b's generator is 358 lines (more field-types + one bounded
  conditional + shallow nesting — NOT a framework; real cross-field logic hand-written in `_semantics`,
  the OQ-3 boundary held). **0c's interface (operation-signature) shape is the real codegen
  STOP-and-flag line** — signatures don't fit the field-DSL at all; reconsider the codegen approach
  there. Per-emitter split (OQ-8) was NOT done (it breaks mypy-from-root under the no-config gate), so
  the generator stays a single sectioned file.

## Updates 2026-06-24 (late) — 0d approved + two Victor findings

**Run 0d — APPROVED, merging.** The operational model (9 entities + a polymorphic `operational-event`
record + event/as-of/rules-as-docs) implemented through the settled 0b machinery; `contracts/` is now
fully poured. Gates green (75 tests), drift = 0, the two single-record `_semantics` rules work
(episode `void⇒void_reason`, footage `spot_check_selected⇒selection_method`), and a programmatic scan
confirmed zero array-of-objects / zero 2-level nesting / zero nullable+enum across all 11 schemas
(the OQ-4 / OQ-B shape boundary held). The four new OQs resolved at annotation: **OQ-A** = hard-enum
only for DOMAIN-closed axes (side/scope/modality/footage_state/selection_method/pairing_method/op),
open-string + WARN-check for today-closed/growth-prone ones (hardware_unit.type/status,
person.role/status, operational-event.event_type) — the principle is "closed by the domain, not by
today's list"; **OQ-B** = calibration intrinsics → opaque object (the heavy data is consumed
Hermes-side from camera_intrinsics.json, not queried operationally), footage locations → scalar array
of strings, both STOP-and-flag edges (matrix / per-location objects) named not crossed; **OQ-C** =
operational-event is ONE polymorphic record (event_type discriminator + opaque payload) in
`contracts/events/`; **OQ-D** = the `session` entity IS the kit↔person binding (no 10th entity) +
a roster event for resolution outside a session window.
- **LEAD DEVIATION ratified — a 1-line `generate.py` bugfix (NOT growth).** 0d introduced the first
  scalar-only entities (kit/task/session/capture_stack/episode); every prior entity had a collection
  field, so the generator's unconditional `from dataclasses import dataclass, field` was always used,
  and scalar-only entities tripped ruff F401 (unused `field`). Fixed by emitting `field` in the import
  only when an object/array field exists (358→~360 lines). Ratified because it makes the existing
  emitter emit VALID Python for a field-shape always legal in the DSL but first exercised in 0d — the
  DSL, the emitters, and every 0b output are byte-identical (verified). The two alternatives were both
  worse: fake collection fields corrupt the model (anti-faithfulness); a `[tool.ruff]` per-file-ignore
  violates the no-ruff-config invariant. The agent correctly STOPPED and flagged it rather than
  quietly editing the generator. The "byte-identical generate.py" check was a proxy for "no generator
  growth"; this honors the intent. Also ratified: `nullable:true + enum` rejects null structurally, so
  `selection_method`/`hardware_unit.side` are non-nullable enums (omitted-not-null).

**FINDING + IN-FLIGHT (Victor, 2026-06-24) — SD-flash provisioning daemon.** The camera will NOT
surface its own connection info (MAC / AP / WiFi / IP, body + .insv serials) even plugged into a
laptop — the stock X3 doesn't expose it. This was the hidden friction in the bench provisioning step.
Victor is adding a **daemon on the SD flash** that, while the card is in the camera, collects the
needed connection info and **pushes it to the fob over telnet** — the SD card becomes the agent that
extracts what a human can't read at the bench. **Where it lands in our design:** the fields are
exactly the `hardware_unit.provisioning` group the contract already models (0d) — only the SOURCE
changes (SD daemon → fob over telnet, not a human); it is part of the **camera-image** module and is
received by the **coordinator** over telnet (a new CoordinatorPort op, or rides the existing channel —
a FIRMWARE-RUN design input). It simplifies the provisioning flow: "capture serial/MAC/AP/IP against
the unit" becomes "the SD daemon reports the connection info to the fob," removing the can't-read gap.
Recorded in hardware-findings §2.5. **NOTE: Victor is actively improving his stack — treat his
in-flight work (this daemon, and others) as inputs to reconcile, not settled given facts.**

**DESIGN RULE generalized (observed across rig runs, 2026-06-24) — button feedback applies to ALL
delayed fob buttons, not just START.** The instant-ack + working-state + lockout treatment (UI layer)
backed by the "valid only from the right state, extra taps dropped" core guarantee was specced for
START (the ~3 s pipeline re-init worst case). It now applies to **every fob control whose action has a
perceptible delay** — any button where the fob does network/telnet/OSC work between the touch and the
result and the operator could wonder whether the tap landed: STOP (finalize/flush latency), and any
settings/sign-in/confirm action that round-trips to the camera network or the god's-view server. The
principle: the visual acknowledgement is decoupled from the slow action on every button, and no button
can be double-fired mid-action — the operator never guesses whether a press landed, regardless of
which control. A genuinely-instant button needs no working-state (the rule is scoped to "perceptible
delay"). Folded into SPEC §1.8 (retitled from START-only to the general rule).

## Firmware prior-art reconnaissance 2026-06-24 (the WiFi-OSC fob is the live direction)

**CORRECTION — there are TWO fob source trees; the WiFi-OSC one is current.** In
`github.com/Pantheon-Industries-Inc/x3-capture-kit` (the predecessor repo, the source to build the
firmware run on):
- `ble_bridge/esp32-fob/` = the **OLD BLE fob** (fw 2.1.0). Its README says "WiFi purged 2026-06-22"
  — that purge applies to THIS variant only. The handoff says explicitly: "do not confuse/overwrite."
- `ble_bridge/esp32-fob-wifi/` = the **LIVE WiFi-OSC fob** (fw 3.8.3), validated end-to-end on the
  rig **2026-06-23** (AFTER the BLE README date). **This is the direction Eunomia was designed
  against — our WiFi/OSC/telnet/SoftAP model is correct, NOT stale.** (Initial recon misread the BLE
  README as current; Mo corrected — there IS WiFi firmware; Victor is sending more soon.)

**PROVEN RIG FACTS (from `HANDOFF_2026-06-23_WIFI_OSC_TRIGGER.md` + the two companion docs
`X3_LIVE_TRIGGER_EXPERIMENTATION.md` / `_REPLICATION.md`) — these are now confirmed constraints, not
design assumptions, and the firmware run MUST build on them:**
- **Architecture:** the ESP32/CYD fob hosts a **2.4 GHz SoftAP** (`PANTHEON-kit_<n>`, OPEN,
  192.168.42.1, DHCP .2–.6); both X3 cameras join as **WiFi STAs** (via the `S99zfobjoin` supervisor
  = persistent direct `wpa_supplicant` join, ZERO OSC); on GRABAR/DETENER the fob drives each cam over
  **OSC :80** (start/stop) + **telnet :23** (metadata env + clip name). This is exactly the
  CoordinatorPort + swappable-transport model.
- **THE TWO HARD RULES (violating either breaks it):** (1) **Zero background OSC** — the X3 cherokee
  OSC server is single-threaded and **CRASHES on concurrent/overlapping OSC**; so camera-presence is
  tracked at **L2 only** (`esp_netif_get_sta_list` / the AP DHCP-station table, NO OSC polling), the
  camera supervisor does zero OSC, and the fob emits OSC **only** at GRABAR/DETENER, **serialized
  under `wifiLock`**. (2) **discardd locks video mode; the fob does NOT arm per take** — discardd
  continuously re-asserts `RES_3008_1504P100`/`captureMode=video`, so the fob fires `startCapture`
  directly. Recording DEPENDS on discardd running on every card. (Both match our decisions exactly.)
- **The ~3 s start delay is real + root-caused:** the X3 re-initializes its capture pipeline at
  `startCapture` (live-view blackout + front-lens flash). This IS the justification for the SPEC §1.8
  button-feedback rule. **Proper fix = camera-side PRE-ARM via discardd's ambashell path** (OSC prearm
  is DEAD on X3 fw 1.1.6 — `prearm_osc_skipped`). The big remaining latency win, camera-side, Eric's
  discardd has prearm logic.
- **Camera clock is POISON** (no RTC, jumps backward) — confirm a recording by clip COUNT
  (`ls | grep -c VID_`) or file growth, NEVER by timestamp. (= our C-10, verbatim from the rig.)
- **OSC transport details the firmware run needs:** OSC has an **off-by-one RESPONSE lag** (the
  response is the PREVIOUS request's result) and the POST blocks the full timeout — so the fob
  **fires-and-forgets** (`oscSendNoWait`: raw socket, send+flush+~120ms grace+close, never read the
  body); the clip filename comes from **telnet `ls`**, never the OSC response. `startCapture` with NO
  card crashes cherokee → reboot to recover (discardd gates on a present card). **NEVER edit
  `/pref/wifi.conf`** (STA-to-absent-SSID = soft-brick); NEVER use `sta_start.sh`/`sta.sh` (kills
  instaAIP / band-locks). exFAT only; `curl -4` always (NAT64 tether trap).
- **Metadata-at-capture refines the join:** discardd stamps a per-clip `VID_<ts>_<seq>.pantheon.json`
  (station/task/episode/seq/record_settings) on the SD AT capture. So the **live-metadata channel is
  PRIMARY; the order-join (`pipeline/trigger_join.py`, Nth START ↔ Nth clip) is the FALLBACK** — and
  live metadata enables collect-anywhere (incl. operators at home), nothing depends on office WiFi.
- **Live firmware state:** fob `3.8.3-fast-guard`; cameras `Insta360X3FW_fobjoin.bin` rev4
  (md5 0ddc285e…); discardd installed on both cards. The fob version history (3.1.1 → 3.8.3, with
  marked DEAD-ENDS: 3.5.0 flush re-crash, 3.8.1 start-first broke stop, GPS/BLE data channels dead,
  OSC prearm on 1.1.6 dead) is the hard-won state the run must build ON, not rediscover.
- **Provisioning-daemon reconciliation:** in the WiFi-OSC world the fob HAS telnet (:23), so Victor's
  "SD daemon pushes connection info to the fob over telnet" is COHERENT here (it would not have been in
  the BLE-only world). The daemon fits the WiFi-OSC architecture cleanly. Camera fob-target is
  provisioned in NAND (`/pref/pantheon_fob.env`, survives flash); the zero-touch goal derives
  `FOB_SSID` from the NAND kit_id.

**DECISION — HOLD the firmware-coordinator prompt until Victor sends his update.** The firmware run is
the most coupled to Victor's in-flight work (the WiFi-OSC fob 3.8.3, the SD provisioning daemon, and
whatever he's improving). Writing the prompt against a fast-moving snapshot risks a prompt that's wrong
by run time (initial recon nearly baked in a backwards "BLE-only" assumption). When Victor's update
lands, fold it in, THEN write the prompt — build-on-Victor's-proven-firmware (Mo's call) means reading
his actual current code, not a point-in-time reconstruction. The four firmware design inputs still
stand (implements CoordinatorPort; emits the nested sidecar shape — the 0b carry-forward; instant-ack/
lockout/spam-safe on all delayed buttons — SPEC §1.8; receives the SD-daemon provisioning push over
telnet). Add to them: build on the `esp32-fob-wifi` 3.8.3 lineage + honor THE TWO HARD RULES.

## Victor's firmware bundle received + read 2026-06-24 (`pantheon-x3-firmware_2026-06-24.zip`)

Victor delivered the full firmware bundle (rootkit v0.7.1, capture KIT_VERSION 0.10.0). Three parts:
**camera/** (`Insta360X3FW_fobjoin_rev4.bin`, md5 `0ddc285e…` — matches the handoff; + a STOCK
recovery bin), **fob/** (compiled ESP32 binaries only — `fob_MERGED_flash_at_0x0.bin` + parts; the
build still reports `3.8.3-fast-guard` but INCLUDES the 2026-06-24 fixes: channel-11 avoidance,
`lockcams /osc/info`, the battery-swap/ghost-REVISA guard; fob source lives in the repo's
`esp32-fob-wifi/`), and **sd-card-rootkit/** (the authoritative readable source: `discardd` is a
~2017-line POSIX shell script, plus `bootup.sh`, `x3_join_fob.sh`, `x3_fob_link.sh`, `autoexec.ash`,
`install_sd_rootkit.sh`, `S61discardd`, and the `fobjoin_arm64`/`armv7` static binaries). This CONFIRMS
the WiFi-OSC direction is live and gives the firmware run its real ground truth.

**⭐ THE 0b SIDECAR CARRY-FORWARD — RESOLVED with the exact shapes (correcting my earlier imprecise
note).** discardd's `pantheon-x3-sidecar/v2` writer (the `cat > "$sidecar"` block) IS nested — NOT
"flat/scattered" as I'd loosely recorded. The real shape:
- Top-level: `ts` (the agent's own write-time string, NOT used as authoritative time), `schema`
  (`pantheon-x3-sidecar/v2`), `kit_version` (= the capture-stack version string), `layout`,
  `timestamp`, `seq` (a QUOTED STRING — confirms the int-vs-string divergence), `qc_status`,
  `qc_reason`, `global_episode_seq` (int), `archive` (int 0/1), `back_size`/`front_size`,
  `record_format_version` (int).
- `files`: nested `{back,front,lrv}` each `{raw, canonical}`.
- `timing`: nested `{started_unix, stopped_unix, start_skew_ms}` — fob-sourced (NTP), the AUTHORITATIVE
  time (camera clock is poison; the top-level `ts` is just the agent's write moment).
- `identity`: ONE big nested block holding EVERYTHING else — `camera_id, kit_id, side, operator_id,
  station_id, site_id, task_id, task_name, prompt, task_source, session_id, episode_id,
  bimanual_episode_id, fob_id, fob_build, camera_firmware, stop_reason, rotation_id, calibration_id,
  record_settings`.
- **The precise divergence from the 0b contract:** the rig LUMPS provenance (`fob_id`, `fob_build`,
  `camera_firmware`), outcome (`stop_reason`), and assignment (`task_*`, `prompt`) all INSIDE
  `identity`; the 0b contract split these into clean `identity`/`timing`/`provenance`/`outcome`
  namespaces. So it's NOT "flat vs nested" — both nest — it's **"one big `identity` block" (rig) vs
  "clean-namespaced sub-objects" (contract)**, plus string-vs-int `seq` and `pantheon-x3-sidecar/v2`
  vs `eunomia-sidecar/v1`. **The firmware-run decision (unchanged in spirit, now exact):** either
  discardd's `identity` block is split into the contract namespaces, OR ingest tolerates the rig's
  lumped shape. This is a firmware-vs-ingest call; the exact field lists on both sides are now known.

**CONFIRMED FROM THE LIVE CODE (decisions we'd made, now verified against discardd):**
- **Two-axis versioning is REAL in the writer:** `kit_version` (capture-stack/record version string)
  ⊥ `record_format_version` (forensic build-scoping int), with discardd's own comment pointing at
  `pantheon_sidecar_schema.py` "Record-format version." Exactly CONTRACT §5.
- **Front-lens / IMU policy RESOLVED + mechanism confirmed:** the IMU (gyro/accel) track is embedded
  ONLY in the FRONT `_00_` `.insv` (the back `_10_` reports "unsupported"). So discardd KEEPS the
  front on-card through offload (`DELETE_FRONT_AFTER_KEEP=0` default); the front HEMISPHERE imagery is
  dropped DOWNSTREAM at ingest via `insv_to_imu_json.py --extract-imu --drop-front`, never on-cam.
  This is exactly our "IMU extraction stays Eunomia/ingest-side; front dropped from training AFTER
  extraction" boundary — now with the precise reason (lose the front file = lose the IMU forever).
- **CAPTURE_LAYOUT for 3K/100 = `single`:** ONE `.insv` (tagged `_00_`) holding BOTH fisheye circles
  side-by-side (2944×1472 = two 1472×1472 circles); `.insv` not `.mp4` is Insta360's container for any
  360/dual-fisheye take; that single file IS the keeper, nothing disposable, front-delete must NEVER
  run. (Hardware-confirmed 2026-06-19.) Refines our "dual-fisheye SBS" detail with exact dims + keeper
  logic. (`auto` default detects dual-vs-single per-seq for back-compat with legacy 5.7K30 pairs.)
- **Archive-on-DESCARTAR is non-destructive:** the fob fires `/tmp/archive.trigger`; discardd KEEPS
  the clip, re-stamps `archive=1` + `stop_reason=operator_discard` + an `archive_marked` ledger entry,
  so ingest routes it to the archive bucket. Matches our `archive`/`stop_reason` fields + void-by-flag.
- **NAND `/pref/` identity layout confirmed:** `pantheon_camera.env` (identity), `pantheon_current_
  task.env` (task/prompt — carries ONLY task fields, never identity; live SD `current_assignment.env`
  overrides; = our task-precedence + the "self-stamp task even when the cam never sees a live
  assignment" path), `pantheon_episode_seq` (NAND monotonic per-camera counter, survives SD + battery
  swaps = our durable global_episode_seq ordinal).
- **discardd's hard boundary = our transport/core split, verbatim:** "this agent NEVER touches wifi,
  ap_start.sh, wpa_supplicant, bt_stop.sh, or any network lifecycle… network bring-up belongs to
  instaAIP." (After a 2026-06-10 incident that hung LEFT's UI.) Confirms the no-background-network +
  zero-OSC-poll rule from the camera side.
- **Trigger mechanism = file-touch:** the fob drives discardd by touching `/tmp/{discard,archive,
  front_cleanup,health,start_at,stop_at,sync_arm,latency_probe}.trigger`; `start_at`/`stop_at` carry
  line1=epoch (may be fractional for sub-second cross-cam sync), line2=episode_id. The fob writes
  per-take outcome + cross-cam timing to `current_stop.env` at STOP, bound to the take by
  `bimanual_episode_id` so a stale stop file is never mis-applied.

**NEW / IN-FLIGHT details for the firmware run:**
- **Cross-cam START sync work (the ~3s-latency "proper fix"):** measured BLE trigger reaches both cams
  in ~6µs, but each cam's record-start lands ~32ms median (25–272ms) later because the encoder
  COLD-STARTS per shutter. The fix is camera-side PRE-ARM (`PREARM_MODE` loopRecording/preRecord, and
  `PREARM_DELAY_S` via the X3's built-in shutter selftimer with PCM countdown beeps — both cams run the
  SAME firmware countdown → variance collapses toward the ~33ms frame floor). **HARD-WON: `t app test
  prerecord start` in `autoexec.ash` HANGS THE BOOT** (autoexec runs before the capture pipeline
  exists) — prearm is now done via the LIVE AmbaIPC PT_ service (0x20000008) AFTER full boot, not at
  boot. OSC prearm is dead on X3 1.1.6. This is in-flight, camera-side, the big remaining latency win.
- **A WiFi-join STRATEGY divergence in Victor's own code (read the delivered code, not one handoff):**
  the WiFi-OSC handoff said "NEVER use `sta.sh`/`sta_start.sh` (kills instaAIP / band-locks)" and the
  `S99zfobjoin` supervisor used direct `wpa_supplicant`; BUT the delivered `x3_join_fob.sh` says "THE
  ONE CORRECT WAY: `wifi_stop.sh → load.sh sta → sta.sh`" (the vendor STA path, because skipping
  `load.sh sta` leaves the radio in AP-firmware mode → SIOCSIFFLAGS). These are two different join
  approaches in his own tree — an active evolution. **LESSON: the firmware run's agent must read the
  ACTUAL delivered scripts as ground truth, not reconcile from a single handoff doc.** It also has a
  mature self-healing health model (IP+OSC both required; "zombie" = IP-but-OSC-dead → rate-limited
  self-reboot; no-IP → re-join only, never boot-loop).
- **`autoexec.ash` = the Ambarella RTOS boot hook** (the RTOS owns sensors/ISP/encoder = ~80% power +
  nearly all heat; cpufreq on the Linux side barely matters). Power/thermal levers (single-lens-back
  `focusSensor=2`+`expectOutputType=1`+`stitch_enable=0`, `preview_mctf_enable=0`, `flow_state_level=0`,
  `mute=1`) are set by discardd over OSC at boot, NOT via autoexec verbs.

**Implication for Eunomia:** the camera-side + fob behavior is FURTHER ALONG and more proven than the
contract assumed — and it largely MATCHES (two-axis versioning, the IMU/front policy, the durable
ordinal, the task-NAND path, the archive path, the transport/core boundary). The firmware run is
therefore mostly ADAPTER + RECONCILIATION work (build on this proven stack, emit/tolerate the contract
shape, implement CoordinatorPort over the real OSC/telnet/file-trigger mechanism), NOT a rewrite —
matching Mo's "build on Victor's proven firmware, rewrite only what the clean architecture requires."

## Run F1 plan APPROVED 2026-06-24 — decisions locked (the coordinator on Victor's stack)

The F1 plan (firmware/coordinator, plan-only) came back strong: the agent read Victor's delivered code
in full (discardd ~2017 lines, bootup.sh, the join scripts, install_sd_rootkit.sh, autoexec.ash) and
its load-bearing findings VERIFY against the actual source (I checked bootup.sh + install_sd_rootkit.sh
myself — both confirmed, and finding 1 corrected MY earlier imprecise read, not the agent's). Decisions:

- **SCOPE = SPLIT (LEAD-OQ resolved). F1 = `coordinator/core/` ONLY; F2 = `transport/` + `ui/`.** core/
  is authored-not-adapted, provable off-target with `pio test -e native` (no rig), and unblocks the
  rest. The decisive new reason: **Victor's fob C++ source is NOT in the bundle or the Eunomia repo** —
  it lives in `x3-capture-kit/ble_bridge/esp32-fob-wifi/src/main.cpp` (fw 3.8.3). transport "adapts
  Victor's source," so F2 is BLOCKED until that source is in reach. → **F2 PREREQUISITE: vendor/obtain
  the esp32-fob-wifi source into the F2 worktree before starting it** (vendoring it under the repo is
  the natural "build on Victor's, adopt where it works" move; decide at F2).
- **SIDECAR RECONCILIATION = (C) HYBRID (the headline decision).** core/ assembles a complete
  `eunomia-sidecar/v1` record from the coordinator-owned fields = the coordinator's CONTRACT SURFACE
  (what F1 conformance-validates off-target + what feeds the god's-view/ordinal-join backup). discardd
  keeps writing `pantheon-x3-sidecar/v2` on the card **UNTOUCHED** (his code is actively evolving;
  changing his writer races his work). The `v2→v1` shape reconciliation lands at INGEST (a later run),
  joined by `episode_id` (identical both arms). Converging discardd→v1 (option A) is a SEPARATE,
  coordinated change owned WITH Victor — explicitly out of F1. **One-source-two-projections (confirmed
  at annotation):** core/ holds ONE source of truth (the coordinator-owned field set) with TWO
  projections — (a) the v1 record (backup/god's-view/conformance), (b) the env files
  `current_assignment.env`/`current_stop.env` that discardd consumes — never double-maintained.
- **THE BIGGER MECHANISM DIVERGENCE the code revealed (reframes write_sidecar):** CONTRACT §1.7 models
  the FOB telnet-writing the sidecar twice. **Victor's stack does not work that way** — the fob pushes
  `current_assignment.env` (identity/task, before START) + `current_stop.env` (outcome+timing, at STOP,
  bound by `bimanual_episode_id`) and touches the trigger files; **discardd assembles + writes the
  single `.pantheon.json` camera-side** on clip detection. So **`CoordinatorPort.write_sidecar` on this
  stack = push the two env files**; the §1.7 two-write INTENT (identity known before the clip, outcome
  bound at stop) is realized by the env mechanism, not a fob-written JSON. [CONTRACT §1.7 should be
  annotated to match the real mechanism in a later docs pass — NOT YET FOLDED IN.]
- **GROUND-TRUTH FINDINGS verified against the code (his code wins):** (1) **WiFi join on the delivered
  rev4 camera = the NAND `S99zfobjoin` supervisor** — bootup.sh seeds `/pref/pantheon_fob.env` and lets
  the supervisor own the join; it launches NEITHER x3_join_fob NOR x3_fob_link on rev4 (running
  x3_fob_link too makes them FIGHT over wlan0, STA↔AP flap every ~23s, verified kit_55). Preference
  order S99zfobjoin(rev4)→x3_fob_link(pre-rev4)→x3_join_fob(legacy). The handoff's "x3_join_fob is THE
  ONE CORRECT WAY" is stale; **F1 only hosts the OPEN SoftAP `PANTHEON-kit_<n>` @192.168.42.1, DHCP
  .2–.6; the join is camera-side + Victor's, untouched.** (2) **"Zero background OSC" = zero CONCURRENT
  OSC** — discardd DOES emit idle video-mode reasserts, but `LOCK_REASSERT_S` was raised 5s→3600s
  (install_sd_rootkit.sh:89-96) precisely because the 5s reassert collided with the fob's startCapture
  on the single-threaded cherokee server (~3s desync, verified kit_56). F1's cross-actor obligation:
  don't reintroduce OSC contention; presence is L2-only (`esp_netif_get_sta_list`), OSC only at
  GRABAR/DETENER under `wifiLock`, fire-and-forget (`oscSendNoWait`).
- **The 7 OQs resolved:** OQ-1 split (above); OQ-2 hybrid-C (above); **OQ-3** flip `pio run -e esp32` to
  blocking at end of F1 — BUT write core/ to ESP32 constraints from the start (no C++ exceptions, no
  RTTI, heap-aware; UUIDv4/clock/NVS stay behind the injected seams so core/ never calls a platform
  API directly) and RUN the esp32 build of core/ during F1 as a portability smoke test — a non-clean
  esp32 build is a REAL core/ portability finding to surface, not a reason to silently defer; **OQ-4**
  `recording_suspect` (NET-NEW, coordinator-owned = the fob's STOP-time telnet-`ls`-grew check) carried
  ONLY in the coordinator's v1 record for F1, no discardd change; **OQ-5** the SD-daemon provisioning
  RECEIVE path = an out-of-band transport channel feeding an operational `hardware_unit.provisioning`
  record (NO contract change; it's operational-model data, not the capture-trigger contract; Victor's
  daemon, an F2 receive at most); **OQ-6** transport fires OSC `startCapture` DIRECTLY; writing
  `start_at.trigger` (prefer the monotonic `U<uptime>` form) to feed discardd's precise cross-cam fire
  is OPTIONAL and OFF until Victor's pre-arm/cross-cam-sync lands — F1 neither implements nor depends on
  pre-arm; **OQ-7** `fob_session_id` minted in core/ (random per boot, the fob-swap disambiguator),
  rides the ordinal-log + the operational `session` record (0d), NOT the sidecar; ingest keys on
  `(kit_id, fob_session_id, ordinal)`.
- **The fob-side ordinal-join ring buffer is NET-NEW vs discardd** (an independent backup medium for the
  order-join: append-at-START, episode_seq+NTP wallclock+kit/fob id, ≥2-day self-bounding, durable-to-
  flash BEFORE the counter advances per SPEC §1.8). discardd has only the camera-side NAND
  `global_episode_seq`; the fob log is the independent second medium.

## DECISION 2026-06-24 — operator_id ⊥ kit_id (Victor's fob collapses them; we restore the split)

**Finding (Victor):** his fob bakes identity as `kit_id` (`-DFOB_KIT_ID`/`cmd kit=`) and the BLE-fob
README states "operator identity is no longer tracked on the fob" — i.e. on the device the kit IS the
identity, with operator collapsed into / equated with kit. Reasonable for "flash a fob per kit, ship
it," but it conflates two axes the operational model deliberately separates.

**Where the collapse actually lives (checked the code):** NOT in discardd. discardd keeps `KIT_ID`
and `OPERATOR_ID` as fully separate variables (discardd:390/394), separate sidecar `identity` slots
(1339/1341), and never derives operator from kit (`KIT_ID` falls back only to `RIG_ID`, never to
operator, :448). **The camera-side writer is already correct.** The conflation is on the FOB: it
dropped operator as a concept, so whatever it pushes into `current_assignment.env`/the NAND task env
for operator is degenerate (kit value or empty). discardd faithfully records whatever the fob sends.

**Decision — restore the two independent identity axes (this is the person ⊥ kit decoupling 0d is
built on):**
- The OPERATOR signs in with their own `operator_id` at the fob (SPEC §1.8 sign-in). One operator can
  use ANY kit; the system RECORDS the (operator, kit) pairing for that session rather than baking it.
- `kit_id` stays the fob's PROVISIONED identity (Victor's "the fob is assigned to a kit" is kept). We
  just stop treating the kit as the operator.
- The operational `session` record (person_id + kit_id + window, 0d) is the system-of-record for
  "operator X used kit Y this shift." Episodes resolve **operator-from-session, kit-from-fob,
  side-from-NAND** (identity precedence §3.3). Why it matters: operator drives the Mexico
  feedback/scorecards; kit drives hardware-fault tracing + calibration; collapsing them makes a kit
  fault and an operator pattern indistinguishable in the data.

**Where the fix lands = F1/F2 (the fob coordinator), with ZERO contract change and ZERO discardd
change.** Operator identity becomes part of what `core/` tracks (operator sign-in state) and projects
into `current_assignment.env` as a field DISTINCT from `kit_id`. Once the fob pushes a real
`operator_id ≠ kit_id`, discardd's sidecar is correct automatically (the slots already exist). Folded
into the F1 prompt's `core/` scope. The contract (`identity.operator_id` ⊥ `identity.kit_id`,
sidecar) and 0d (`person`/`kit`/`session` as separate entities) already model this correctly — no
schema edit.

## F2 prep 2026-06-24 — pulled Victor's WiFi-OSC fob source; README + header both stale

Pulled `esp32-fob-wifi/` from `x3-capture-kit` (authenticated Chrome). Findings (the prerequisite for
F2 = the fob source) — and TWO stale-doc gotchas the ground-truth rule caught:

**CONFIRMED: `ble_bridge/esp32-fob-wifi/src/main.cpp` IS the WiFi-OSC fob.** Single file, **3240 lines
/ 160 KB**, fw **3.8.3-fast-guard**, commit **a38f5a9** ("x3-wifi-fob: sync fob fw 3.8.3-fast-guard;
discardd validated end-to-end") — matches Victor's delivered binary exactly. The file header is
explicit: "Pantheon X3 WiFi-OSC Fob — triggers two Insta360 X3 cameras over WiFi and writes a
per-episode metadata sidecar onto each camera's SD." The prerequisite is satisfiable from the repo.
- **GOTCHA 1 — the folder README is STALE:** it describes a BLE-trigger + WiFi-*upload* fob (GATT, the
  trigger log POSTed over WiFi) and its build steps say `cd ble_bridge/esp32-fob` (the OLD folder). It
  was copied from the BLE fob and never updated. IGNORE it; the code is WiFi-OSC.
- **GOTCHA 2 — even main.cpp's own top comment is partly STALE:** it describes the original lineage
  ("one camera is the WiFi AP hub and the fob STA-joins it," the coordinator.py port), but the actual
  code has the **FOB hosting the AP** (`apEnsureUp`/`apSsid`/`apChannel`, matching the bundle's
  `PANTHEON-kit_<n>` @192.168.42.1 with cameras joining IT). The prose topology is INVERTED from what
  the code does. → The ground-truth rule bites TWICE in one folder (README + file header both trail
  the code); F2's agent must read the CODE, not the comments.

**Structure (the symbol map — F2's adaptation targets):** `FobConfig` (NVS identity/assignment),
`Cam` class + `StartGate` (the SD-pass gate: a take is refused unless every cam reports
cardState=pass), `makeFobSession` (**per-boot fob_session_id via `esp_random()` — matches our OQ-7
exactly**), the locks `wifiLock`/`camLock`/`fsLock`, `wifiJoin`/`apEnsureUp`/`apSsid`/`apChannel`/
`scanBestWifiTarget` (AP hosting + uplink-borrow), `macAllowed` (the RPA-proof MAC allowlist),
`appendEpisodeLine`/`logStart`/`logStop`/`logDelete` (the LittleFS episode log), `apiRequest`/
`wifiUploadBurst`/`refreshLiveTelem` (the idle uplink upload + telemetry), the UI screens
`SCREEN_PROVISION/MESA/MAIN/CONFIRM/CONFIRM_ID`, `CamTelem`.

**platformio.ini (F2's build basis):** `framework=arduino`, `platform=espressif32@^6.5.0`,
board `esp32dev`, **default env `cyd`**, partitions `min_spiffs.csv` (dual app slots → OTA-capable),
deps `bodmer/TFT_eSPI@^2.5.43` + `bblanchon/ArduinoJson@^7.0.4`, filesystem `littlefs`. The CYD TFT
config (ILI9341_2 driver + the documented red/blue-swap + inversion color-fix flags + pins). Telemetry
gates `PANTHEON_TELEM_RELAY`/`PANTHEON_TELEM_BLE` OFF by default. **"WiFi runs on the core-0 worker (it
no longer blocks the touch loop)"** — confirms the dedicated-core wifiTask (UI on one core, WiFi on
core 0) that makes the instant touch-ack possible. **NO BLE stack** — the single 2.4 GHz radio is STA
(camera hub AP + brief uplink borrow).

**FRAMEWORK BOUNDARY (key for F2):** Victor's fob is Arduino-framework (TFT_eSPI + ArduinoJson +
LittleFS + HTTPClient). Our `core/` is pure C++17, framework-free (proven to cross-compile under
env:esp32, `-fno-exceptions -fno-rtti`). So **F2's `transport/`+`ui/` are Arduino-framework code
(adapted from Victor); `core/` stays pure; `seams.h` is the boundary** — do NOT pull Arduino/TFT/JSON
into `core/`. The seams (`CaptureFleet`/`CaptureDevicePort`, `PresenceSource`, `PersistentStore`,
`Clock`/`Rng`, the uplink) are what transport implements with the real ESP32/WiFi/OSC/telnet/NVS.

**REFINEMENT to the earlier operator⊥kit note (IMPORTANT — I conflated two fobs):** my earlier entry
said "Victor's fob collapses kit==operator." That was the OLD **BLE** fob's README ("operator identity
is no longer tracked on the fob"). The **WiFi-OSC fob keeps `kit_id` and `operator_id` as SEPARATE NVS
fields** (config grammar `kit=`, `op=`, `station=`, `prompt=`) and has a REGISTRO flow + a
`SCREEN_CONFIRM_ID` "Are you <name>?" confirm (the typed kit# resolves a provisioned NVS identity,
caught before logging under the wrong person). So the WiFi-OSC fob is ALREADY closer to our
operator⊥kit model than the BLE README implied — it does carry operator distinctly. Our decision
stands unchanged (operator-from-session, kit-from-fob, the session binds them); F2 reconciles the exact
REGISTRO/confirm identity flow with our sign-in model, but there is no kit==operator collapse to undo
in the WiFi-OSC fob.

**VENDORING (F2's first action):** the faithful copy is a git operation, NOT a browser scrape (the 160
KB blob is virtualized; `get_page_text` only returns the first ~118 lines). F2 (Conductor, gh-authed
as Mzcassim) clones `x3-capture-kit` and copies `esp32-fob-wifi/{src/main.cpp, platformio.ini}` (+ reads
the companion docs FOB_AP_HARDENING.md, FW_2.2.0_CAPTURE_FIXES.md, RTC_TIMEKEEPING.md, and the repo-root
X3_LIVE_TRIGGER_REPLICATION.md/EXPERIMENTATION.md) into `firmware/coordinator/transport/vendor/
esp32-fob-wifi/` with a provenance note (repo, path, commit a38f5a9, fw 3.8.3-fast-guard, md5). Then
read main.cpp IN FULL under the ground-truth rule.

## Run F2 plan APPROVED 2026-06-24 — decisions locked (transport on Victor's WiFi-OSC fob)

The F2 plan-only pass came back strong: the agent vendored Victor's source, read main.cpp in full, and
its load-bearing findings VERIFY against the code (I checked uplinkUp line 969 + apChannel myself —
both confirmed). Decisions:

- **SCOPE = SPLIT (LEAD-OQ). F2 = `transport/`** (+ the headless app-glue + the core-0/core-1
  scaffolding + `env:cyd` building HEADLESS); **F3 = `ui/`.** Decisive reason (concrete, not
  theoretical): Victor's own `esp32dev` headless build runs the entire trigger/transport path with
  BOOT-button + serial as the only inputs — so transport stands alone and is validatable end-to-end
  (mock OSC/telnet + headless build + rig) before a pixel is drawn. The two-hard-rules correctness
  lands gate-green in its own PR; F3 only adds render/touch.
- **OQ-1 (the headline design call) = (A).** The X3 adapter's `start()` pushes `current_assignment.env`
  then fires OSC; `write_sidecar` pushes `current_stop.env`; the adapter gets the projected bytes from
  a provider callback the app-glue wires, calling `core::project_assignment_env(assignment,
  coordinator.take())`. Correct because `trigger()` populates `take_` BEFORE the `start()` loop and
  `take()`/`project_*`/`Assignment` are already public → **ZERO core change**, preserves Victor's proven
  env-then-OSC ordering. Guardrail: if `take_` isn't populated early enough / the accessor isn't public,
  STOP and flag — don't reach into core/ silently.
- **⭐ FINDING #5 / OQ-3 — NO FIELD WALLCLOCK (the biggest hardware finding, VERIFIED).** `uplinkUp()`
  has an unconditional `return false` at line 969 ("NEVER borrow the radio / tear down the SoftAP — the
  teardown drops EVERY camera"); everything below is dead code; `configTime`/NTP runs ONLY inside
  `wifiJoin(forUplink=true)` which is only reachable via `uplinkUp` → **NTP never runs, the `Clock` seam
  has no field source, `isoNow()` returns "" unless a serial `time=` is sent.** DECISION: **DS3231 RTC
  is the durable fix** (RTC_TIMEKEEPING.md; ~$1/fob; survives the 4–5×/day battery swaps; the only
  option not dependent on site WiFi or a daemon) — but the RTC is Victor's hardware, so for F2
  (software) the stopgap is serial `time=` at provision PLUS the loud-not-silent defenses
  (`recording_suspect`/`no_wallclock`/`needs_review` when `g_timeSet` is false; the ordinal-log `ms` for
  backfill). Untimed footage must be VISIBLY flagged, never silently recorded on a bad clock. → flagged
  to Victor as a hardware-coordination item (DS3231 or boot-time NTP-before-AP).
- **OQ-4 (TelemetrySink) = keep optional/best-effort/OFF** (the F1 seam; `flush_telemetry` is a no-op
  until a non-AP-destroying uplink exists; the durable ordinal-log backup is the fail-safe).
- **OQ-2 (PresenceSource handle mapping) = (B) MAC→side allowlist now** (depot-provisioned, entry
  0=left/1=right, RPA-stable), **migrating to (C)** the SD-daemon authoritative MAC→side binding when
  it lands. DHCP-lease order (A) too fragile. COUPLED to OQ-9: the allowlist needs the `lockcams
  /osc/info` fix (vendored `lockToConnectedCams` reads a never-populated serial → empty allowlist).
- **OQ-9 (the 2026-06-24 source gap) = (A) if reachable, else (B) with each delta flagged in the diff.**
  The vendored `a38f5a9` (2026-06-23) is BEHIND Victor's 2026-06-24 binaries — missing channel-11
  avoidance (vendored `apChannel` spreads `{1,6,11}`, confirmed), `lockcams /osc/info` (load-bearing for
  OQ-2), and the battery-swap/ghost-REVISA guard. Request the updated source; else adapt + re-derive the
  three deltas, each flagged. → flagged to Victor for a source refresh.
- **OQ-7-flow (operator sign-in) = (b)-lite** — keep REGISTRO's kit confirmation AND add operator
  selection at sign-in so `operator_id` is set per SHIFT, not baked per kit (the operator⊥kit decision
  realized at the UI: one operator roams kits, the session captures the pairing). Lands in F3; F2's
  `Assignment` must carry `operator_id` distinctly from the start (it already does — `project_assignment_env`
  emits `OPERATOR_ID`).
- **OQ-10 (env-key conformance with discardd) = REQUIRED in F2.** Diff `core::project_*`'s key set
  against what discardd's `load_envs` actually READS (the readable discardd source is in the bundle).
  Extra keys (TASK_ID/ROTATION_ID) harmless; a key discardd reads that core renamed/dropped
  (OPERATOR_NAME dropped, SESSION_ID shifted) silently loses a field — a real conformance check.
- **OQ-11 (clang-tidy) = flip to blocking, SCOPED to hand-written transport/+ui/** (exclude
  `transport/vendor/` + framework headers). And `build_src_filter` MUST exclude `transport/vendor/` —
  the vendored main.cpp is reference-only, never compiled.
- **OQ-5/OQ-8 (SD-daemon RX) = (A)** a bounded inbound TCP listener on the fob AP IP that does NOT talk
  OSC, feeding an operational `hardware_unit.provisioning` record — NO contract change, no new port op.
  The wire format/port is Victor's daemon's (in-flight) → SPEC the receive path but gate the wiring on
  confirming the format with Victor.

**Ground-truth findings the agent surfaced (his code wins) — the rule earned its keep FIVE times in
one file:** (1) the folder README is the BLE fob's, stale [known]; (2) main.cpp's top comment inverts
the AP topology (fob hosts AP, not camera) [known]; (3) NEW — the top comment claims the fob writes the
sidecar JSON (it pushes env files; discardd writes v2 — re-confirms option C); (4) NEW — vestigial
NimBLE/CE81/BE80 references throughout (no BLE stack; record state is the fob-authoritative `g_anyRec`
toggle; `setCamSupervision` referenced but doesn't exist) — dropped in adaptation; (5) NEW + verified —
the uplink-borrow is code-disabled (OQ-3 above). Vendored md5 `df64685…` (main.cpp) / `1e1b5d8…`
(platformio.ini), commit `a38f5a9`, recorded in `transport/vendor/.../PROVENANCE.md`.

**Victor-coordination items surfaced by F2 (for Mo's next sync):** (1) the fob needs a real field time
source — DS3231 RTC (preferred) or boot-time NTP-before-AP (OQ-3); (2) a source refresh to the
2026-06-24 fob with ch-11 avoidance + `lockcams /osc/info` + the battery-swap guard (OQ-9); (3) confirm
the SD-daemon provisioning push wire format/port (OQ-8).

## Victor's setup-app + 2026-06-24 fixes — read 2026-06-24 (integrate what's useful)

Victor shipped **`setup-app/`** in `x3-capture-kit` (commits `79e61d8`/`6365643`/`f96b97a`, handoff
`HANDOFF_2026-06-24_SETUP_APP_AND_FIXES.md`) — a one-screen Mac web app (FastAPI + browser wizard) that
builds a UMI kit end-to-end with buttons, no terminal. Proven end-to-end on fresh hardware (kit_58).
Read the handoff, README, and the key source (`kitsetup/cameras.py`, `kitsetup/netwifi.py`) + the
package layout.

**⭐ THE 2026-06-24 FIXES — these CLOSE several open F2/firmware OQs (they are now KNOWN, in `main` of
x3-capture-kit, NOT pending):**
- **OQ-9 RESOLVED (the source gap):** the three deltas the vendored `a38f5a9` was missing are now
  landed: **ch-11 dead** → `apChannel` `{1,6,11}`→**`{1,6,6}`** (ESP32 SoftAP reports up on ch11 but no
  client can associate; `kit_num%3==2` hit it on kit_56); **`lockcams` /osc/info** → a one-shot
  `/osc/info` per cam at lock time learns the full `IAQEB…` serial (fixes the empty-allowlist bug =
  OQ-2's dependency); **start-sync** → `LOCK_REASSERT_S=3600` AND it now reaches discardd's env at
  launch via `bootup.sh` `set -a; . config.env` (the in-loop source alone didn't reach the reassert
  guard). **F2 should adapt from the UPDATED source, not `a38f5a9` — pull the newer fob source** (the
  re-derivation fallback is no longer needed; OQ-9 → option A is now available).
- **REVISA-after-battery-swap fix:** the card-check required EVERY station (`nOk==nTot`); a ghost
  station (a battery-pull lingers ~18h in the AP table) failed it → now `nOk>=kMinCams`. Relevant to
  our presence/`detect_drop` logic — a lingering ghost STA must not block GRABAR.
- **rev4 auto-join bootstrap (confirms the F2 finding):** on rev4, `bootup.sh` seeds/re-points NAND
  `/pref/pantheon_fob.env` from the SD hint and lets the `S99zfobjoin` supervisor join (NOT
  `x3_fob_link`, which fights it = the STA↔AP flap). Exactly the F2 register finding, now also handling
  reused cams (re-points stale NAND).
- **Flashing:** CYD USB-serial drops mid-write at 460800 → `upload_speed=115200` + app auto-retry; a
  half-written board is NOT bricked (bootloader intact). (Provisioning-tooling detail.)

**⭐ THE CONSTRAINT MO FLAGGED — tethered internet is NON-CIRCUMVENTABLE, and it's CODE-ENFORCED.**
`kitsetup/netwifi.py::uplink_safe()` checks `route -n get default` and **refuses to switch `en0` to a
no-internet cam/fob AP unless a non-WiFi uplink (USB tether / ethernet) carries the internet** —
otherwise joining the AP would strand the Mac. This is the "channel must be open to be used on the fob"
rule: provisioning a fob/cam requires the laptop to keep its internet on a *different* interface
(plugged-in phone hotspot over USB, or ethernet) while `en0` joins the cam/fob AP. **Eunomia's
provisioning console MUST carry this exact safety gate** (don't switch the provisioning machine's WiFi
to the AP unless the default route is already off-WiFi). Plus the one-time-internet need: first run
installs pip deps + the PlatformIO esp32 toolchain (hundreds of MB, once).

**⭐ THE PROVISIONING LOGIC — directly relevant to Eunomia's provisioning console + the SD-daemon
RECEIVE OQ.** `kitsetup/cameras.py` is the proven flow (the fragile WiFi step made one-click): read the
camera's **real body serial over telnet** (the AP-SSID file `X3 <serial>.OSC`, or a LOCAL
`/osc/info` — one deliberate cherokee-safe OSC call — never trust a human label), look up its **side in
the fleet registry**, and write `/pref/pantheon_camera.env` (NAND identity: CAMERA_ID/KIT_ID/SIDE/
MOUNT) + the fob target over telnet; **discardd applies identity live, no reboot**. `scan_fob()` reads
all cams on .2–.6 so the UI fills the register instead of an operator reading tiny labels.
**Relationship to our SD-daemon RECEIVE path (F2 OQ-5/OQ-8):** this is the *Mac-side, AP-join*
provisioning that exists TODAY. Victor's in-flight *SD-daemon* (pushes connection info to the fob over
telnet) is the EVOLUTION that removes the manual cam-AP-join step. So the provisioning has two
generations: (gen-1, shipped) the setup-app reads serial + writes identity over telnet from the Mac on
the cam AP; (gen-2, in-flight) the SD daemon self-reports from inside the camera to the fob. Our
console should target gen-2's model but the gen-1 logic is the reference for the telnet identity write.

**The setup-app structure (FastAPI):** `server.py` (the app + endpoints), `kitsetup/` package
(`sd.py` = erase→exFAT→discardd→firmware→md5-verify; `fob.py` = USB detect + PlatformIO flash + set
kit#; `cameras.py` = the telnet provisioning above; `fleet.py` = the YAML registry via
`fleet_registry.py`; `netwifi.py` = the uplink-safety gate; `jobs.py` = job/log orchestration;
`cfg.py`/`util.py`), `static/` (the wizard UI), `config.json` (repo-relative paths), `launch.command`,
`firmware/` (rev4 cam bin + fob build via Git LFS, ~94 MB).

**DECISION — what's useful to integrate into Eunomia (NOT a wholesale adopt):**
1. **The tether-safety gate (`uplink_safe`) → REQUIRED in Eunomia's provisioning console.** Port the
   `route -n get default != en0` rule verbatim-in-spirit. This is the non-circumventable constraint.
2. **The telnet provisioning logic (`cameras.py`) → the reference for our provisioning console** (read
   real serial, registry side-lookup, write NAND identity, discardd-applies-live). It maps onto the 0d
   `hardware_unit.provisioning` group + the operator/kit/side identity model. Eunomia's console is a
   *consumer of the contract*; setup-app's logic is the proven mechanism it wraps.
3. **The 2026-06-24 firmware fixes → F2 adapts from the UPDATED fob source** (ch6, lockcams /osc/info,
   the reassert-env fix, the REVISA `nOk>=kMinCams` change). Re-pull the fob source for F2; the OQ-9
   re-derivation fallback is moot.
4. **NOT adopting wholesale:** the setup-app is x3-capture-kit's Mac bring-up tool (FastAPI + a Mac
   `.command` + PlatformIO + Git-LFS firmware). Eunomia's provisioning belongs in the
   `consoles/`/`substrate` layer of the clean monorepo, built against the contract — it BORROWS the
   proven logic (the telnet writes, the serial read, the tether gate) rather than vendoring the whole
   app. The provisioning console is a LATER Eunomia run (after the coordinator F2/F3); this is captured
   now so that run starts from Victor's proven flow.

**Deferred items Victor flagged (Eunomia-relevant):** (a) **one-sided record after battery swap** —
the fob counts socket-connected as "started" without verifying recording; a not-yet-ready cam silently
no-ops → only one wrist records. **His stated defense is INGEST-side: pair by `bimanual_episode_id`,
void/quarantine the unpaired — and surface it as a QC FLAG, not a silent drop.** This is exactly our
dual-signal-join + the `recording_suspect`/phantom-gate territory; our ingest + QC must surface
one-sided takes as a review flag (confirm when the ingest/QC runs land). (b) **camera never-power-off /
wifi-always-on** not actively asserted yet (needs firmware-confirmed OSC keys + a hardware test). (c)
**fob provision UX:** when the app sets the kit, the fob still asks the operator to confirm the kit#
on-screen; Victor wants to skip that (a `kitok=1` serial confirm) and **ask operator ID on-device
instead** — which ALIGNS with our operator⊥kit decision (operator signs in on the fob; kit is
provisioned). Good convergence signal.

## FEATURE SPEC 2026-06-24 (Eric) — the god's-view dashboard screen design

Eric described the god's-view dashboard he wants. It is a **three-level drill-down**:
1. **Operators list** — all operators, each with **name + telemetry** (live status).
2. **Click an operator → their last 10 episodes** (the most recent episodes we have from that operator).
3. **Click a video → the player with the episode's metadata alongside** (video left, metadata right).

This is the screen design for the **god's-view** OPS surface already named in the architecture
(CONTRACT §1 "Ops / god's-view (live)"; SPEC §1.3/§1.4/§4.8 `F-OPS-*`) — NOT a new system. It is a
**console** (the `consoles/` layer of the monorepo), a CONSUMER of the operational store + the Hades
render. **It is a LATER Eunomia run — NOT F2** (F2 is the transport firmware). Captured now so the
console run starts from a real screen spec.

**The spec splits cleanly into two halves with very different buildability:**

- **The HISTORICAL half (last-10-episodes → video + metadata) — the strong, buildable part, NOT
  blocked.** It is a read over data that already lands: episodes drain to Styx (the operational store)
  and render on Hades; the metadata is exactly the `eunomia-sidecar/v1` + the operational episode
  records we've poured into the contract. "Last 10 episodes from operator X" = a query keyed on
  `operator_id`, resolved via the **session binding** (operator-from-session — THIS is why the
  operator⊥kit decision matters: the dashboard pivots on operator, so operator must be a first-class
  identity, not collapsed into kit). "Click a video → player + metadata" = the Hades render (preferred)
  or the Styx-raw fresh-window fallback (the §1.9 spot-check path) + the episode's sidecar fields shown
  alongside. **This is essentially umi-qa's territory** (Victor's FastAPI QA viewer on :8090 already
  does per-operator/per-episode browsing + on-demand clip transcode into a bounded cache) — Eunomia
  unifies it into the console layer, built against the contract. Eric's drill-down = the natural
  operator→episodes→clip join over the operational store + render.

- **The LIVE half (the operators list with live telemetry) — real as a design, BLOCKED on the same
  single-radio problem F2's OQ-4 surfaced.** "Live telemetry per operator" has **no transport today**:
  the fob's uplink-borrow is **code-disabled** (`uplinkUp()`→`return false` — tearing down the camera
  AP to borrow the radio drops every camera; verified for F2). The fob KNOWS online/recording state
  (its L2 station table + the `g_anyRec` toggle), but it cannot PUSH it while hosting the camera AP. So
  the live operators view needs one of: (a) a **non-AP-destroying uplink** (a second radio / the
  hardware conversation with Victor — same root as the OQ-3 DS3231/time discussion), or (b) liveness
  read from a **different vantage** — e.g. Styx seeing cards/episodes land (a "last seen N min ago / last
  episode at HH:MM" derived liveness, near-real-time at drain/episode granularity, NOT a live battery/SD
  stream). Recall the architecture already says the god's-view is **near-real-time, not live** (§1.4:
  events batch at STOP/sign-out) — so Eric's "telemetry" is best served as **state-transition +
  last-seen** freshness, with battery/SD as best-effort when a real uplink exists. Spec the live strip;
  name the uplink dependency; do NOT promise a live stream the hardware can't carry yet.

**Design placement (for the later console run):** operators list reads the operational `person` +
`session` records (who is signed in, on which kit, last-seen) + whatever telemetry the uplink delivers;
operator→episodes reads the operational `episode` records filtered by `operator_id` (via session),
newest 10; episode→player reads the footage_reference (Hades render preferred, Styx-raw fresh-window
fallback) + the sidecar/episode metadata. Tailnet-reachable from Mexico + SF (like the spot-check
dashboard). Likely the SAME unified dashboard as the spot-check viewer (§1.9) — one Eunomia ops console
with a spot-check/QC view AND this operator drill-down view, both reading the same store + render, not
two apps. Folded into SPEC §1.10.

**Dependencies/links:** the live half ⟂ the uplink (OQ-4 / the second-radio-or-different-vantage
question — flag to Victor alongside the DS3231 time-source conversation, since both are "the fob can't
do X while hosting the AP" with the same fix family); the historical half ⟂ the operational store +
the Hades render being populated (i.e. after ingest/QC runs) + umi-qa's transcode/cache logic as the
reference. Eric's per-operator pivot ⟂ the operator⊥kit decision (already locked) + the session binding
(0d). NOT blocking F2.

## FEATURE SPEC 2026-06-24 (Eric) — IMU QC heuristics (red-border flagging) + supervisor ground-truth

Eric asked for: (a) heuristics on IMU data that put a **red border around flagged videos** that don't
adhere; and (b) a way for a **supervisor to add their 'ground truth'** somewhere. He said he thought a
dashboard using these heuristics is in the x3 repo. **VERIFIED — it exists and is well-developed; both
asks are already-built prior art in `x3-capture-kit`.** This is the QC + human-label layer Eunomia's
QC/console builds on; recorded as prior art + the integration contract, NOT an F2 item, NOT a build-now.

**The IMU QC stack (Eric's part a — the machine heuristics):**
- **`pipeline/qc_score.py`** — THE scorer (its docstring literally quotes Eric's ask: "pre-categorization
  of saved episodes as bad or not based on accelerometer / gyro data (frequent pauses, out-of-
  distribution, too slow vs median)"). Pure stdlib (no numpy — runs at ingest or cam-side), runs over
  the IMU stream the X3 embeds in every `.insv` (`EXTRA_TYPE_GYRO` + `EXTRA_TYPE_SECGYRO`). Emits an
  **OPEN set of flags with reasons** (no closed taxonomy — repo convention), **defaults to "ok"** (a flag
  is the exception; thresholds set so a normal episode trips nothing), thresholds in a config dict
  (`DEFAULT_CONFIG`) so a new site retunes without code edits. The flags: idle_fraction, idle_longest_seg,
  frequent_pause, freefall/drop (accel), too_slow (COHORT-relative), ood (cohort z-score), tiny/
  min_duration, shake_gyro_rms (absolute), gyro/accel saturation (clipping → unreliable), jerk_rms
  (snag/yank/bang signature, absolute). **too_slow + ood only fire when a COHORT is passed** (never
  guesses a population from one episode) — `pipeline/qc_batch.py` builds that cohort + does batch scoring.
- **`pipeline/qc_from_imu.py`, `qc_annotate.py`, `insv_to_imu_json.py`** — extraction/annotation glue
  (insv → per-episode `VID_<ts>_<seq>.imu.json` → scored flags annotated onto each paired row at ingest).
  `qc_video.py` is the sibling video-QC. Output fields (per `METADATA_SCHEMA.md`): **`qc_flags`/`qc_sus`**
  (IMU accel/gyro QC from qc_score) + **`quality_flags`** (the DETERMINISTIC bad-video superset: IMU +
  video/audio + L/R desync).

**The dashboard Eric remembered = `umi-dashboard-real/`** (a FastAPI app). The red-border rendering:
- **`ledger_rollup.py`** runs `qc_score` over per-episode IMU → `operator_rollup.json`; **`team_stats.py`**
  reads it and builds the per-operator profile + the cleaned/paired episode list (with a strict
  **dashboard_ready gate**: deleted/void/unpaired/needs_review episodes are NEVER shown — it never
  displays a guessed label). **`templates/team_operator.html`** renders the **red-border "sus" episodes**
  (qc_score's docstring names this file explicitly as where the red border lives). So Eric's "red line
  around flagged videos" = `team_operator.html` rendering the `qc_flags`/`qc_sus`/`quality_flags` the
  pipeline already computes. Other dashboard modules: `app.py` (the FastAPI app), `auth.py` (login),
  `video_index.py` (clip routing), `make_table_cards.py`/`table_cards/`, `gsheet_sync.py` (Google-Sheet
  sync), `ingest_receiver.py`, `org.py`.

**⭐ The supervisor ground-truth (Eric's part b — what he wasn't sure how to describe) = `umi-dashboard-
real/labels.py`.** It is the **human good/bad label store** (team-lead + admin QA): a supervisor marks an
episode **`good`/`bad` with an optional note**; stored **append-only JSONL** at `data/episode_labels.jsonl`,
**latest line wins** per (episode_id, labeler_email), with **multi-labeler `consensus()`** (good / bad /
mixed). Record shape: `{episode_id, kit_id, ordinal, side_pair, labeler_email, verdict, note, ts}`. **Its
docstring states the integration contract verbatim: "This file is the CONTRACT the ingest side reads to
stamp a `human_label` into release metadata."** So the supervisor's verdict is overlaid on top of the
machine flags and flows into release metadata. (`pipeline/apply_human_labels.py` — note: in `pipeline/`,
NOT `pipeline/deploy/` — is the likely ingest-side consumer.)

**So both asks are TWO LAYERS of the same QC surface:** the **machine heuristics** (`qc_score` → the
auto-flagged red-border "sus" episodes) and the **human ground-truth** (`labels.py` → a supervisor
good/bad verdict + note, consensus across labelers, stamped into release metadata). The red border = the
UI rendering of the machine flags; the ground-truth = the human label store that overrides/augments them.

**How this maps into Eunomia (the DECISION — prior art Eunomia's QC + console layer builds on, a LATER
run, NOT F2):**
- The **IMU QC heuristics** (`qc_score`/`qc_batch`) are the reference scorer for Eunomia's QC stage. They
  run at INGEST (Hermes-side per DECIDED-2 / the cleaning+render layer) over the IMU pulled from the front
  `_00_` lens (`--extract-imu --drop-front`). Eunomia's contract already carries QC outputs: the open-set
  flags map onto our `qc_flags`/`qc_sus` + the deterministic `quality_flags` (no closed taxonomy — matches
  our open-string+WARN convention for growth-prone vocab). The cohort-relative flags (too_slow/ood) need a
  cohort, which is a batch/population concern at ingest, not capture.
- The **red-border flagging** is a **console rendering concern** — it belongs to the SAME unified ops
  console as the god's-view operator drill-down (§1.10) and the spot-check viewer (§1.9): a QC view that
  renders each episode's qc/quality flags as the red border. One console, multiple views, all reading the
  operational store + the Hades render. `umi-dashboard-real/` is the prototype to unify in (as umi-qa is
  for spot-check, and team_operator.html is for the operator drill-down).
- The **supervisor ground-truth** (`labels.py`) is a **human-label / override store** — Eunomia models it
  as an operational write surface: a supervisor verdict (good/bad + note) per episode, append-only, latest-
  wins, consensus across labelers, that the ingest/release side reads to stamp a `human_label` into the
  record. This is the human-judgment counterpart to the machine QC, and it maps to the FUTURE annotation/QC
  layer (the human-review/override store). Eric's "ground truth" = exactly this: the authoritative human
  good/bad that supersedes the heuristic guess. Worth a contract touch later (a `human_label` field on the
  episode/release record + an operational label-event); flag when the QC/console run is scoped — NOT now.
- **Convergence note:** `qc_score`'s open-set-flags + default-to-ok + config-dict-thresholds is the same
  design philosophy as our contract's open-string+WARN for growth-prone axes. Eric's pipeline and our
  contract already agree on "no closed taxonomy, retune without code edits." Good sign for adopting his
  scorer under our contract.

**Dependencies/links:** the QC heuristics ⟂ ingest populating per-episode IMU JSON (the `--extract-imu`
front-lens pull — already a known policy) + a cohort for the relative flags; the red border ⟂ the ops
console run (the same one as §1.9/§1.10); the supervisor ground-truth ⟂ a future `human_label` contract
field + the annotation/QC layer + supervisor auth (`auth.py` is the prototype). NONE of this blocks or
touches F2.

## Run F2 transport/ — IMPLEMENTED + reviewed 2026-06-24 (CLEARED TO MERGE pending CI)

F2 (transport/ only, per the approved SPLIT; ui deferred to F3) came back strong and faithful. All four
headline checks I said I'd scrutinize were delivered and held: the two-hard-rules diff vs the vendored
main.cpp, seam conformance vs a mock OSC/telnet server incl. persist-before-advance under a FORCED
NVS-write failure, env-key conformance vs discardd, and BOTH env:esp32 + env:cyd building green with
transport/vendor/ excluded (vendor = 0 .o). Gates: 75 pytest / ruff / mypy / lint-imports clean; 33/33
native (16 transport); both board builds SUCCESS; codegen drift 0; zero core//contracts/ diff.

- **Re-vendored to `f96b97a` (the steering note).** OQ-9 closed via option (A) — diff-checked vs
  `a38f5a9` = ONLY the four expected 2026-06-24 areas (apChannel `{1,6,6}`, camCardCheckAll ghost-STA
  `nOk>=kMinCams`, lockcams `/osc/info`, upload_speed 115200) — no sprawl, so adapted not stopped
  (ground-truth discipline). New md5s in PROVENANCE.md superseding `a38f5a9`.
- **OQ-1 landed exactly as predicted** — zero core change; `coord.take()` populated before `start()`;
  proven by test_coordinator_two_hard_rules_and_oq1; the public-accessor guardrail held.
- **persist-before-advance proven under a forced NVS failure** (test_persist_before_advance_under_nvs_
  failure): `fail_next` → trigger() returns false → ordinal stays 0 (not burned) → no startCapture →
  rolled back before the burst. NvsStore::write_i64 returns false on a 0-byte write (the gate).
- **NVS 15-char-key remap:** core's `fob_episode_ordinal` (19) > ESP32 NVS 15-char limit → mapped to
  `"ord"` in the transport seam (`nvs_key_for`), zero core change. Clean.

**⭐ OQ-10 (env-key conformance vs discardd) — one silently-lost field found: OPERATOR_NAME. DECISION:
ACCEPT the ledger-only loss; do NOT add it back.** discardd reads OPERATOR_NAME (oncam/discardd:395,537)
but ONLY into its own discards.jsonl/episode_files.jsonl LEDGERS — NOT into the v2 sidecar identity{};
core::project_assignment_env drops it. Reasoning for accepting the loss (consistent with the locked
model, not minimal-effort): `operator_id` is the CANONICAL identity (operator⊥kit); the name is a
PROJECTION resolvable from the person record; baking it into the env is denormalization that drifts on
rename/typo-fix while the id never does; discardd's ledgers are operational logs, NOT the system of
record (Eunomia's operational store is, and it resolves id→name by design); and the loss touches nothing
live — kit_56/57 run VICTOR'S fob (still emits the name), so the existing dashboard is unaffected; the
loss only concerns Eunomia's FUTURE coordinator feeding discardd, where id→name resolution is the
intended path. **Flip-condition (the only cases to add the one-line emit, marked denormalized-convenience
NOT identity):** if OPERATOR_NAME is capture-time ground-truth not reconstructable from the id, OR if
discardd ledger rows carry the name but NOT the id (orphaning them). SESSION_ID conformant (discardd
never reads FOB_SESSION_ID); TASK_ID/ROTATION_ID additive-correct. The check is encoded as
test_env_key_conformance_with_discardd.

**⭐ CORRECTION [NOT YET FOLDED IN → SPEC §1.7/§1.8 dedicated-core claim]: there is no trigger queue.**
Ground-truth from Victor's code (the agent's finding, sound): his `wifiTask`/queue serve the DISABLED
uplink, NOT the trigger. The trigger OSC runs INLINE on the loop core under the wifi lock (fast — fire-
and-forget, ~120 ms grace/fire); DISCOVERY/presence runs on core 0, lock-serialized (so a mid-take
camera drop is still detected). The instant touch-ack is `core/button_feedback` decoupling the visual
from the slow action (set working-state synchronously on tap → fire → settle) — NOT "the UI thread isn't
blocked" (the UI is INTENTIONALLY in working-state during the brief inline fire). So SPEC §1.7's "network
work on a dedicated core so the UI never stalls … the instant touch-ack is only possible because the UI
thread isn't blocked" needs nuancing: discovery on a dedicated core (yes); trigger inline (UI in
working-state during the fire); touch-ack = button_feedback. Fold into the next docs pass WITH the §1.7
fob-doesn't-write-sidecar correction. The `wifi_worker` was folded into hw/app.cpp (mutex + core-0 task,
no separate file) — fine.

**clang-tidy (OQ-11):** configured + scoped to `core/` + `transport/proto/` (excludes vendor +
framework-coupled `hw/`), wired blocking-in-CI via a tool-guarded target; NOT run on the worktree host
(binary absent → verified-by-config). **MERGE-GATE CAVEAT: CI must HARD-FAIL (not skip) if clang-tidy is
absent** — a tool-guarded skip can mask a non-running blocking gate; the PR check must actually exercise
it green before the squash-merge. hw/-exclusion ACCEPTED for F2 (framework-coupled → tidy-noisy); `hw/`
tidy with a HeaderFilterRegex is a later tuning item, not never.

**MERGE STATUS: CLEARED to commit + open PR** (no code change blocks it — OPERATOR_NAME = accept-loss).
Conditions before squash-merge: (1) CI green INCLUDING clang-tidy actually running (not skipped); (2)
Conductor does the squash-merge; (3) delete the remote branch post-merge. Squash subject `[FEAT] Run F2
— coordinator/transport/ …` fine. **Branch nit:** report shows `Mzcassim/revendor-fob-transport` (capital
M, off-pattern) — convention is lowercase `mzcassim/`; prefer `mzcassim/eunomia-run-f2-transport` to match
F1. Record the squash hash here post-merge. After F2 merges → F3 = ui/ (renders core/button_feedback —
which is where the touch-ack actually lives — + the camera-count color + REGISTRO/MESA/MAIN/CONFIRM +
operator sign-in per OQ-7-flow (b)-lite; the app already plumbs operator_id distinct from kit_id, so F3
only adds the selection UI).

## Run F2 — CLEARED, handed to Conductor for squash-merge 2026-06-24

PR **#6** (https://github.com/Pantheon-Industries-Inc/Eunomia/pull/6), branch
`mzcassim/eunomia-run-f2-transport` (lowercase convention, base `main`), single commit `f13f42f` (33
files), `mergeable: MERGEABLE` / `mergeStateStatus: CLEAN`, 0 behind / 1 ahead, zero core//contracts/
drift re-confirmed. All checks green: `gates` pass, `cpp` pass (clang-format per-file · native build+test
· esp32 build · cyd build · clang-tidy blocking · camera-image checksum).

- **clang-tidy CI verification (the one gate not exercised on the worktree host) — PASSED + verified
  both ways.** CI log shows it executing (`[1/5]…[5/5] Processing …/transport/proto/*.cpp`), no
  "NOT installed / skipped" line; the hard-fail-if-absent guard confirmed (absent+CI → non-zero exit;
  present → green). The load-bearing merge condition is met.
- **clang-tidy BLOCKING SCOPE narrowed to `transport/proto/` ONLY** (off the accepted `core/`+proto/).
  Reason: `core/` (F1 code) has **5 pre-existing `performance-enum-size` findings**; fixing them would
  edit core/, outside F2's transport-only boundary. **ACCEPTED** — narrowing in the safe direction, not
  a regression (F1 never caught them; tidy wasn't blocking then), preserves the zero-core-diff invariant.
  **FOLLOW-UP (tiny core PR, fold with/before F3):** clear the 5 `performance-enum-size` enums + extend
  blocking tidy scope to `core/`. Note F3's `ui/` is framework-coupled (TFT_eSPI) like `hw/` → excluded
  from tidy, so the natural scope-extension is `core/` only.
- **CI deviations (both sound, both necessary for a deterministic gate, both ACCEPTED):**
  (1) clang-format/clang-tidy **PINNED via PyPI wheels** (`clang-format==22.1.5`, `clang-tidy==22.1.7`)
  instead of unpinned apt — apt's version disagreed with local 22.x on brace spacing + UTF-8 trailing-
  comment alignment; pinning makes local==CI deterministic; verified clean incl. core/. **Standing
  convention:** devs should install the SAME pinned wheel (via the dev setup) so dev-local == CI — don't
  rely on apt/brew. (2) clang-format gate is **PER-FILE** (`xargs -n1`) — the clang-format-22 multi-file
  `--dry-run` quirk exits 1 on clean files; per-file is equivalent + version-robust; `transport/vendor/`
  pruned. (Both also touch the F1 baseline; now consistent across the gate.)
- **Open items (all per the GO):** OPERATOR_NAME = ledger-only loss, no code change, conformance test
  retained; clang-tidy scope accepted (narrowed, see above); SPEC §1.7 no-queue correction left untouched
  (the tracked docs-pass item).

**HANDED to Conductor for the squash-merge.** Post-merge: delete the remote branch; **the squash produces
a NEW commit on `main` (NOT `f13f42f`, which is the pre-merge branch commit)** — record THAT squash hash
here, matching the F1 pattern. **SQUASH HASH ON MAIN: `a0ba39c`** (`[FEAT] Run F2 — coordinator/transport/: seams on Victor's WiFi-OSC fob (env:cyd + clang-tidy blocking) (#6)`). Remote branch deleted. Merge note: `gh pr merge --delete-branch` skipped its LOCAL cleanup because `main` was checked out in another worktree — server-side squash completed fine, remote branch deleted manually; the stale local F2 worktree is harmless (gets discarded when the fresh F3 worktree is cut off main). Docs (the contract/spec/etc. updates) were folded into this merge.

Squash subject: `[FEAT] Run F2 — coordinator/transport/: seams on Victor's WiFi-OSC fob (env:cyd +
clang-tidy blocking)`.

## F3 plan — grounding pass + decisions 2026-06-25

The F3 plan-only run (runF3_ui_prompt.md) got a read-only grounding pass against the MERGED F1/F2 code
(the plan's own "code wins over doc" rule). Plan is sound; SIX code-vs-plan discrepancies surfaced, all
legitimate, all folded before implement. Two material. The plan UNDERSTATED the work (esp. A + E); F3 is
correspondingly larger but still ONE coherent run (the CYD UI + the two follow-ups — NOT split). The
agent's read is trusted (specific file:line cites, internally consistent, matches the F2 no-queue
finding — same standard as F2's grounding which verified out). Decisions:

- **A (build config) — MATERIAL.** Eunomia's `[env:cyd]` is BARE (no lib_deps, no TFT flags), contrary
  to the plan's "F2 already added the TFT dep, just flip the guard" (F2 built env:cyd headless-minimal —
  no point carrying an unused TFT dep). F3 PORTS the full TFT config from the vendored platformio.ini:
  `bodmer/TFT_eSPI@^2.5.43`, `-DPANTHEON_HAS_TFT=1`, the CYD display block (USER_SETUP_LOADED,
  ILI9341_2_DRIVER, pins 12/13/14/15/2/-1/21, fonts, SPI freqs), and the **colour-fix** `TFT_RGB_ORDER=
  TFT_BGR` + `TFT_INVERSION_ON` — **colour-critical: the GO/NO-GO green/red must not swap** (verify on
  the board). ui/touch carries the XPT2046 pins (T_CLK=25/MISO=39/MOSI=32/CS=33/IRQ=36, separate VSPI
  bus — hardcoded in main.cpp, not the ini). Real config porting, not a guard flip. env:esp32 stays
  headless.
- **B (button_feedback) — MATERIAL, corrects OQ-3.** `DelayedButton` is a standalone **2-STATE** primitive
  (`working()`/not), NOT a Coordinator member, zero callers today (only a unit test; coordinator.h:11
  says so). So there is NO `core::button_feedback` to poll and NO core accessor for it. Correct model
  (matches the F2 no-queue finding): **ui/ OWNS the DelayedButton instance(s)**, drives `press()` on touch
  → runs the slow inline action → `complete()`; `render_state` reads `working()`. The instant-ack =
  `working()` flipping true synchronously on press (before the action). The visual states
  (idle/working/recording/locked) are ui/'s MAPPING of `working()` + other core state into pixels; the
  primitive is 2-state. (Plan §3's table implied tri-state — corrected.)
- **C (the real accessor) — the actual "one tiny core accessor."** GO/NO-GO must NOT call `detect_drop()`
  per frame (it's a MUTATING port op). The live present-count lives in transport's PresenceSource
  (`g_registry.present()`). **DECISION: add a tiny `const Coordinator::present_count()` reading
  `deps_.presence`** (read-only, no logic) — keeps ui reading core state through the coordinator (the
  ui→core seam), genuinely minimal. (Alt: app glue feeds the count to ui = zero core change but ui reads
  from app/transport; the const accessor is preferred.) **EXPANDS the core-edit boundary from "enums
  only" to "enums + one tiny const present_count() accessor" — surfaced, not silent.** `detect_drop()`
  stays for drop-detection logic, not rendering.
- **D (stale comments)** — "ui/ (F2)"→"(F3)" in button_feedback.h:8, coordinator.h:12 (free — touched by
  the §5.1 enum cleanup) + core/README.md:24. Comment-only; rides the enum-cleanup edit.
- **E (omitted screen elements)** — FOLD IN: **MESA re-entry** (MAIN-header double-tap → table change;
  the take-counter "resets on table change" depends on it), **CONFIRM 45s auto-timeout**, and the
  **three-reason startGate** (CAMS/UPLINK/SAVING, not just camera-count): SAVING → button `working()`/
  lockout (can't START mid-finalize); **UPLINK → INVESTIGATE** given the uplink is code-disabled (F2
  uplinkUp()→return false) — drop-if-vestigial (do NOT gate START on a dead uplink), else map + flag.
  **LLAMAR "call lead" button**: keep-if-UI-only-splash (no network — cheap, operator-familiar),
  drop/defer-if-needs-network (the dead uplink — could ride the god's-view live uplink later). Both
  UPLINK + LLAMAR are code-determined; flag the resolutions.
- **F (clang-tidy mechanics + Makefile)** — to extend blocking tidy to core/: (1) add `core/*.cpp` to
  TIDY_FILES, (2) extend `.clang-tidy` HeaderFilterRegex to `firmware/coordinator/core/.*` (the 5 enums
  are in HEADERS — the check only fires if the header passes the filter), (3) reconcile the PRE-EXISTING
  Makefile inconsistency (help text line 26 + gates-cpp-tidy help claim "core/ + transport/proto/" while
  TIDY_FILES + echo line 63 are proto-only). ui/ + transport/vendor/ stay excluded.

What CHECKED OUT in the grounding pass: the 5 enums (GateOutcome coordinator.h:39, Press button_feedback.h:16,
State/Input/Action trigger_state_machine.h:15/18/21 — all header, no underlying type → all fire); the §4
adaptation map (all SCREEN_* renderers, drawPromptBand, glyphs, the XPT2046 pressure read +
debounce-latch kPressHi=220/kReleaseLo=90/kRelSamples=3, camCol = cams>=2?GREEN:RED with no amber); OQ-1(A)
mirrors Victor's provisionVerify→CONFIRM_ID→identityYes/No exactly; the swappable-UI seam is real
(app.h:6). Agent to fold all six flags into plan.md as resolved OQs/corrected claims, then implement.

## LLAMAR "call lead" — Victor's lock-until-stop workflow (design decision 2026-06-25)

Victor's proposed LLAMAR workflow: **LLAMAR locked while recording** (available only when stopped/idle);
on press, the fob switches the radio (leave AP → join uplink → send the help signal → rebuild AP), then
back. Alternative he floated: drop the button if switching is too slow — but Mo noted that would ALSO
kill the god's-view telemetry plan (same network-switch).

**DECISION: KEEP the button; Victor's lock-until-stop workflow is SOUND.** The uplink was disabled
(`uplinkUp()`→`return false`, line 969) because tearing down the AP drops EVERY camera *while recording*.
Lock-until-stop means nothing is recording → a brief AP teardown is recoverable (cameras auto-rejoin via
`S99zfobjoin`). The constraint was never "never use the radio"; it's "never tear down the AP
mid-recording." LLAMAR-when-idle respects it.

**Guardrails (the foreseeable issues):**
1. **UNCONDITIONAL AP-restore + timeout (critical).** The switch must leave-AP → try-uplink (N-sec
   timeout) → send → **ALWAYS rebuild the AP (finally-semantics) even on uplink-join failure** →
   success/fail toast. The fob must NEVER end with the AP down (same risk family as the provisioning
   tether-gate). The real failure mode is the fob getting STRANDED (uplink not there, AP down), not
   slowness.
2. **Honest GO/NO-GO during camera re-associate** (~15–40s round-trip, dominated by uplink-join +
   re-associate) — the camera-count shows NOT-GO until cams are back; LLAMAR stays locked/working through
   it. Acceptable because the operator pressing LLAMAR is stopped/dealing-with-a-problem anyway.
3. **LLAMAR is a §1.8 DELAYED BUTTON** — instant-ack/working/locked, settle on success/fail toast;
   another ui-owned `DelayedButton` instance. Slots into F3 with no new machinery.

**THE GOD'S-VIEW RESOLUTION (Mo's worry — resolves in our favor).** God's-view was ALWAYS planned as
NEAR-REAL-TIME, flush-in-idle-gap (SPEC §1.4), NOT continuous-live. LLAMAR-when-idle is the SAME mechanism
(switch during idle, do the network thing, switch back). The slow switch only sets the freshness
GRANULARITY: idle-gap-flush works during REAL idle (breaks, between sessions, end-of-batch), NOT between
rapid back-to-back takes (gaps too short for a 15–40s round-trip). So god's-view freshness = "updates at
breaks" = what near-real-time means. The ONLY thing impossible on one radio is continuous telemetry
*during* recording — and nothing needs it (near-real-time god's-view doesn't; LLAMAR doesn't). **NOT
fucked — the architecture (§1.4) already anticipated exactly this; the LLAMAR conversation CONFIRMS the
god's-view mechanism rather than killing it.** REFINEMENT: **throttle the idle-flush** (don't switch on
every brief stop — too much camera churn at a 15–40s drop each; switch on a throttle / confirmed-long-idle
/ meaningful state change).

**HARDWARE OUT:** a SECOND RADIO (cheap ESP32 companion for the uplink) makes both LLAMAR and telemetry
SEAMLESS (no switch delay, no camera drop) AND unblocks live-during-recording telemetry — the SAME Victor
hardware conversation as the DS3231 clock ("things the fob can't do while hosting the AP with one radio").
Bonus: whenever the fob switches to uplink (LLAMAR/idle-flush), it can opportunistically grab NTP — a free
clock correction (doesn't replace DS3231 for during-recording time, but a bonus).

**F3 + SEQUENCING:** F3 (mid-run) **RENDERS** the button + lock-while-recording + the delayed treatment +
posts a "llamar requested" intent (UI is real + cheap). The actual network-switch is a SEPARATE
**idle-uplink TRANSPORT task** — re-enable + harden Victor's disabled uplink-borrow (remove the `return
false`), idle-GATED, with the timeout + unconditional AP-restore + throttle — which ALSO unblocks the
god's-view idle-gap flush (same mechanism, one piece). It's SAFETY-CRITICAL (the mock must assert the AP
is ALWAYS restored on an uplink-join failure), lives beside the F2 transport work, and serves LLAMAR +
god's-view both. The running F3 annotation's "if LLAMAR needs network → stub/defer + flag" branch already
yields the right F3 outcome (button present, network deferred), so NO need to interrupt the run — confirm
on review the button is rendered+locked (not dropped). Victor-coordination: add the second-radio option to
the same hardware sync as DS3231 + the live-telemetry uplink.

## CORRECTION 2026-06-25 — single-radio idle-flush does NOT work for quick episodes (Mo caught this)

My prior "throttle the idle-flush" framing was WRONG for the realistic collection pattern. Mo pushed:
won't this throttle for quick episodes (30–90s)? Yes — and the throttle doesn't resolve it, it just
picks which way you lose:
- **Throttle down** → telemetry almost never flushes during active collection (no gap reliably exceeds
  the ~15–40s switch, and even a long-enough gap gets eaten by the flush, delaying the next take). The
  dashboard shows "last seen [last long break]" → an operator collecting for 2h straight looks OFFLINE.
  Misleading, not just coarse.
- **Don't throttle** → each flush costs ~15–40s cameras-unavailable. Once-per-episode ≈ HALVES
  throughput; every-5-min ≈ 5–13% tax + leans on camera re-association being fast/reliable (the F2
  ghost-STA/flap findings say it isn't).
So the quick-episode cadence is exactly where single-radio idle-flush breaks. SPEC §1.4's "near-real-time,
flush in idle gap" quietly assumed gaps longer than the switch — true for breaks/between-sessions, FALSE
for active rapid collection. **LLAMAR is still fine** (rare, operator-initiated, they're stopped and
waiting) — frequency+automation is what breaks telemetry, not the switch.

**The free single-radio baseline (no harm):** piggyback a telemetry heartbeat on the **boot-time uplink**
— the fob reboots at the 4–5×/day battery swaps (cameras already down then), so a brief uplink-on-boot to
grab NTP AND push a heartbeat costs nothing extra → ~4–5 dashboard updates/day per operator. Coarse but
honest ("who collected today / roughly how much"), useless for live. SAME mechanism as the OQ-3
boot-NTP-before-AP clock option — one mechanism, two payoffs.

**The real answer for live-during-collection = SECOND RADIO** (companion ESP32 over UART, or an LTE modem
— clean for a mobile rig: cellular uplink, WiFi stays on the cameras). Continuous telemetry, zero
throughput cost, seamless LLAMAR. Mo's question elevates this from "nice upgrade" to "the requirement for
a useful live god's-view."

**Reframed Victor hardware decision — ONE decision (what uplink does the fob get?), clock payoff + telemetry
payoff, in tiers:**
- **DS3231 only:** clock robust; telemetry nothing (god's-view = historical + coarse-at-boot).
- **Boot-NTP-before-AP (single radio):** clock fresh at boot (drifts in long sessions) + free coarse
  telemetry heartbeat at swaps. No new hardware.
- **Second radio (companion ESP32 / LTE):** clock perfect (NTP anytime) + live telemetry + seamless
  LLAMAR. Premium tier, solves all three.

**The product question that decides it (Eric's):** does god's-view need LIVE status during active
collection (→ second radio, justified because it also fixes the clock + LLAMAR), or is daily-ish operator
status + the historical drill-down enough (→ free boot-flush on current hardware)? Either way the
**HISTORICAL half** (last-10-episodes → video+metadata) is UNAFFECTED — never on this path; only the live
telemetry strip carries the constraint. This supersedes the prior entry's "throttle the idle-flush"
refinement.

## DECISION 2026-06-25 (Mo) — DROP god's-view live camera telemetry for now; keep everything else

Mo's product call: do NOT do the live camera telemetry on god's-view for now; keep everything else. This
cleanly resolves the single-radio/second-radio/throttle tangle by cutting the one piece that depended on
the radio-switch.

**CUT (for now):** the fob-pushed live/near-real-time camera telemetry (battery, SD space, live
recording-state), AND any fob telemetry-push machinery (live OR the coarse boot-heartbeat). Not building
the uplink-switch-for-telemetry at all.

**KEEP (everything else) — god's-view = the operator-pivoted HISTORICAL browser + QC surface, one unified
ops console:**
- The **operators list** — populated from the operational store (person/session: who exists, who's been
  collecting), with each operator's **last-episode-landed timestamp** as the honest freshness signal
  (free, derived from when episodes drain — NO telemetry needed). The "name + telemetry" of Eric's spec
  becomes "name + last-episode freshness."
- The full **drill-down**: operator → their last 10 episodes → video + metadata player (Hades render +
  sidecar fields). Unchanged.
- The **spot-check viewer** (§1.9) — unaffected.
- The **IMU-QC red-border flagging** (qc_score → dashboard) + the **supervisor ground-truth** (labels.py)
  — unaffected.
Only loss: "who's active right this second." Last-episode timestamp covers "who's been collecting / roughly
when" honestly.

**Pleasant simplifications this produces:**
- **The idle-uplink transport task is now LLAMAR-ONLY** — no throttle, no heartbeat, no flush-cadence
  tuning. Just the on-demand lock-until-stop switch + the unconditional AP-restore. Smaller + safer.
- **The second radio is no longer needed for god's-view** — drops out of the must-have list; becomes a
  "someday if you ever want live telemetry" item, not a current ask.
- **The clock decouples** — DS3231 stands on its own as the robust fix (never needed telemetry to justify
  it; the boot-NTP "free heartbeat bonus" reasoning is moot now). The Victor hardware conversation shrinks
  to: **DS3231 for the clock + single-radio lock-until-stop for LLAMAR. No second radio.**

**Unchanged:** LLAMAR still ships (lock-until-stop). The historical half was always buildable and is now
god's-view's freshness surface. **F3 is untouched** (F3 = the operator's fob CYD screen; god's-view = the
supervisor's dashboard, a separate later console run).

**Docs:** SPEC §1.10 needs a small update — the live-telemetry strip → explicitly DEFERRED (not building
fob telemetry for now); the operators list → store-derived with last-episode freshness; richer live
telemetry → a future second-radio item. **Fold into the pending docs pass** (now: §1.7 sidecar-model +
§1.7 "fob NTP wallclock" + §1.8 no-queue + §1.10 live-telemetry-cut + CONTRACT §1.7). The pass is
accumulating — worth doing soon, with or just after F3.

## Run F3 ui/ — IMPLEMENTED + reviewed 2026-06-25 (CLEARED TO COMMIT/PR)

F3 (ui/, the CYD touchscreen) came back strong; all six NOTE flags folded into plan.md (the plan-of-record)
+ implemented. All headline checks held. Gates: 75 pytest / ruff / mypy / lint-imports clean; 39/39 native
(6 new test_ui); env:esp32 headless SUCCESS (ui/ guarded, NO TFT dep, links clean — OQ-5); env:cyd TFT-on
SUCCESS (TFT_eSPI@2.5.43, 42.5% flash); clang-tidy NOW core/+transport/proto/ with 0 findings (5 enums
cleared, ui/ excluded); clang-format clean; codegen drift 0. (Same benign uv-sync fresh-worktree bootstrap
as F2.)

**The six flags (all folded):** A — real CYD TFT config ported into [env:cyd] (deps + PANTHEON_HAS_TFT +
colour-fix TFT_BGR+TFT_INVERSION_ON + pins). B — ui OWNS the DelayedButton, no core accessor for it. C —
added `Coordinator::present_count()` (the only new core accessor). D — F2→F3 comments fixed. E — MESA
re-entry + CONFIRM 45s timeout folded; GATE_UPLINK investigated → VESTIGIAL → DROPPED; LLAMAR KEPT (splash +
local log, dashboard POST deferred to the idle-uplink task). F — tidy extended to core/ via TIDY_FILES +
HeaderFilterRegex, 5 enums → `:std::uint8_t`, Makefile reconciled.

**§1.8 faithful:** instant-ack = `press()`→render working→inline action→`complete()` (visual synchronous
BEFORE the action — the no-queue truth); camCol exact (2/2 green, 0/2 & 1/2 red); **spam-safety preserved
through the INPUT path** (UI lockout drops re-taps AND TriggerStateMachine never double-fires even if the
lockout leaks — proven in test_ui). **SPEC §1.8 prose CORRECTED in this PR** (the no-queue correction) → so
§1.8 is now HANDLED, removed from the pending docs pass.

**Swappable-UI seam holds:** no ui/ file includes a transport/ header; core/ changed only by the enums +
present_count() + comments. A new screen swaps ui/ against the same core guarantee.

**Deviations (all sound):**
- **present_count CACHING — correctness IMPROVEMENT, ACCEPTED.** The discovery task (core-0, lock owner)
  computes present_count() and caches it; the UI reads the cache (Victor's g_connCount pattern, thread-safe
  — avoids a cross-core unsynchronized read of deps_.presence). The accessor is still the source; the live
  phantom-gate in trigger() stays authoritative (a stale cache can't cause a wrong trigger — at worst the
  color lags one discovery cycle).
- Take counter is ui-owned (core has none) — correct (presentation state).
- **Mid-take cam-drop NOT shown until the take ends** (the cache is frozen during recording — F2's
  discovery skips during a take). F3 renders faithfully, doesn't change transport. KNOWN UX GAP — the
  operator can record a doomed take unaware one cam died; the authoritative one-sided-record catch is
  downstream at INGEST (pair by bimanual_episode_id). REVISIT in the transport/one-sided-record work: since
  L2 presence is a PASSIVE station-table read (no OSC), can it run during a take for an early mid-drop
  warning? NOT an F3 blocker.
- **OQ-1 "Operador #N" fallback — SANCTIONED.** No on-device number→name roster → CONFIRM_ID shows
  "Operador #N", name resolves downstream. NOTE: this REDUCES CONFIRM_ID's mistype-protection (no name to
  verify against — the operator just re-sees the number they typed). Fix = an on-device roster (number→name),
  a PROVISIONING-CONSOLE item. Acceptable now; not yet working identity confirmation.
- Two bilingual error strings clip at 34 chars — cosmetic, faithful to Victor's renderNumEntry.

**COLOUR-FIX:** ported (TFT_BGR+TFT_INVERSION_ON, verbatim from Victor's PROVEN ini) — env:cyd builds, but
"red/green renders correctly" is a BENCH step (can't be gate-verified); confirm at rig. High confidence.

**MERGE: CLEARED to commit + open PR** (uncommitted on branch "Mzcassim/angkor"). **BRANCH NIT:** rename to
lowercase **`mzcassim/eunomia-run-f3-ui`** to match F1/F2 (`mzcassim/eunomia-run-<f>-<name>`); the agent
offered "agent/f3-ui" citing a CONTRIBUTING agent/<run> convention, but the F1/F2 precedent is
`mzcassim/eunomia-run-…` — use that unless CONTRIBUTING genuinely mandates otherwise. Conditions: CI green
incl. clang-tidy actually RUNNING (now core/+proto/, not skipped — F2's hard-fail-on-absent guard should
hold); Conductor squash-merges; delete branch post-merge; **record the squash hash here.** Squash subject
`[FEAT] Run F3 — coordinator/ui/ …` fine. **[F3 SQUASH HASH ON MAIN: PENDING]**

**PENDING DOCS PASS (now MINUS §1.8, which F3 handles):** §1.7 sidecar-model + §1.7 "fob NTP wallclock" +
§1.10 live-telemetry-cut + CONTRACT §1.7. Fold soon (its own pass, or with the next run).

**With F3, the firmware coordinator is COMPLETE: contracts 0a–0d + F1 core/ + F2 transport/ + F3 ui/.** Next:
the provisioning console (tether-gate + cameras.py telnet logic + the on-device roster that fixes OQ-1's
CONFIRM_ID), the ops/QC console (god's-view historical drill-down [no live telemetry] + spot-check + IMU-QC
red-border + supervisor ground-truth), the idle-uplink transport task (LLAMAR-only network-switch), and
ingest (v2→v1 sidecar reconciliation + dual-signal-join + the one-sided-record QC flag).

## Daily hardware-setup flow ("today's setup: X3 camera, gripper version V") — where it lives (Mo asked) 2026-06-25

Mo: "I don't see the flow for daily hardware setup." It IS designed (B-9 capture-stack provenance); not
visible for two reasons + has real gaps to close. Precise state:

- **MODELED (B-9 + the kit registry).** The `capture_stack` entity = modality + camera model + camera fw +
  fob board + fob fw + **UMI GRIPPER HW VERSION** + SD + Eunomia sw, referenced by `capture_stack_id`. The
  un-sensable provisioning-time parts (camera model, gripper version, SD, mount) live in the **kit
  REGISTRY** against the kit/serials, resolved per-episode via `kit_id` on the card (NOT stamped on every
  card). The sidecar carries the per-episode/sensable facts (kit_id, camera_serial, camera_firmware,
  fob_build, kit_version, calibration_id). **So the gripper version IS captured — registry-side, via
  kit_id.**
- **THE DAILY FLOW IS DESIGNED (B-9):** the fob auto-assembles the sensable parts at session start; a
  **start-of-day CONSOLE prefills the resolved stack and the SUPERVISOR confirms it daily — explicitly to
  catch un-sensable changes like a GRIPPER SWAP.** Robust-by-default (record correct even if the confirm is
  skipped); the daily confirm = the accountability/override. THAT is Mo's "this is today's setup" step.
- **WHY MO DOESN'T SEE IT:** (a) the FLOW NARRATIVE is only in the register (B-9) — the SPEC has the
  capture_stack ENTITY (§2.2/§422) but NOT the daily-confirm-flow narrative → **SURFACE IN SPEC** (add to
  the pending docs pass). (b) The console isn't BUILT — a later run (ops/provisioning console family); the
  coordinator (F1–F3) is the operator's fob, this is a separate supervisor surface.
- **REAL GAPS/ACTIONS (not just visibility):**
  1. **PROVISIONING SCOPE NOTE:** the current fleet registry (fleet.yaml: insv_serial/ble_mac/calibration/
     serial-crosswalk) does NOT capture the gripper hw version / mount / SD / camera model — it's
     camera-identity-focused. The **provisioning console must capture the FULL rig config** (gripper hw
     version + mount + SD + camera model) into the registry, else the daily-confirm + capture_stack
     resolution have nothing to prefill for the gripper. Extend provisioning beyond camera-identity.
  2. **FOLD-IN RECONCILE:** B-9 says "the fob assembles capture_stack_id at session start," but the BUILT
     sidecar (§2.2) carries the COMPONENTS (camera_firmware/fob_build/kit_version/calibration_id) + kit_id,
     NOT a capture_stack_id. So in practice capture_stack_id is **RESOLVED AT INGEST** (join the episode
     components + the kit registry) — the more robust design (card = raw facts, ingest = resolve id).
     Reconcile B-9's wording; the resolution + the daily-confirm UI land at INGEST + the console, NOT the
     coordinator.
  3. **FLOW OWNER:** supervisor-at-start-of-day (a console), NOT the operator at the fob — sensible
     (hardware config is a setup concern, not a per-take action), robust-by-default. Flagged for Mo: say if
     he wants it at the fob / operator-affirmed instead or in addition.
- **CALIBRATION (C-11) is the linked piece:** calibration_id nullable on the episode; scope =
  none|fleet|per_camera (accommodated, Eric testing via SLAM error); currently scope=none (pilot
  uncalibrated). "Today's setup" calibration is modeled; its WORLD is Eric's open call.

**NONE of this is F3** (the coordinator). It lands across: the SPEC docs pass (surface the flow), the
**provisioning console** (capture the gripper + the full rig config), and **ingest + the ops console**
(resolve capture_stack_id + the daily-confirm UI). The gripper version IS modeled — Mo's instinct caught a
SPEC-visibility gap + a not-built console + the provisioning-must-capture-the-gripper scope note, not a
missing design.

## Task-setup flow ("today's tasks": catalog + station→task assignment) — design + model decision 2026-06-25

Mo wants a start-of-day task-setup flow: replace Eric's hardcoded task/prompt/id list with a STORED
catalog; the supervisor decides #tables, sees a VISUAL LAYOUT, adjusts, numbers tables, assigns a
task/prompt to each station; the operator's station_id at the fob then resolves the task. Mo asked:
possible? + be intentional about failure modes (esp. 2 supervisors picking the same table# → intertwined
backend) + which model: (i) deterministic fixed task↔table# never-change, or (ii) permanent table# +
supervisor links task daily.

**GROUNDING (found in x3-capture-kit): the station→task model IS the existing architecture, currently
config-driven/hardcoded — Mo is NOT missing anything.**
- `config/stations.yaml` (2026-06-10 era; refactored/moved since — NOT on main now) = station# → task_id;
  "operator types e.g. 1000 → gets a task prompt."
- The task/prompt is NAND-staged: `/pref/pantheon_current_task.env` carries TASK_ID/TASK_NAME/PROMPT/
  ROTATION_ID/STATION_ID (task fields ONLY, never identity), staged by the coordinator in a cam-reach
  window, sourced by discardd, stamped on every episode (task_source="nand_staged"); survives SD/battery
  swaps.
- Eric supplies a STATIC table#→prompt chart ("static table# -> prompt chart (Eric supplies), stamped
  with station").
- The sidecar carries station_id, site_id, task_id, task_name, prompt, rotation_id (fields exist).
- METADATA_SCHEMA: "station_id | the mesa" → the fob MESA screen = station entry.
→ Mo's flow is literally how it works today (station#→task via stations.yaml + NAND staging), just
HARDCODED. His evolution = make it DYNAMIC + supervisor-managed + collision-safe.

**RECOMMENDED MODEL — (ii)-refined (Mo's second instinct; REJECT (i)):**
- **Task/prompt CATALOG: stored, global, versioned.** task_id stable + GLOBAL (fold=Fold Towel=its prompt
  everywhere). Replaces Eric's static chart. `rotation_id` EXISTS → a task has multiple PROMPT VARIANTS
  that rotate; the catalog is task→{prompts}+rotation, not just task→one-prompt. VERSIONED: editing a
  prompt = a new version; episodes PIN the version (past episodes don't retroactively change).
- **STATIONS: REGISTERED, stable, globally-unique — NOT free-chosen (THE COLLISION FIX).** A station is a
  permanent physical identity with a stable id; global uniqueness via **site_id + station#** (site_id
  already a sidecar field → SF-3 ≠ MX-3). The supervisor does NOT type a free number — picks from the
  site's REGISTERED stations (the visual layout) or registers a new one (allocates the next free #). →
  two supervisors CAN'T pick the same #; #s are allocated per-site, the layout shows what's taken, the
  backend key is site_id+station# (never a bare typed number).
- **TASK→STATION ASSIGNMENT: a time-ranged, append-only EVENT** ("station S assigned task T effective
  from time t"). Supervisor sets at start-of-day (Mo's "links task every morning"); a mid-day change is a
  new event → granular "what was this station doing at any moment."
- **RESOLUTION:** episode records station# + site_id + timestamp; task resolves via the assignment in
  effect at the episode's start time (ingest authoritative). The fob DISPLAYS the resolved prompt for the
  entered station (operator instruction + error-check) → the day's assignment is staged to the fob,
  reusing the existing NAND task-staging (pantheon_current_task.env).

**REJECT (i) fixed task↔table# never-change:** too RIGID (tasks rotate across stations to balance data;
can't have 5 tables on the same task; can't repurpose a table) AND doesn't solve the collision (two sites
could both call their fold-table "3"). (ii) gives granularity without rigidity.

**FAILURE MODES (Mo asked to be intentional):**
1. **Cross-supervisor/site number collision (Mo's):** FIXED — registration + site-scoping (site_id+station#
   key) + the visual layout surfacing taken numbers. #s allocated, not typed.
2. **Temporal ambiguity (table 3 = X yesterday, Y today):** FIXED — time-ranged assignment + episode
   timestamp; resolve via the assignment in effect then.
3. **Mid-day reassignment:** the time-ranged event keeps the RECORD correct (ingest resolves by
   timestamp), BUT the fob shows a STALE prompt until re-staged (pushing mid-day = the uplink problem) →
   the operator could demonstrate the wrong task. MITIGATION: treat mid-day reassignment as a DELIBERATE
   re-setup (re-stage the station to the fob + operator re-confirms), not a silent backend change. The one
   real edge.
4. **Operator types wrong station#:** the fob shows the resolved task/prompt ("Station 3: fold the
   towel") → operator catches it (the CONFIRM_ID pattern). Requires the mapping on the fob (staged).
5. **Station not yet assigned (operator beats the supervisor):** the fob shows "no task for station N —
   ask supervisor" (NO-GO), never a silent null task.
6. **Catalog edit after episodes referenced a task:** episode pins task_id + the prompt VERSION; editing
   the catalog doesn't change past episodes (the task-menu-version concern).
7. **Station decommissioned:** retire the id, NEVER reuse (reuse re-intertwines history). Registered
   stations are permanent.

**WHERE IT LIVES / SEQUENCING:**
- SAME start-of-day supervisor session as the B-9 hardware-config confirm — UNIFY: one start-of-day
  console = "today's setup: these stations (visual layout), these task assignments, this
  hardware/calibration."
- CONTRACT/operational ADDITIONS: a **station registry** entity (registered, site-unique, retire-not-reuse
  — station is NOT a first-class entity today, just a field) + a **task→station assignment** event
  (time-ranged, append-only) + **versioning + rotation** on the task catalog. The sidecar fields
  (station_id/site_id/task_id/prompt/rotation_id) already exist; the entities to MANAGE them are new.
- DELIVERY to the fob reuses the existing NAND task-staging (the coordinator already stages task fields);
  the dynamic source (catalog+assignment) is the new part.
- NOT F3: the fob MESA = station entry, already there + COMPATIBLE; only the resolution source changes
  (hardcoded stations.yaml → dynamic supervisor assignment, staged). No F3 rework.

So task-setup + the B-9 hardware-config confirm + operator sign-in CONVERGE into ONE start-of-day
supervisor/operator setup flow — built in the ops/provisioning console family, against the contract (with
the catalog + station-registry + assignment additions). LATER run. Strengthens the case that the
provisioning/ops console is the natural next pick after the coordinator.

## Boot-uplink + provision profile + per-kit hardware config + god's-view metadata — design batch 2026-06-25 (Mo+team)

Five threads from Mo; most ALIGN with B-8 (event-sourcing) + B-9 (capture-stack) and resolve the mid-day
task-staleness edge. Captured + the genuine decisions flagged.

**1. BOOT-UPLINK (time + task mapping) — DECISION: every fob power cycle, connect to office/site wifi
FIRST → pull NTP (time) + the refreshed task↔table mapping → THEN host the camera AP.** Cleanest uplink
case: the AP isn't up yet at boot, so NO camera disruption (cameras associate AFTER the sync). Bounds
task-mapping staleness to the swap cadence (4–5×/day) → a mid-day reassignment is auto-picked-up at the
next swap; only a can't-wait change needs a deliberate re-setup or a power-cycle. Cost ~30–60s at boot
(wifi assoc + NTP + mapping fetch + bring up AP) → show a "syncing…" screen. Single radio, at boot — NO
second radio (consistent with the live-telemetry cut). Reuses the LLAMAR transport capability, minus the
teardown (AP not up yet).
  • **CLOCK FORK (clarifying Mo's "pull time from an RTC somehow"): NTP ≠ RTC.** NTP = the network pull at
    boot (no extra hw). DS3231 = an onboard ~$1 chip that HOLDS time across power cycles without network.
    Complementary. **Boot-NTP alone** works IF site wifi is reachable at every boot (clock drifts ~seconds
    over a few hours — fine); risk = a no-wifi boot has no time. **+DS3231** removes that risk (time always
    available; NTP-at-boot corrects it). **RECOMMEND both** — the DS3231 is cheap insurance; it's the one
    OPTIONAL piece (skip only if site wifi at EVERY boot is guaranteed). This UPDATES the earlier
    "clock = just DS3231" → now **boot-NTP + DS3231 backstop** (still no second radio).
  • **GRACEFUL FALLBACK (requirement):** if wifi is unreachable at boot, do NOT block collection — use the
    NAND-cached mapping (flagged stale) + RTC-or-last-known time (flagged). A wifi outage degrades, not
    halts.

**2. PROVISION PROFILE + VALIDATION FLOW + SEAMLESS SWAP.**
  • **Provision profile = the per-unit registry record.** Per camera: real **body serial** (physical,
    immutable, READ from the device, never a label) + assigned **camera_id** (logical, GLOBALLY UNIQUE,
    UNCHANGING) + side + mount + wifi config (the body-serial↔camera_id crosswalk). Per fob: fob_id, board,
    firmware. Per kit: grouping + the hardware config (thread 3).
  • **camera_id "universally different and unchanging" → ALLOCATION SCHEME guaranteeing global uniqueness**
    (registry-allocated, like the station #s — NOT free-typed) + **immutability, NO REUSE** (a swapped-out
    camera_id retires FOREVER; the replacement gets a NEW id — that's what lets episodes resolve to the
    right physical camera across a swap). [DECISION to confirm: camera_id registry-allocated + never-reused.]
  • **Provisioning VALIDATION flow:** write the identity, then READ IT BACK + confirm (CAMERA_ID/SIDE/KIT_ID
    correct, real serial matches expected, camera reachable + recording-capable), flag any mismatch. =
    cameras.py write + a verification step.
  • **SEAMLESS CAMERA SWAP (event-sourced, B-8):** pull kit_id from the fob → timestamped "decommission"
    event for the outgoing camera (profile retires) → provision the replacement into the same role
    (left-of-kit_042, NEW camera_id) → the fob's kit_id is unchanged (operator notices nothing); history
    preserved (episodes resolve to the right physical camera by camera_id + time).

**3. PER-KIT HARDWARE CONFIG (gripper/camera/firmware versions) — CONFIRMS + sharpens B-9.** Per-KIT,
recorded at PROVISIONING, event-sourced + TIMESTAMPED so you reconstruct "kit 42 ran gripper v2 from date
X, v3 from Y." = B-9's capture-stack tied to the kit, made event-sourced via B-8. NEW piece: **a
lightweight "update kit hardware config" flow SEPARATE from firmware reprovision** — swapping a gripper
doesn't reflash, but must emit a timestamped "gripper changed" event so the config stays truthful. So:
the config-update flow + provisioning = where config is SET/CHANGED (event-sourced source of truth); the
B-9 daily supervisor confirm = the ACCOUNTABILITY BACKSTOP (catches a swap someone forgot to record).
Video-based validation flag (detect a config mismatch from footage) = DEFER (speculative; only if feasible
+ worth it — Mo's call to spec later).

**4. GOD'S-VIEW METADATA PANEL — yes, trivially.** The episode-detail panel (video left, metadata right)
shows the resolved provenance: kit, gripper version, camera/firmware, calibration + task/prompt + QC
flags. All resolvable from kit_id + timestamp against the registry (the capture-stack at that episode's
time). Part of the already-buildable historical half — just include the capture-stack provenance.

**WHERE IT LANDS (none of it is F3, which is merging):**
- **Firmware capability:** the BOOT-UPLINK (wifi → NTP + mapping → AP, + graceful fallback) = the
  idle-uplink transport task (now also boot-uplink) + the DS3231 (Victor's hardware).
- **Provisioning console:** the profile, the validation flow, seamless swap, the per-kit config + the
  config-update flow.
- **Ops console:** the god's-view metadata panel.
- **Contract pass:** new operational entities — provision-profile/unit-registry, event-sourced
  hardware-config history, + (from the task-setup thread) the station registry + task→station assignment +
  catalog versioning. The sidecar fields largely exist; the entities to MANAGE + the event history are new.
- **OPEN DECISIONS for Mo:** (a) DS3231 in/out (recommend in unless site wifi at every boot guaranteed);
  (b) confirm camera_id registry-allocated + never-reused.

Reinforces: the **provisioning + ops consoles + a contract pass** are the next big chunks after the
coordinator, and the start-of-day setup (hardware config + task assignment + sign-in) + provisioning
(profiles + validation + swap) are the two console surfaces. The boot-uplink is a firmware capability that
can run in parallel.

## RTC deferred + F3 merge-ready + flows.html fold-in 2026-06-25

**RTC DEFERRED (Mo): "treat as if we do NOT have these for now."** DS3231 RTCs won't arrive for a while.
SUPERSEDES the earlier "boot-NTP + DS3231 backstop (recommend in)": the clock is now **boot-NTP ONLY**.
Consequence: a no-wifi-at-boot OR clock drift relies ENTIRELY on the loud-not-silent flagging
(recording_suspect / no_wallclock) — flagging is load-bearing, not a backstop to a backstop. DS3231 remains
the eventual fix WHEN it arrives. (NTP ≠ RTC: NTP = the boot-time network pull; the DS3231 was the onboard
holdover, now unavailable.) flows.html OPEN-CLOCK already written this way ("no RTC yet, boot-NTP only,
flagged").

**F3 / PR #8 — MERGE-READY (not yet merged; squash hash PENDING).** PR #8, branch
`mzcassim/eunomia-run-f3-ui` (lowercase, F1/F2 convention), single commit `ec2fd89`, squash subject
"[FEAT] Run F3 — coordinator/ui/: the CYD touchscreen rendering core state (env:cyd TFT-on + tidy
extended to core/)". Both CI jobs green: cpp (3m4s: native + esp32 headless + cyd TFT-on + clang-tidy),
gates (31s: 5 Python gates + codegen drift). ⭐ **clang-tidy VERIFIED RUN on core/ + transport/proto/** (the
key concern): `make gates-cpp-tidy` echoed the scope string, processed all 11 TUs ([1–6] the six core .cpp
incl. coordinator/trigger_state_machine/button_feedback where the 5 enums live, [7–11] the five proto
.cpp), 110 suppressed (all non-user) → 0 user findings, NOT skipped. mergeable CLEAN, 0 behind main, zero
unintended drift (contracts unchanged, transport/vendor/ excluded, core/ touched only by the 5-enum fix +
present_count() + F2→F3 comments). Branch-case churn corrected (capital Mzcassim/ pushed first → lowercase
re-pushed, PR #7 closed, #8 recreated, capital remote branch deleted; a stale orphaned check-run briefly
held #8 UNSTABLE → close+reopen fired one fresh authoritative run → CLEAN). plan.md + the SPEC §1.8
correction + the CI scope strings all landed in the PR. → squash-merge (external) → Mo sends the hash → I
record it, closing the coordinator lineage a17ba20→201c0d5→cc5c40f→d07490a→cc20e93→a0ba39c→F3.

**PROCESS NOTE (Mo's feedback): do NOT refer to "Conductor" in a prompt to the agent — confusing (the
agent runs IN Conductor).** In future agent-facing prompts: say "report and stop; do not merge" and leave
the merge as an external step, WITHOUT naming Conductor. (Updates the earlier merge-convention note.)

**flows.html FOLD-IN — this session's new flows added/updated + JS syntax-verified (node --check on all 3
script blocks = OK; backup /tmp/flows.bak).** 9 edits: added 7 REFS (OPEN-CLOCK, EDGE-BOOTNOWIFI,
OPEN-MIDDAY, OPEN-CAMID, OPEN-STATIONREG, OPEN-CFGVALID, EDGE-LIVETELEM); ADDED steps F-CAP-00 (power-on /
boot sync), F-CAP-12 (call lead / LLAMAR), F-OPS-05 (start-of-day supervisor setup), F-OPS-06 (god's-view
drill-down), F-OPS-07 (QC review: IMU red-border + ground truth), F-PROV-10 (per-kit hardware config +
update flow); UPDATED F-CAP-02 (task selection → station entry → task resolution, dynamic assignment +
NO-GO + collision-safe station registry), F-CAP-10 (telemetry flush → coarse boot/idle flush, live
telemetry CUT), F-OPS-02 (live state → last-seen freshness, cut), F-PROC-05 (quality eval → + IMU
heuristics → qc_sus/red-border + human_label), F-PROV-04 (provisioning → + read real serial + validate
readback + store provision profile [body serial ↔ camera_id unique/unchanging + side/mount/wifi/fob_id]),
F-PROV-07 (repair/swap → seamless swap via profile: outgoing camera_id retires, new id at same kit_id,
resolve by camera_id + time).

**FLOWS THAT STILL NEED MORE DETAILED SPECCING (Mo asked):** the new console/supervisor steps use M.generic
placeholder panels, not bespoke UI — flagged for later detailed design: (1) F-OPS-05 start-of-day setup
console UI (the station visual-layout editor + registration + task-assignment + the per-kit hardware
confirm — the most complex new surface); (2) F-OPS-06 god's-view dashboard layout (the 3-level
operator→episodes→video drill-down + the metadata panel contents); (3) F-OPS-07 IMU-QC red-border + the
ground-truth good/bad UI; (4) F-PROV-04/F-PROV-10 the provision-profile schema + the validation/readback
flow + the config-update flow (real fields/states); (5) F-CAP-00 boot-sync + F-CAP-12 LLAMAR — represented
with placeholder fob panels, but their actual CYD screens + the boot-uplink fallback states + the LLAMAR
network-switch need bespoke mockups; (6) the station-registry/collision mechanics (site_id+station#
allocation, the layout "what's taken" view) — OPEN-STATIONREG. These are all LATER-run console/firmware
work, not blockers; the flows now REPRESENT them so they're discoverable + on the map.

## RTC DEFERRED — "treat as if we do NOT have these for now" (Mo) 2026-06-25

SUPERSEDES the "+DS3231 backstop (recommend both)" recommendation from the boot-uplink batch above. The
DS3231 RTCs won't arrive for some time → **treat the system as having NO RTC.** So the clock is **boot-NTP
ONLY** (NTP = the network pull when the fob joins office/site wifi at boot; the DS3231 was the onboard
backstop, now unavailable).
- **Consequence:** a no-wifi-at-boot OR clock drift during a session now relies ENTIRELY on the
  loud-not-silent flagging (recording_suspect / no_wallclock). The boot graceful fallback (cached NAND
  mapping flagged stale + last-known/flagged time, never halt) becomes the ONLY backstop — there is no
  hardware holdover.
- The boot-uplink (time + task-mapping pull, single radio, before hosting the AP) is UNCHANGED — it's the
  time source. Only the DS3231 hardware backstop is removed (deferred).
- When DS3231s eventually arrive, revisit (the boot-NTP + DS3231-backstop design from the batch above is
  the eventual target); for now, boot-NTP only.

## F3 ui/ — MERGE-READY, handed off (PR #8) 2026-06-25

Conductor handoff received. PR #8 (https://github.com/Pantheon-Industries-Inc/Eunomia/pull/8), branch
`mzcassim/eunomia-run-f3-ui` → main (lowercase, F1/F2 convention). Squash subject: `[FEAT] Run F3 —
coordinator/ui/: the CYD touchscreen rendering core state (env:cyd TFT-on + tidy extended to core/)`.
Single squashable commit `ec2fd89`.
- **Both jobs green:** cpp pass 3m4s (native + esp32 headless + cyd TFT-on + clang-tidy), gates pass 31s
  (5 Python gates + codegen drift).
- **⭐ clang-tidy verified RUN on core/ + proto/ (NOT skipped):** `make gates-cpp-tidy` (CI=true, pinned
  clang-tidy 22.1.7) echoed "clang-tidy (blocking, scoped: core/ + transport/proto/)", processed all 11
  TUs — [1/11]–[6/11] the six core/ .cpps (incl. coordinator.cpp, trigger_state_machine.cpp,
  button_feedback.cpp where the 5 enums live) + [7/11]–[11/11] the five transport/proto/ .cpps — "Suppressed
  110 warnings (110 in non-user code)" → 0 user findings. The extended blocking scope is real + green.
- **Merge-readiness:** mergeable MERGEABLE, mergeStateStatus CLEAN, 0 behind origin/main, single commit,
  zero drift (contracts/ unchanged [drift gate 0], transport/vendor/ excluded, core/ touched only by the
  5-enum underlying-type fix + present_count() + the F2→F3 comments — reviewer-confirmed).
- **Process gotcha (corrected):** first pushed as `Mzcassim/…` (capital — macOS case-insensitive FS made
  local refs look capital; real F1/F2 remotes are lowercase). Corrected: pushed lowercase, recreated as
  PR #8, closed the wrong PR #7, deleted the capital remote branch. A stale orphaned check-run briefly held
  #8 UNSTABLE; close+reopen fired one fresh authoritative run (28189822131, success) → CLEAN. Agent
  recorded the gotcha + the `uv sync --all-packages` fresh-worktree bootstrap to its memory.
- plan.md, the SPEC §1.8 correction, and the CI scope strings all landed in this PR.
- **STATUS: merge-ready; the squash-merge + post-merge remote-branch delete is the external step.** Await
  the squash hash on main to close the coordinator lineage:
  a17ba20 → 201c0d5 → cc5c40f → d07490a → cc20e93 → a0ba39c → [F3 hash pending].

## SD-flash / rootkit preservation — ingest must NOT strip the cards (Mo) 2026-06-25 [verified in x3-capture-kit]

Mo: "ensure ingest does not strip the SD cards of the flash they need (we flash all SDs for daemons that
do important things)." VERIFIED — confirmed + the failure mode is real:
- **The cards are mass-flashed with a ROOTKIT** (`oncam/install_sd_rootkit.sh`): creates `PANTHEON/` +
  installs `bootup.sh`, `discardd` (also as `pantheon_x3_agent.sh`), generic `PANTHEON/config.env`,
  `card_ready.json`, `fleet_version.txt`. The stock X3 firmware **auto-runs `bootup.sh` from the SD root AS
  ROOT at boot** (no per-cam jailbreak), which launches discardd. discardd = the load-bearing on-cam agent:
  writes the per-episode `*.pantheon.json` sidecars (Eric's ingest input) + the `PANTHEON/camera.json`
  ledger (kit/side for Layer-0 routing) + (unverified) mode-lock/thermal/instant-delete.
- **THE FAILURE MODE:** `bootup.sh` REFUSES to run the agent unless `PANTHEON/card_ready.json` is present
  ("protects against an operator inserting a random / wiped / off-the-shelf SD"). So a wiped/reformatted
  card silently reverts the camera to STOCK behavior — no sidecars, no settings-lock, no instant-delete =
  broken capture, and the data is unattributable.
- **Identity is DELIBERATELY NOT on the SD** (LESSONS #9) — it's in NAND. The SD flash is GENERIC
  (mass-flash, one identical image to every card); the only per-camera step is the one-time NAND identity
  burn. So the rootkit is identical across cards and re-flashable, BUT see the firmware caveat.
- **What the predecessor Layer 0 (Victor, styx-local-ingest.sh) does:** whole-card rsync that PRESERVES
  the DCIM tree + the `*.pantheon.json` sidecars + the `PANTHEON/` ledger → atomic `.tmp→final` promote →
  verify → **then "wipe card"** (Layer 0's stated responsibility: "mount SD, route, atomic-promote, verify,
  wipe card"). **The contract does NOT disambiguate "wipe" = clear-footage-only vs full-reformat.** The
  mass-flash "deployment is cheap" framing suggests a full-wipe+re-flash is tolerated there.

**CONSTRAINT for the Eunomia ingest/drain run (the real ask):**
1. **MIRROR everything verified BEFORE touching the card** — DCIM + `*.pantheon.json` sidecars + the
   `PANTHEON/` ledger (the on-card `camera.json` kit/side is load-bearing Layer-0 ROUTING; the sidecars are
   the metadata-ingest input). The predecessor already preserves all three in the rsync — match that.
2. **The card-clear MUST guarantee the card returns PROVISIONED.** Either (a) clear ONLY the footage (DCIM)
   and PRESERVE the rootkit (`bootup.sh`/`discardd`/`pantheon_x3_agent.sh`/`config.env`/`card_ready.json`/
   `fleet_version.txt`), OR (b) full-wipe then RE-FLASH the mass-flash image. **NEVER leave a
   wiped-unprovisioned card** — `bootup.sh`'s `card_ready.json` guard refuses it → broken capture.
   **RECOMMEND (a) clear-footage-only** (preserve the rootkit): no re-flash step, and it sidesteps the
   firmware-version re-root fragility (next point).
3. **Firmware-version caveat (carry to Victor/ops):** auto-root is X3-v1.1.6-SPECIFIC — the contract calls
   the per-firmware (not per-camera) compatibility "the real fragility." A full-wipe+re-flash path depends
   on the whole fleet being on a compatible firmware to re-root from one image; **clear-footage-only avoids
   the re-root entirely** (the rootkit was never removed).
4. **The front `_00_` lens drop is NOT a card op:** `DELETE_FRONT_AFTER_KEEP=0` keeps the front lens
   on-card so the IMU survives; ingest extracts the IMU then drops the front lens FROM THE MIRRORED COPY in
   staging — legitimate footage processing, never touches the card's rootkit.

WHERE IT LANDS: the Eunomia **ingest/drain** run (the Layer-0-equivalent card-handling) — make the
card-clear policy EXPLICIT (clear-footage-only, preserve rootkit) rather than inheriting an ambiguous
"wipe card." Flows.html DRN area gets a card-clear/return-to-service step. NOT F3.

## Post-F3 sequencing — LOCKED (Mo) 2026-06-25

After F3 (coordinator complete), the remaining work + order, both calls confirmed by Mo:
- **(1) Contract pass FIRST** — the shared spine; every console + ingest builds against it. Cheaper to
  design the multi-consumer entities once, up front, than to let the first console define them; the
  project has run contract-first the whole way (0a–0d before firmware). = **Run 0e** (operational-model
  extensions + docs fold-in); plan-only prompt drafted (`run0e_contract_prompt.md`).
- **(2) Then the provisioning console** — the most loose threads converge there, it's UPSTREAM (creates
  profiles, registers stations, seeds the catalog the setup console assigns from), and it carries the
  CONFIRM_ID roster fix (a known soft spot in what F3 shipped). Its FIRST run is scoped to the identity
  foundation (profile + validation + camera_id registry); swap + rig-config + station/catalog are
  follow-ons.
- Then: the **start-of-day setup console** (station layout + task assignment + daily hardware-config
  confirm), **ingest** (v2→v1 reconciliation + dual-signal join + one-sided-record catch + capture_stack
  resolution + card-clear), the **ops console** (god's-view drill-down + spot-check + IMU-QC + ground-truth).
- **Boot-uplink firmware runs IN PARALLEL** — a separate firmware stream; doesn't need the contract pass;
  gated on Victor's uplink-borrow + the field-clock conversation anyway.
- **The two consoles stay SEPARATE, split by cadence:** provisioning = build-time/occasional; setup =
  daily; ops = continuous. The per-kit hardware config is the clean test of the split — it's a contract
  entity (the event-sourced history) that provisioning CREATES and setup CONFIRMS: same entity, different
  operations, no duplication. Works only because the contract OWNS the entity → contract first.
- Mo: "build all of this asap."

**Run 0e scope (the contract pass):** station registry (site_id+station# unique, registered,
retire-not-reuse); task catalog versioning + prompt variants + rotation (episodes pin the version);
time-ranged append-only task→station assignment (resolve by site_id+station#+timestamp); provision profile
on hardware_unit (body_serial ↔ camera_id [registry-allocated, unique, unchanging, retire-not-reuse] +
side/mount/wifi/fob; fob profile); event-sourced hardware-config history + capture_stack (resolved AT
INGEST from kit_id+components+timestamp — NOT a forced sidecar capture_stack_id; reconcile B-9 wording).
[REVISED below — docs fold-in DROPPED; 0e is pure contract code.] Additive +
non-breaking to the firmware-facing wire types. PLAN-ONLY first.

## F3 MERGED + docs strategy + Run 0e revised 2026-06-25

**F3 MERGED.** PR #8 squash-merged as `c7638cd` (2026-06-25T20:29:19Z), now top of origin/main above F2;
remote branch deleted. **Coordinator lineage CLOSED:**
a17ba20 (0a) → 201c0d5 (0b) → cc5c40f (0c) → d07490a (0d) → cc20e93 (F1 core) → a0ba39c (F2 transport)
→ **c7638cd (F3 ui)**. The firmware coordinator is complete: contracts 0a–0d + F1 core + F2 transport +
F3 ui (render_state/touch/screens/flow + test_ui), all six NOTE flags, the SPEC §1.8 no-queue correction,
the clang-tidy scope extension to core/+proto/ (CI-verified RAN, not skipped).
- **F3 carry-forwards (open, tracked):** (1) the CONFIRM_ID roster→name resolution (the "Operador #N"
  fallback; an on-device number→name roster) — a PROVISIONING-CONSOLE item; (2) the "can passive L2
  presence run DURING a take for an early one-sided-record warning?" question — PARKED for the later
  transport / one-sided-record work (the authoritative one-sided catch stays at ingest).
- **Register bookkeeping NOTE:** the F3 merge + these carry-forwards are captured HERE, in the register Mo
  maintains + pushes (= repo `docs/DECISION_REGISTER.md`). Mo should push THIS register rather than have
  the agent draft a separate `[DOCS] Register F3 merge` commit editing the repo copy — two writers on
  `docs/DECISION_REGISTER.md` would fork it. (If a separate repo `BUILD_PLAN.md` is agent-maintained,
  that's the agent's to update — the register is Mo's single canonical copy.)

**DOCS STRATEGY — SPEC/CONTRACT deprioritized (Mo: "the docs pushes are lowkey annoying, are they
necessary").** Honest answer: mostly NO. The system has FOUR overlapping representations — the REGISTER
(decisions / why), flows.html (the visual flow map), the contracts/ CODE (the actual contract that
consoles + ingest build against), and SPEC.md / CONTRACT.md (a narrative restatement). The first three are
each load-bearing + non-redundant; SPEC/CONTRACT mostly RESTATE them — that duplication is the maintenance
tax and the thing that drifts. Decision:
- The per-decision "fold every new flow into SPEC prose" obligation is **DROPPED.** flows.html + the
  register are the live flow/decision artifacts.
- SPEC/CONTRACT get a **deliberate refresh only when there's a READER who needs them** (onboarding a new
  hire, an external handoff) — NOT per-decision / per-run.
- The few **actively-wrong load-bearing lines stay FLAGGED here for a someday 5-minute one-off fix** (NOT
  bundled into a build run): the SPEC §1.7 "fob writes the sidecar via its NTP wallclock" framing (stale
  on both counts — the on-cam agent writes the sidecar; time is boot-NTP-only/no-RTC) + CONTRACT §1.7
  (fob-doesn't-write-sidecar). §1.10 telemetry-deferred is a one-liner, do-if-convenient. Low risk to
  leave: the people building know the truth, and the register + code + flows are right.

**Run 0e REVISED → pure contract CODE (docs fold-in DROPPED).** Per the docs strategy, 0e is now ONLY the
five operational entities + codegen (station registry; task catalog versioning + variants + rotation;
time-ranged task→station assignment; provision profile on hardware_unit; event-sourced hardware-config
history + capture_stack resolved-at-ingest). No SPEC/CONTRACT edits. Additive + non-breaking to the
firmware-facing wire types. Plan-only first. Prompt `run0e_contract_prompt.md` updated to match.

## ESP32 fob boards frying (thermal) — endurance requirement + mitigations 2026-06-25

**ISSUE (Mo):** the CYD fob boards get FRIED during use — PERMANENT (won't restart after), suspected
HEATING frying a component. Team investigating; weighing a different board or heatsinks. **REQUIREMENT: a
board must run 6–7 hours continuous without permanent damage.**

**Prime suspect (hardware, grounded — web-confirmed CYD failure mode):** the CYD (ESP32-2432S028R) onboard
**AMS1117 LDO regulator** + the **TFT backlight** are the documented CYD weak points. Under continuous
WiFi (the coordinator AP must stay up) + full backlight + 240MHz CPU, the LINEAR LDO burns (Vin−3.3)×I
continuously in a poor-thermal SOT-223 package; in a sealed handheld enclosure with no airflow it cooks →
permanent failure. "Won't restart" = dead regulator (no 3.3V rail). Over-volting VIN accelerates it.
(Confirmed: CYD projects commonly fail on unstable power — WiFi peaks + backlight draw; the fix is a clean
switching converter, and the ESP32-S3 is the documented upgrade path.)

**Hardware levers (Victor/Zak — the PRIMARY fix):**
- **Power delivery = the biggest lever:** feed a clean regulated 3.3V (BYPASS the onboard LDO) or replace
  the LDO path with a switching BUCK; keep VIN low. LDO heat ∝ (Vin−3.3)×I → attacks the cause.
- Heatsink the regulator/ESP32 (cheap; treats the symptom).
- Enclosure ventilation / thermal path (sealed handheld traps heat).
- Board choice: ESP32-S3 module (documented CYD upgrade) or any board with a switching regulator + better
  thermals — the durable fix if the CYD is marginal for all-day continuous duty.

**Firmware mitigations (coordinator firmware — REDUCE load + a safety net; NOT a substitute for the
hardware fix):**
- **Backlight management** (in the F3 `ui/` layer): dim/sleep the backlight after N s idle, wake on touch
  — the screen doesn't need full brightness between episodes; a real chunk of continuous draw.
- **CPU clock scaling:** 240→80MHz (80 = the WiFi floor) during idle gaps; full clock only while actively
  coordinating.
- **WiFi TX power:** tune to the minimum that reliably reaches the wrist cameras (they're within arm's
  length) — less RF heat. (AP must stay up during a session → TX power is the lever, not WiFi sleep.)
- **Thermal monitoring, loud-not-silent:** the ESP32 internal temp sensor is ROUGH (relative trend /
  threshold only, not absolute) → for real coverage add a small external thermistor on the regulator
  hot-spot. If temp climbs toward danger, flag it + optionally shed load (force-dim, drop clock). Rides
  the COARSE boot/idle ping channel we kept (NOT live mid-take telemetry — consistent with the single-radio
  live-telemetry cut), so the fleet self-reports thermal health + you catch a marginal unit before field
  death.

**The ENSURE (so we don't repeat at fleet scale) — a gate, like the camera already has:**
- **Board-thermal ENDURANCE GATE** (parallels the existing camera "2-hr continuous 3K/100 thermal
  survival" gate in the INGESTION_CONTRACT): no board variant deploys to a fleet until one unit, **IN ITS
  ENCLOSURE, running the real firmware load (AP up + display + coordinating), survives a 6–7 hr continuous
  soak** at expected ambient with temps LOGGED. Add to the bench-test plan / hardware findings.
- **Bake thermal monitoring into the firmware** so the fleet keeps reporting against the requirement
  post-deployment.

**Ownership / roadmap:** hardware fix (power/regulator/buck/heatsink/enclosure/board) → Victor/Zak
(PRIMARY). Firmware thermal/power-management (backlight + clock + TX + temp monitoring) → a coordinator
firmware capability — folds naturally into the **boot-uplink firmware run** (both are coordinator firmware
outside the F1–F3 core). The endurance soak → a **bench/validation gate**. ORTHOGONAL to 0e (the contract
pass proceeds untouched).

## Board issue UPDATE — recovers + reconnection-flaky, NOT permanent death 2026-06-25

CORRECTION to the thermal entry above: the board DOES power back on — it just doesn't reliably RECONNECT
to the cameras after the event (struggles; one unit did reconnect). So it is NOT permanent frying / a dead
regulator. Reframe: a **camera-reconnection-after-power-event robustness problem.** Mo: not certain of the
cause; Victor debugging; continue meanwhile.
- **Plausible unifying thread (consistent-with, NOT confirmed — Victor's debug decides):** the CYD's known
  POWER INSTABILITY (WiFi current peaks + backlight) → a brownout/voltage dip mid-session resets the fob →
  on recovery the fob re-hosts the AP but the X3 cameras don't cleanly RE-ASSOCIATE to the re-appeared AP
  (the flaky part). The "thermal frying" may be a red herring (or heat degrades RF/reconnection). The
  camera-reassociation-after-AP-flap is the EXACT area Victor's been hardening (the 2026-06-24 channel
  {1,6,6} + ghost-STA nOk>=kMinCams + lockcams /osc/info fixes).
- **If that's the root:** the hardware clean-power fix (buck / clean 3.3V / stable VIN) addresses the
  brownout-resets AT THE SOURCE — so the same fix that helps the (rare) frying also helps the (common)
  flaky-reconnection. Firmware complements: robust re-association after any reboot (fob actively re-hosts +
  re-confirms the camera links, unconditional-AP-up, loudly flags if it can't re-establish).
- **General robustness goal ("optimize to avoid issues like this"):** DETERMINISTIC RECOVERY after any
  power event/reboot — the fob must reliably re-host the AP AND re-confirm the cameras, never silently sit
  disconnected. Rides the boot-uplink firmware run (boot → re-host AP → verify cameras) + Victor's
  reconnection hardening. The endurance soak gate stays useful to rule thermal in/out.
- Defer the diagnosis to Victor; no build action now; **0e proceeds.**
