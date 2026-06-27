#include "radio_borrow.h"

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <cstdint>
#include <ctime>

#include "softap.h"

namespace eunomia::transport {

namespace {
constexpr std::uint32_t kAssocTimeoutMs = 5000;
constexpr std::uint32_t kNtpTimeoutMs = 1000; // brief best-effort (not the 4s boot timeout)
constexpr std::uint32_t kPostTimeoutMs = 3000;
constexpr long kTimeSanityFloor = 1700000000L;
} // namespace

void RadioBorrow::configure(const Config &cfg) { cfg_ = cfg; }

bool RadioBorrow::sta_associate() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  IPAddress dns1(8, 8, 8, 8);
  IPAddress dns2(1, 1, 1, 1);
  WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE, dns1, dns2);
  delay(60);
  WiFi.begin(cfg_.wssid.c_str(), cfg_.wpass.c_str());
  const std::uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < kAssocTimeoutMs) {
    delay(200);
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[radio-borrow] STA timeout");
    return false;
  }
  delay(350); // DHCP settle
  Serial.printf("[radio-borrow] STA ok rssi=%d ch=%d\n", WiFi.RSSI(),
                static_cast<int>(WiFi.channel()));
  return true;
}

bool RadioBorrow::ntp_sync_brief() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  const std::uint32_t start = millis();
  while (time(nullptr) < kTimeSanityFloor && millis() - start < kNtpTimeoutMs) {
    delay(100);
  }
  if (time(nullptr) >= kTimeSanityFloor) {
    setenv("TZ", "PST8PDT,M3.2.0,M11.1.0", 1);
    tzset();
    Serial.println("[radio-borrow] NTP ok (opportunistic)");
    return true;
  }
  Serial.println("[radio-borrow] NTP miss (best-effort, continuing)");
  return false;
}

bool RadioBorrow::http_post(const std::string &url, const std::string &json_body) {
  HTTPClient http;
  http.setTimeout(kPostTimeoutMs);
  if (!http.begin(url.c_str())) {
    Serial.println("[radio-borrow] HTTP begin failed");
    return false;
  }
  http.addHeader("Content-Type", "application/json");
  const int code = http.POST(reinterpret_cast<uint8_t *>(const_cast<char *>(json_body.data())),
                             json_body.size());
  http.end();
  Serial.printf("[radio-borrow] POST %s → %d\n", url.c_str(), code);
  return code >= 200 && code < 300;
}

void RadioBorrow::sta_teardown() {
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  delay(100);
}

RadioBorrowResult RadioBorrow::borrow_and_post(SoftAp &ap, const std::string &endpoint_path,
                                               const std::string &json_body) {
  RadioBorrowResult r;

  if (cfg_.wssid.empty() || cfg_.base_url.empty()) {
    Serial.println("[radio-borrow] no uplink configured — skip");
    r.ap_restored = true;
    return r;
  }

  r.attempted = true;

  // Phase 1: teardown AP (cameras drop)
  WiFi.mode(WIFI_OFF);
  delay(100);

  // Phase 2: STA associate
  r.associated = sta_associate();
  if (!r.associated) {
    sta_teardown();
    ap.ensure_up();
    r.ap_restored = true;
    return r;
  }

  // Phase 3: opportunistic NTP (1s best-effort)
  r.ntp_synced = ntp_sync_brief();

  // Phase 4: HTTP POST
  const std::string url = cfg_.base_url + endpoint_path;
  r.posted = http_post(url, json_body);

  // Phase 5: STA teardown (unconditional)
  sta_teardown();

  // Phase 6: AP restore (unconditional — the critical safety invariant)
  ap.ensure_up();
  r.ap_restored = true;
  Serial.printf("[radio-borrow] done posted=%d ap_restored=%d\n", r.posted ? 1 : 0,
                r.ap_restored ? 1 : 0);
  return r;
}

} // namespace eunomia::transport
