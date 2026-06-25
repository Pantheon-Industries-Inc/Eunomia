// firmware/coordinator/transport/proto/ — the framework-free transport seams.
//
// `proto/` is the PURE, host-testable half of transport: it builds the X3 wire bytes (OSC +
// telnet), parses the responses, and maps the L2 station table to camera sides — depending ONLY on
// these seams + the std lib + core/ headers. The real WiFiClient/esp_netif/Preferences live in
// transport/hw/ (Arduino, on-target only); the native tests drive mocks of the seams below. This is
// what lets `pio test -e native` cover the two-hard-rules + seam-conformance logic with NO rig (the
// one-machine rule), exactly as core/ is covered.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_PROTO_CONN_H
#define EUNOMIA_COORDINATOR_TRANSPORT_PROTO_CONN_H

#include <cstddef>
#include <cstdint>
#include <string>

namespace eunomia::transport {

// A minimal byte-stream connection seam — the exact subset of Arduino's WiFiClient the X3
// OSC/telnet paths use. Hardware impl = WifiConn (wraps WiFiClient); tests = MockConn (scripted,
// recording). Each fob→cam request opens a fresh connection (connect → … → stop), mirroring
// Victor's per-request WiFiClient lifetime (`oscSendNoWait`/`telnetCmd`).
class Conn {
public:
  virtual ~Conn() = default;
  virtual bool connect(const std::string &host, std::uint16_t port, std::uint32_t timeout_ms) = 0;
  virtual bool connected() = 0;
  virtual int available() = 0; // # bytes ready to read now (>= 0)
  virtual int read() = 0;      // next byte, or -1 if none ready
  virtual std::size_t write(const std::uint8_t *data, std::size_t n) = 0;
  virtual void flush() = 0; // push buffered bytes onto the wire
  virtual void stop() = 0;  // graceful close (FIN)

  // Convenience: write a whole string.
  std::size_t write(const std::string &s) {
    return write(reinterpret_cast<const std::uint8_t *>(s.data()), s.size());
  }
};

// Bounded sleep seam (Arduino delay() on-target; a no-op/recording fake off-target) — keeps the
// fire-and-forget grace (~120 ms) + the inter-request OSC settle gap (~150 ms) out of the pure code
// so the wire logic stays deterministic and testable.
class Delayer {
public:
  virtual ~Delayer() = default;
  virtual void delay_ms(std::uint32_t ms) = 0;
};

// Supplies the core-owned env-file bytes to the X3 device adapter (OQ-1, option A). The app glue
// implements this by calling core::project_assignment_env(assignment, coordinator.take()) /
// project_stop_env(coordinator.take()) — so the env CONTENT stays core's (no ArduinoJson
// re-derivation); transport only PUSHES the bytes over telnet.
class EnvProvider {
public:
  virtual ~EnvProvider() = default;
  virtual std::string assignment_env() = 0; // current_assignment.env (pushed before startCapture)
  virtual std::string stop_env() = 0;       // current_stop.env (pushed at write_sidecar)
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_PROTO_CONN_H
