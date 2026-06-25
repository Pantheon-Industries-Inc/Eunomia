// firmware/coordinator/transport/hw/ — the SD-daemon provisioning RECEIVE listener (OQ-5/OQ-8).
//
// A bounded inbound TCP listener on the fob AP IP that accepts Victor's SD-daemon push (camera
// MAC/AP/IP/serials = the 0d hardware_unit.provisioning group), parses it (proto/provisioning.h),
// and holds the latest record. It does NOT talk OSC (no HARD-RULE-1 risk) and is NOT a
// CoordinatorPort op / contract change — it is out-of-band operational-model data (F1 OQ-5).
//
// ⚠ GATED (OQ-8): the wire FORMAT + PORT are Victor's in-flight daemon's. This receiver is SPEC'd +
// compile-clean but is NOT started by default (the app does not call begin() unless
// PANTHEON_SD_DAEMON_RX is defined, and the port/format are confirmed with Victor). Don't guess the
// protocol.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_HW_PROVISIONING_RX_H
#define EUNOMIA_COORDINATOR_TRANSPORT_HW_PROVISIONING_RX_H

#include <Arduino.h>
#include <WiFiServer.h>

#include "provisioning.h"

namespace eunomia::transport {

// PLACEHOLDER port — UNCONFIRMED, gated on Victor (OQ-8). Do not treat as final.
inline constexpr std::uint16_t kProvisioningRxPort = 47999;

class ProvisioningReceiver {
public:
  void begin(); // start listening (no-op unless PANTHEON_SD_DAEMON_RX is defined)
  void poll();  // accept + parse one push (call from the core-0 worker; cheap)
  bool has_info() const { return last_.valid; }
  const ProvisioningInfo &last() const { return last_; }

private:
  WiFiServer server_{kProvisioningRxPort};
  ProvisioningInfo last_;
  bool started_ = false;
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_HW_PROVISIONING_RX_H
