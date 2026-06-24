# X3 Capture — Hardware Findings & Requirements (for future board/camera design)

**Purpose.** A running list of everything we've learned about the current hardware (Insta360 X3
cameras + the ESP32-2432S028R "CYD" fob) — the quirks, limits, and failure modes — and the
**requirements each implies for the boards and cameras Jackson is speccing for future use.**

This is backfilled from the design/validation work on the current pilot rig. It is the
hardware-side companion to the system spec and the decision register. Add to it as the bench runs
surface more.

Legend: **[FINDING]** = something true about the current hardware. **[REQ]** = a requirement it
implies for future hardware. **[WATCH]** = something to measure/confirm at the bench.

---

## 1. The camera (Insta360 X3)

### 1.1 OSC control server is single-threaded and fragile
- **[FINDING]** The X3's on-camera web server (cherokee) that answers OSC commands is
  **single-threaded**. Two overlapping/concurrent OSC requests crash it; it then either resets
  TCP connections (a "connection reset by peer" storm) or returns the *previous* request's
  response (an off-by-one). This is the single most painful X3 behavior and shaped the entire
  coordinator design (one serialized OSC client, no background polling, ever).
- **[REQ]** Future camera (or camera-control interface) should support **concurrent/robust
  control** — at minimum a control API that tolerates overlapping requests, ideally a proper
  multi-client or queued command interface. The need to serialize ALL control traffic through one
  client is a major architectural constraint we'd love to drop.
- **[REQ]** A reliable **command-response** (knowing a command succeeded from the response, not
  by side-channel checks) — see 1.2.

### 1.2 OSC response is unreliable; truth comes from the filesystem
- **[FINDING]** The OSC response body is unreliable (off-by-one under load), so we never trust it.
  The clip filename is recovered via `telnet ls -t`, and "did it record" is judged by **clip
  count / file growth**, not the API response.
- **[REQ]** Future camera should give a **trustworthy, synchronous acknowledgment** that a
  recording started/stopped and the resulting filename — so we don't need a telnet side channel to
  verify basic operations.

### 1.3 No reliable real-time clock
- **[FINDING]** The X3 has no dependable RTC — its clock jumps backward and cannot be trusted.
  Camera timestamps are "poison" and are never used; all timing comes from the fob.
- **[REQ]** Future camera with a **stable, syncable RTC** (or a clean way to stamp frames with a
  trusted external clock) would remove a whole class of timing complexity. At minimum, the camera
  should accept and hold an externally-set time across a session.

### 1.4 No genlock / hardware sync between cameras
- **[FINDING]** Two cameras can't be hardware-synced; even with tight triggering there's a
  residual start offset (~1.4 s observed), absorbed downstream by audio cross-correlation.
- **[REQ]** For bimanual capture, **hardware sync / genlock between the two cameras** (or a shared
  trigger line) would eliminate the offset and the audio-sync dependency. High-value for data
  quality.

### 1.5 WiFi join is brittle and the config is a brick risk
- **[FINDING]** All WiFi-mode changes are transient vendor-script hacks. Editing `/pref/wifi.conf`
  is a **soft-brick path** (the AP never returns if it points at an absent SSID). Recovery is via
  a stock `.bin` on an exFAT SD (safe, can't hard-brick).
- **[FINDING]** Low camera battery causes WiFi drops (a known cause of mid-session disconnects).
- **[REQ]** Future camera with a **stable, documented, non-bricking network-join mechanism** (a
  real "join this AP" API that persists safely and reverts cleanly). The current
  edit-the-config-and-pray approach is a liability at fleet scale.
- **[REQ]** **Brown-out resilience** / a battery floor where WiFi stays up — or external power
  options — so a sagging battery doesn't silently drop a camera mid-take.

### 1.6 The L2 blind spot (can't tell "recording" from "connected")
- **[FINDING]** Because we can't poll OSC mid-take (1.1), camera presence is tracked at L2 (WiFi
  association). But L2 only says *connected*, not *recording* — a camera can stop recording
  (card error, internal fault) while staying associated. We catch this at STOP (clip-grew check)
  and at ingest (`recording_suspect`), but cannot catch it live.
- **[REQ]** Future camera should expose a **cheap, safe, real-time recording-status signal**
  (a heartbeat or status pin/endpoint that doesn't crash under polling) so a stopped-recording
  camera is detectable live, not after the fact.

### 1.7 Custom firmware required for control at all
- **[FINDING]** Stock X3 only talks to Insta360's phone app over Bluetooth. WiFi+OSC+telnet
  control requires a modified ("fobjoin") firmware image — a stock-derived telnet image + an
  init-script supervisor. This is a reverse-engineered dependency we maintain.
- **[REQ]** Future camera with **first-class programmatic control** (documented API, no firmware
  hacking) removes a major maintenance and fragility burden.
- **[FINDING]** exFAT SD only; footage is large (~200 GB/session class) and never moves over the
  control network — it drains off the card physically.
- **[REQ]** Future camera storage/offload that supports the fleet drain model (fast offload,
  reliable filesystem, ideally a faster-than-SD path for the footage volumes involved).

### 1.8 Long continuous-take behaviors (self-restart, thermal, file-splitting)
- **[FINDING — observed on the rig, 2026-06-23]** Recording continuously on Victor's rig (START
  then left to run), the **cameras restarted themselves at ~30 minutes**. The cause isn't yet
  pinned (likely a firmware watchdog / buffer or thermal-adjacent limit on a single unbroken take).
  **Likely benign for us:** real UMI tasks are short (seconds to a couple of minutes per take), so a
  30-minute *single* take should never occur in normal collection. Noted so it isn't a surprise if
  anyone runs a long soak, and because it interacts with the count-reconcile (a self-restart mid-take
  ends one clip and starts another — the join must treat that like any other multi-clip case, not a
  mislabel).
- **[FINDING]** The camera also auto-stops at its **thermal limit** (`TEMP_HIGH_SHUTDOWN`, readable
  via OSC temp keys) — a genuine end-of-take cause recorded as `stop_reason=overheat`. Over an hour
  at 3K/100 Victor saw no thermal shutdown, so the thermal margin is comfortable for session-length
  use; it's only a concern for pathologically long single takes.
- **[OPEN — confirm with Victor]** Whether a long take is written as **one file or auto-split** into
  segments is still unconfirmed (the cheapest answer: was his ~hour recording one file or several?).
  This is a property of the *camera* firmware + the locked capture mode, identical on his rig and
  ours, so either rig answers it. The ingest count-reconcile is built to handle a split (clips-per-
  start ≥ 1, flagged `needs_review` on an unexpected mismatch rather than positionally mislabeled).
- **[REQ]** Future camera should support an **uninterrupted long recording** (no surprise watchdog
  restart) and **documented segmentation behavior** (predictable file-splitting with a stable naming
  scheme), so a long take is never ambiguous to the pipeline.

---

## 2. The fob board (ESP32-2432S028R "CYD", 2.8" 320×240)

### 2.1 SoftAP capacity under load is the critical unknown
- **[FINDING/WATCH]** The ESP32's hosted SoftAP is **marginal** for sustaining two cameras
  associated + triggered + occasional telemetry under a full shift. This is the single biggest
  hardware risk and is gated by **GATE-LOAD** (stress today, soak tomorrow). A failure here is the
  one that changes the hardware.
- **[REQ]** Future fob board with a **stronger/dedicated radio** (or the ability to use an external
  AP) sized for the real fleet load with margin. Don't spec the future board on the assumption the
  CYD's SoftAP is sufficient until GATE-LOAD says so.
- **[WATCH]** Quantify at the bench: max sustained takes, drop rate under load, behavior at low
  camera battery, RF headroom, heap stability over hours, thermals.

### 2.2 Resistive touchscreen misses presses
- **[FINDING]** The CYD has a **resistive** touchscreen (less sensitive than capacitive). Victor
  reports it sometimes doesn't physically register a START/STOP tap, leaving the operator unsure
  whether to wait or re-tap (and re-tapping risks a spurious toggle). We're mitigating in firmware
  with instant touch-ack + working-state + input-robustness (register the fob-feedback/robustness requirement), but the root cause is
  the hardware.
- **[REQ]** Future fob with a **capacitive touchscreen** (or physical tactile buttons for
  START/STOP, which give mechanical feedback and never "miss" ambiguously). For a
  glance-and-press field device operated quickly, **physical buttons for the primary
  start/stop action** may beat any touchscreen.
- **[WATCH]** Measure resistive-touch missed-press frequency at the bench — if frequent, it
  strengthens the case for capacitive or hardware buttons in the next board.

### 2.3 Single radio (no concurrent camera-net + uplink)
- **[FINDING]** The fob has one radio, so it cannot be on the camera AP and an uplink WiFi
  simultaneously. Telemetry to god's-view only flushes in idle gaps between takes (the radio's
  home is the camera network during a take). This is why god's-view is near-real-time, not live.
- **[REQ]** Future fob with **two radios** (or a radio + a separate uplink, e.g. cellular) could
  give genuinely live telemetry and decouple uplink from the camera network. Evaluate against cost
  /power/complexity — the idle-gap model works, this is an enhancement.

### 2.4 No onboard RTC (timing depends on connectivity)
- **[FINDING]** The current fob has no RTC, so absolute time depends on connectivity (NTP);
  offline, it degrades to monotonic ordering (uptime-based) with absolute time reconstructed at
  landing on reconnect. (See register the time-model decision.)
- **[REQ]** Future fob with an **onboard RTC** (e.g. a DS3231-class part, battery-backed) so
  offline takes carry a trustworthy absolute time. This is already anticipated — the time model is
  RTC-ready; the hardware just doesn't have one yet. A DS3231 can be added to the current CYD over
  I2C as an interim.

### 2.5 Provisioning / identity at fleet scale
- **[FINDING]** Today each camera's fob-assignment is hand-written; kit/fob identity is manual.
  The plan is zero-touch (derive the join from a kit_id burned at provisioning).
- **[FINDING — the camera won't surface its own connection info, even on a laptop (Victor, 2026-06-24)].**
  The connection facts provisioning needs (the camera's MAC / AP / WiFi / IP, body + .insv serials)
  **cannot reliably be read off the X3 even with it plugged into a laptop** — the stock device simply
  doesn't expose them that way. This was the friction in the bench provisioning step (it assumed those
  facts were readable at the bench; they aren't).
- **[IN FLIGHT — Victor's fix: an SD-flash provisioning daemon].** Victor is adding a **daemon on the
  SD flash** that, while the card is in the camera, **collects the camera info needed to connect** and
  **pushes it to the fob over telnet**. So the SD card itself becomes the agent that extracts the
  connection info — turning "read facts you can't actually read at the bench" into "the card reports
  them automatically to the fob." This is the practical realization of the programmatic-provisioning
  REQ below for the *current* hardware (no new camera firmware needed beyond what the card carries).
  **Where it lands in our design:** the fields it produces are exactly the `hardware_unit.provisioning`
  group the contract already models (MAC / AP / IP / firmware) — only the *source* changes (the SD
  daemon → fob over telnet, not a human at the bench); it is part of the **camera-image** module (the
  card's packaged agent) and is received by the **coordinator** over its existing telnet channel
  (possibly a new CoordinatorPort operation, or it rides the existing channel — a firmware-run design
  input). It also **simplifies the provisioning flow**: the "capture serial/MAC/AP/IP against the unit"
  step becomes "the SD daemon reports the connection info to the fob," removing the can't-read gap.
- **[REQ]** Future hardware should support **programmatic, persistent identity/provisioning** (a
  writable, durable kit/unit id the device self-reads to join the right network) so 1,000-unit
  fleets don't need hand-config. Applies to both the fob and the camera. (Victor's SD daemon is the
  bridge to this on current hardware.)

---

## 3. System-level hardware requirements (both devices, fleet scale)

- **[REQ] Fleet firmware updates.** Both fob and camera will need a safe, scalable
  firmware-update path across ~1,000 units (the current camera flash is a manual SD-swap; the fob
  is esptool-over-USB). Future hardware should support robust OTA or a fast bulk-flash workflow.
- **[REQ] Power/thermal for a full shift.** Cameras drop on low battery (1.5); the fob's thermals
  under sustained load are unmeasured (2.1). Future hardware should be specced for a full shift of
  continuous operation with margin — battery life, charging, and thermal dissipation.
- **[REQ] Integrity at the edges.** The control network and the metadata it carries should be
  authenticatable (a rogue device shouldn't be able to join the kit AP and pollute the L2 count or
  emit telemetry). Currently any device on the AP counts as a "camera" (the phantom-camera issue).
- **[REQ] Bimanual as a first-class unit.** The kit is fundamentally a *pair* of cameras + a
  coordinator. Future hardware ideally treats the bimanual kit as a designed unit (shared
  trigger/sync, shared power, paired identity) rather than two independent cameras lashed together.

---

## 4. Quick reference — current hardware, as-built

| Thing | Current part | Key limitation | Future requirement |
|---|---|---|---|
| Camera | Insta360 X3 (fobjoin rev4 fw) | single-threaded OSC, no RTC, no genlock, brittle WiFi, custom-fw dependency | robust concurrent control API, stable RTC, genlock, safe join, first-class programmatic control |
| Fob board | ESP32-2432S028R "CYD" | marginal SoftAP, resistive touch, single radio, no RTC | stronger/dedicated radio, capacitive or physical buttons, dual radio (opt), onboard RTC |
| Camera↔fob link | fob-hosted 2.4 GHz SoftAP | capacity under load (GATE-LOAD), low-battery drops, phantom devices | radio sized for fleet load + margin, brown-out resilience, authenticated join |
| Timing | fob NTP (no RTC) | offline = monotonic only | onboard RTC, externally-settable camera clock |
| Storage/offload | exFAT SD, physical drain | large footage, SD-speed | fast reliable offload path |
| Provisioning | hand-written assignment | manual, doesn't scale | programmatic persistent identity |

---

*Backfilled from the X3 capture design + validation work. Owner of future board/camera spec:
Jackson. Keep adding findings as the bench runs (GATE-LOAD especially) produce real numbers.*

---

## 5. Firmware-confirmed values (from FIRMWARE_FINDINGS.md, X3 1.1.6 — for the coordinator + camera-image builds)

These were read from the firmware binaries (authoritative). They matter at firmware/camera-image
build time and for the capture-settings the contract records.

- **[FINDING] Locked capture mode = `RES_3008_1504P100`** (3K/100, "Mode B"), dual-fisheye SBS.
  discardd hard-locks it (re-asserts whenever idle, never mid-take) so operators can't change
  res/fps from the UI. The symbolic string is authoritative; the enum int is NOT firmware-confirmed
  (probe via OPT_PROBE if needed).
- **[FINDING] AUDIO MUST STAY ON** (`mute=false`). The cross-cam pairing aligns the two wrist cams
  by AUDIO cross-correlation; muting breaks deterministic sub-frame pairing. → a hard capture-
  settings invariant: `record_settings` always reflects audio-on; never mute for UMI capture.
- **[FINDING] Front-lens policy RESOLVED: KEEP the front lens THROUGH ingest, DROP it from the
  TRAINING OUTPUT.** Subtle 3-stage lifecycle (reconciles the apparent "keep both" vs "back-only"
  contradiction): (1) discardd KEEPS the front `_00_` lens on-card (`DELETE_FRONT_AFTER_KEEP=0`,
  `KILL_FRONT_SENSOR=0`) because the front file is the ONLY source of the IMU motion track — the
  `_10_` back reports "unsupported", and discardd's on-card "gyro" events are just OSC metadata
  probes, not a usable stream; (2) ingest EXTRACTS the IMU from the front lens (`--extract-imu`);
  (3) ingest then DROPS the front lens from the training output (`--drop-front`) so the TRAINING SET
  is back-half-only. Net: captured/ingested data keeps the front until the IMU is pulled; the
  training data is back-lens-only. The front `_00_` (~600MB) survives on the SD until offload (the
  SD-cost tradeoff). With `DELETE_FRONT_AFTER_KEEP=1` the entire accel/gyro QC feature is dead on
  arrival — so it MUST stay 0. `RES_3008_1504P100` IS the 2:1 dual-fisheye 360 frame (both lenses
  in the single `_00_` file: left half = front/selfie + IMU, right half = back/workspace).
- **[SUPERSEDED] Single-lens-back** (focussensor=2, expect_output_type=1, stitch_enable=0) was a
  power/heat optimization but is NOT used — keeping the front lens for its IMU stream took priority.
  FlowState-off + MCTF-off may still apply; single-lens does not.
- **[FINDING] Thermal auto-shutdown is real + readable.** TEMPERATURE_STATE enum: TEMP_LOW →
  MIDDLE → HIGH → ALERT → HIGH_SHUTDOWN; the cam AUTO-STOPS recording at SHUTDOWN ("Recording
  stopped to prevent overheating"). OSC read keys: temp_value, sensor_temp_value,
  overheat_protection. → a confirmed source of the `recording_suspect` / `stop_reason=overheat`
  case, and directly relevant to the GATE-LOAD 2-hr thermal gate. **[WATCH]** at the bench: does a
  2-hr 3K/100 take hit TEMP_HIGH_SHUTDOWN? (esp. with single-lens-back reducing heat.)
- **[FINDING] OSC surface (CONFIRMED):** camera.setOptions/getOptions/startCapture/stopCapture/
  takePicture/listFiles/delete/getMetadata/reset; endpoints /osc/commands/execute, /osc/commands/
  status, /osc/info, /osc/state. Send snake_case keys (focussensor, expect_output_type) — the
  camelCase proto field names are NOT the OSC keys.
- **[FINDING] The prerecord lever** (`t app test prerecord start`, AmbaShell, RTOS-side via
  autoexec.ash) keeps the encoder hot — the candidate to shrink the ~3s cross-cam cold-start
  (the fob-feedback/robustness requirement latency). Camera-side; OSC prearm is DEAD on 1.1.6. **[REQ]** future camera: instant-start
  / pre-armed capture so startCapture has no re-init latency.
- **[FINDING] Battery %** = battery_level/battery_scale*100 (OSC Options.battery_status).
- **[FINDING] CONFIRMED-DEAD (don't chase):** selfTimer/exposureDelay over OSC; BE80 sync-capture
  opcodes (no hardware genlock); live cross-cam frame-lock; `apply_network_role` (soft-bricks).
- **[FINDING] The X3 is AMP:** RTOS owns sensors/ISP/encoder, Linux owns WiFi. RTOS reachable at
  boot via `autoexec.ash` on the SD root; OSC reaches the Options backend.
