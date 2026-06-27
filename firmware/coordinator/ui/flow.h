// firmware/coordinator/ui/ — the screen-navigation state machine + the operator-input seam. Behind
// PANTHEON_HAS_TFT (it drives the TFT screens/touch). flow OWNS the screen-nav (UI concern) and the
// ui-owned DelayedButton; core owns the TRIGGER state machine. flow reads core state + posts
// operator inputs ONLY through UiHost — it never reaches into transport. Swapping the screen =
// re-implementing the renderers against the same UiHost (the swappable-UI seam). (Run F3; SPEC §1.8
// / OQ-1 / OQ-2.)
#ifndef EUNOMIA_COORDINATOR_UI_FLOW_H
#define EUNOMIA_COORDINATOR_UI_FLOW_H

#ifdef PANTHEON_HAS_TFT

#include <cstddef>
#include <cstdint>
#include <string>

#include "button_feedback.h"       // eunomia::core::DelayedButton
#include "trigger_state_machine.h" // eunomia::core::State

namespace eunomia::ui {

// The operator-input + render-read seam the app glue (transport) implements. ui posts inputs and
// reads state ONLY through this; it never includes a transport header. (The composition root in
// app.cpp implements UiHost over the Coordinator + the wifi-locked record path.)
class UiHost {
public:
  virtual ~UiHost() = default;

  // ---- reads (for rendering) ----
  virtual eunomia::core::State core_state() = 0; // the trigger SM state (same-core read)
  virtual bool last_start_failed() = 0;          // F6: the last START rolled back (fire didn't
                                                 // confirm) — drives the brief failure notice
  virtual std::size_t present_count() = 0;       // live L2 count, cached by the discovery task (the
                                                 // lock owner) — never read the registry from here
  virtual std::size_t required_cameras() = 0;
  virtual const char *station() = 0;
  virtual const char *prompt() = 0;
  virtual const char *kit_id() = 0;
  virtual bool kit_provisioned() = 0;   // boot routes REGISTRO (false) vs operator sign-in (true)
  virtual bool time_set() = 0;          // F7: clock loud-not-silent (NTP synced?)
  virtual const char *clock_hhmm() = 0; // F7: "HH:MM" local time (null when not set)
  virtual bool has_task_config() = 0;   // F9: a task config was fetched + parsed at boot
  virtual const char *task_name() = 0;  // F9: resolved task name for the current station

  // ---- operator inputs (posted) ----
  virtual void
  record_toggle() = 0;          // the SLOW inline GRABAR/DETENER (serialized under the wifi lock)
  virtual void save_take() = 0; // GUARDAR (keep)
  virtual void discard_take() = 0;                   // DESCARTAR (mark_archive + keep)
  virtual void set_kit(const char *kit_id) = 0;      // commit a typed kit (REGISTRO fallback only)
  virtual void sign_in(const char *operator_id) = 0; // set operator_id per shift (operator⊥kit)
  virtual void select_table(const char *table) = 0;  // set station (+ reset prompt)
  // F9: resolve station→task from the boot-fetched config. Returns true if resolved (fills task
  // fields in the assignment); false if station not found in the config.
  virtual bool resolve_station(const char *station_id) = 0;
  virtual bool call_lead() = 0; // F8: radio-borrow + POST; returns true on success
};

class Flow {
public:
  explicit Flow(UiHost &host) : host_(host) {}

  void begin();                 // init the TFT + touch and draw the first screen
  void tick(std::uint32_t now); // poll touch, dispatch, render — call each loop iteration

private:
  enum class Screen : std::uint8_t {
    Registro,
    SignIn,
    ConfirmId,
    Mesa,
    ConfirmTask,
    Main,
    Confirm
  };

  void dispatch(int sx, int sy, std::uint32_t now);
  void do_toggle(std::uint32_t now); // press -> render(working) -> slow inline action -> complete
  void render_current();             // draw whatever screen_ is showing now
  void render_main_now();            // assemble the MainView from core/host and draw it

  UiHost &host_;
  Screen screen_ = Screen::Registro;
  eunomia::core::DelayedButton toggle_btn_; // the ui-owned delayed button for GRABAR/DETENER
  eunomia::core::DelayedButton llamar_btn_; // F8: delayed button for LLAMAR (call lead)
  std::string prov_kit_;                    // typed kit number (REGISTRO)
  std::string signin_num_;                  // typed operator number (sign-in)
  std::string mesa_num_;                    // typed table number (MESA)
  std::string err_;                         // current entry-screen error line
  std::uint32_t take_n_ = 0;           // per-session take counter (resets on boot / table change)
  std::uint32_t confirm_start_ms_ = 0; // CONFIRM auto-save timer
  std::uint32_t hdr_arm_ms_ = 0;       // MAIN header double-tap arm (table-change guard)
  std::uint32_t start_fail_until_ms_ = 0; // F6: show "START FALLO" on MAIN until this ms (0 = none)
  std::uint32_t llamar_result_until_ms_ = 0; // F8: show LLAMAR success/fail toast until this ms
  bool llamar_ok_ = false;                   // F8: result of the last LLAMAR attempt
  std::uint32_t main_sig_ = 0;               // last MAIN render signature (redraw only on change)
  bool force_ = true;                        // force a redraw next tick
};

} // namespace eunomia::ui

#endif // PANTHEON_HAS_TFT

#endif // EUNOMIA_COORDINATOR_UI_FLOW_H
