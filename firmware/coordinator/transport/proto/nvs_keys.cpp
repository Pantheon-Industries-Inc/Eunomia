#include "nvs_keys.h"

namespace eunomia::transport {

std::string nvs_key_for(const std::string &logical) {
  // Fixed aliases for long keys in use. Each is unambiguous within the fob namespace and distinct
  // from Victor's keys (we own a fresh namespace; we never read his NVS layout).
  if (logical == kOrdinalLogicalKey) {
    return "ord";
  }
  if (logical == "uplink_ssid") {
    return "wssid";
  }
  if (logical == "uplink_pass") {
    return "wpass";
  }
  if (logical == "uplink_url") {
    return "upurl";
  }
  if (logical.size() <= kNvsKeyMax) {
    return logical;
  }
  return logical.substr(0, kNvsKeyMax); // deterministic fallback for an unforeseen long key
}

} // namespace eunomia::transport
