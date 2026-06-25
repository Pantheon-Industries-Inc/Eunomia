// firmware/coordinator/transport/proto/ — NVS key mapping (the ESP32 15-char-key constraint), pure.
//
// FINDING (F2): core's durable-ordinal key is "fob_episode_ordinal" (19 chars), but ESP32 NVS keys
// are capped at 15 chars (NVS_KEY_NAME_MAX_SIZE). core/ is platform-free and rightly uses the full
// name; transport maps it to a valid NVS key here — ZERO core change. The mapping is a fixed table
// for the keys in use, with a deterministic truncation fallback (logged) for anything unforeseen.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_PROTO_NVS_KEYS_H
#define EUNOMIA_COORDINATOR_TRANSPORT_PROTO_NVS_KEYS_H

#include <string>

namespace eunomia::transport {

// The NVS namespace the fob's Preferences live under (Victor's "pantheon-fob").
inline constexpr const char *kNvsNamespace = "pantheon-fob";

// core's logical durable-ordinal key (Coordinator's kOrdinalKey). Kept here so the mapping is
// asserted against the real value in the native test.
inline constexpr const char *kOrdinalLogicalKey = "fob_episode_ordinal";

// Max NVS key length on the ESP32 (usable chars; the C constant is 16 incl. the NUL terminator).
inline constexpr std::size_t kNvsKeyMax = 15;

// Map a core logical key → a valid (≤15-char) NVS key. Known long keys get a stable short alias;
// short keys pass through; any other over-length key is truncated deterministically.
std::string nvs_key_for(const std::string &logical);

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_PROTO_NVS_KEYS_H
