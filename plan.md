# Run F2 — `firmware/coordinator/transport/` + `ui/`: the hardware layer on Victor's WiFi-OSC fob (PLAN ONLY)

> **Status: IMPLEMENTED (transport/ only; ui/ deferred to F3 per the approved SPLIT).** F2 implements
> the F1 seams against the real ESP32/WiFi/OSC/telnet/NVS by **adapting** Victor's proven WiFi-OSC fob
> (`esp32-fob-wifi`, fw `3.8.3-fast-guard`, re-vendored at commit `f96b97a` — supersedes `a38f5a9`, §4)
> — adaptation + wiring, **not a rewrite, not a reinvention of
> `core/`**. The vendored source is the reviewable baseline the adaptation diffs against
> (`transport/vendor/esp32-fob-wifi/`, see §4).
>
> **Ground-truth rule honored.** Every claim below is checked against the *vendored code*
> (`main.cpp`, 3240 lines, read in full + `platformio.ini` + the companion docs) and the F1
> `core/` seams (`seams.h`, `coordinator.*`, `sidecar_assembly.*`, `button_feedback.*`,
> `trigger_state_machine.*`, `episode.*`, `ordinal_log.*`) + the generated `CaptureDevicePort` +
> the authority docs (SPEC §1.5–1.9, CONTRACT §1.6/§1.7/§3.3/§3.5/§3.6, DECISION_REGISTER). **Where a
> comment or doc disagrees with the code, the code wins and it is flagged (§3).** Five stale-doc /
> dead-code cases were found (two already known, three new); one is consequential (the uplink-borrow
> is code-disabled, so the `Clock` and `TelemetrySink` seams have no live source — §3, OQ-3/OQ-4).

---

## 1. Summary

**What F2 produces.** The hardware-coupled half of the coordinator, implementing the F1 seams against
real hardware, adapted from Victor's `main.cpp`:

- **`transport/`** — the Arduino-framework radio/IO layer: WiFi SoftAP hosting (`PANTHEON-kit_<n>`,
  192.168.42.1, DHCP .2–.6, cameras join as STAs); the **`CaptureDevicePort` X3 adapter** (OSC :80
  fire-and-forget start/stop, telnet :23 clip-name read + env-file push); **`PresenceSource`** (L2
  station table, never OSC); **`PersistentStore`** (NVS, wired to core's durable-ordinal seam);
  **`Clock`/`Rng`** (NTP wallclock + `esp_random()`); the optional **`TelemetrySink`** uplink; the
  **dedicated core-0 `wifiTask`** + fire-and-forget queue that makes the instant touch-ack possible;
  and the **SD-daemon provisioning RECEIVE** path (out-of-band, no contract change — OQ-5).
- **`ui/`** — the CYD touchscreen (TFT_eSPI): the `REGISTRO → MESA → MAIN → CONFIRM` flow
  (+ `CONFIRM_ID` "Are you <name>?"), rendering **`core/button_feedback`**'s instant-ack / working /
  lockout states for **every delayed button** (SPEC §1.8), the camera-count GO/NO-GO color from
  `detect_drop()`, the take counter, GUARDAR/DESCARTAR + toast — swappable without touching `core/`.

**The explicit Victor boundary** (full table §11-A): F2 **authors** the seam adapters + the app glue
that wires `core/` to hardware; **adapts** Victor's proven functions (`apEnsureUp`, `discoverCams`,
`oscSendNoWait`, `telnetCmd`, `Preferences`, the CYD screens…); leaves **untouched** discardd, the
camera-side WiFi join (`S99zfobjoin`), the camera pre-arm/cross-cam-sync, the camera firmware, and
discardd's v2 sidecar writer.

**What F2 defers.** No `core/` changes; no `contracts/` changes; no reimplementation of Victor's
camera-side stack; no ingest (the v2→v1 sidecar reconciliation lands at a later ingest run — F2 emits
the env files + the coordinator's v1 backup record only); not converging discardd's writer to v1
(option A — separate, with Victor). The precise-fire `start_at` trigger stays OFF (OQ-6, per F1).

---

## 2. ⭐ LEAD OQ — one run or split (transport then ui)?

**Options.**
- **(A) Split — F2 = `transport/`, F3 = `ui/`.** (Mo's lean.)
- **(B) One run — `transport/` + `ui/` together.**

**Recommendation: (A) SPLIT, F2 = `transport/` (+ the headless app-glue + the dedicated-core
scaffolding), F3 = `ui/`.** Reasoning, honestly weighed:

1. **The two-hard-rules correctness lives entirely in `transport/`.** Presence-is-L2-only,
   `wifiLock`-serialized fire-and-forget OSC, no-per-take-arm — these are the load-bearing, must-be-
   right-first behaviors. `ui/` is presentation that *renders* the state `transport/` + `core/`
   produce. Getting the hard layer correct and gate-green first, in its own reviewable PR, is the
   lower-risk sequencing.
2. **Victor's own tree proves the split is real, not artificial.** His `esp32dev` env builds a
   **headless** firmware (no `PANTHEON_HAS_TFT`) that runs the entire trigger/transport path with the
   BOOT button + serial as the only inputs (`buttonTask`, `cmd=shutter`). So `transport/` stands alone
   without the screen — F2 can be validated end-to-end (mock OSC/telnet + headless build + rig)
   before a single pixel is drawn.
3. **The dedicated-core boundary is a clean split line.** Core 0 = the `wifiTask` worker + the
   fire-and-forget queue (transport's domain); core 1 = the UI render + touch loop (ui's domain). The
   contract between them is narrow: `ui` renders `core` state and posts operator inputs to the queue.
   That is a seam, not a tangle — splitting does not fracture the coupling, it names it.
4. **Smaller, independently gate-able PRs.** Each lands `pio run -e esp32`/`-e cyd` green on its own;
   F3 cannot regress F2's hard-rules code because it only adds the render/touch layer.

**Honest argument for (B):** both modules adapt the *same* `main.cpp`, and the core-0/core-1 split is
defined once — doing them together avoids re-opening `main.cpp` twice. **Why it loses:** the re-open
cost is small (the adaptation map §3 is done once, here), and it is outweighed by shipping the hard-
rules layer correct-and-proven before layering presentation on top.

**Either way, this plan documents BOTH modules** (§5). If annotation prefers (B), the §5 content is
delivered in one PR; nothing in the design changes, only the PR boundary.

**F2/F3 seam if split:** F2 lands `transport/` + the app glue (the FreeRTOS task split, the queue,
the headless `setup()/loop()` driving `core/` from BOOT-button/serial) and **adds `env:cyd` building
headless** (so the deployment board is on the blocking on-target gate from F2). F3 flips
`PANTHEON_HAS_TFT` on for `env:cyd`, adds `TFT_eSPI`, and fills `ui/`.

---

## 3. What I read in Victor's `main.cpp` — the function→seam map + the contradictions

### 3-A. The adaptation map (his function → our seam / port op)

| F1 seam / port op (`core/`) | Victor's function(s) in `main.cpp` | Adaptation note |
|---|---|---|
| `PresenceSource::present()` | `discoverCams()` (`esp_wifi_ap_get_sta_list` + `esp_netif_get_sta_list`, the AP DHCP/station table); `onWiFiEvent` kick; `g_connCount`/`g_cam[]` | **L2 only, zero OSC.** Victor fills `g_cam[].ip` from the station table; serial stays empty (no OSC poll). Our `present()` must return camera **handles** (`{"left","right"}`), so the adapter needs a MAC/IP→side map (see OQ-2 — the station table yields MAC+IP, not serials). |
| SoftAP substrate (feeds presence) | `apEnsureUp` / `apSsid` / `apChannel` / `apTuneDriver` / `onWiFiEvent` | Host `PANTHEON-kit_<n>` @192.168.42.1, DHCP .2–.6. `apTuneDriver` = `WIFI_PS_NONE` + long inactivity + `max_connection` at creation. Channel spread is a **stale delta** — see OQ-9. |
| `CaptureDevicePort::start()` / `stop()` | `oscSendNoWait`→`oscFire`→`oscStartCapture`/`oscStopCapture` | Fire-and-forget (raw socket: connect→print→flush→~120 ms grace→`stop()`, never read the body — the OSC off-by-one). **Serialized under `wifiLock`** (HARD RULE 1). `start()` issues `startCapture` **directly — no `oscArmVideo` per take** (HARD RULE 2). |
| `CaptureDevicePort::read_back_filename()` | `telnetCmd(... "ls -t /tmp/SD0/DCIM/Camera01/ \| grep VID_ \| head -1")` (PASS 2 of `camStopAll`) + `sidecarPathForClip` | Clip name comes from **telnet `ls`**, never OSC. Empty → `core` sets `recording_suspect=1` (the §2.2 no-SD trap; already in `coordinator.cpp::read_clip_filename`). |
| `CaptureDevicePort::write_sidecar(record)` | `telnetWriteFile` (mkdir -p + quoted heredoc + `sync` + `echo WROTE`) + `buildAssignmentEnv`/`buildStopEnv` | **The env CONTENT is `core`'s, not Victor's:** replace `buildAssignmentEnv`/`buildStopEnv` with `core::project_assignment_env`/`project_stop_env`. transport only **pushes** the bytes over telnet to `/tmp/SD0/PANTHEON/current_{assignment,stop}.env`. **The push mechanism is OQ-1.** |
| `CaptureDevicePort::get_state()` | `camCardCheckAll` (`telnetCmd "grep -q SD0 /proc/mounts && echo PCARDOK"`) | The cherokee-safe card-readiness check (telnet, not OSC). Maps to the no-SD guard / `get_state` token. |
| `CaptureDevicePort::set_profile()` | (n/a — discardd locks `RES_3008_1504P100`/video mode) | **No-op on this stack** (HARD RULE 2: discardd owns the profile). `oscArmVideo` is used only in the bench `firetest`, never per take. |
| `PersistentStore::read_i64`/`write_i64` | `Preferences`/`FobConfig`, `cfgLoad`, `cfgPutOrdinal`, `g_prefs.getUInt/putUInt` | Wire core's durable-ordinal key `fob_episode_ordinal` → NVS `putUInt`/`getUInt`. Victor's `logStart` already does **persist-before-advance**; map it onto `DurableOrdinal::advance` (write-then-bump, returns 0 on failure). The identity strings (kit/op/station/prompt/allow/site) load into core's `Assignment`. |
| `Clock::unix_seconds`/`unix_seconds_frac`/`monotonic_millis` | `time(nullptr)` / `isoNow` / `configTime` / `g_timeSet`; `millis()` | `monotonic_millis`→`millis()`; `unix_seconds`→`time(nullptr)`. **⚠ wallclock source is broken in the field — see contradiction #5 + OQ-3.** |
| `Rng::fill` | `esp_random()` (in `makeFobSession`) | Feeds `core::mint_uuid_v4` (episode_id). Reuse `makeFobSession`'s `esp_random()` for the OQ-7 `fob_session_id`. |
| `TelemetrySink::send` (optional) | `wifiUploadBurst` / `scanBestWifiTarget` / `apiRequest` / `uplinkUp` / `uplinkDown` | The single-radio uplink-borrow. **⚠ code-disabled — see contradiction #5 + OQ-4.** Maps to `core::flush_telemetry`; idle/touch-quiet/both-cams-up gate. |
| dedicated-core scaffolding | `wifiTask` (core 0) + `g_wifiQ` + `xTaskCreatePinnedToCore`; `discoveryTask` | Core 0 = WiFi worker (transport); core 1 = UI/touch (ui). This is what makes the instant touch-ack possible (UI never blocks on a multi-second associate/POST). |
| file-triggers / archive | `camMarkArchive` (`touch /tmp/archive.trigger` + re-write stop-env `ARCHIVE=1`); `start_at`/`stop_at` (NOT written) | `mark_archive` (DESCARTAR) → archive.trigger + `project_stop_env` with `ARCHIVE=1`. `start_at`/`stop_at` precise-fire stays **OFF** (OQ-6). |
| SD-daemon RECEIVE (OQ-5) | (net-new — Victor's `main.cpp` is OSC/telnet **client** only; no inbound server) | F2 adds a small inbound TCP listener on the fob AP IP; feeds an operational `hardware_unit.provisioning` record. **Placement/framing = OQ-8.** |

### 3-B. Where the code contradicts a comment/doc/assumption (his code wins; flagged)

1. **`esp32-fob-wifi/README.md` is STALE — CONFIRMED.** It is the verbatim **BLE-fob** README:
   `Insta360 GPS Remote`, GATT `0xFE60/61/62`, BLE pairing, `[ble] advertising`, build step
   `cd ble_bridge/esp32-fob` (the OLD folder). Ignore it entirely; the code is WiFi-OSC. *(Known —
   register "F2 prep" GOTCHA 1.)*
2. **`main.cpp`'s own top comment (lines 5–9) inverts the topology — CONFIRMED.** It says "one camera
   is the WiFi AP hub and the … fob STA-join[s] it … join the hub camera's WiFi AP (STA)". The actual
   code (lines 188–194 + `apEnsureUp`/`apSsid`/`apChannel`) has the **FOB hosting the SoftAP** and
   cameras joining IT (.2–.6). The prose is the dead `coordinator.py` lineage. *(Known — GOTCHA 2.)*
3. **NEW — `main.cpp` top comment (lines 32–37) says the fob writes the sidecar JSON.** "write a
   `pantheon_episode_v1` sidecar JSON next to the clip … over … telnet." The real code (lines 209–211
   + `camStartAll`/`camStopAll`) writes **`current_assignment.env` / `current_stop.env`** and
   **discardd** materializes the `pantheon-x3-sidecar/v2` JSON. Third stale comment in one file — and
   it exactly confirms the F1 option-C decision (`write_sidecar` = push env files).
4. **NEW — vestigial NimBLE / CE81 / BE80 references throughout.** There is **no BLE stack** in this
   build, yet comments reference "the NimBLE host CE81 callback" (lines 276, 410, 464–468), the BLE
   start-confirm watcher (`g_startConfirmPending`/`kStartConfirmMs`/`g_startRecAcks`, 415–429 —
   **declared but unused** in the WiFi path), the BLE link-supervision constants
   (`kSupervRecCs`/`kSupervIdleCs`, 446–447) + `setCamSupervision` (referenced, **does not exist**),
   and "the episode log is driven by CE81 edges" (2837–2838). Record state is **fob-authoritative**
   (`g_anyRec` toggle), not CE81-driven. *Adaptation drops all of this dead lineage.*
5. **NEW + CONSEQUENTIAL — the uplink-borrow is CODE-DISABLED.** `uplinkUp()` has an unconditional
   `return false;` (line 969, comment: "PANTHEON persistence: NEVER borrow the radio / tear down the
   SoftAP" — the teardown drops every camera). So `wifiUploadBurst`/`postCamTelemetry`/`doHelpPost`
   all no-op on the network. **Two seams inherit this:** (a) `TelemetrySink` has no live transport
   today (OQ-4 — it stays the optional/best-effort/off seam F1 already allows); (b) **`Clock` has no
   wallclock source in the field** — `configTime`/NTP is called *only* inside `wifiJoin(forUplink)`,
   which never runs, so `g_timeSet` stays false and `isoNow()` returns `""` unless a serial `time=`
   is sent. This is the single biggest hardware finding for F2 (OQ-3).
6. **NEW (vs the register, confirmed against the vendored source) — the source is BEHIND Victor's
   2026-06-24 binaries.** Per DECISION_REGISTER, the 2026-06-24 binaries (still `3.8.3-fast-guard`)
   include **channel-11 avoidance**, **`lockcams` via `/osc/info`**, and the **battery-swap /
   ghost-`REVISA` guard** — none of which are in `a38f5a9`. The vendored `apChannel()` spreads
   `{1,6,11}` (no ch-11 avoidance), and `lockToConnectedCams` reads `Cam::serial`, which
   `discoverCams` never populates → it would persist an **empty allowlist**. The readable code is a
   step behind the shipped binary. **OQ-9** (obtain the updated source, or re-derive the three
   deltas). *(Recorded in `transport/vendor/.../PROVENANCE.md`.)*
7. **NEW (minor) — SoftAP open-vs-WPA2.** DECISION_REGISTER says SoftAP is **OPEN**;
   `FOB_AP_HARDENING.md` says **WPA2**; the code is **conditional** (`apEnsureUp`: WPA2 if
   `cam_pass.length() >= 8`, else OPEN dev-fallback). The proven rig ran OPEN (cam_pass unprovisioned).
   Provisioning decides; F2 honors whatever `cam_pass` is set (OQ for the depot, not a code choice).

---

## 4. The vendoring (DONE — the prerequisite first action)

Cloned `Pantheon-Industries-Inc/x3-capture-kit` (gh-auth `Mzcassim`) into the gitignored
`.context/x3-capture-kit/` (the whole clone is **not** committed). Copied the two files into
`firmware/coordinator/transport/vendor/esp32-fob-wifi/` (flattened) + a `PROVENANCE.md`:

**RE-VENDORED to the UPDATED source (steering, 2026-06-24)** — superseding the first `a38f5a9`
vendoring. Victor shipped his 2026-06-24 fixes to `main`, so OQ-9's re-derive fallback is moot; F2
adapts the current source directly:

| committed file | source path in the clone | md5 | size |
|---|---|---|---|
| `main.cpp` | `ble_bridge/esp32-fob-wifi/src/main.cpp` | `60f433227fefc145b12ddde21961d927` | 3269 lines |
| `platformio.ini` | `ble_bridge/esp32-fob-wifi/platformio.ini` | `87acc2e09a3f36fa81c5d0a4ddd6e4ab` | 136 lines |

Provenance: repo HEAD **`f96b97a`** (2026-06-24); `main.cpp` last modified by **`6365643`** ("fix two
REVISA/join bugs", 2026-06-24 17:34); fw string still **`3.8.3-fast-guard`** (Victor bumps fixes under
the same string — read the commit, not the version). `a38f5a9` is a linear **ancestor** of `f96b97a`
(clean supersede). **Diff-checked:** `git diff a38f5a9..f96b97a` over the two files touches ONLY four
bounded areas — `apChannel` (`{1,6,11}`→`{1,6,6}`), `camCardCheckAll` (`nOk==nTot`→`nOk>=kMinCams`),
`lockToConnectedCams` (one-shot `/osc/info`), and `platformio.ini` `upload_speed` (a flashing tweak).
No surprise sprawl → adapted, not stopped. **The vendor dir is reference-only — every `build_src_filter`
excludes `transport/vendor/`** (verified: 0 vendored `.o`); `CPP_FILES` + clang-tidy also prune it. Full
detail in `PROVENANCE.md`.

---

## 5. Per-module plan

### 5-A. `transport/` — implement the seams against real hardware

All files Arduino-framework, depending on `core/` (`seams.h`, `sidecar_assembly.h`) + the generated
`CaptureDevicePort`. Proposed layout:

- `transport/softap.{h,cpp}` — `apEnsureUp`/`apSsid`/`apChannel`/`apTuneDriver`/`onWiFiEvent` adapted
  verbatim-in-spirit; hosts `PANTHEON-kit_<n>`. (Channel policy: adopt `{1,6}` ch-11 avoidance per
  OQ-9 once the updated source is in hand; otherwise carry the vendored `{1,6,11}` and flag.)
- `transport/presence.{h,cpp}` — implements **`PresenceSource`** from the L2 station table
  (`discoverCams`). Returns camera handles via the MAC→side map (OQ-2). **No OSC, ever** (HARD RULE 1).
- `transport/x3_capture_device.{h,cpp}` — implements **`CaptureDevicePort`** for one camera: `start()`
  (push `current_assignment.env` then OSC `startCapture` fire-and-forget — OQ-1), `stop()` (OSC
  `stopCapture`), `read_back_filename()` (telnet `ls`), `get_state()` (telnet card check),
  `set_profile()` (no-op), `write_sidecar(record)` (push `current_stop.env`). Mechanics adapted from
  `oscSendNoWait`/`telnetCmd`/`telnetWriteFile`/`sidecarPathForClip`; **env CONTENT from
  `core::project_*`**.
- `transport/nvs_store.{h,cpp}` — implements **`PersistentStore`** over `Preferences`; wires
  `fob_episode_ordinal` to NVS and loads the identity strings into `Assignment`.
- `transport/clock_rng.{h,cpp}` — implements **`Clock`** (`time()`/`millis()`) + **`Rng`**
  (`esp_random()`); mints/reuses `fob_session_id` (OQ-7). Wallclock acquisition strategy = OQ-3.
- `transport/uplink.{h,cpp}` — implements the optional **`TelemetrySink`** (`flush_telemetry`) over
  the (currently disabled) uplink-borrow; OFF/best-effort by default (OQ-4).
- `transport/wifi_worker.{h,cpp}` — the core-0 `wifiTask` + `g_wifiQ` fire-and-forget queue + the
  `xTaskCreatePinnedToCore` split; the serialization owner of `wifiLock`.
- `transport/provisioning_rx.{h,cpp}` — the **SD-daemon RECEIVE** listener (OQ-5/OQ-8); parses the
  pushed connection info into an operational `hardware_unit.provisioning` record. **No new port op,
  no contract change.**
- `transport/app.{cpp}` (headless `setup()/loop()`) — constructs the `Coordinator` with the real
  `Deps` + the X3 `Fleet`; drives `trigger()`/`stop()`/`write_sidecar()`/`detect_drop()`/
  `flush_telemetry()` from the BOOT button (`buttonTask`) + serial (`cmd=shutter`) until `ui/`
  (F3) adds touch. This is where the projected env strings are supplied to the adapters (OQ-1).

Each seam → Victor's function is in the §3-A table; SPEC/CONTRACT/`seams.h` referenced there, not
re-typed.

### 5-B. `ui/` — the CYD touchscreen (TFT_eSPI), rendering `core/` state

Adapted from Victor's screens; **renders, never owns logic** (swappable seam). Proposed layout:

- `ui/screens.{h,cpp}` — `renderMain`/`renderConfirm`/`renderConfirmId`/`renderProvision`/`renderMesa`
  /`renderNumEntry` + `drawPromptBand`/glyphs, adapted from Victor.
- `ui/touch.{h,cpp}` — the XPT2046 pressure-based read + hysteresis/debounce-latch (the "single tap =
  double" fix) + the per-screen hit-test dispatch.
- `ui/render_state.{h,cpp}` — the thin mapping from **`core` state → pixels**:
  - **`core::DelayedButton`** (instant-ack / `working()` lockout) drives the START/STOP/confirm button
    treatment — the instant visual flip on touch (before any network), the working/locked style that
    ignores taps, settle on `complete()`. **Applies to ALL delayed buttons** (SPEC §1.8) — START
    (~3 s worst case), STOP (finalize/flush), and settings/sign-in/confirm round-trips.
  - **`detect_drop()` / present count → the camera-count color** (green 2/2, red 0/2 **and** 1/2 — a
    one-sided take is a hard stop; matches Victor's `camCol`), the "revisa cámaras" / "1/2 — una
    camara cayo" warning on an incomplete stop.
  - **`g_sessionTakes`** (per-session take counter, resets on boot/table-change) → "TOMA #n";
    GUARDAR/DESCARTAR + the confirm-splash toast; the lockout (ignore taps while working).
  - The `REGISTRO → MESA → MAIN → CONFIRM` flow + `CONFIRM_ID` (the operator sign-in reconciliation,
    §8).
- Guarded by `PANTHEON_HAS_TFT` so the `env:esp32` headless build still links (Victor's pattern).

---

## 6. THE TWO HARD RULES — how `transport/` enforces them

**HARD RULE 1 — Zero CONCURRENT OSC.** The X3 cherokee OSC server is single-threaded and crashes on
overlapping OSC. Enforcement in F2:

- **Presence is L2-only.** `PresenceSource` reads `esp_netif_get_sta_list` (the AP DHCP/station table)
  — **never** an OSC poll. The vendored `discoverCams` already removed all background OSC (the
  root-cause fix, `main.cpp:1506-1546`); F2 carries that property and a test asserts the presence path
  opens **no** socket to port 80 (§9).
- **OSC only at GRABAR/DETENER, serialized under `wifiLock`, one camera at a time, fire-and-forget.**
  `core::trigger()` issues exactly one `dev->start()` per present camera; `core::stop()` fires both
  `stop()`s then finalizes (already the §1.7 shape in `coordinator.cpp`). The X3 adapter wraps each
  fire in `oscSendNoWait` (send+flush+~120 ms grace+close, never read the body) and holds `wifiLock`
  across the burst so the core-0 discovery worker can't poll OSC concurrently.
- **Cross-actor obligation.** Do NOT reintroduce contention with discardd's idle video-mode reassert
  (`LOCK_REASSERT_S=3600` on the card). F2 adds no background OSC and no inbound channel that talks
  OSC; the SD-daemon RX is plain TCP to the fob, not OSC to cameras (§3-A, OQ-8).

**HARD RULE 2 — discardd locks video mode; the fob does NOT arm per take.** `CaptureDevicePort::start()`
fires `startCapture` **directly** (no `oscArmVideo`/`setOptions` per take); `set_profile()` is a no-op
(discardd owns `RES_3008_1504P100`/`captureMode=video`). Recording **depends on discardd running on
every card**. STOP fires both `stopCapture`s first, then per camera: telnet `ls` for the clip name,
confirm it grew (empty → `recording_suspect`), push `current_stop.env` — exactly `coordinator.cpp`'s
`stop()` + `read_clip_filename()`.

These map onto: `wifiLock` (serialization), `oscSendNoWait` (fire-and-forget), the L2 station table
(presence), and direct `startCapture` (no per-take arm).

---

## 7. The framework boundary (confirmed)

- **`transport/` + `ui/` are Arduino-framework code** — `TFT_eSPI` (screen), the WiFi/OSC/telnet/NVS
  stack (transport). Adapted from Victor's `main.cpp`.
- **`core/` stays pure C++17 and untouched** — no Arduino, no `TFT_eSPI`, no `ArduinoJson` in `core/`
  (it cross-compiles under `env:esp32` with `-fno-exceptions -fno-rtti`, proven in F1).
- **`seams.h` is the line.** transport implements `Clock`/`Rng`/`PersistentStore`/`PresenceSource`/
  `TelemetrySink` + the generated `CaptureDevicePort`; ui renders `core` state. **`core`'s pure
  serializer owns the `v1` record + the env-string projection (`project_assignment_env`/
  `project_stop_env`); transport just pushes those strings over telnet — it does NOT re-derive them
  with `ArduinoJson`.** Victor's `ArduinoJson` stays only for HIS episode-log/upload paths if those
  are carried over (they are currently disabled — §3 #5).
- Dependency direction within `firmware/coordinator/`: `ui → core`, `transport → core → contracts`.
  Cross-module imports are unchanged (firmware depends only on `contracts/`; the internal
  core↔transport↔ui edges are the include structure the firmware rule allows).

---

## 8. Operator sign-in reconciliation (Victor's REGISTRO/CONFIRM_ID vs our operator⊥kit model)

**The good news (corrected in the register's "F2 prep" refinement, re-verified in code):** the
WiFi-OSC fob **already keeps `operator_id` and `kit_id` as SEPARATE NVS fields** (`cfgLoad`:
`getString("kit")` ⊥ `getString("op")`; the `kit=`/`op=`/`opname=` config grammar). There is **no
kit==operator collapse to undo** — that was the OLD BLE fob's README. So F2 reconciles flow, not a
data-model bug.

**The reconciliation.** Map Victor's flow onto CONTRACT §3.3 (**operator-from-session, kit-from-fob,
side-from-NAND**):

- **`kit_id`** = the fob's depot-PROVISIONED identity (`cmd kit=kit_N`, persisted, gates REGISTRO).
  Kept exactly as Victor has it.
- **`operator_id`** = the operator who signed in. Victor's `SCREEN_PROVISION` (REGISTRO) currently
  types a **kit number** and `provisionVerify` resolves the local NVS identity, then `CONFIRM_ID`
  ("Are you <name>?") guards a mistyped number before committing. **The gap vs our model:** REGISTRO
  is kit-centric; an *operator* sign-in (one operator may use any kit; the session records the
  pairing) is not a first-class step. Victor's `g_verifOp = g_cfg.operatorId` just carries the
  depot-set operator (may be empty).
- **The session binds them.** The operational `session` record (person_id + kit_id + window, 0d) is
  the system-of-record for "operator X used kit Y this shift." `core` projects `operator_id` into
  `current_assignment.env` **distinct from `kit_id`** (already true in `project_assignment_env` — it
  emits `OPERATOR_ID`, not a kit-derived value).

**Decision needed (OQ-7-flow):** does F2 (a) keep REGISTRO kit-only and treat operator as
depot-provisioned per kit (minimal change, matches today), or (b) add an operator sign-in step
(operator picks/enters their `operator_id`) so one operator can roam kits and the session captures the
real pairing? **Recommendation: (b)-lite** — keep REGISTRO's kit confirmation, and add operator
selection at sign-in (a short operator list/number on the same numeric keypad) so `operator_id` is set
per shift, not baked per kit. This is the operator⊥kit decision realized at the UI. **Flag, do not
silently collapse.**

**Note the env-key divergence (a finding, fold into the conformance check §9):** `core`'s
`project_assignment_env` **drops `OPERATOR_NAME`**, **adds `TASK_ID`/`ROTATION_ID`**, and **shifts
`SESSION_ID` semantics** (Victor: per-boot `fob_session_id`; core: the operational `session_id`, with
`fob_session_id` riding the ordinal-log per OQ-7). The **stop-env key set matches** Victor exactly.
F2 must confirm the keys `discardd` actually *sources* against `core`'s projected set (OQ-10) — extra
keys are harmless, but a renamed/dropped key discardd reads is not.

---

## 9. Test / validation plan

**The one-machine rule: default target = the mock/host path.** Victor's transport is Arduino code that
can't run on `native`, so the strategy splits each adapter into a **pure protocol layer (host-testable)
+ a thin hardware binding (compile-checked on-target, rig-validated)**:

1. **Pure protocol unit tests (`env:native`, Unity — mirror the F1 fakes).** Host-test the framework-
   free parts: the OSC fire request bytes, the telnet IAC-negotiation + `ls -t | grep VID_ | head -1`
   parse, `sidecarPathForClip`, and the seam-conformance of the X3 adapter against an **in-process
   mock** (`MockCaptureDevice` recording start/stop/ls/env — the same shape as F1's `FakeDevice`).
   Asserts: `start()` pushes `current_assignment.env` **before** the fire (OQ-1 ordering); `stop()`
   fires both stops before finalize; `write_sidecar` pushes `current_stop.env`; env bytes equal
   `core::project_*` output (no ArduinoJson divergence).
2. **Mock OSC/telnet server (host TCP).** A small host server the protocol layer drives over real POSIX
   sockets (a socket seam lets the same code use `WiFiClient` on-target). Exercises the wire format and
   demonstrates **THE TWO HARD RULES off-target**: (a) the presence path opens **no** port-80 socket
   (the mock fails the test if OSC is touched during presence); (b) fires are **serialized** (the
   single-threaded mock asserts no overlapping connects) and **fire-and-forget** (the mock never
   receives a body read); (c) `start()` issues `startCapture` with **no** preceding `setOptions`
   (no per-take arm).
3. **Seam conformance.** transport's `Clock`/`Rng`/`PersistentStore`/`PresenceSource` satisfy
   `core/seams.h` (the durable-ordinal seam preserves persist-before-advance: a forced NVS-write
   failure must NOT advance the ordinal — mirror F1's `FakeStore.fail_next`).
4. **Build gates (both BLOCKING).** `pio run -e esp32` (headless — core + transport, no TFT) **and**
   `pio run -e cyd` (the deployment board) clean; `pio test -e native` (core's tests + the new
   protocol tests) green; `clang-format` clean; `clang-tidy` (state per OQ-11).
5. **Rig validation (the real two-hard-rules behavior).** On Victor's rig: 2 cams on the fob AP,
   record/stop/save + discard end-to-end, `*.pantheon.json` sidecars land with the fob-injected
   assignment + shared `bimanual_episode_id`; the induced-failure checks (silent-stop →
   `recording_suspect`; no-SD start) from the build-and-try reframe. The UI is bench/rig-checked (F3).

---

## 10. Build + gate impact

- **`env:esp32` stays BLOCKING + green.** Currently builds `core/` only (`build_src_filter +<*>
  +<../core/>`). F2 extends the filter to include `transport/` (headless — no TFT), **excluding
  `transport/vendor/`**. The `-fno-exceptions -fno-rtti` flags stay; transport must compile under them
  (TFT_eSPI/ArduinoJson are known to build under `-fno-exceptions`; verify on-target).
- **`env:cyd` ADDED + BLOCKING.** New env for the deployment board (ESP32-2432S028R): `framework=
  arduino`, `board=esp32dev`, `board_build.partitions=min_spiffs.csv`, deps `bodmer/TFT_eSPI@^2.5.43`
  + `bblanchon/ArduinoJson@^7.0.4`, `board_build.filesystem=littlefs`, and the documented CYD TFT
  flags (ILI9341_2 driver + the red/blue-swap + inversion color-fix + pins) — all from the vendored
  `platformio.ini`. **In F2 (if split) `env:cyd` builds headless** (TFT dep present, `ui/` lands F3);
  F3 flips `PANTHEON_HAS_TFT`. Both `env:cyd` and `env:esp32` must build clean (esp32 blocking).
- **The 5 Python gates + contract drift: UNAFFECTED** (no Python, no `contracts/` change → `make
  codegen` drift = 0).
- **`clang-tidy` — OQ-11.** CONTRIBUTING says it flips to blocking when `transport/`/`ui/` land. F2
  proposes: **flip it to blocking but SCOPED to hand-written `transport/`/`ui/` only** — exclude
  `transport/vendor/` (reference) and the Arduino/TFT framework headers (not ours). Blanket clang-tidy
  over framework code is noise, not signal.
- **Arduino/TFT deps live ONLY in `transport/`+`ui/`** — `core/` and the native test env pull none.

---

## 11. Open questions (numbered; options + recommendation)

**OQ-1 — the env-projection push mechanism (the headline design OQ).** `core::trigger()` calls
`dev->start()` directly but does NOT push `current_assignment.env`; yet the assignment env (with
`EPISODE_ID`/`BIMANUAL_EPISODE_ID`) must reach the card **before** `startCapture`. Options:
- **(A, recommended)** The X3 adapter's `start()` pushes `current_assignment.env` (then fires OSC) and
  `write_sidecar(record)` pushes `current_stop.env`. The adapter gets the projected bytes from a
  provider callback the transport app-glue wires, calling `core::project_assignment_env(assignment,
  coordinator.take())` — valid because `trigger()` populates `take_` (episode_id/bimanual/ordinal)
  **before** the `start()` loop, and `take()` + `project_*` + the app's own `Assignment` are all
  already public. **Zero `core` change**, preserves Victor's proven env-then-OSC ordering.
- (B) App calls `coordinator.write_sidecar(cam, assemble_current_sidecar(...))` before `trigger()`;
  the adapter projects env from the `Sidecar` — needs a `project_*_from_sidecar` helper (a small
  `core` addition).
- (C) Add a dedicated env-push port op (contract change — out of scope; would be an OQ to Victor).
**Recommend (A).**

**OQ-2 — `PresenceSource` handle mapping.** The L2 station table yields **MAC+IP only** (serials need
OSC, which we don't poll). `present()` must return stable handles (`"left"`/`"right"`). Options:
(A) DHCP-lease order (.2=left, .3=right) — fragile across reconnects; (B) a **MAC→side allowlist**
(`macAllowed` order: entry 0 = left, 1 = right — Victor's `refreshLiveTelem` intent), provisioned at
the depot; (C) the **SD-daemon push** (OQ-5) supplies the authoritative MAC→side binding.
**Recommend (B) now, migrating to (C)** when the daemon lands — the allowlist is depot-known and
RPA-stable; the daemon makes it authoritative. *(Note: the vendored `lockToConnectedCams` can't fill
the allowlist serials without OSC — that's the OQ-9 `lockcams /osc/info` fix.)*

**OQ-3 — wallclock acquisition (consequential).** NTP runs only in the disabled uplink path (§3 #5),
so the `Clock` seam has no field source. Options: (A) serial `time=` at provision (lost across battery
swaps — 4–5×/day); (B) a **brief boot-time NTP** on site WiFi **before** hosting the AP (needs site
WiFi at boot; one-shot, then host AP); (C) a **DS3231 RTC** (the `RTC_TIMEKEEPING.md` permanent fix,
~$1/fob, ~15 lines, survives swaps); (D) take wallclock from the **SD-daemon push** if the camera has
synced time. **Recommend (C) as the durable fix, with (A) as the F2 stopgap** — and keep the existing
loud-not-silent defenses (`recording_suspect`/`no_wallclock`/`needs_review`; the ordinal-log carries
`ms` for backfill). Flag prominently: untimed footage is the failure mode this guards.

**OQ-4 — `TelemetrySink`/`flush_telemetry` mapping.** The uplink-borrow is code-disabled (tearing down
the AP drops every camera). **Recommend:** keep `TelemetrySink` the **optional, best-effort, OFF**
seam F1 already models (`Deps.telemetry` may be null) — `flush_telemetry()` is a no-op until a non-AP-
destroying uplink exists. The durable ordinal-log backup is unaffected (it's the fail-safe, not this).

**OQ-5/OQ-8 — SD-daemon RECEIVE placement + framing.** Victor's daemon pushes camera MAC/AP/IP/serials
to the fob over telnet; `main.cpp` has **no inbound server**. Options for placement: (A) a dedicated
inbound TCP listener on the fob AP IP (e.g. `192.168.42.1:<port>`), accept→parse→store an operational
`hardware_unit.provisioning` record, on core 0, yielding during a take; (B) ride an existing channel.
**Recommend (A)** — a bounded listener that does **not** talk OSC (no HARD-RULE-1 risk). **The wire
format/port is Victor's daemon's, in-flight → confirm with Victor (OQ-8).** **No contract change, no
new port op** (per F1 OQ-5).

**OQ-6 — precise-fire `start_at` trigger.** Stays **OFF** (per F1): transport fires `startCapture`
directly; writing `start_at.trigger` (prefer the monotonic `U<uptime>` form) for discardd's cross-cam
precise fire is **optional and OFF until Victor's pre-arm/cross-cam-sync lands**. F2 neither implements
nor depends on pre-arm.

**OQ-7 — `fob_session_id` + the operator-flow.** `fob_session_id` is minted in `core` (random per boot
via the `Rng` seam = `esp_random()`), rides the ordinal-log + the operational `session`, **NOT** the
sidecar (ingest keys `(kit_id, fob_session_id, ordinal)`). transport reuses `makeFobSession`'s
`esp_random()`. The operator sign-in flow decision is §8 / OQ-7-flow (recommend (b)-lite).

**OQ-9 — the 2026-06-24 source gap — RESOLVED (A), per steering.** Victor shipped the fixes to `main`,
so F2 re-vendored from the current source (`f96b97a`/`6365643`, §4) instead of re-deriving. The three
deltas are now adapted from his code, not guessed: `apChannel` = `{1,6,6}` (`hw/softap.cpp`), `lockcams`
does a one-shot `/osc/info` per cam (`hw/app.cpp::lockcams`), and the ghost-`REVISA` lesson (gate on
*required cams present*, not *exactly N stations*) is honored by the side-based registry + core's
`present_count >= required` gate (`proto/presence.h`). Diff vs `a38f5a9` was bounded (§4) → adapted,
not stopped.

**OQ-10 — env-key conformance with discardd.** Confirm `discardd` sources exactly the keys
`core::project_*` emits (§8 divergence: dropped `OPERATOR_NAME`, added `TASK_ID`/`ROTATION_ID`, shifted
`SESSION_ID`). **Recommend** a conformance check against the readable discardd source (in the bundle)
during F2; extra keys are harmless, a key discardd reads that we renamed/dropped is not.

**OQ-11 — clang-tidy.** Flip to blocking, **scoped** to hand-written `transport/`+`ui/` (exclude
`transport/vendor/` + framework headers). See §10.

---

## 12. What F2 deliberately does NOT do (restated)

- **No `core/` changes** — F2 implements against the merged seams (the only possible touch is a tiny
  accessor if OQ-1 lands on a non-(A) option; (A) needs none — flag if it arises).
- **No `contracts/` changes** — the SD-daemon RECEIVE (OQ-5) and `recording_suspect` (OQ-4/F1) stay
  no-contract-change. If something genuinely needs a port/contract change, it is flagged as an OQ.
- **No reimplementing Victor's camera-side stack** — discardd, the WiFi join (`S99zfobjoin`/
  `x3_fob_link`/`x3_join_fob`), the camera pre-arm/cross-cam-sync, the camera firmware, discardd's v2
  writer. F2 hosts the AP, drives OSC/telnet, writes the triggers/env; the camera side is his.
- **No ingest** — the v2→v1 sidecar reconciliation lands at a later ingest run, joined by `episode_id`.
  F2 emits the env files + the coordinator's v1 backup record only.
- **Not converging discardd's writer to v1** (option A) — separate, coordinated with Victor.
- **The precise-fire `start_at`** stays OFF (OQ-6).

---

### Appendix 11-A — Victor boundary table

| F2 AUTHORS (new) | F2 ADAPTS (from `main.cpp`, his function names) | Victor's — UNTOUCHED |
|---|---|---|
| The seam adapter classes + the app glue wiring `core`↔hardware; the host protocol/mock-server test rig; the SD-daemon RX listener; `env:cyd` | `apEnsureUp`/`apSsid`/`apChannel`/`apTuneDriver`/`onWiFiEvent`; `discoverCams`; `oscSendNoWait`/`oscFire`/`oscStart/StopCapture`; `telnetCmd`/`telnetWriteFile`/`sidecarPathForClip`; `camCardCheckAll`; `Preferences`/`FobConfig`/`cfgLoad`/`cfgPutOrdinal`; `time()`/`millis()`/`esp_random()`/`makeFobSession`; `wifiTask`/`g_wifiQ`/`wifiLock`; `camMarkArchive`/archive.trigger; the CYD screens + XPT2046 touch | **discardd** (v2 writer, video-mode lock, archive); the camera WiFi join (`S99zfobjoin`, `x3_fob_link`, `x3_join_fob`); the camera pre-arm / cross-cam-sync; the camera firmware (`Insta360X3FW_fobjoin` rev4); `/pref/` NAND identity |

> **Next step: STOP and wait for `NOTE:` annotations.** No implementation, no PR, no force-push. On
> "implement", build to this plan, run the gates, and report per the prompt's shape (real gate tails,
> the two-hard-rules diff vs the vendored `main.cpp`, seam conformance, UI faithfulness, the Victor-
> boundary statement, a reviewer-subagent diff vs this plan, deviations, merge-readiness).
