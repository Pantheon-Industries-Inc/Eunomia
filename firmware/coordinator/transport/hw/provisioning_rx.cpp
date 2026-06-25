#include "provisioning_rx.h"

#include <WiFiClient.h>

namespace eunomia::transport {

void ProvisioningReceiver::begin() {
#ifdef PANTHEON_SD_DAEMON_RX
  server_.begin();
  server_.setNoDelay(true);
  started_ = true;
#else
  // GATED (OQ-8): the daemon's wire format/port are unconfirmed; do not listen until confirmed.
  started_ = false;
#endif
}

void ProvisioningReceiver::poll() {
  if (!started_) {
    return;
  }
  WiFiClient client = server_.available();
  if (!client) {
    return;
  }
  String payload;
  const std::uint32_t deadline = millis() + 500; // bounded read
  while (client.connected() && millis() < deadline) {
    while (client.available()) {
      payload += static_cast<char>(client.read());
      if (payload.length() > 1024) { // overrun guard
        break;
      }
    }
    if (payload.length() > 1024 || payload.indexOf('\n') >= 0) {
      break;
    }
    delay(5);
  }
  client.stop();
  const ProvisioningInfo info = parse_provisioning_push(std::string(payload.c_str()));
  if (info.valid) {
    last_ = info; // hold the latest; the app surfaces it as an operational provisioning record
  }
}

} // namespace eunomia::transport
