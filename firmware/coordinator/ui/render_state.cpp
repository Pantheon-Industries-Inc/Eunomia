#include "render_state.h"

namespace eunomia::ui {

using eunomia::core::State;

CamLight cam_light(std::size_t present, std::size_t required) {
  return present >= required ? CamLight::Go : CamLight::NoGo;
}

MainButton main_button(State core_state, bool action_working, std::size_t present,
                       std::size_t required) {
  // 1) The ui-owned DelayedButton in flight wins — the §1.8 lockout window. The visual is set
  // synchronously on tap (before the slow inline START/STOP), so the ack is instant; while it is in
  // flight every tap is ignored (spam-safe at the UI; core's TriggerStateMachine is the guarantee
  // underneath). NOTE: this covers only the IN-FLIGHT finalize window (the STOP/sidecar-push action
  // duration); it does NOT subsume Victor's GATE_SAVING — discardd's .pantheon.json materializes
  // ASYNCHRONOUSLY after working() clears, so a fast re-START can still race an owed prior sidecar.
  // A separate gate for that is UNVERIFIED, pending the rapid-re-START rig check (VALIDATION_PLAN
  // §C / F6); priorSidecarsReady is deliberately NOT implemented yet.
  if (action_working) {
    return MainButton::Working;
  }
  // 2) Recording: DETENER stays live so the operator can stop even if a camera dropped mid-take.
  if (core_state == State::Recording) {
    return MainButton::Recording;
  }
  // 3) Idle: GO only when the cams you need are present (the phantom/one-sided hard stop = the
  // GATE_CAMS lock). GATE_UPLINK is intentionally not represented (dead uplink — FLAG-E).
  return cam_light(present, required) == CamLight::Go ? MainButton::Go : MainButton::WaitingCams;
}

} // namespace eunomia::ui
