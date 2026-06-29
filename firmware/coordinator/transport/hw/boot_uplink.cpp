#include "boot_uplink.h"

#include <Arduino.h>
#include <WiFi.h>
#include <cstdio>
#include <time.h>

namespace eunomia::transport {

namespace {
constexpr std::uint32_t kAssocTimeoutMs = 5000; // 5s — fast fail at boot (Victor uses 8s runtime)
constexpr std::uint32_t kNtpTimeoutMs = 4000;   // 4s — proven in Victor's wifiJoin
constexpr std::uint32_t kDhcpSettleMs = 350;    // DHCP/route settle (Victor's uplink value)
constexpr std::uint32_t kRadioSettleMs = 100;   // radio settle after mode switch
constexpr long kTimeSanityFloor = 1700000000L;  // 2023-11 (Victor's / EspClock's floor)

// PST8PDT — the shipped on-screen clock TZ (Victor's default). Server-driven per site later.
constexpr const char *kDefaultTz = "PST8PDT,M3.2.0,M11.1.0";
} // namespace

void BootUplink::configure(const std::string &ssid, const std::string &pass) {
  ssid_ = ssid;
  pass_ = pass;
}

bool BootUplink::sta_associate() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  // Public DNS for .ts.net / Tailscale Funnel resolution (Victor's forUplink path).
  WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE, IPAddress(8, 8, 8, 8), IPAddress(1, 1, 1, 1));
  delay(60);
  WiFi.begin(ssid_.c_str(), pass_.c_str());
  const std::uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - t0) < kAssocTimeoutMs) {
    delay(200);
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("[boot-uplink] association failed (status=%d, %lums)\n",
                  static_cast<int>(WiFi.status()), static_cast<unsigned long>(millis() - t0));
    return false;
  }
  delay(kDhcpSettleMs);
  Serial.printf("[boot-uplink] associated ssid=%s ip=%s rssi=%ld ch=%d\n", ssid_.c_str(),
                WiFi.localIP().toString().c_str(), static_cast<long>(WiFi.RSSI()), WiFi.channel());
  return true;
}

bool BootUplink::ntp_sync() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  const std::uint32_t t0 = millis();
  while (time(nullptr) < kTimeSanityFloor && (millis() - t0) < kNtpTimeoutMs) {
    delay(100);
  }
  if (time(nullptr) < kTimeSanityFloor) {
    Serial.printf("[boot-uplink] NTP timeout (%lums)\n", static_cast<unsigned long>(millis() - t0));
    return false;
  }
  // configTime() clobbers the TZ env var — set the display TZ AFTER (the gmtime_r timestamps and
  // unix_seconds are unaffected; only localtime_r display changes).
  setenv("TZ", kDefaultTz, 1);
  tzset();
  Serial.println("[boot-uplink] NTP synced");
  return true;
}

void BootUplink::sta_teardown() {
  WiFi.disconnect(true); // erase stored STA creds from flash
  WiFi.mode(WIFI_OFF);
  delay(kRadioSettleMs);
}

BootUplinkResult BootUplink::run() {
  result_ = BootUplinkResult();
  if (ssid_.empty()) {
    Serial.println("[boot-uplink] skipped (no wssid configured)");
    return result_;
  }
  result_.attempted = true;
  Serial.printf("[boot-uplink] connecting to '%s'...\n", ssid_.c_str());

  // Phase 1: STA association
  if (!sta_associate()) {
    sta_teardown();
    return result_;
  }
  result_.associated = true;

  // Phase 2: NTP sync (best-effort — a miss is harmless, clock stays loud-not-silent)
  result_.ntp_synced = ntp_sync();

  // Phase 3: tear down STA so the SoftAP can start on a clean radio
  sta_teardown();
  return result_;
}

} // namespace eunomia::transport
