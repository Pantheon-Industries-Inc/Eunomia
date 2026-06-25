#include "nvs_keys.h"

namespace eunomia::transport {

std::string nvs_key_for(const std::string &logical) {
  // Fixed alias for the one long key in use. "ord" is unambiguous within the fob namespace and
  // distinct from Victor's "ordinal" (we own a fresh namespace; we never read his NVS layout).
  if (logical == kOrdinalLogicalKey) {
    return "ord";
  }
  if (logical.size() <= kNvsKeyMax) {
    return logical;
  }
  return logical.substr(0, kNvsKeyMax); // deterministic fallback for an unforeseen long key
}

} // namespace eunomia::transport
