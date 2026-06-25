// firmware/coordinator/transport/hw/ — the fob SoftAP host + L2 station snapshot (on-target only).
//
// Adapted from Victor's apEnsureUp/apSsid/apChannel/apTuneDriver + discoverCams. The fob hosts
// PANTHEON-kit_<n> (192.168.42.1, DHCP .2–.6); cameras join as STAs (the join is camera-side +
// Victor's, untouched). station_snapshot() is the L2-ONLY presence source (HARD RULE 1) feeding the
// CameraRegistry — never an OSC poll.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_HW_SOFTAP_H
#define EUNOMIA_COORDINATOR_TRANSPORT_HW_SOFTAP_H

#include <Arduino.h>

#include <cstdint>
#include <vector>

#include "presence.h" // StationEntry

namespace eunomia::transport {

// Stable per-DEVICE id from the ESP32 efuse MAC (survives reboots) — the sidecar's fob_id (Victor's
// fobHwId). Shared by the SoftAP SSID fallback + NvsStore::load_assignment.
String fob_hw_id();

class SoftAp {
public:
  // Provisioned identity (from NVS): kit_id picks the SSID + channel; cam_pass (≥8) => WPA2, else
  // OPEN.
  void configure(const String &kit_id, const String &cam_pass, const String &subnet) {
    kit_id_ = kit_id;
    cam_pass_ = cam_pass;
    if (subnet.length()) {
      subnet_ = subnet;
    }
  }

  String ssid() const;          // PANTHEON-<kit> (per-kit unique so rigs never cross-join)
  std::uint8_t channel() const; // {1,6,6} spread by trailing kit number (ch11 dropped — see .cpp)
  bool ensure_up();             // idempotent SoftAP bring-up + driver tuning (apEnsureUp)
  std::uint8_t station_count(); // associated STA count (WiFi.softAPgetStationNum)

  // The L2 station table (MAC + leased IP) — the ONLY presence source. No OSC.
  std::vector<StationEntry> station_snapshot();

private:
  void tune_driver(); // esp_wifi power-save off + inactivity + max_connection (apTuneDriver)
  String kit_id_;
  String cam_pass_;
  String subnet_ = "192.168.42";
  bool ap_up_ = false;
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_HW_SOFTAP_H
