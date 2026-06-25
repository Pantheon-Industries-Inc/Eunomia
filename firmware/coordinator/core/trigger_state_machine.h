// firmware/coordinator/core/ — the trigger state machine (SPEC §1.8 core layer).
//
// This is the non-negotiable spam-safety guarantee, independent of the UI: a START is acted on ONLY
// from `idle`; from arming/starting/recording/stopping, further START inputs are DROPPED (never
// double-fired). STOP is valid ONLY from `recording`. Spamming the screen is harmless BY DESIGN —
// the UI's instant-ack/lockout (button_feedback) is the comfort on top of this guarantee, not the
// guarantee itself. Pure logic: no side effects beyond the state field, fully off-target testable.
#ifndef EUNOMIA_COORDINATOR_CORE_TRIGGER_STATE_MACHINE_H
#define EUNOMIA_COORDINATOR_CORE_TRIGGER_STATE_MACHINE_H

#include <cstdint>

namespace eunomia::core {

// idle → arming → starting → recording → stopping → idle. arming/starting bracket the START burst
// (presence gate + the per-camera OSC fires); the ~3 s pipeline re-init lives in `starting`.
enum class State : std::uint8_t { Idle, Arming, Starting, Recording, Stopping };

// Operator inputs offered to the machine.
enum class Input : std::uint8_t { Start, Stop };

// What the caller (the Coordinator) should do in response to an offered input.
enum class Action : std::uint8_t {
  Ignored,    // dropped by spam-safety: the input is not valid from the current state
  BeginStart, // idle + Start → caller runs the presence gate + START sequence
  BeginStop   // recording + Stop → caller runs the STOP sequence
};

class TriggerStateMachine {
public:
  State state() const { return state_; }

  // Offer an input. START advances only from idle; STOP only from recording. Any other case is
  // Ignored (the second-trigger-mid-sequence drop — the spam-safety guarantee).
  Action offer(Input in);

  // Sequence callbacks the Coordinator invokes as the START/STOP burst progresses.
  void begin_firing();     // arming → starting (presence gate passed; firing OSC)
  void on_started();       // starting → recording (both cams fired)
  void on_start_aborted(); // arming/starting → idle (phantom/one-sided: no commit)
  void on_stopped();       // stopping → idle (STOP finalized)

private:
  State state_ = State::Idle;
};

} // namespace eunomia::core

#endif // EUNOMIA_COORDINATOR_CORE_TRIGGER_STATE_MACHINE_H
