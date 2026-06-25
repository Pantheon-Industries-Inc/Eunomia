# Run F1 — `firmware/coordinator/`: the coordinator on Victor's proven stack (PLAN ONLY)

> **Status: PLAN — not implemented.** This is the first *consumer* of the contract: it implements the
> generated `CoordinatorPort` (Run 0c) against Victor's **real, proven, actively-evolving** fob/camera
> stack delivered as `pantheon-x3-firmware_2026-06-24.zip` (rootkit v0.7.1 / KIT_VERSION 0.10.0, fob
> `3.8.3-fast-guard`). It is **adapter + reconciliation work on top of that stack, NOT a rewrite.**
>
> **Ground-truth rule honored:** every claim below is checked against Victor's *delivered code*
> (`discardd`, `bootup.sh`, `x3_join_fob.sh`, `x3_fob_link.sh`, `install_sd_rootkit.sh`, `autoexec.ash`),
> the generated ports/sidecar headers, and the authority docs (CONTRACT §1.6/§1.7/§2/§3.3/§3.5/§3.6,
> SPEC §1.8, DECISION_REGISTER). Where his code disagrees with a handoff or with our assumptions, **his
> code wins and the disagreement is flagged** (§3). Two decisions are raised prominently for annotation
> (§2): the **sidecar reconciliation** and the **one-run-vs-split LEAD OQ**.

---

## 1. Summary

**What F1 produces (recommended scope = `core/` only — see the LEAD OQ §2.2):** the pure,
hardware-free, off-target-testable heart of the coordinator — a real `CoordinatorPort` implementation
with a provable correctness guarantee, authored (not adapted):

- **`coordinator/core/` — the trigger state machine + episode/ordinal logic + sidecar assembly + the
  button-feedback STATE machine.** Implements the generated `CoordinatorPort` against *injected seams*
  (a `CaptureDevicePort` fleet, an L2 `PresenceSource`, and `Clock`/`Rng`/`PersistentStore`) so the
  logic is exercised with `pio test -e native` and **no rig** (the one-machine rule). Carries the two
  non-negotiable guarantees: **START-valid-only-from-idle** (spam-safety) and the **both-cams-acked
  (`sent==2`) phantom-press gate**.
- **The sidecar-assembly artifact:** `core/` assembles an `eunomia-sidecar/v1` record from the fields
  the coordinator owns and proves it **validates against the generated `eunomia_sidecar` C++ target +
  the golden fixtures** off-target — the F1 analog of how the contract runs proved things in CI.
- **The reconciliation decision** (§2.1) made concrete: what the coordinator emits, what discardd
  emits, where the translation lands.

**What F1 defers** (the recommended split → **F2**): `coordinator/transport/` (WiFi SoftAP hosting,
the `wifiLock`-serialized fire-and-forget OSC client, the telnet client, the file-trigger writes — i.e.
THE TWO HARD RULES on hardware, adapted from Victor's `esp32-fob-wifi` source) and `coordinator/ui/`
(the CYD touchscreen). These are hardware-coupled adapters of Victor's proven binary, best done **with
the rig and his actual source in hand** — and his fob source is **not in this bundle or repo** (§3,
finding 6). This plan still specifies them (§5.2, §5.3, §7) so the boundary and the two hard rules are
fully drawn now.

**The explicit boundary to Victor's stack** (full table in §5.4): F1 AUTHORS the state machine + the
ordinal/episode logic + the sidecar assembly + the button-feedback state. F1 (in F2) ADOPTS Victor's
`esp32-fob-wifi` transport patterns (SoftAP, `oscSendNoWait`, `wifiLock`, `esp_netif_get_sta_list`).
F1 leaves UNTOUCHED — and depends on — discardd, the WiFi join (`S99zfobjoin`/`x3_fob_link`/
`x3_join_fob`), the camera-side pre-arm/cross-cam-sync work, and the camera firmware. **Nothing in F1
reimplements discardd, the WiFi join, or the pre-arm.**

---

## 2. The two decisions I most want to make at annotation

### 2.1 THE SIDECAR RECONCILIATION (the headline decision)

Victor's `discardd` writes `pantheon-x3-sidecar/v2`; the contract is `eunomia-sidecar/v1`. **Both are
nested.** The divergence is **bidirectional** (not a clean subset — confirmed from the
`write_episode_sidecar` `cat >` block, discardd:1312–1360):

| Axis | discardd `v2` (delivered) | contract `v1` |
|---|---|---|
| schema string | `pantheon-x3-sidecar/v2` | `eunomia-sidecar/v1` |
| sidecar filename | `VID_<ts>_<seq>.pantheon.json` | `VID_<ts>_<seq>.eunomia.json` (CONTRACT §2.1) |
| `seq` | **quoted STRING** (3-digit filename counter) | **int** |
| namespacing | **one big `identity`** block lumps provenance (`fob_id`/`fob_build`/`camera_firmware`) + outcome (`stop_reason`) + assignment (`task_*`/`prompt`) | split into `identity` / `provenance` / `outcome` |
| `files` | `{back,front,lrv}` each `{raw,canonical}` | `files.back` (one HARD string) |
| only in `v2` | `ts`, `timestamp`, `layout`, `qc_status`, `qc_reason`, `back_size`/`front_size`, nested `record_settings` object | — |
| only in `v1` | — | `episode_ordinal`, `display_id`, `modality`, **`recording_suspect`** (NET-NEW), `camera_clock`, `assignment_source` |
| `record_settings` | nested JSON object | string |
| two-axis versioning | `kit_version` ⊥ `record_format_version` ✓ | same ✓ |

**A second, larger divergence the code revealed — WHO writes the sidecar, and WHEN** (this reframes the
whole decision; see §3 finding 2): CONTRACT §1.7 models the **fob** telnet-writing the sidecar twice
(identity-at-START, outcome-at-STOP). **Victor's stack does not work that way.** The fob pushes
`current_assignment.env` (identity/task, before START) and `current_stop.env` (outcome+timing, at STOP,
bound by `bimanual_episode_id`) over telnet and touches the trigger files; **discardd** assembles and
writes the single `.pantheon.json` *camera-side* when it detects the finalized clip
(discardd:1136–1360). There is no fob-written JSON. So `CoordinatorPort.write_sidecar` on this stack
**= push the two env files**, and discardd materializes — the §1.7 two-write *intent* (identity known
before the clip + outcome bound at stop) is realized by the env mechanism.

**Options:**

- **(A) Converge discardd's writer to `eunomia-sidecar/v1`.** Cleanest end-state (one shape, system of
  record). **Cost:** changes Victor's actively-evolving code (he is mid-stream on pre-arm/cross-cam
  sync); a writer change races his work, and he's the owner. Cross-language conformance would then bind
  his shell writer. **Not F1's to do unilaterally.**
- **(B) Ingest tolerates BOTH shapes; discardd unchanged; coordinator emits nothing new.** Lowest
  disruption to Victor. **But** it leaves F1 with no defined sidecar-assembly artifact to prove
  off-target (the run explicitly wants `core/`'s assembly to validate), and pushes 100% of the
  shape-bridging to a later ingest run with no coordinator-side contract surface.
- **(C) HYBRID — the boundary the code already draws (RECOMMENDED).**
  1. `core/` assembles a complete **`eunomia-sidecar/v1`** record from the **coordinator-owned
     fields** (the fob-sourced set, §5.1) + the camera-owned fields it receives — this is the
     coordinator's **contract surface**: it is what F1 conformance-validates off-target, and what the
     coordinator logs to its god's-view / ordinal-join backup.
  2. The **on-card per-clip JSON stays discardd's job** (do **not** touch his writer in F1).
     `transport`'s `write_sidecar` (F2) realizes it as **pushing `current_assignment.env` (START) +
     `current_stop.env` (STOP)** — exactly the env mechanism discardd already consumes — so discardd
     keeps emitting `v2` unchanged.
  3. The **`v2`→`v1` shape reconciliation lands at INGEST (a later run)**: ingest translates discardd's
     lumped `identity` into the clean namespaces and casts `seq`. The join key is `episode_id`
     (identical both arms), so the coordinator's `v1` record and discardd's `v2` card-file reconcile
     cleanly downstream.
  4. **Converging discardd to `v1` (option A) becomes a *separate, coordinated* change owned with
     Victor** — explicitly out of F1.

  **Why C:** it gives F1 a real, testable `v1` assembly (the correctness proof the run wants) **without
  changing Victor's moving code**, honors the env-push mechanism his stack actually uses, and keeps the
  contract as the coordinator's emitted surface. It matches the DECISION_REGISTER framing
  ("mostly ADAPTER + RECONCILIATION work… emit/tolerate the contract shape," 2026-06-24 bundle block).

  **Contract-change check (C requires none):** `eunomia-sidecar/v1` already has every field the
  coordinator owns. **One field to confirm at annotation:** `recording_suspect` is NET-NEW and
  **coordinator-owned** (the fob's STOP-time "did the clip actually grow?" check via telnet `ls` +
  growth) — discardd does not write it. C carries it in the coordinator's `v1` record; whether it also
  reaches the card today depends on (A) later. No schema edit needed.

> **I am not silently picking.** Recommendation = **(C)**. This is the call I most want to confirm at
> annotation, including the "leave discardd's writer alone in F1" boundary.

### 2.2 LEAD OQ — one run or split? (RECOMMENDED: SPLIT — F1 = `core/`, F2 = `transport` + `ui`)

`core/` (pure state machine + ordinal/episode logic + sidecar assembly) is a fundamentally different
*shape of work* from `transport/` (hardware-coupled OSC/telnet/SoftAP adapted from Victor's source) and
`ui/` (the touchscreen). **Recommend splitting**, F1 = `core/`:

| Reason | core/ (F1) | transport + ui (F2) |
|---|---|---|
| **Authored vs adapted** | Authored from scratch (our correctness logic) | Adapted from Victor's proven 3.8.3 binary |
| **Provable off-target** | ✅ `pio test -e native`, no rig — spam-safety + phantom-press + sidecar conformance are *provable in CI* (like the contract runs) | ❌ needs the rig + the cameras to validate the OSC/telnet/SoftAP behavior |
| **Source available now** | ✅ needs only `contracts/` | ❌ **Victor's fob source is not in this bundle/repo** (§3 finding 6) — only compiled binaries |
| **Unblocks** | Unblocks transport+ui (they implement against core's seams) | Depends on core |
| **Reviewability** | A clean, self-contained, host-tested PR | Hardware-coupled; touches Victor's evolving code; best reviewed with rig evidence |

The one-PR alternative bundles an unprovable, source-blocked, rig-dependent half with a clean provable
half — larger and harder to review, and gated on obtaining the fob source. **Mo decides at annotation.**
This plan documents all three modules either way; if Mo prefers one run, §5.2/§5.3/§7 are the transport/ui
spec to fold in.

---

## 3. What I read in Victor's bundle — and where his code contradicts a handoff or our assumptions

**discardd (the authoritative readable source, ~2017 lines POSIX shell) — actual behavior:** boots →
asserts `captureMode=video` + the locked `RES_3008_1504P100` + power/thermal levers → enters a 2 s
(0.1 s when a scheduled trigger is pending) loop that: `scan_episodes` (detect new clips) →
`log_episode_group` → `write_episode_sidecar` (the `.pantheon.json` writer); handles the touch-triggers
`/tmp/{discard,archive,front_cleanup,health,start_at,stop_at,sync_arm,latency_probe}.trigger`; fires
OSC start/stop; runs telemetry/lock-reassert/low-space/health. It **NEVER touches wifi/AP/wpa_supplicant**
(discardd:11–15, the hard boundary after the 2026-06-10 LEFT-UI-hang incident) — confirming the
transport/core split from the camera side.

**The fob↔discardd control mechanism, as delivered (= our transport contract):** file-trigger + env +
OSC + telnet. The fob touches the trigger files; `start_at`/`stop_at` carry line1=epoch (fractional ok)
**or `U<uptime>`**, line2=`episode_id` (discardd:1565–1621). The fob writes `current_assignment.env`
(identity/task) before START and `current_stop.env` (`STOP_REASON`, `START_SKEW_MS`, `CAM_STARTED_UNIX`,
`CAM_STOPPED_UNIX`, `ARCHIVE`, keyed by `EP_BIMANUAL_EPISODE_ID`) at STOP (discardd:1282–1293). discardd
self-reads `camera_firmware` from `/osc/info`, fills NAND identity/ordinal, and writes the sidecar.

**Findings where the *delivered code* contradicts a handoff / our framing (his code wins):**

1. **WiFi-join — THREE approaches in his own tree, and the delivered rev4 default is NEITHER the one the
   run prompt quoted.** The prompt and an older handoff frame `x3_join_fob.sh`'s `wifi_stop.sh → load.sh
   sta → sta.sh` as "THE ONE CORRECT WAY." But the **delivered `bootup.sh`** (lines 229–268) treats
   `x3_join_fob.sh` as the **LEGACY strand-prone fallback**, prefers `x3_fob_link.sh` (whose own header
   says the raw shell path **fails with `SIOCSIFFLAGS` on bcmdhd** and uses the vendor `fobjoin` cmd-112
   path as primary), and **on rev4 cameras (the delivered firmware) launches neither** — it seeds NAND
   `/pref/pantheon_fob.env` and lets the **`S99zfobjoin` supervisor** own the join, because running
   `x3_fob_link` too makes them **fight over `wlan0`** (verified 2026-06-24, kit_55). **Net:** the live
   join path for the delivered rev4 camera is the **NAND `S99zfobjoin` supervisor** — camera-side,
   Victor's, **F1 does not touch it.** F1's only obligation: the fob must host the OPEN SoftAP
   `PANTHEON-kit_<n>` @ `192.168.42.1`, DHCP `.2–.6`, for the camera to join.

2. **The on-card sidecar is written by discardd (camera-side), NOT by the fob — contradicting CONTRACT
   §1.7's "the fob telnet-writes the identity sidecar at START + the outcome sidecar at STOP."** Reality
   (§2.1): the fob pushes `current_assignment.env` + `current_stop.env` and touches triggers; discardd
   assembles+writes ONE `.pantheon.json` on clip-detection. **This is the single biggest mechanism
   divergence and it redefines `CoordinatorPort.write_sidecar` on this stack** (= push the env files).
   The §1.7 *intent* is preserved; the *mechanism* is the env push, not a fob-written JSON.

3. **discardd DOES emit OSC** (the `captureMode=video` reassert, the idle `record_resolution` re-assert,
   and the start/stop fires), in mild tension with "zero background OSC." It is serialized on discardd's
   single loop and **idle-gated** (`recording_in_progress()` blocks mid-take). Crucially, `config.env`
   **raised `LOCK_REASSERT_S` from 5 s → 3600 s** precisely because the 5 s idle reassert was *colliding
   with the fob's `startCapture` on the single-threaded cherokee server* (install_sd_rootkit.sh:88–96;
   verified 2026-06-24, kit_56). So "zero background OSC" means **zero *concurrent* OSC**; the fob's
   rule (L2-only presence; OSC only at GRABAR/DETENER under `wifiLock`) is what F1 owns. **Cross-actor
   note:** the fob's `startCapture` and discardd's reassert must not collide — `LOCK_REASSERT_S=3600` is
   the current mitigation; F1 must not reintroduce contention.

4. **Two start paths exist.** (a) The fob fires OSC `startCapture` directly (immediate — HARD RULE: only
   at GRABAR). (b) discardd's `run_scheduled_action_if_due` busy-waits to a precise target from
   `start_at.trigger` and fires (sub-second cross-cam sync; pairs with PREARM). **Path (b) +
   PREARM is Victor's in-flight camera-side work — F1 does NOT own it.** F1's transport does the direct
   fire; it MAY *also* write `start_at.trigger` (preferring the monotonic `U<uptime>` form, immune to the
   poison clock) to feed his precise-fire, but F1 neither implements nor depends on the pre-arm.

5. **`seq` is a quoted string; the field sets differ both ways** (the §2.1 table). The contract is **not**
   a clean re-namespacing of `v2` — each side has fields the other lacks. This is why the reconciliation
   is real and lands at ingest (option C).

6. **The fob C++ source is NOT in this bundle (compiled binaries only: `fob_MERGED_flash_at_0x0.bin` +
   parts) and NOT in the Eunomia repo.** It lives in `Pantheon-Industries-Inc/x3-capture-kit` at
   `ble_bridge/esp32-fob-wifi/src/main.cpp` (fw 3.8.3) — confirmed by `grep`/`find` over the repo (no
   `ble_bridge/`, no `esp32-fob*`). **Implication:** `transport`'s "adopt/adapt Victor's source" is
   blocked until that source is obtained; from this bundle alone you have only observable binary behavior
   + the docs. **A decisive additional reason to split** and do `core/` (which needs only `contracts/`)
   first (OQ-1).

**Things his code CONFIRMS (we build on, do not rediscover):** two-axis versioning
(`kit_version` ⊥ `record_format_version`, discardd:17–22); the front-lens/IMU keep policy
(`DELETE_FRONT_AFTER_KEEP=0`, front `_00_.insv` carries the IMU); `CAPTURE_LAYOUT` for 3K/100 = `single`
(one `_00_.insv`, 2944×1472, the keeper); archive-on-DESCARTAR = non-destructive (`archive=1` +
`stop_reason=operator_discard`); NAND `/pref/` identity (`pantheon_camera.env`),
task (`pantheon_current_task.env`, task-only), and ordinal (`pantheon_episode_seq`, swap-proof);
task precedence NAND→SD→none (`load_envs`, discardd:422–445); camera clock is poison (fob NTP / NAND
ordinal authoritative).

**The SD-flash provisioning daemon (Victor, in-flight, camera-image module):** while a card is in the
camera it collects the unit's connection info (MAC/AP/WiFi/IP, body+`.insv` serials = the
`hardware_unit.provisioning` group, 0d) and **pushes it to the fob over telnet**. **It is a
coordinator-RECEIVE path, Victor's daemon — F1 does not implement it.** How the coordinator receives it
is an OQ (§10, OQ-5): not in today's 6-op `CoordinatorPort`, so either an out-of-band transport channel
feeding an operational provisioning record (no contract change — recommended) or a new port op (a
contract-change PR).

---

## 4. The `firmware/coordinator/` tree after F1 (recommended split: `core/` authored; transport/ui = F2)

```
firmware/coordinator/
├── platformio.ini                      EDIT  (add core/ + new native test sources; esp32 blocking? → OQ-2)
├── src/main.cpp                        UNCHANGED  (placeholder shell; transport/ui wire-up is F2)
├── core/                               ── AUTHORED (F1) ──
│   ├── README.md                       REWRITE  (stub → real)
│   ├── seams.h                         NEW  injected interfaces: CaptureFleet (CaptureDevicePort set),
│   │                                        PresenceSource (L2), Clock (NTP), Rng (UUIDv4), PersistentStore (NVS)
│   ├── trigger_state_machine.{h,cpp}   NEW  idle→arming→starting→recording→stopping; START-only-from-idle;
│   │                                        phantom-press gate (sent==2); STOP/discard/archive transitions
│   ├── episode.{h,cpp}                 NEW  mint_episode_id (UUIDv4) + display_id (structured, derived) +
│   │                                        episode_ordinal + fob_session_id (random per boot)
│   ├── ordinal_log.{h,cpp}             NEW  fob-side append-at-START ring buffer (≥2-day bound, self-bounding);
│   │                                        durable-to-flash BEFORE the counter advances (CONTRACT §1.7)
│   ├── sidecar_assembly.{h,cpp}        NEW  assemble eunomia::Sidecar from coordinator-owned fields;
│   │                                        + the env-projection (current_assignment.env / current_stop.env) for discardd
│   ├── button_feedback.{h,cpp}         NEW  instant-ack / working / lockout STATE for ALL delayed buttons (logic only)
│   └── coordinator.{h,cpp}             NEW  the CoordinatorPort implementation tying the above to the injected seams
├── transport/                          ── STUB in F1; AUTHORED-BY-ADAPTATION in F2 ──
│   └── README.md                       (annotated with the §5.2/§7 plan: SoftAP, wifiLock OSC, telnet, triggers)
├── ui/                                 ── STUB in F1; AUTHORED in F2 ──
│   └── README.md                       (annotated with the §5.3 plan: screens, color state, take counter)
└── test/                               ── all run by `pio test -e native` ──
    ├── test_contract/test_contract.cpp MOVED (was test/test_contract.cpp; content UNCHANGED) [as-built]
    └── test_core/test_core.cpp         NEW  the 12 core suites in ONE program [as-built]
```

> **AS-BUILT test layout (deviation from the tree above, recorded at implement).** PlatformIO runs ONE
> `main()` per `test/` subfolder, and only `test_`-prefixed subfolders are test suites (siblings are
> shared code). So the four planned files (`test_state_machine`/`test_button_feedback`/`test_episode`/
> `test_sidecar_assembly`) are **consolidated into one program** `test/test_core/test_core.cpp` (12
> RUN_TESTs covering all four areas + detect_drop, stop/recording_suspect, env projections), and the
> existing `test_contract.cpp` was **relocated** into `test/test_contract/` (content byte-identical) so
> the two suites build as independent programs. Coverage is a superset of the plan, not a subset. The
> build also needed `test_build_src = yes` in `platformio.ini` (so `pio test` compiles `core/` into the
> test program; by default it builds only the test files + libs).

**Annotation key:** `core/*` and `test/*` are **authored** by F1. `transport/`, `ui/`, `src/main.cpp`
are **left as F2** (transport adapts Victor's `esp32-fob-wifi`; nothing in F1 imports them). discardd,
the WiFi join, the camera pre-arm, and the camera firmware are **Victor's-and-untouched**.

---

## 5. Per-module plan

> Signatures are in `contracts/_generated/cpp/eunomia_coordinator_port.h` /
> `eunomia_capture_device_port.h` / `eunomia_sidecar.h` — referenced, not re-typed.

### 5.1 `core/` — the `CoordinatorPort` implementation (F1)

**Dependency law:** `core/` depends only on `contracts/_generated/cpp/` + its own `seams.h`. It is
hardware-free; the real OSC/telnet/SoftAP/NVS live behind the seams (provided by `transport` in F2; by
fakes in the native tests). This is what makes `pio test -e native` cover it with no rig.

**Implements the 6 `CoordinatorPort` ops:**

| Op | core/ logic | delegates to seam |
|---|---|---|
| `mint_episode_id()` | UUIDv4 (the §7/C-9 pairing key, identical both arms) + derive `display_id` (`<YYYYMMDD>_<operator>_<station>_<NNNNNN>`, warn/derived) | `Rng`, `Clock` |
| `trigger(cameras)` | The state machine + the phantom-press gate: advance only from `idle`; fire the fleet **serialized**; count acks; return `sent==2`. `sent==0`→drop (phantom); `sent==1`→one-sided orphan → `needs_review`/void. Bump `episode_ordinal` + append the ordinal-log line **after** the durable write. | `CaptureFleet` (start), `PresenceSource` (both present?), `PersistentStore` |
| `read_clip_filename(camera)` | At STOP: recover the clip name; confirm it grew → set `recording_suspect` (NET-NEW, coordinator-owned) | `CaptureDevicePort.read_back_filename` (telnet `ls`) |
| `write_sidecar(camera, rec)` | Assemble the `eunomia-sidecar/v1` record (§2.1 option C) and **project it to the env files** discardd consumes | `CaptureDevicePort.write_sidecar` (telnet env push) |
| `detect_drop()` | Return dropped cameras from the **L2 station table only** (never OSC) — the camera-count source feeding the 2/2·1/2·0/2 gate | `PresenceSource` (`esp_netif_get_sta_list`) |
| `flush_telemetry()` | Drain the queued god's-view + ordinal-log events in the idle gap (single-radio) | `CaptureFleet`/uplink (F2) |

**Authored core data:** `episode_ordinal` (the fob label ordinal), `fob_session_id` (random per boot;
the fob-swap disambiguator, ingest keys on `(kit_id, fob_session_id, ordinal)`), the **fob-side
ordinal-join ring buffer** (CONTRACT §1.7: append-at-START, `episode_seq`+NTP wallclock+kit/fob id,
≥2× drain cadence ≈ 2 days/few-hundred, self-bounding) — this is **net-new vs discardd** (discardd has
only the camera-side NAND `global_episode_seq`; the fob backup is the independent medium). The durable
ordinal is written **to flash before the counter advances** (crash/swap can't lose or reuse a number,
SPEC §1.8) — abstracted behind `PersistentStore` so the native test uses a fake and esp32 uses NVS.

**Sidecar assembly (the F1 conformance artifact):** `core/` fills the coordinator-owned `v1` fields —
`identity` (`kit_id`←fob, `operator_id`/`station_id`/`task_*`/`prompt`/`rotation_id`/`session_id` from
sign-in/assignment, `episode_id`, `bimanual_episode_id`, `episode_ordinal`, `display_id`,
`assignment_source`), `timing` (`started_unix`/`stopped_unix`/`start_skew_ms`), `provenance`
(`fob_id`/`fob_build`/`site_id`/`modality=umi`), `outcome` (`stop_reason`/`archive`/`recording_suspect`)
— and accepts the camera-owned fields (`camera_id`/`side`←NAND, `camera_firmware`, `kit_version`,
`global_episode_seq`, `seq`, `files.back`, `record_settings`) that discardd supplies. It proves the
assembled record validates (§8). Identity precedence (§3.3: kit←fob, side←NAND) and task precedence
(§3.5) are honored by *which actor fills which field*, exactly as the env mechanism already enforces.

### 5.2 `transport/` — the hardware-coupled swappable layer (F2; spec drawn now)

WiFi SoftAP hosting (`PANTHEON-kit_<n>`, OPEN, `192.168.42.1`, DHCP `.2–.6`) + the **`wifiLock`-serialized
fire-and-forget OSC client** (`oscSendNoWait`: raw socket, send+flush+~120 ms grace+close, never read
the body — the OSC off-by-one response lag) + the **telnet client** (`ls -t` clip-filename read;
`current_assignment.env`/`current_stop.env` write) + the **file-trigger writes** to discardd
(`start_at`/`stop_at`, prefer `U<uptime>`). **THE TWO HARD RULES live here** (§7). The implementation
**adopts/adapts Victor's `esp32-fob-wifi` 3.8.3 source** (blocked on obtaining it, §3 finding 6) and is
the home of the **dedicated-core `wifiTask`** (pinned core 0; UI+touch on core 1; fed by `core/`'s
fire-and-forget queue) that makes the instant touch-ack possible. It also receives the SD-daemon
provisioning push (OQ-5). Implements the `CaptureDevicePort` (the X3 OSC+telnet adapter) that `core/`
drives. Swapping the board/radio = replace `transport/`, not `core/`.

### 5.3 `ui/` — the CYD touchscreen (F2; spec drawn now)

The SPEC §1.8 screens, presentation only (logic is in `core/button_feedback`): full-screen color state
(idle/working/recording/locked), **instant visual flip on touch** (before any network), the **take
counter**, the GUARDAR/DESCARTAR decision + toast, the **camera-count color** (green 2/2 / amber 1/2 /
red 0/2 from `detect_drop`), the **"revisa cámaras"** warning on an incomplete stop, haptic/audio tick
on a registered press, and the lockout (ignore taps during working). The button-feedback rule applies to
**ALL delayed buttons** (§6). Swappable without touching `core/`.

### 5.4 Relationship to Victor's stack — the explicit boundary (per module)

| Module | F1 AUTHORS | ADOPTS from Victor | Victor's-and-UNTOUCHED |
|---|---|---|---|
| `core/` | state machine, ordinal/episode logic, ordinal-log ring buffer, sidecar assembly, button-feedback state | (nothing — pure) | — |
| `transport/` (F2) | the `CaptureDevicePort`/`CoordinatorPort` seam wiring | `esp32-fob-wifi` SoftAP, `oscSendNoWait`, `wifiLock`, `esp_netif_get_sta_list`, the telnet/trigger/env mechanism | the WiFi join (`S99zfobjoin`/`x3_fob_link`/`x3_join_fob`) |
| `ui/` (F2) | the CYD screens against the core state | the proven UX (color state, ribbon, take counter) | — |
| camera-side | — | reads discardd's `v2` sidecar shape (reconciled at ingest) | **discardd**, the camera pre-arm/cross-cam sync, the camera firmware (`fobjoin_rev4`), the SD provisioning daemon |

---

## 6. The state machine + the two guarantees + button-feedback for ALL delayed buttons

**States / transitions** (`core/trigger_state_machine`):

```
idle ──START(valid only here)──▶ arming ──both present & both ack (sent==2)──▶ starting ──▶ recording
  ▲                                  │                                  │
  │                                  └── sent<2 (phantom/one-sided) ────┘ (no advance; orphan voided/needs_review)
  │                                                                       
  └──────── stopped ◀── stopping ◀── STOP (valid only from recording) ◀──┘
```

**Guarantee 1 — spam-safety (START-only-from-idle).** A START is acted on **only** from `idle`; from
`arming`/`starting`/`recording`/`stopping` further inputs are **dropped or coalesced, never
double-fired**. Spamming the screen is harmless **by design** (SPEC §1.8 core layer), independent of the
UI. Proven off-target by feeding a burst of STARTs mid-sequence and asserting exactly one fire.

**Guarantee 2 — phantom-press gate (`sent==2`).** `trigger()` advances only when **both cameras are
present (L2) AND both acked**: `sent==2` ⇒ START commits (ordinal advances after the durable write);
`sent==0` ⇒ dropped (`phantom_start`, button locked, non-blocking); `sent==1` ⇒ kept-but-`needs_review`
(one-sided orphan voided). At `<2` cameras present, START is **locked** (the GRABAR-locks-at-<2-cams
rule). Proven off-target with a `PresenceSource`/`CaptureFleet` fake returning 0/1/2.

**Button-feedback for ALL delayed buttons (SPEC §1.8 + the 2026-06-24 generalized rule).**
`core/button_feedback` is a per-button state `idle → ack(instant) → working(locked) → settled` driven by
"touch registered" and "action completed" events, **decoupled** so the visual ack fires *before* any
network and the working state **ignores taps** (lockout) until the slow action completes. It applies to
**START** (~3 s pipeline re-init — the worst case, camera-side latency F1's UI must behave correctly
*given* it exists), **STOP** (finalize/flush), and **any settings/sign-in/confirm** that round-trips to
the camera network or god's-view. `ui/` (F2) renders these states; `core/` guarantees them. Proven
off-target: every delayed button flips to `ack` synchronously and refuses re-entry while `working`.

---

## 7. THE TWO HARD RULES — how `transport/` enforces them, mapped to Victor's source

> These live in `transport/` (F2). `core/` is *built to not violate them*: it reads presence only via the
> L2 `PresenceSource` (never OSC), and it issues exactly one serialized fleet-trigger per START.

1. **Zero (concurrent) background OSC.** Camera presence is tracked **at L2 only**
   (`esp_netif_get_sta_list` / the AP DHCP station table) — **`detect_drop()` never polls OSC**. The fob
   emits OSC **only at GRABAR/DETENER**, **serialized under `wifiLock`**, one camera at a time (~150 ms
   spacing), **fire-and-forget** (`oscSendNoWait`: raw socket, send+flush+~120 ms grace+close, never read
   the body — the off-by-one response lag). Maps to `esp32-fob-wifi`'s `wifiLock` + `oscSendNoWait`. F1's
   cross-actor obligation (§3 finding 3): do not contend with discardd's idle reassert (kept at
   `LOCK_REASSERT_S=3600`).
2. **discardd locks video mode; the fob does NOT arm per take.** discardd continuously re-asserts
   `RES_3008_1504P100`/`captureMode=video`, so the fob fires `startCapture` **directly** (no per-take
   arm). **Recording DEPENDS on discardd running on every card** — F1 builds on this and never
   reimplements it. STOP ordering: fire **both** `stopCapture`s first, then finalize per camera (telnet
   `ls`, confirm grew → `recording_suspect`, push `current_stop.env`) — avoids the stop-stagger artifact
   (CONTRACT §1.7).

---

## 8. Conformance / test plan (all `pio test -e native`, no rig)

| Test (NEW unless noted) | Proves |
|---|---|
| `test_contract.cpp` (UNCHANGED) | the 0b/0c conformance + ports-implementable still pass |
| `test_state_machine.cpp` | **spam-safety** (START dropped from every non-idle state; a burst → one fire) + **phantom-press gate** (no commit unless `sent==2`; 0/1/2 paths) + STOP/discard/archive transitions |
| `test_button_feedback.cpp` | instant-ack flips synchronously; working-state lockout drops taps; settles only on completion — for START, STOP, and a round-tripping settings/confirm |
| `test_episode.cpp` | `episode_id` uniqueness + identical-both-arms; `display_id` derivation; ordinal **monotonic + durable-before-advance** (a fake `PersistentStore` asserting flash-write precedes the bump; restart resumes, never reuses) |
| `test_sidecar_assembly.cpp` | the assembled **`eunomia-sidecar/v1`** record `serialize_sidecar`→`parse_sidecar` round-trips **and** validates against the golden `contracts/conformance/fixtures/sidecar/{valid,warn}/` (the `EUNOMIA_FIXTURES_DIR` wiring already in `platformio.ini`) — the F1 correctness artifact for option (C) |

The conformance pattern matches `test_contract.cpp`'s `check_dir<>` over the golden fixtures: the C++
field-bag owns the structural layer (presence/type of hard leaves); the enum/non-empty/conditional/
cross-field layers stay Python/JSON-Schema (the existing split, OQ-5 of 0b). **transport/ui validation
(F2) is rig/mock:** the `CaptureDevicePort` X3 adapter is exercised against a mock OSC/telnet server
off-target and on the rig for the real two-hard-rules behavior (the one-machine→mock rule).

---

## 9. Build + gate impact

- **The 5 Python gates + the codegen-drift gate are UNAFFECTED** — F1 touches no `contracts/` source and
  no Python (it adds C++ under `firmware/coordinator/`, outside the import-linter; its boundary is the
  include path + the conformance gate). Drift stays 0; `pio test -e native` stays the blocking C++ gate.
- **`pio test -e native` (BLOCKING)** gains the four new test files (state machine, button feedback,
  episode/ordinal, sidecar assembly) — the core correctness proof.
- **`pio run -e esp32` (esp32 target build) — flip to blocking? → OQ-2.** CONTRIBUTING/OQ-13 says flip
  "when `firmware/coordinator/core/` lands" — F1 lands it. `core/` is pure C++17 with header-only
  contract deps (no Arduino/hardware), so it should compile clean under `env:esp32`. **Recommendation:
  flip `pio run -e esp32` to blocking at end of F1, conditional on `core/` building clean with no added
  deps** (it will); `clang-tidy` can stay non-blocking until transport/ui (F2). If the esp32 build pulls
  surprises, defer the flip to F2 and say so.
- **No new firmware deps in F1** (Unity is already the native test framework; the contract headers are
  the only include). `transport/` (F2) will add the ESP32/WiFi/OSC/telnet deps.
- **Hand-written C++ is `clang-format`-clean**; the generated headers stay exempt but must compile in the
  native test (they already do).

---

## 10. Open questions (numbered — options + recommendation)

1. **One run or split?** (the LEAD OQ, §2.2) — Options: (a) **split**, F1=`core/`, F2=`transport`+`ui`;
   (b) one run. **Recommend (a)** — provable-off-target + authored-not-adapted + the fob source isn't
   available yet for transport.
2. **Sidecar reconciliation** (§2.1) — Options (A) converge discardd→`v1`; (B) ingest-tolerates-both,
   coordinator emits nothing; (C) **hybrid** (core assembles `v1`; discardd keeps `v2` via env push;
   ingest reconciles by `episode_id`). **Recommend (C)**, with "leave discardd's writer untouched in F1."
3. **Flip `pio run -e esp32` to blocking in F1?** (§9) — Options: (a) flip now (core/ is pure, should
   build clean); (b) defer to F2. **Recommend (a)** conditional on a clean esp32 build of `core/`.
4. **`recording_suspect` ownership/placement.** It is NET-NEW and coordinator-owned (fob STOP-time
   clip-grew check). Options: (a) carry it only in the coordinator's `v1` record (F1); the card gets it
   when/if discardd converges (option A, later); (b) push it into `current_stop.env` now so discardd can
   stamp it onto `v2` (a *tiny* discardd-reads-one-more-env-var change — coordinate with Victor).
   **Recommend (a)** for F1 (no discardd change); revisit (b) when converging.
5. **SD-daemon provisioning RECEIVE path** (§3) — not in today's 6-op `CoordinatorPort`. Options:
   (a) **out-of-band transport channel** feeding an operational `hardware_unit.provisioning` record (no
   contract change); (b) add a `CoordinatorPort` op (a contract-change PR). **Recommend (a)** — it's
   operational-model data, not part of the capture-trigger contract; it is Victor's daemon and an F2
   transport receive at most. Flag (b) as a contract-change OQ if a port op is wanted.
6. **Precise-fire / `start_at.trigger`.** Does F1's transport (F2) *also* write `start_at.trigger`
   (preferring `U<uptime>`) to feed discardd's precise cross-cam fire, or fire OSC directly only?
   **Recommend: direct OSC fire is F1/F2's job; writing `start_at` to feed Victor's precise-fire is
   optional and OFF until his pre-arm/sync work lands** — F1 neither implements nor depends on pre-arm.
7. **`fob_session_id` source.** Confirm it is minted in `core/` (random per boot, the fob-swap
   disambiguator) and surfaced on the operational `session` record (0d), not on the sidecar. **Recommend:
   yes — `core/` mints it; it rides the ordinal-log + operational session, per CONTRACT §3.6.**

---

## 11. What F1 deliberately does NOT do (restated)

- **Does not reimplement Victor's camera-side stack** — discardd, the WiFi join
  (`S99zfobjoin`/`x3_fob_link`/`x3_join_fob`), the camera-side pre-arm/cross-cam-sync, the camera
  firmware. F1 **integrates with** them and depends on discardd holding video mode.
- **Does not change discardd's `v2` writer** (option C) — convergence to `v1` is a separate, coordinated
  change owned with Victor.
- **No ingest/edge/console/Hermes code.** If the reconciliation's `v2→v1` translation lands at ingest,
  that is a later run; F1 only specifies the `v1` shape the coordinator emits.
- **No spot-check, no substrate, no web stack.**
- **No new contract changes** — option (C) needs none. If the SD-daemon receive (OQ-5) or
  `recording_suspect` (OQ-4) is taken down a port-op path, that is flagged as a contract-change OQ, never
  a silent edit to the merged `contracts/`.
- **(Recommended split) F1 does not implement `transport/` or `ui/`** — those are F2, on Victor's source
  + the rig. Their spec is drawn here (§5.2/§5.3/§7) so the boundary and the two hard rules are settled.

---

Plan ready for annotation — I have not implemented anything.
