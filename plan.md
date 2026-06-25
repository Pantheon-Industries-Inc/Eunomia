# Run F3 — `firmware/coordinator/ui/`: the CYD touchscreen, rendering `core/` state (PLAN-OF-RECORD)

> **Status: APPROVED — implementing.** F3 builds the **`ui/`** module: the CYD (ESP32-2432S028R)
> touchscreen that renders the coordinator's state and posts operator inputs back to it. Presentation
> on top of the already-merged, unchanged `core/` (F1) + `transport/` (F2). It **renders `core` state
> and owns NO capture logic** — a different screen reimplements `ui/` against the same `core` guarantee
> (the swappable-UI seam). Adapted from Victor's proven CYD screens in the vendored
> `transport/vendor/esp32-fob-wifi/main.cpp`; **adaptation + wiring, not a rewrite**.
>
> **This is the plan-of-record after Mo's `NOTE:` annotations** (2026-06-25). The original F3 plan made
> six ground-truth claims that a read-only pass against the F1/F2 code corrected; all six were ACCEPTED
> and are folded below as **resolved decisions / corrected claims** (marked ✅ FLAG-A … ✅ FLAG-F). The
> plan UNDERSTATED the work (esp. A and E); F3 is correspondingly larger but stays **one coherent run**
> — it is all "the CYD UI + the two F2 follow-ups." Do not split it.
>
> **Ground-truth rule honored.** Read Victor's ACTUAL CYD code (the `SCREEN_*` render functions, the
> XPT2046 touch read + the single-tap-is-double debounce fix, `drawPromptBand`/glyphs, `camCol`,
> `startGate`, `callLead`) in the vendored `main.cpp`, plus the F1 `core/button_feedback.*`,
> `trigger_state_machine.*`, `coordinator.*`, the F2 `transport/hw/*`, and SPEC §1.8/§1.9/§1.10 +
> CONTRACT §3.3 + the DECISION_REGISTER. **Where a comment or doc disagrees with the code, the code wins
> and it is flagged** — six such cases were found in the original F3 plan and are corrected here.

---

## 0. The six folded flags (the plan-of-record corrections)

| Flag | What the original F3 plan claimed | Ground truth (code wins) | Resolution folded in |
|---|---|---|---|
| **A** | `env:cyd` "already built headless with the TFT dep present in F2"; F3 just "flips the guard." | `[env:cyd]` is **bare** — no `lib_deps`, no TFT flags. The vendored `platformio.ini` carries them. | **§1, §8.** Real config porting: add `TFT_eSPI` dep + `-DPANTHEON_HAS_TFT=1` + the full CYD display block + the `ui/touch` pins. **Verify the colour-fix on the board** (GO/NO-GO is colour-critical). |
| **B** | The delayed-button treatment "renders from `core::button_feedback`" via a tri-state read. | `DelayedButton` is a **2-state** primitive (`working()`/not), **not a `Coordinator` member**, **zero callers** today. | **§3, §6-OQ3.** `ui/` **owns** the `DelayedButton` instance(s), drives `press()`→inline action→`complete()`; `render_state` reads `working()`. Instant-ack = `working()` flipping true synchronously before the action. No core accessor for it. |
| **C** | Render the camera-count colour from `detect_drop()`. | `detect_drop()` is a **mutating** port op — wrong for a per-frame poll. There is **no const present-count accessor**; the live count lives in `transport`'s `PresenceSource`. | **§5, §6-OQ3, §9.** Add one tiny const `Coordinator::present_count()` (reads `deps_.presence`). This is the only core accessor F3 adds. `detect_drop()` stays for drop-detection logic, not rendering. |
| **D** | (silent) | `button_feedback.h:8`, `coordinator.h:12`, `core/README.md:24` all say "ui/ (F2)" — ui/ is **F3**. | **§5.3.** Comment-only fix, rides the §5.1 enum-cleanup edit (same files). |
| **E** | The flow is `REGISTRO→MESA→MAIN→CONFIRM/CONFIRM_ID`; the camera-count colour is the only NO-GO. | Victor also has: MAIN-header double-tap → MESA (table change); a CONFIRM 45 s auto-timeout; `startGate` with **three** NO-GO reasons (CAMS/UPLINK/SAVING); a **LLAMAR** "call lead" button. | **§4, §6-OQ1/§7.** Fold in MESA re-entry + CONFIRM 45 s timeout. Map SAVING→button `working()`/lockout; **DROP GATE_UPLINK** (vestigial — the uplink-borrow is code-disabled; never fires). KEEP LLAMAR splash + local help-log; **defer the dashboard POST** to the god's-view uplink (SPEC §1.10). |
| **F** | "Extend the blocking clang-tidy scope to `core/`." | The 5 enums are in **headers**; `TIDY_FILES` is `.cpp`-only and `HeaderFilterRegex` is proto-only. The Makefile help already (wrongly) claims "core/ + proto/". | **§5.1, §8.** `TIDY_FILES += core/*.cpp` **and** `HeaderFilterRegex += core/.*`; reconcile the Makefile help/echo to the now-true scope. `ui/` excluded (framework-coupled); `vendor/` excluded. |

---

## 1. Summary

**What F3 produces.** The Arduino-framework touchscreen layer, guarded by `PANTHEON_HAS_TFT`:

- **`ui/screens.{h,cpp}`** — the screen renderers (`MAIN`, `CONFIRM`, `CONFIRM_ID`, `PROVISION`/
  REGISTRO, `MESA`, numeric entry) + `drawPromptBand`/glyphs/`confirmSplash`/`callSplash`, adapted
  from Victor's `SCREEN_*` renderers.
- **`ui/touch.{h,cpp}`** — the XPT2046 pressure-based read + the hysteresis/debounce-latch (Victor's
  single-tap-is-double fix: `kPressHi=220`/`kReleaseLo=90`/`kRelSamples=3`, `s_down`/`s_relCount`) +
  the calibration (axis-swapped `touchScreenX/Y`) + the per-screen hit-test dispatch + `keypadHit`.
  The XPT2046 touch pins (`T_CLK=25/MISO=39/MOSI=32/CS=33/IRQ=36`, a **separate VSPI bus**) live here
  (hardcoded in Victor's `main.cpp`, not his `.ini`).
- **`ui/render_state.{h,cpp}`** — the thin, **host-testable** mapping from **`core` state → render
  tokens** (the only place that reads `core`): the `DelayedButton::working()` → button-treatment token
  for **every delayed button** (SPEC §1.8); the camera-count GO/NO-GO colour from
  `Coordinator::present_count()` vs `required` (**✅ FLAG-C**); the per-session take counter; the
  GUARDAR/DESCARTAR token. **2-state**, per ✅ FLAG-B — the rich idle/working/recording/locked visuals
  are this module's mapping of `working()` + present-count + nav-state into tokens; the primitive
  itself is 2-state.
- **`ui/flow.{h,cpp}`** — the screen-navigation state machine (`REGISTRO → MESA → MAIN → CONFIRM` +
  `CONFIRM_ID`, **plus the MAIN-header double-tap → MESA table-change re-entry and the CONFIRM 45 s
  auto-timeout** — ✅ FLAG-E) and the operator sign-in step (OQ-1). **Screen navigation is a UI concern
  and lives here; `core` owns the trigger state machine, not the screen state machine.** `ui/` **owns
  the `DelayedButton` instance(s)** and drives `press()`→(slow inline action)→`complete()` (✅ FLAG-B);
  it posts operator inputs (sign-in, kit confirm, GRABAR/DETENER, GUARDAR/DESCARTAR, LLAMAR) to the
  coordinator via the F2 app glue.

**What F3 changes elsewhere.**
- **✅ FLAG-A — real build-config porting (NOT a guard flip).** `[env:cyd]` is bare today. F3 ports from
  the vendored `platformio.ini` into Eunomia's `[env:cyd]`: `lib_deps = bodmer/TFT_eSPI@^2.5.43`,
  `-DPANTHEON_HAS_TFT=1`, and the complete CYD display block — `USER_SETUP_LOADED`, `ILI9341_2_DRIVER`,
  the **mandatory colour-fix** (`TFT_RGB_ORDER=TFT_BGR` + `TFT_INVERSION_ON` — without it green/red are
  swapped, which makes the GO/NO-GO unreadable; **verify on the board**), the TFT pins
  (`MISO=12/MOSI=13/SCLK=14/CS=15/DC=2/RST=-1/BL=21`), the font loads, the SPI freqs — then adds
  `+<../ui/>` to the `cyd` `build_src_filter`. `env:esp32` **stays headless** (no TFT dep; `ui/`
  excluded by the `PANTHEON_HAS_TFT` guard — must still link).
- **✅ FLAG-F — clang-tidy scope extended to `core/`** (after the §5.1 enum cleanup): `TIDY_FILES +=
  core/*.cpp` **and** `.clang-tidy` `HeaderFilterRegex += firmware/coordinator/core/.*`; the Makefile
  help/echo reconciled to the now-true `core/ + transport/proto/` scope.
- The §5.1 5-enum cleanup, the §5.2 `present_count()` accessor, the §5.3 stale-comment fix, and the
  §5.4 SPEC §1.8 docs correction.

**What F3 does NOT do.** No `core/` capture-logic changes (the only `core/` touches are the bundled
enum cleanup §5.1, the one tiny `present_count()` accessor §5.2, and the comment fix §5.3); no
`contracts/` changes; no `transport/` behavior changes; no reimplementation of Victor's camera-side
stack; **no new network path** (the LLAMAR dashboard POST is deferred, not built). It renders and posts
inputs — nothing more.

---

## 2. Scope — `ui/` only, on the unchanged `core/` + `transport/`

`ui/` depends on `core/` (`button_feedback.h`, `trigger_state_machine.h`, `coordinator.h`) and is wired
by the F2 app glue; it pulls **no** new contract surface. The dependency direction stays
`ui → core → contracts`; `ui` never reaches into `transport/` internals (it observes `core` state — now
including `present_count()` — and posts inputs through the coordinator the F2 app already constructs).
The framework boundary is unchanged: `ui/` is Arduino + `TFT_eSPI`; `core/` stays pure C++17
framework-free; `seams.h` is the line. `ui/` adds `TFT_eSPI` (and reuses `transport/`'s touch/SPI
patterns) **only** under `PANTHEON_HAS_TFT`.

---

## 3. The screen → `core` mapping (what each surface renders, and from what)

| Screen / element | Renders from `core` | Behavior |
|---|---|---|
| **The delayed-button treatment (START/STOP/confirm/sign-in)** | **`ui`-owned `core::DelayedButton`** (`working()` — 2-state) | On touch, `ui` calls `press()`; on **Accepted** it flips the button **visually before any work** (instant-ack = `working()` true synchronously) and **ignores taps** while `working()` (UI lockout); it runs the slow inline action, then `complete()` settles. **Applies to EVERY delayed button** (SPEC §1.8): START (~3 s worst case), STOP (finalize/flush), and any settings/sign-in/confirm round-trip. **This is the touch-ack decoupling the F2 no-queue finding identified as `button_feedback`'s job** — the ack is instant because the visual is set before the slow inline action, not because a thread is free (✅ FLAG-B). |
| **The camera-count colour (GO/NO-GO)** | **`Coordinator::present_count()`** vs `required` (✅ FLAG-C) | Green **2/2**; red **0/2 AND 1/2** (a one-sided take is a hard stop — matches Victor's `camCol`). On an incomplete stop, the "revisa cámaras / 1/2 — una cámara cayó" warning. **Require the cams you need, do NOT gate on an exact station count** (the F2 REVISA ghost-STA lesson). Read via the new const accessor each frame — **never** `detect_drop()` (a mutating port op). |
| **The "ESPERA" lockout reasons** | `DelayedButton::working()` (SAVING/finalize in flight) + present-count (CAMS) | Two NO-GO reasons survive into F3: **CAMS** (present-count NO-GO) and **SAVING** (a STOP/finalize is in flight → the relevant `DelayedButton` is `working()`). **GATE_UPLINK is DROPPED** (✅ FLAG-E): it fires only on the radio-borrow, which is code-disabled (`transport/hw/uplink.h` `DisabledUplink`), so it can never trigger — do not gate START on a dead uplink. |
| **The take counter** | **`ui`-owned** per-session counter (Victor's `g_sessionTakes` pattern — `core` has no per-session counter; it owns only the lifetime `episode_ordinal`) — incremented on a committed START (`trigger()` returns true), reset on boot / table change (MESA re-entry) | "TOMA #n". |
| **GUARDAR / DESCARTAR + toast** | `core` save/discard + `mark_archive` | The confirm-splash toast; the lockout (ignore taps while working). |
| **LLAMAR (call lead)** | (UI splash + a **local** help-event log) | KEEP the yellow `callSplash` + the local help-event line. **Defer the dashboard "bell" POST** — it rides the god's-view live uplink (SPEC §1.10) when that lands; the radio-borrow POST path is dead today (✅ FLAG-E). No START gating, no radio borrow. |
| **`REGISTRO → MESA → MAIN → CONFIRM` + `CONFIRM_ID` (+ MESA re-entry, CONFIRM timeout)** | screen-nav state (UI-owned) + `core` Assignment | The flow, with `CONFIRM_ID` ("Are you <name>?") guarding a mistyped entry, the operator sign-in step (OQ-1), the **MAIN-header double-tap → MESA** table-change re-entry (drives the take-counter reset), and the **CONFIRM 45 s auto-timeout** (✅ FLAG-E). |

`ui/` **never** decides whether a trigger is valid, mints an id, or assembles a sidecar — `core` does.
`ui/` shows what `core` reports and posts what the operator pressed.

---

## 4. The adaptation map (Victor's CYD function → ours)

| F3 piece | Victor's function(s) in the vendored `main.cpp` | Adaptation note |
|---|---|---|
| `ui/screens` | `renderMain`/`renderConfirm`/`renderConfirmId`/`renderProvision`/`renderMesa`/`renderNumEntry`, `drawPromptBand`, `drawLockGlyph`/`drawPhoneIcon`, `confirmSplash`/`callSplash`, `keypadHit` | Adapt verbatim-in-spirit; strip the dead BLE/CE81 lineage visible in the screen code (same as F2). Keep LLAMAR + `callSplash` (✅ FLAG-E). |
| `ui/touch` | `xptRead`/`touchRaw` (`kTouchZThresh=1000`), the hysteresis/debounce-latch (`kPressHi=220`/`kReleaseLo=90`/`kRelSamples=3`, `s_down`/`s_relCount`), `touchScreenX/Y` (axis-swapped calibration), the per-screen hit-test | Carry the debounce property — a stray re-tap must not inject a toggle (the UI half of SPEC §1.8; the `core` half already guarantees spam-safety). |
| `ui/render_state` | `camCol`, the take-counter/toast draws, the `lockedStart`/`startGate` button treatment | **Re-point at `core`:** read the `ui`-owned `DelayedButton::working()` + `present_count()` + the take count, instead of Victor's `g_anyRec`/`g_connCount`/`startGate` locals. Map `GATE_CAMS`→present-count, `GATE_SAVING`→`working()`, **drop `GATE_UPLINK`**. |
| `ui/flow` | the screen-nav transitions; `provisionVerify`/`SCREEN_PROVISION`; `g_verifOp`/`identityYes`/`identityNo`/`CONFIRM_ID`; the MAIN-header double-tap (`s_hdrArmMs`)→MESA; the CONFIRM 45 s timeout | Add the operator sign-in step (OQ-1). Post inputs to the coordinator via the F2 app glue. Own + drive the `DelayedButton`(s). |

`env:esp32` (headless) must still link — every `ui/` entry point is behind `PANTHEON_HAS_TFT`, exactly
as Victor's `esp32dev` headless build excludes the TFT path (`g_screen`/`g_forceRender`/`g_sessionTakes`
live outside the guard; only the draws are TFT-only).

---

## 5. The bundled follow-ups + the F3 core touches (all surfaced, none silent)

The §9 boundary is: the ONLY `core/` edits are **§5.1 (enums)**, **§5.2 (one accessor)**, and
**§5.3 (comments)** — all behavior-preserving. Anything else is an OQ.

### 5.1 `core/` enum-size cleanup → extend clang-tidy's blocking scope to `core/` (✅ FLAG-F)

F2 found 5 pre-existing `performance-enum-size` findings in `core/` (F1 code) and scoped blocking
clang-tidy to `transport/proto/` to keep F2's zero-core-diff boundary. F3 clears them:

- Add an explicit underlying type to the **5** enums (verified present): `GateOutcome`
  (`coordinator.h:39`), `Press` (`button_feedback.h:16`), `State`/`Input`/`Action`
  (`trigger_state_machine.h:15/18/21`). A ~5-line, behavior-preserving change (e.g. `: uint8_t`).
- **Extend the blocking clang-tidy scope to `core/`** — and do it correctly (✅ FLAG-F): the enums are
  in **headers**, so both halves are required —
  1. `Makefile` `TIDY_FILES += $(shell find firmware/coordinator/core -name '*.cpp')` (so the headers
     get pulled into a compiled TU), **and**
  2. `.clang-tidy` `HeaderFilterRegex` extended to cover `firmware/coordinator/core/.*` (so the
     in-header `performance-enum-size` diagnostics are actually reported, not suppressed as non-user).
  3. Reconcile the **pre-existing Makefile inconsistency**: the help text (line 26) + the
     `gates-cpp-tidy` help already claim "core/ + transport/proto/" while `TIDY_FILES` + the echo
     (line 63) are proto-only — make them match the now-true `core/ + transport/proto/` scope.
- `ui/` is framework-coupled (TFT_eSPI) like `hw/`, so `ui/` is **excluded** from clang-tidy; the tidy
  scope after F3 is **`core/ + transport/proto/`**. `transport/vendor/` stays excluded.
- Verify the 5-enum change leaves all `core/` tests byte-for-byte green (native + esp32 build) and that
  clang-tidy on `core/` surfaces **no other** findings (if it does, fix behavior-preserving or flag).

### 5.2 The one tiny `core/` accessor — `Coordinator::present_count()` (✅ FLAG-C)

Add a const `std::size_t present_count() const` that returns `deps_.presence ? deps_.presence->present().size() : 0`
(read-only, no logic). This is what `render_state` polls each frame for the GO/NO-GO colour — keeping
`ui` reading `core` state **through the coordinator** (the `ui→core` seam) instead of reaching into
`transport`'s registry. `detect_drop()` is unchanged and stays the drop-detection path. This **expands
§9's core-edit boundary** from "only the enums" to "the enums + one tiny read-only accessor + the
comment fix" — surfaced, not silent.

### 5.3 Stale "ui/ (F2)" comment fix (✅ FLAG-D)

Correct `button_feedback.h:8`, `coordinator.h:12`, and `core/README.md:24` — all say "ui/ (F2)"; ui/
is F3. Comment-only; the first two ride the §5.1 enum-cleanup edit (same files). Within §9's boundary.

### 5.4 SPEC §1.8 no-queue docs correction

Update the §1.8 sentence that currently reads "the fob running its network work on a dedicated core so
the UI never stalls … the instant touch-ack is only possible because the UI thread isn't blocked." The
F2 ground-truth: there is **no trigger queue** (Victor's `wifiTask`/queue serve the disabled uplink,
not the trigger); the trigger OSC runs **inline** on the loop core under the WiFi mutex (fast, because
fire-and-forget); **discovery/presence** runs on a dedicated core, lock-serialized (so a mid-take
camera drop is still detected); and the instant touch-ack is **`core::DelayedButton` decoupling the
visual from the slow action** (set working-state synchronously on tap → fire → settle), NOT a freed UI
thread. Keep the de-jargon rule (no internal codes in SPEC). *(The §1.7 sidecar-model + "fob NTP
wallclock" + the CONTRACT §1.7 corrections are a separate docs pass — do NOT touch them in F3.)*

---

## 6. Resolved decisions (the former open questions)

**OQ-1 — the operator sign-in UI — RESOLVED (A).** Keep REGISTRO's kit confirmation AND add an
operator sign-in so `operator_id` is set **per shift**, not baked per kit (the operator⊥kit decision at
the UI; one operator roams kits, the session records the pairing). Mechanism: **(A) numeric operator-ID
entry + `CONFIRM_ID`** — operator types their ID number, the roster resolves number→name, "Are you
<name>?" confirms. Mirrors Victor's exact REGISTRO + CONFIRM_ID pattern (type number → resolve →
confirm), reuses the numeric keypad. **Flag if the roster→name resolution isn't available on-device**
(then sign-in carries the id and the name resolves downstream).

**OQ-2 — screen-navigation state ownership — RESOLVED.** `ui/` owns the screen-nav state machine
(`REGISTRO/MESA/MAIN/CONFIRM/CONFIRM_ID`, incl. the MESA re-entry + CONFIRM timeout) entirely; `core`
owns only the trigger state machine. `ui/` reads `core` state for rendering and posts operator inputs
through the coordinator. Keeps the swappable-UI seam clean (a new screen swaps `ui/` without touching
`core`).

**OQ-3 — how `render_state` observes `core` — RESOLVED (corrected by ✅ FLAG-B + ✅ FLAG-C).** Poll each
render frame. Two sources:
- **The delayed-button treatment** reads the **`ui`-owned `DelayedButton::working()`** (2-state). There
  is **no `core::button_feedback` to poll and no core accessor needed for it** — `ui` owns the
  instance(s) and drives `press()`/`complete()` around the slow inline action (matches the F2 no-queue
  finding). `DelayedButton` has zero callers today; F3 is where it gets owned + wired.
- **The GO/NO-GO colour** reads the new const **`Coordinator::present_count()`** (§5.2) — **not**
  `detect_drop()`.

**OQ-4 — touch debounce fidelity — RESOLVED.** Carry Victor's XPT2046 pressure-read + hysteresis/
debounce-latch property exactly. The UI lockout (ignore taps while `working()`) is the §1.8 UI half;
the `core` spam-safety (START valid only from `idle`, extra taps dropped — `TriggerStateMachine`) is the
guarantee underneath — a test shows that even if the debounce is defeated, `core` never double-fires
(an F1 property; F3 must not regress it via the input path).

**OQ-5 — `env:esp32` headless link — RESOLVED (BLOCKING gate).** Every `ui/` symbol is behind
`PANTHEON_HAS_TFT` so the headless `esp32` build (core + transport, no TFT) still links clean. A
headless-link break is a stop-and-fix.

---

## 7. Test / validation plan

1. **Headless link preserved (`env:esp32`, BLOCKING).** core + transport build clean with `ui/`
   excluded via `PANTHEON_HAS_TFT` — the F2 headless path must not regress.
2. **`env:cyd` builds with `PANTHEON_HAS_TFT` on (BLOCKING).** The deployment board builds with `ui/`
   linked (TFT_eSPI + the ported CYD flags). The colour-fix (`TFT_BGR` + `TFT_INVERSION_ON`) is
   compiled in; **bench-verify the colours are correct** (✅ FLAG-A — GO/NO-GO is colour-critical).
3. **`core` spam-safety not regressed by the input path (`env:native`).** A test driving the
   coordinator from simulated rapid/queued inputs shows `core` still never double-fires (START valid
   only from `idle`), and a forced no-clock condition still surfaces `recording_suspect`/`needs_review`
   rather than silently recording (the OQ-3/loud-not-silent property from F2 must survive the UI path).
4. **`render_state` mapping unit-tested off-target.** The pure mapping (`working()` → button-treatment
   token; `present_count` vs `required` → GO/NO-GO; take count → label; SAVING `working()` → ESPERA
   token; UPLINK dropped) is host-testable even though the draw calls are not — test the mapping,
   compile-check the draws on-target.
5. **The 5-enum cleanup leaves `core/` green** — native tests byte-identical, esp32 build clean,
   clang-tidy blocking scope extended to `core/` (incl. the `HeaderFilterRegex`) and passing.
6. **Build gates (all five Python gates + drift unaffected; clang-format/clang-tidy per the F2 pins).**
   No Python, no `contracts/` change → codegen drift = 0. clang-format stays the per-file (`xargs -n1`)
   gate with the pinned wheel; clang-tidy blocking on `core/ + transport/proto/` (ui/ + vendor +
   framework-coupled hw/ excluded). `transport/vendor/` stays excluded from the build.
7. **Bench / rig validation (the real UI).** On the CYD + Victor's rig: the screen flow
   (REGISTRO→sign-in→MESA→MAIN, the MESA re-entry, the CONFIRM timeout), the instant-ack on START/STOP,
   the working/locked treatment, the camera-count colour on a real cam drop (with the colours verified
   correct), GUARDAR/DESCARTAR + toast, LLAMAR splash, and the spam-the-screen-is-harmless
   demonstration (rapid taps during the ~3 s START window do not corrupt the take).

---

## 8. Build + gate impact

- **`env:cyd`: TFT config PORTED (✅ FLAG-A) + `PANTHEON_HAS_TFT` ON + `ui/` in the build filter; stays
  BLOCKING + green.** The `lib_deps`/display-block/pins are added from the vendored `platformio.ini`;
  this is real config work, not a guard flip.
- **`env:esp32`: stays headless + BLOCKING** (no TFT dep; ui/ excluded by the guard; must still link).
- **clang-tidy: blocking scope EXTENDED to `core/`** (after the 5-enum cleanup) **+ `transport/proto/`**,
  via `TIDY_FILES` **and** the `.clang-tidy` `HeaderFilterRegex` (✅ FLAG-F); the Makefile help/echo
  reconciled. **`ui/` excluded** (framework-coupled, like `hw/`), `transport/vendor/` excluded.
  clang-format stays per-file + pinned wheel.
- **The 5 Python gates + contract drift: UNAFFECTED** (no Python, no `contracts/` change).
- **Arduino/TFT deps live ONLY in `transport/` + `ui/`** — `core/` and the native test env pull none.

---

## 9. What F3 deliberately does NOT do

- **No `core/` capture-logic changes** — the ONLY `core/` edits are the 5-enum cleanup (§5.1), the one
  tiny read-only `present_count()` accessor (§5.2), and the stale-comment fix (§5.3); all
  behavior-preserving. Flag anything else as an OQ.
- **No `contracts/` changes**; **no `transport/` behavior changes** (ui observes `core` + posts inputs).
- **No new network path** — the LLAMAR dashboard "bell" POST is **deferred** (rides the god's-view
  uplink, SPEC §1.10); F3 ships only the splash + the local help-event log.
- **No reimplementing Victor's camera-side stack** (discardd, the camera WiFi join, pre-arm/cross-cam-
  sync, the camera firmware, discardd's v2 writer).
- **No §1.7 / CONTRACT docs edits** — only the §1.8 no-queue correction (§5.4).
- **No operator-roster management UI** beyond the sign-in selection (OQ-1) — roster provisioning belongs
  to the later provisioning console.

---

> **On approval (given): implement, run the gates, report per the F1/F2 shape** — real gate tails; the
> SPEC §1.8 rendering shown faithful as a diff vs the vendored CYD screens (instant-ack-before-work via
> `working()`, lockout, the camera-count colour with the colour-fix verified, the spam-safety preserved
> through the input path); the swappable-UI seam statement (ui renders `core`, owns no logic); the
> 5-enum cleanup + the extended clang-tidy scope (incl. the `HeaderFilterRegex`) shown green; both
> `env:cyd` (TFT on) and `env:esp32` (headless) building clean with `transport/vendor/` excluded; a
> reviewer-subagent diff vs this corrected plan; deviations; and merge-readiness. **Wait for the
> go-ahead before opening the PR.** Conductor does the squash-merge.
