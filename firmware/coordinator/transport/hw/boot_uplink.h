// firmware/coordinator/transport/hw/ — the boot-time STA uplink (F7).
//
// Runs ONCE at boot, BEFORE the SoftAP comes up. Connects to the site WiFi (STA mode), pulls NTP
// time, fetches the station task-config from the dashboard, then tears down STA so the SoftAP can
// start. Sequential STA→AP (not coexistent) — at boot no cameras are connected, so there's no AP
// to tear down and no STA+AP channel-lock problem.
//
// Graceful fallback: if wssid is empty, or association fails, or NTP fails, or fetch fails — each
// stage is skipped and the AP comes up regardless. Collection NEVER halts.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_HW_BOOT_UPLINK_H
#define EUNOMIA_COORDINATOR_TRANSPORT_HW_BOOT_UPLINK_H

#include <cstdint>
#include <string>

namespace eunomia::transport {

struct BootUplinkResult {
  bool attempted = false;       // true if wssid was non-empty (STA phase ran)
  bool associated = false;      // site WiFi association succeeded
  bool ntp_synced = false;      // NTP time set (time(nullptr) > 1700000000)
  bool config_fetched = false;  // task-config HTTP GET returned 200
  std::string task_config_body; // raw response body (empty on skip/failure)
};

// Boot-time STA→NTP→fetch→teardown. NOT a TelemetrySink — this is an initialization module,
// not a continuous uplink. Called from app_setup() between Coordinator construction and SoftAP.
class BootUplink {
public:
  void configure(const std::string &ssid, const std::string &pass, const std::string &base_url,
                 const std::string &kit_id);
  BootUplinkResult run();
  const BootUplinkResult &result() const { return result_; }
  const std::string &task_config_response() const { return result_.task_config_body; }

private:
  bool sta_associate();
  bool ntp_sync();
  void sta_teardown();

  std::string ssid_;
  std::string pass_;
  std::string base_url_;
  std::string kit_id_;
  BootUplinkResult result_;
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_HW_BOOT_UPLINK_H
