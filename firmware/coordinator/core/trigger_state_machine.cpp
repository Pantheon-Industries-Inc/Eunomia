#include "trigger_state_machine.h"

namespace eunomia::core {

Action TriggerStateMachine::offer(Input in) {
  if (in == Input::Start) {
    // Spam-safety: START is valid ONLY from idle. From any in-flight state, drop it.
    if (state_ == State::Idle) {
      state_ = State::Arming;
      return Action::BeginStart;
    }
    return Action::Ignored;
  }
  // STOP is valid ONLY from recording.
  if (state_ == State::Recording) {
    state_ = State::Stopping;
    return Action::BeginStop;
  }
  return Action::Ignored;
}

void TriggerStateMachine::begin_firing() {
  if (state_ == State::Arming) {
    state_ = State::Starting;
  }
}

void TriggerStateMachine::on_started() {
  if (state_ == State::Starting) {
    state_ = State::Recording;
  }
}

void TriggerStateMachine::on_start_aborted() {
  if (state_ == State::Arming || state_ == State::Starting) {
    state_ = State::Idle;
  }
}

void TriggerStateMachine::on_stopped() {
  if (state_ == State::Stopping) {
    state_ = State::Idle;
  }
}

} // namespace eunomia::core
