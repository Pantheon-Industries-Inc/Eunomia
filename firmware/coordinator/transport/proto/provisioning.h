// firmware/coordinator/transport/proto/ — the SD-daemon provisioning RECEIVE parser (OQ-5/OQ-8),
// pure.
//
// Victor's in-flight SD daemon pushes a camera's connection info (MAC/AP/IP, body + .insv serials =
// the 0d `hardware_unit.provisioning` group) to the fob over telnet, removing the "the stock X3
// won't surface its own connection info" gap. F2 RECEIVES it as an out-of-band channel feeding an
// OPERATIONAL provisioning record — NO contract change, NO new CoordinatorPort op (F1 OQ-5).
//
// ⚠ The wire FORMAT/PORT is Victor's daemon's and IN-FLIGHT. This parser handles a PROVISIONAL
// key=value framing (mirroring Victor's existing `key=value;…` config grammar — the most likely
// shape); the actual receive wiring in transport/hw/ is GATED on confirming the format with Victor
// (OQ-8). Do not treat this framing as final.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_PROTO_PROVISIONING_H
#define EUNOMIA_COORDINATOR_TRANSPORT_PROTO_PROVISIONING_H

#include <string>

namespace eunomia::transport {

// The 0d hardware_unit.provisioning group the daemon supplies (operational-model data, not the
// capture-trigger contract). Filled best-effort; `valid` true once a MAC is present.
struct ProvisioningInfo {
  std::string mac;         // camera AP/STA MAC
  std::string ap_ssid;     // the camera's own AP ssid (provisioning provenance)
  std::string ip;          // leased IP on the fob subnet
  std::string body_serial; // the camera body serial
  std::string insv_serial; // the .insv (capture) serial
  std::string side;        // "left"/"right" if the daemon resolves it (else "")
  bool valid = false;
};

// Parse a PROVISIONAL key=value push payload (lines or ';'-separated). Recognized keys
// (case-folded): mac, ap_ssid|ap, ip, body_serial|serial, insv_serial|insv, side. Unknown keys
// ignored.
ProvisioningInfo parse_provisioning_push(const std::string &payload);

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_PROTO_PROVISIONING_H
