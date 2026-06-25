// firmware/coordinator/core/ — the button-feedback STATE for ALL delayed buttons (SPEC §1.8).
//
// The LOGIC (not the pixels) behind the instant-ack + working + lockout treatment that applies to
// EVERY fob control with a perceptible delay — START (the ~3 s pipeline re-init), STOP (finalize/
// flush), and any settings/sign-in/confirm that round-trips to the camera network or god's-view.
// The visual ack is DECOUPLED from the slow action: a press flips the button instantly (before any
// network), the working state IGNORES taps (lockout), and it settles only when the action
// completes. ui/ (Run F3) renders these states; core/ owns the transitions. Same class for every
// delayed button.
#ifndef EUNOMIA_COORDINATOR_CORE_BUTTON_FEEDBACK_H
#define EUNOMIA_COORDINATOR_CORE_BUTTON_FEEDBACK_H

#include <cstdint>

namespace eunomia::core {

// The result of a touch on a delayed button.
enum class Press : std::uint8_t {
  Accepted,     // idle → working: the FIRST press; the UI flips visually NOW (before any network)
  IgnoredLocked // already working: a re-tap during the slow action — dropped (lockout / spam-safe)
};

class DelayedButton {
public:
  // A touch registered. The instant visual ack happens on Accepted, decoupled from the slow action.
  Press press();
  // The slow action (OSC/telnet/round-trip) completed — settle, ready for the next press.
  void complete();
  // True while the action is in flight (the UI shows the working/locked style and ignores taps).
  bool working() const { return working_; }

private:
  bool working_ = false;
};

} // namespace eunomia::core

#endif // EUNOMIA_COORDINATOR_CORE_BUTTON_FEEDBACK_H
