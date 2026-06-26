// firmware/coordinator/transport/proto/ — the X3 CaptureDevicePort adapter (OSC + telnet), pure.
//
// Implements the generated `eunomia::CaptureDevicePort` (CONTRACT §1.6 "Contract B") for ONE camera
// (one side). It drives the X3 over the injected Conn/Delayer using the proto wire helpers, and
// pulls the camera's live IP from the CameraRegistry (DHCP-assigned, so dynamic). Pure: no Arduino
// — the real WiFiClient is injected as a Conn by transport/hw/, the mock by the native tests. THE
// TWO HARD RULES are realized here: start() pushes current_assignment.env THEN fires startCapture
// DIRECTLY (no per-take arm), and every OSC is fire-and-forget (no body read). Serialization
// (`wifiLock`) is the worker's job one layer up; this adapter never overlaps its own calls (core
// drives it sequentially).
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_PROTO_X3_CAPTURE_DEVICE_H
#define EUNOMIA_COORDINATOR_TRANSPORT_PROTO_X3_CAPTURE_DEVICE_H

#include <string>

#include "conn.h"
#include "eunomia_capture_device_port.h"
#include "presence.h"
#include "start_confirmable.h"

namespace eunomia::transport {

class X3CaptureDevice : public eunomia::CaptureDevicePort, public eunomia::core::StartConfirmable {
public:
  // `side` = this device's fleet handle ("left"/"right"); the registry resolves it to a live IP.
  X3CaptureDevice(std::string side, CameraRegistry &reg, Conn &conn, Delayer &delayer,
                  EnvProvider &env);

  // Push current_assignment.env (telnet) THEN fire camera.startCapture (OSC, direct — HARD RULE 2).
  // The contract port is void; it routes through start_confirmed() (the two never double-fire).
  void start() override;
  // F6 fire-confirm: same push+fire, returning the startCapture connect-ack (true = delivered). The
  // connect-ack is a TCP connect+write, NEVER a body read, so HARD RULE 2 holds. "" IP (not present
  // at L2) → false. This is the signal core counts to roll back an under-confirmed take.
  bool start_confirmed() override;
  // Fire camera.stopCapture (OSC, fire-and-forget).
  void stop() override;
  // Recover the just-written clip filename via telnet `ls -t … grep VID_` (never the OSC reply).
  std::string read_back_filename() override;
  // Card-readiness token over telnet ("card_ok" / "no_card" / "absent"): the cherokee-safe check.
  std::string get_state() override;
  // No-op: discardd holds the camera in video mode (HARD RULE 2); the fob never sets a per-take
  // profile.
  void set_profile(const std::string &) override {}
  // Push current_stop.env (telnet); on archive==1 also fire /tmp/archive.trigger (DESCARTAR).
  void write_sidecar(const eunomia::Sidecar &record) override;

private:
  std::string side_;
  CameraRegistry &reg_;
  Conn &conn_;
  Delayer &d_;
  EnvProvider &env_;
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_PROTO_X3_CAPTURE_DEVICE_H
