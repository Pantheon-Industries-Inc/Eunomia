// firmware/coordinator/core/ — the START fire-confirmation side-channel (Run F6).
//
// The generated contract port `eunomia::CaptureDevicePort::start()` returns `void`, so a fire
// landing or NOT landing is invisible to core through that seam. This OPTIONAL, non-contract
// interface is how a device adapter reports the per-camera fire result (the startCapture
// connect-ack — a TCP connect+write, NEVER a body read, so HARD RULE 2 holds) back to the
// Coordinator. core counts the confirmed fires and rolls back a take whose fire under-confirms
// (the fire-then-commit order; SPEC §1.8 / Victor's camStartAll connect-ack count).
//
// It is REGISTERED opt-in via Coordinator::set_confirmer(side, *), so the Fleet type + ctor are
// unchanged: an adapter/test that registers no confirmer keeps the F1 behaviour (the void start()
// fire, counted as started). This is deliberately a side-channel — the clean long-term shape is the
// contract port's start() returning the result, which is its own reviewed contract PR (out of F6).
#ifndef EUNOMIA_COORDINATOR_CORE_START_CONFIRMABLE_H
#define EUNOMIA_COORDINATOR_CORE_START_CONFIRMABLE_H

namespace eunomia::core {

// A device adapter that can confirm its startCapture fire (the connect-ack). Implemented alongside
// CaptureDevicePort by the same adapter; the adapter's void start() routes through
// start_confirmed() so the two never double-fire.
class StartConfirmable {
public:
  virtual ~StartConfirmable() = default;
  // Fire startCapture and return true iff the device confirmed delivery (connected + wrote the
  // request). False = the fire did not land on this camera (no connect) — core treats it as a cam
  // that did not start.
  virtual bool start_confirmed() = 0;
};

} // namespace eunomia::core

#endif // EUNOMIA_COORDINATOR_CORE_START_CONFIRMABLE_H
