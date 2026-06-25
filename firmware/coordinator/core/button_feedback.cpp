#include "button_feedback.h"

namespace eunomia::core {

Press DelayedButton::press() {
  if (working_) {
    // Lockout: a re-tap while the slow action is in flight is dropped (spam-safe).
    return Press::IgnoredLocked;
  }
  working_ = true;
  return Press::Accepted;
}

void DelayedButton::complete() { working_ = false; }

} // namespace eunomia::core
