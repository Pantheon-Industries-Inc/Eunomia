#include "flow.h"

#ifdef PANTHEON_HAS_TFT

#include "render_state.h"
#include "screens.h"
#include "touch.h"

namespace eunomia::ui {
namespace {

using eunomia::core::Press;
using eunomia::core::State;

// How long the brief "START FALLO — reintenta" notice stays on MAIN after a rolled-back START (F6).
// Long enough to read, short enough to clear itself so the operator just retries. Not a blocking
// splash (NOTE: loud-not-silent, but light).
constexpr std::uint32_t kStartFailNoticeMs = 2500;

// Cheap djb2 over a C string — for the MAIN redraw-on-change signature only.
std::uint32_t str_hash(const char *s) {
  std::uint32_t h = 5381;
  if (s != nullptr) {
    for (; *s; ++s) {
      h = (h * 33u) ^ static_cast<std::uint8_t>(*s);
    }
  }
  return h;
}

} // namespace

void Flow::begin() {
  screens::begin();
  touch::begin();
  // Boot routes by provisioning: a provisioned fob goes straight to the per-shift operator sign-in;
  // an unprovisioned / NVS-wiped fob starts at REGISTRO (kit entry) so it can never dead-end.
  screen_ = host_.kit_provisioned() ? Screen::SignIn : Screen::Registro;
  force_ = true;
}

void Flow::render_main_now() {
  screens::MainView v;
  const std::size_t present = host_.present_count();
  const std::size_t required = host_.required_cameras();
  v.button = main_button(host_.core_state(), toggle_btn_.working(), present, required);
  v.cam = cam_light(present, required);
  v.present = present;
  v.required = required;
  v.station = host_.station();
  v.prompt = host_.prompt();
  v.start_failed = (start_fail_until_ms_ != 0); // F6: brief rolled-back-START notice (tick expires)
  screens::render_main(v);
}

void Flow::render_current() {
  switch (screen_) {
  case Screen::Registro:
    screens::render_provision(prov_kit_.c_str(), err_.c_str());
    break;
  case Screen::SignIn:
    screens::render_sign_in(signin_num_.c_str(), err_.c_str());
    break;
  case Screen::ConfirmId: {
    // No on-device number->name roster (the OQ-1 flagged fallback): the operator NUMBER is carried
    // and the name resolves downstream. Show the number as the thing being confirmed.
    std::string name = "Operador " + signin_num_;
    screens::render_confirm_id(name.c_str(), host_.kit_id());
    break;
  }
  case Screen::Mesa:
    screens::render_mesa(mesa_num_.c_str(), err_.c_str());
    break;
  case Screen::Main:
    render_main_now();
    break;
  case Screen::Confirm:
    screens::render_confirm(take_n_);
    break;
  }
}

// press -> render the working/lockout state BEFORE the slow inline action (the instant-ack: the
// visual is set synchronously, NOT because a thread is free — the F2 no-queue finding) -> run the
// action -> complete -> render the result. core's TriggerStateMachine is the spam-safety guarantee
// underneath.
void Flow::do_toggle(std::uint32_t now) {
  if (toggle_btn_.press() != Press::Accepted) {
    return; // already working: a re-tap during the slow action is dropped (UI lockout)
  }
  const State before = host_.core_state();
  render_main_now(); // working() is now true -> draws ESPERA (working) immediately
  host_.record_toggle();
  toggle_btn_.complete();
  const State after = host_.core_state();
  if (before == State::Idle && after == State::Recording) {
    take_n_++;                // a START committed this session
    start_fail_until_ms_ = 0; // a good START clears any lingering failure notice
    force_ = true;
  } else if (before == State::Recording && after == State::Idle) {
    screen_ = Screen::Confirm; // a STOP finalized -> the GUARDAR/DESCARTAR decision
    confirm_start_ms_ = now;
    force_ = true;
  } else if (host_.last_start_failed()) {
    // The START was refused by the FIRE-CONFIRM rollback (cams present, but startCapture didn't
    // confirm on enough cams, or the durable commit failed). Surface it loudly + briefly so the
    // operator retries — distinct from a presence NO-GO, which the button already shows (F6).
    start_fail_until_ms_ = now + kStartFailNoticeMs;
    force_ = true;
  } else {
    force_ = true; // a presence/spam refusal (still idle) — repaint MAIN, no notice
  }
}

void Flow::dispatch(int sx, int sy, std::uint32_t now) {
  switch (screen_) {
  case Screen::Main: {
    const bool recording = (host_.core_state() == State::Recording);
    const screens::MainHit hit = screens::hit_main(sx, sy);
    if (recording) {
      // While recording the ONLY valid action is DETENER; header/LLAMAR are disabled so a stray
      // touch can never trap the operator away from the stop/decision flow.
      if (hit == screens::MainHit::Toggle) {
        do_toggle(now);
      }
    } else if (hit == screens::MainHit::Header) {
      // Table change = a DELIBERATE double-tap within 1.5 s (a stray header tap only arms, stays on
      // MAIN). The header hint reads "toca 2x" so it is discoverable.
      if (hdr_arm_ms_ != 0 && now - hdr_arm_ms_ < 1500) {
        hdr_arm_ms_ = 0;
        mesa_num_.clear();
        err_.clear();
        screen_ = Screen::Mesa;
        force_ = true;
      } else {
        hdr_arm_ms_ = now;
      }
    } else if (hit == screens::MainHit::Toggle) {
      // GRABAR only when cams are present (the GO state). Any NO-GO is a physical no-op: the button
      // already shows the reason; nudge a redraw so a just-changed state repaints.
      const MainButton btn =
          main_button(State::Idle, false, host_.present_count(), host_.required_cameras());
      if (btn == MainButton::Go) {
        do_toggle(now);
      } else {
        force_ = true;
      }
    } else if (hit == screens::MainHit::Call) {
      host_.call_lead();
      screens::call_splash();
      force_ = true;
    }
    break;
  }
  case Screen::Confirm:
    if (screens::confirm_is_save(sy)) {
      host_.save_take();
      screens::confirm_splash_save();
    } else {
      host_.discard_take();
      screens::confirm_splash_discard();
    }
    screen_ = Screen::Main;
    force_ = true;
    break;
  case Screen::ConfirmId:
    if (screens::confirm_id_in_band(sy)) {
      if (screens::confirm_id_is_yes(sx, sy)) {
        host_.sign_in(signin_num_.c_str()); // commit operator_id for the shift
        mesa_num_.clear();
        err_.clear();
        screen_ = Screen::Mesa;
      } else {
        signin_num_.clear(); // re-enter the operator number
        err_.clear();
        screen_ = Screen::SignIn;
      }
      force_ = true;
    }
    break;
  case Screen::Registro: {
    int r, c;
    if (screens::keypad_hit(sx, sy, r, c)) {
      if (screens::keypad_is_del(r, c)) {
        if (!prov_kit_.empty()) {
          prov_kit_.pop_back();
        }
      } else if (screens::keypad_is_enter(r, c)) {
        if (prov_kit_.empty()) {
          err_ = "Escribe el numero de kit / Enter kit number";
        } else {
          err_.clear();
          host_.set_kit(prov_kit_.c_str()); // commit the typed kit (depot fallback)
          screen_ = Screen::SignIn;         // -> operator sign-in
        }
      } else if (prov_kit_.size() < 9) {
        prov_kit_ += screens::keypad_label(r, c)[0];
      }
    }
    force_ = true;
    break;
  }
  case Screen::SignIn: {
    if (screens::hit_back(sx, sy)) {
      err_.clear();
      screen_ = Screen::Registro; // ATRAS -> re-enter the kit
      force_ = true;
      break;
    }
    int r, c;
    if (screens::keypad_hit(sx, sy, r, c)) {
      if (screens::keypad_is_del(r, c)) {
        if (!signin_num_.empty()) {
          signin_num_.pop_back();
        }
      } else if (screens::keypad_is_enter(r, c)) {
        if (signin_num_.empty()) {
          err_ = "Escribe tu numero / Enter your operator #";
        } else {
          err_.clear();
          screen_ = Screen::ConfirmId; // confirm "Are you <operator>?"
        }
      } else if (signin_num_.size() < 9) {
        signin_num_ += screens::keypad_label(r, c)[0];
      }
    }
    force_ = true;
    break;
  }
  case Screen::Mesa: {
    if (screens::hit_back(sx, sy)) {
      err_.clear();
      screen_ = Screen::SignIn; // ATRAS -> back to sign-in
      force_ = true;
      break;
    }
    int r, c;
    if (screens::keypad_hit(sx, sy, r, c)) {
      if (screens::keypad_is_del(r, c)) {
        if (!mesa_num_.empty()) {
          mesa_num_.pop_back();
        }
      } else if (screens::keypad_is_enter(r, c)) {
        if (mesa_num_.empty()) {
          err_ = "Escribe el numero de mesa / Enter table number";
        } else {
          err_.clear();
          host_.select_table(mesa_num_.c_str());
          take_n_ = 0; // a table change resets the per-session take counter
          screen_ = Screen::Main;
        }
      } else if (mesa_num_.size() < 9) {
        mesa_num_ += screens::keypad_label(r, c)[0];
      }
    }
    force_ = true;
    break;
  }
  }
}

void Flow::tick(std::uint32_t now) {
  if (!screens::ready()) {
    return;
  }
  // Touch dispatch (one debounced press = one action).
  int sx = 0, sy = 0;
  if (touch::poll(now, &sx, &sy)) {
    dispatch(sx, sy, now);
    if (screen_ != Screen::Main) {
      render_current();
      force_ = false;
    }
  }

  if (screen_ == Screen::Main) {
    // Expire the brief START-failure notice (F6). Signed elapsed compare — the deadline is stamped
    // in the future (now + kStartFailNoticeMs), so (now - deadline) stays negative until it passes.
    if (start_fail_until_ms_ != 0 && static_cast<std::int32_t>(now - start_fail_until_ms_) >= 0) {
      start_fail_until_ms_ = 0;
      force_ = true; // repaint to clear the notice
    }
    // MAIN redraws ONLY on change (no idle flicker) — but a cam dropping (present_count) or a state
    // change must repaint. Signature mirrors exactly what MAIN draws.
    const std::uint32_t sig = static_cast<std::uint32_t>(host_.present_count()) ^
                              (static_cast<std::uint32_t>(host_.core_state()) << 8) ^
                              (toggle_btn_.working() ? 0x10000u : 0u) ^
                              (start_fail_until_ms_ != 0 ? 0x20000u : 0u) ^
                              (str_hash(host_.station()) * 3u) ^ (str_hash(host_.prompt()) * 7u);
    if (force_ || sig != main_sig_) {
      main_sig_ = sig;
      force_ = false;
      render_main_now();
    }
    screens::tick_prompt(now);
  } else if (force_) {
    force_ = false;
    render_current();
  }

  // CONFIRM auto-save: if the operator walks off without choosing, default to KEEP after 45 s so
  // the fob never sticks off MAIN (a wrong keep can be deleted at ingest; a wrong delete cannot be
  // undone). SIGNED elapsed compare — confirm_start_ms_ is stamped LATER in the same loop iteration
  // than `now`, so an unsigned subtract would underflow and auto-save instantly.
  if (screen_ == Screen::Confirm && static_cast<std::int32_t>(now - confirm_start_ms_) > 45000) {
    host_.save_take();
    screens::confirm_splash_save();
    screen_ = Screen::Main;
    force_ = true;
  }
}

} // namespace eunomia::ui

#endif // PANTHEON_HAS_TFT
