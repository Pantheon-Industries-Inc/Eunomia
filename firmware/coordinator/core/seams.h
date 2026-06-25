// firmware/coordinator/core/ — injected platform seams.
//
// core/ is pure, hardware-free, and off-target-testable: it depends ONLY on
// contracts/_generated/cpp/
// + these abstract seams. The real implementations (the ESP32 hardware RNG, the NTP wallclock, NVS,
// the L2 station table, the opportunistic uplink) live in transport/ (Run F2); the native tests
// drive fakes. This is what makes `pio test -e native` cover core/ with no rig (the one-machine
// rule), and it keeps platform APIs out of core/ entirely (the OQ-3 ESP32-portability constraint).
//
// ESP32 constraints honored throughout core/: no C++ exceptions, no RTTI, heap-aware, no direct
// platform calls (everything platform-touching is behind a seam).
#ifndef EUNOMIA_COORDINATOR_CORE_SEAMS_H
#define EUNOMIA_COORDINATOR_CORE_SEAMS_H

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace eunomia::core {

// The fob's NTP-synced wallclock + a monotonic boot clock. The camera clock is POISON (no RTC,
// jumps backward, CONTRACT §2.2); episode time is ALWAYS the fob wallclock, durations the monotonic
// clock.
class Clock {
public:
  virtual ~Clock() = default;
  // Whole seconds since the Unix epoch (the authoritative episode time source).
  virtual std::int64_t unix_seconds() = 0;
  // Fractional seconds since the epoch (sub-second start targets); may equal unix_seconds().
  virtual double unix_seconds_frac() = 0;
  // Monotonic milliseconds since boot (immune to wallclock jumps) — skew/duration math only.
  virtual std::uint64_t monotonic_millis() = 0;
};

// Random bytes for the UUIDv4 episode_id (transport feeds the ESP32 hardware RNG).
class Rng {
public:
  virtual ~Rng() = default;
  // Fill `out` with `n` random bytes.
  virtual void fill(std::uint8_t *out, std::size_t n) = 0;
};

// Durable key/value store (NAND/NVS on the ESP32; a file/memory fake off-target). The ordinal MUST
// be persisted here BEFORE the in-RAM counter advances (SPEC §1.8: a crash/swap can't lose OR reuse
// a number).
class PersistentStore {
public:
  virtual ~PersistentStore() = default;
  // Read an integer; returns `fallback` if absent/unparseable.
  virtual std::int64_t read_i64(const std::string &key, std::int64_t fallback) = 0;
  // Persist an integer durably; returns true only once the write has reached stable storage.
  virtual bool write_i64(const std::string &key, std::int64_t value) = 0;
};

// L2 camera presence — the AP DHCP/station table (esp_netif_get_sta_list), NEVER OSC polling
// (HARD RULE 1, CONTRACT §1.3). This is the ONLY source of "which cameras are connected."
class PresenceSource {
public:
  virtual ~PresenceSource() = default;
  // The capture-device handles currently associated at L2 (e.g. {"left","right"}).
  virtual std::vector<std::string> present() = 0;
};

// Opportunistic god's-view uplink, drained only in the idle gap (single-radio constraint, §1.4).
// Optional: null in F1; provided by transport in F2.
class TelemetrySink {
public:
  virtual ~TelemetrySink() = default;
  // Best-effort send of one god's-view event line (idle-gap only; failures are non-fatal).
  virtual void send(const std::string &event_json) = 0;
};

} // namespace eunomia::core

#endif // EUNOMIA_COORDINATOR_CORE_SEAMS_H
