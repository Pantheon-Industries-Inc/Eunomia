// firmware/coordinator/transport/hw/ — the LLAMAR radio-borrow lifecycle (F8).
//
// Tears down the SoftAP → joins site WiFi (STA) → optionally syncs NTP → POSTs a notification →
// tears down STA → restores the AP. INVARIANT: the AP is ALWAYS restored on exit
// (finally-semantics), even on STA association or POST failure. Cameras drop during the borrow
// (~15–29s reconnect) — acceptable because LLAMAR is only available when stopped/idle.
//
// Not on BootUplink: BootUplink runs BEFORE the AP exists (no teardown/restore); LLAMAR runs WHILE
// the AP is hosting cameras. Different lifecycle, different error semantics.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_HW_RADIO_BORROW_H
#define EUNOMIA_COORDINATOR_TRANSPORT_HW_RADIO_BORROW_H

#include <string>

namespace eunomia::transport {

class SoftAp; // forward — the AP we teardown and restore

struct RadioBorrowResult {
  bool attempted = false;
  bool associated = false;
  bool ntp_synced = false;
  bool posted = false;
  bool ap_restored = false;
};

class RadioBorrow {
public:
  struct Config {
    std::string wssid;
    std::string wpass;
    std::string base_url;
    std::string kit_id;
  };

  void configure(const Config &cfg);

  // Execute the full borrow. Caller MUST hold g_wifi_lock for the entire call.
  // ap.ensure_up() is called unconditionally before return.
  RadioBorrowResult borrow_and_post(SoftAp &ap, const std::string &endpoint_path,
                                    const std::string &json_body);

private:
  bool sta_associate();
  bool ntp_sync_brief();
  bool http_post(const std::string &url, const std::string &json_body);
  void sta_teardown();

  Config cfg_;
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_HW_RADIO_BORROW_H
