#include "nvs_store.h"

#include "nvs_keys.h"
#include "softap.h" // fob_hw_id

namespace eunomia::transport {

void NvsStore::begin() { prefs_.begin(kNvsNamespace, /*readOnly=*/false); }

std::int64_t NvsStore::read_i64(const std::string &key, std::int64_t fallback) {
  return prefs_.getLong64(nvs_key_for(key).c_str(), fallback);
}

bool NvsStore::write_i64(const std::string &key, std::int64_t value) {
  // putLong64 returns the bytes written (0 on failure) — the durable-write contract the ordinal's
  // persist-before-advance relies on (a false return must NOT advance the in-RAM counter).
  return prefs_.putLong64(nvs_key_for(key).c_str(), value) > 0;
}

eunomia::core::Assignment NvsStore::load_assignment() {
  eunomia::core::Assignment a;
  a.kit_id = prefs_.getString("kit", "").c_str();         // ← FOB (decides canonical naming; §3.3)
  a.operator_id = prefs_.getString("op", "").c_str();     // ⊥ kit_id (operator-from-session; §3.3)
  a.station_id = prefs_.getString("station", "").c_str(); // operator-keyed table#
  a.prompt = prefs_.getString("prompt", "").c_str();
  a.task_name = a.prompt; // Victor maps TASK_NAME=prompt; task_id stays NAND-supplied
  a.site_id = prefs_.getString("site", "").c_str();
  a.fob_id = fob_hw_id().c_str();
  a.fob_build = kFobBuild;
  a.assignment_source = "fob_wifi";
  // operator sign-in (the operator-flow, F3) refines operator_id/session_id per shift; F2 carries
  // whatever the depot provisioned (operator_id may be empty until sign-in lands).
  return a;
}

String NvsStore::cam_pass() { return prefs_.getString("cpass", ""); }
String NvsStore::allow_csv() { return prefs_.getString("allow", ""); }
void NvsStore::set_allow_csv(const String &v) { prefs_.putString("allow", v); }
String NvsStore::sides_csv() { return prefs_.getString("sides", ""); }
void NvsStore::set_sides_csv(const String &v) { prefs_.putString("sides", v); }
String NvsStore::uplink_ssid() { return prefs_.getString("wssid", ""); }
String NvsStore::uplink_pass() { return prefs_.getString("wpass", ""); }
String NvsStore::uplink_url() { return prefs_.getString("upurl", ""); }

} // namespace eunomia::transport
