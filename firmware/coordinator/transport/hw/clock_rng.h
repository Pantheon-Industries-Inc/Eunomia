// firmware/coordinator/transport/hw/ — the ESP32 Clock + Rng seams (on-target only).
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_HW_CLOCK_RNG_H
#define EUNOMIA_COORDINATOR_TRANSPORT_HW_CLOCK_RNG_H

#include <Arduino.h>
#include <esp_system.h> // esp_random
#include <sys/time.h>
#include <time.h>

#include "seams.h"

namespace eunomia::transport {

// NTP/serial-set wallclock + the monotonic boot clock.
//
// ⚠ OQ-3 (consequential): the fob has NO battery-backed RTC, and NTP runs ONLY in Victor's
// uplink-borrow path — which is code-disabled (it drops every camera). So in the field the
// wallclock has NO live source unless a serial `time=<unix>` is sent at provision (the F2 stopgap),
// or a DS3231 RTC is fitted (the durable fix — Victor hardware coordination). LOUD-NOT-SILENT: when
// time is not set, unix_seconds() returns 0 (NOT a bogus value), so downstream flags no_wallclock /
// needs_review rather than recording footage under a wrong clock. The monotonic ms still rides
// every take for backfill once a sync lands.
class EspClock : public eunomia::core::Clock {
public:
  std::int64_t unix_seconds() override {
    const time_t now = time(nullptr);
    return time_valid(now) ? static_cast<std::int64_t>(now) : 0;
  }
  double unix_seconds_frac() override {
    struct timeval tv{};
    gettimeofday(&tv, nullptr);
    return time_valid(tv.tv_sec) ? static_cast<double>(tv.tv_sec) + tv.tv_usec / 1e6 : 0.0;
  }
  std::uint64_t monotonic_millis() override { return static_cast<std::uint64_t>(millis()); }

  // F2 stopgap (serial `time=`): set the system clock; without it the clock stays unset (above).
  void set_unix_time(std::uint32_t secs) {
    struct timeval tv{};
    tv.tv_sec = static_cast<time_t>(secs);
    settimeofday(&tv, nullptr);
  }
  bool time_set() { return time_valid(time(nullptr)); }

private:
  static bool time_valid(time_t t) {
    return t > 1700000000L;
  } // after 2023-11 (Victor's sanity floor)
};

// Hardware RNG for the UUIDv4 episode_id + the per-boot fob_session_id (Victor's makeFobSession
// path).
class EspRng : public eunomia::core::Rng {
public:
  void fill(std::uint8_t *out, std::size_t n) override {
    for (std::size_t i = 0; i < n;) {
      std::uint32_t r = esp_random();
      for (int b = 0; b < 4 && i < n; ++b, ++i) {
        out[i] = static_cast<std::uint8_t>(r >> (8 * b));
      }
    }
  }
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_HW_CLOCK_RNG_H
