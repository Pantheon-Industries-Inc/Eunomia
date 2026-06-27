// firmware/coordinator/transport/hw/ — the NVS-backed PersistentStore + identity load (on-target).
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_HW_NVS_STORE_H
#define EUNOMIA_COORDINATOR_TRANSPORT_HW_NVS_STORE_H

#include <Arduino.h>
#include <Preferences.h>

#include "seams.h"            // PersistentStore
#include "sidecar_assembly.h" // Assignment

namespace eunomia::transport {

// Our firmware build string for the sidecar's fob_build (distinct from Victor's FOB_FW_VERSION;
// this is the Eunomia coordinator, adapting his stack).
inline constexpr const char *kFobBuild = "eunomia-coordinator-f7";

// PersistentStore over the ESP32 Preferences/NVS (Victor's "pantheon-fob" namespace). Maps core's
// long logical keys to ≤15-char NVS keys (nvs_key_for) — see the 15-char-limit finding. Also loads
// the depot-provisioned identity into core's Assignment, and holds the serial allowlist (Victor's
// "allow", ship-gate/isolation) + the MAC→side binding (our L2 presence map, populated by
// lockcams).
class NvsStore : public eunomia::core::PersistentStore {
public:
  void begin(); // open the NVS namespace (call once in setup)

  std::int64_t read_i64(const std::string &key, std::int64_t fallback) override;
  bool write_i64(const std::string &key, std::int64_t value) override;

  // The depot-provisioned per-shift identity/task context (operator_id ⊥ kit_id — §3.3).
  eunomia::core::Assignment load_assignment();

  String cam_pass();  // the SoftAP PSK (≥8 => WPA2, else OPEN); depot-provisioned ("cpass")
  String allow_csv(); // serial allowlist (Victor's cross-talk isolation / ship-gate)
  void set_allow_csv(const String &); // persisted by lockcams (serials via /osc/info)
  String sides_csv(); // MAC→side CSV: macL,macR (entry 0=left,1=right) — L2 presence
  void set_sides_csv(const String &); // persisted by lockcams (MACs from the station snapshot)

  // F7 boot-uplink: the site WiFi credentials + the dashboard base URL for the task-config fetch.
  // Provisioned via serial (`wssid=...; wpass=...; upurl=...`) or the provisioning console (P1).
  String uplink_ssid();
  String uplink_pass();
  String uplink_url();

private:
  Preferences prefs_;
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_HW_NVS_STORE_H
