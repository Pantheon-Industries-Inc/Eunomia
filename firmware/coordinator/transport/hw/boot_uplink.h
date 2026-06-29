// firmware/coordinator/transport/hw/ — the boot-time STA uplink (F7).
//
// Runs ONCE at boot, BEFORE the SoftAP comes up. Connects to the site WiFi (STA mode), syncs NTP
// time, then tears down STA so the SoftAP can start. Sequential STA→AP (not coexistent) — at boot
// no cameras are connected, so there's no AP to tear down and no STA+AP channel-lock problem.
//
// Graceful fallback: if wssid is empty, or association fails, or NTP fails — each stage is skipped
// and the AP comes up regardless. Collection NEVER halts.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_HW_BOOT_UPLINK_H
#define EUNOMIA_COORDINATOR_TRANSPORT_HW_BOOT_UPLINK_H

#include <cstdint>
#include <string>

namespace eunomia::transport {

struct BootUplinkResult {
  bool attempted = false;  // true if wssid was non-empty (STA phase ran)
  bool associated = false; // site WiFi association succeeded
  bool ntp_synced = false; // NTP time set (time(nullptr) > 1700000000)
};

// Boot-time STA→NTP→teardown. NOT a TelemetrySink — this is an initialization module,
// not a continuous uplink. Called from app_setup() between Coordinator construction and SoftAP.
class BootUplink {
public:
  void configure(const std::string &ssid, const std::string &pass);
  BootUplinkResult run();
  const BootUplinkResult &result() const { return result_; }

private:
  bool sta_associate();
  bool ntp_sync();
  void sta_teardown();

  std::string ssid_;
  std::string pass_;
  BootUplinkResult result_;
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_HW_BOOT_UPLINK_H
