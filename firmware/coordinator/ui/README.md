# `firmware/coordinator/ui/` — the CYD touchscreen (swappable)

Landed in **Run F3**. The display/touchscreen layer for the CYD (ESP32-2432S028R, 2.8" 320×240,
resistive touch — which can miss presses, hence the instant acknowledgement). It **renders `core/`
state and posts operator inputs back**; it owns **no** capture logic. A different screen reimplements
`ui/` against the same `core` guarantee (the swappable-UI seam). Adapted from Victor's proven CYD
screens in `transport/vendor/esp32-fob-wifi/main.cpp` — adaptation + wiring, not a rewrite.

## Dependency rule

`ui → core` only. `ui/` reads the `Coordinator` for render state and posts inputs through the abstract
`UiHost` seam (`flow.h`) — it **never** includes a `transport/` header. The composition root in
`transport/hw/app.cpp` implements `UiHost` over the coordinator + the wifi-locked record path. Swapping
the screen = reimplementing the renderers against the same `Coordinator` + `UiHost`, without touching
`core/`. The whole module is Arduino/`TFT_eSPI`-coupled, so everything except the pure `render_state`
is behind `PANTHEON_HAS_TFT`: the headless `env:esp32` build compiles `ui/` to nothing and still links
(`render_state` is pure C++17 and always compiles).

## What lives here

| File | Responsibility |
|---|---|
| `render_state.{h,cpp}` | **PURE** (no TFT/Arduino) core-state → render-token mapping — the host-testable heart: `cam_light()` (GO/NO-GO from `present_count()`, not `detect_drop()`) and `main_button()` (GRABAR/DETENER/ESPERA from `State` + the ui-owned `DelayedButton`). |
| `touch.{h,cpp}` | XPT2046 pressure read + the hysteresis/debounce-latch (Victor's single-tap-is-double fix) + the calibrated raw→screen mapping. The UI half of SPEC §1.8 (core spam-safety is the guarantee underneath). |
| `screens.{h,cpp}` | The renderers (MAIN / CONFIRM / CONFIRM_ID / REGISTRO / sign-in / MESA / numeric entry) + glyphs + the confirm/call splashes; the layout geometry + hit-tests (one source of truth for render AND touch). |
| `flow.{h,cpp}` | The screen-nav state machine (`REGISTRO → sign-in → CONFIRM_ID → MESA → MAIN → CONFIRM`, the MAIN-header double-tap → MESA table change, the CONFIRM 45 s auto-save), the `UiHost` seam, and the ui-owned `DelayedButton` (instant-ack: render working → run the slow inline action → settle). |

## The two guarantees it preserves (not owns)

1. **Spam-safety through the input path** — the touch debounce-latch + the `DelayedButton` lockout are
   the UI comfort; `core::TriggerStateMachine` (START only from `idle`) is the real guarantee. Even a
   defeated debounce never double-fires `core` (the F1 property, host-tested via the input path).
2. **GO/NO-GO** — green only when the cams you need are present (`present_count() >= required`); 0/req
   and one-sided are both a hard stop. Colour-critical: the CYD colour-fix must be verified on board.

## Deliberately not here

The dashboard "bell" POST behind LLAMAR (deferred to the god's-view live uplink, SPEC §1.10 — the
radio-borrow path is code-disabled); any operator-roster management UI (the provisioning console's
job); any `core/`/`transport/` behaviour change.
