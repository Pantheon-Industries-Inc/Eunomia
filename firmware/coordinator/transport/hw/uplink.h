// firmware/coordinator/transport/hw/ — the (disabled) opportunistic uplink seam (OQ-4).
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_HW_UPLINK_H
#define EUNOMIA_COORDINATOR_TRANSPORT_HW_UPLINK_H

#include <string>

#include "seams.h"

namespace eunomia::transport {

// OQ-4: the single-radio uplink-borrow tears down the SoftAP and drops every camera, so Victor
// keeps it code-disabled (`uplinkUp()` has an unconditional `return false`). This sink is a no-op
// until a non-AP-destroying uplink exists (F7). The real fail-safe is the DURABLE LittleFS
// ordinal-join log (transport/hw/episode_log.h), written in core's trigger() — independent of this
// opportunistic uplink. Deps.telemetry may be left null; this exists for parity with the F1 seam.
class DisabledUplink : public eunomia::core::TelemetrySink {
public:
  void send(const std::string & /*event_json*/) override {
    // intentionally empty — see OQ-4 (no AP-destroying borrow)
  }
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_HW_UPLINK_H
