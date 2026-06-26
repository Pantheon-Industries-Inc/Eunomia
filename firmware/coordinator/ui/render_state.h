// firmware/coordinator/ui/ — the PURE core-state → render-token mapping (the only place ui reads
// core). Framework-free C++17 (NO TFT_eSPI, NO Arduino) so it is host-testable on `env:native`; the
// actual draw calls live in screens.cpp behind PANTHEON_HAS_TFT. This module owns NO logic — it is
// the thin decision layer the swappable screen renders. (Run F3; SPEC §1.8 / CONTRACT §3.3.)
//
// The two mappings here are the testable heart of "ui renders core, owns nothing":
//   * cam_light()  — the GO/NO-GO camera light (FLAG-C: from present_count(), NOT detect_drop()).
//   * main_button()— the GRABAR/DETENER/ESPERA treatment from core State + the ui-owned
//   DelayedButton.
#ifndef EUNOMIA_COORDINATOR_UI_RENDER_STATE_H
#define EUNOMIA_COORDINATOR_UI_RENDER_STATE_H

#include <cstddef>
#include <cstdint>

#include "trigger_state_machine.h" // eunomia::core::State

namespace eunomia::ui {

// GO/NO-GO camera light (matches Victor's camCol). GREEN iff the cameras you need are present
// (>= required); RED otherwise — both 0/required AND a one-sided count are a hard stop (a one-sided
// take is useless). No amber middle state: "not both" must read as red. We require the cams we
// NEED, not an exact station count (the F2 REVISA ghost-STA lesson: a lingering ghost STA must not
// wedge it).
enum class CamLight : std::uint8_t { Go, NoGo };

// The MAIN toggle's visual treatment, decided from core State + the ui-owned
// DelayedButton::working().
//   Go          — idle, cams present: green GRABAR (a START is allowed).
//   WaitingCams — idle, cams NOT present: red ESPERA + padlock (START locked — Victor's GATE_CAMS).
//   Working     — the ui-owned DelayedButton is in flight (the ~3 s START or the STOP/finalize):
//   red
//                 lockout that ignores taps. This is the §1.8 instant-ack/lockout window — the
//                 visual is set synchronously on tap BEFORE the slow inline action (the F2 no-queue
//                 finding), NOT a freed thread. This covers the IN-FLIGHT finalize window ONLY (the
//                 duration of the STOP/sidecar-push action) — it does NOT cover Victor's
//                 GATE_SAVING (discardd's .pantheon.json materializes ASYNCHRONOUSLY, a moment
//                 AFTER the action returns and working() clears, so a fast re-START can still race
//                 an owed sidecar). Whether a separate persistent GATE_SAVING gate is needed here
//                 is UNVERIFIED — pending a rapid-re-START rig check (VALIDATION_PLAN §C); see F6.
//   Recording   — recording: red DETENER (the operator can ALWAYS stop, even on a mid-take cam
//   drop).
// Note: Victor's GATE_UPLINK is deliberately absent — the single-radio uplink-borrow is
// code-disabled (transport/hw/uplink.h DisabledUplink), so it can never fire; gating START on a
// dead uplink would mean never being able to record (F3 FLAG-E).
enum class MainButton : std::uint8_t { Go, WaitingCams, Working, Recording };

// present >= required ? Go : NoGo.
CamLight cam_light(std::size_t present, std::size_t required);

// The toggle treatment. `action_working` is the ui-owned DelayedButton::working() for the toggle.
MainButton main_button(eunomia::core::State core_state, bool action_working, std::size_t present,
                       std::size_t required);

} // namespace eunomia::ui

#endif // EUNOMIA_COORDINATOR_UI_RENDER_STATE_H
