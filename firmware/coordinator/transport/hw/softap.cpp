#include "softap.h"

#include <WiFi.h>
#include <cstdio>
#include <cstring>
#include <esp_netif.h>
#include <esp_wifi.h>

namespace eunomia::transport {

namespace {
constexpr std::uint8_t kApChannelDefault = 6;
constexpr std::uint16_t kApInactiveSec = 65535; // ~18h — effectively never idle-deauth a station
constexpr std::uint8_t kApMaxStations = 4;      // left+right + headroom
constexpr int kSubnetScanMax = 6;
} // namespace

String fob_hw_id() {
  std::uint64_t mac = ESP.getEfuseMac();
  char buf[16];
  std::snprintf(buf, sizeof(buf), "fob_%06x", static_cast<unsigned>(mac & 0xFFFFFFu));
  return String(buf);
}

String SoftAp::ssid() const {
  if (kit_id_.length()) {
    return "PANTHEON-" + kit_id_;
  }
  return "PANTHEON-" + fob_hw_id();
}

std::uint8_t SoftAp::channel() const {
  // 2.4GHz non-overlapping channels are 1/6/11, BUT ch11 is DROPPED (2026-06-24, kit_56): the ESP32
  // SoftAP reports up on ch11 yet no client can associate. The n%3==2 slot maps to ch6 instead of
  // 11 until root-caused. kit_57->ch1, kit_55->ch6 unchanged. (Victor f96b97a.)
  const std::uint8_t chans[3] = {1, 6, 6};
  long n = -1;
  const int us = kit_id_.lastIndexOf('_');
  String tail = (us >= 0) ? kit_id_.substring(us + 1) : kit_id_;
  if (tail.length()) {
    char *end = nullptr;
    const long v = strtol(tail.c_str(), &end, 10);
    if (end && *end == '\0') {
      n = v;
    }
  }
  if (n < 0) {
    return kApChannelDefault;
  }
  return chans[static_cast<std::uint8_t>(n % 3)];
}

void SoftAp::tune_driver() {
  const wifi_interface_t ap_if =
#ifdef WIFI_IF_AP
      WIFI_IF_AP;
#else
      static_cast<wifi_interface_t>(ESP_IF_WIFI_AP);
#endif
  esp_wifi_set_ps(WIFI_PS_NONE); // #1 cause of SoftAP client deauth loops
  esp_wifi_set_inactive_time(ap_if, kApInactiveSec);
  wifi_config_t ap_cfg;
  std::memset(&ap_cfg, 0, sizeof(ap_cfg));
  if (esp_wifi_get_config(ap_if, &ap_cfg) == ESP_OK) {
    ap_cfg.ap.max_connection = kApMaxStations;
    esp_wifi_set_config(ap_if, &ap_cfg);
  }
}

bool SoftAp::ensure_up() {
  const bool healthy = ap_up_ && (static_cast<int>(WiFi.getMode()) & static_cast<int>(WIFI_AP)) &&
                       (static_cast<std::uint32_t>(WiFi.softAPIP()) != 0);
  if (healthy) {
    return true;
  }
  WiFi.persistent(false);
  WiFi.mode(WIFI_AP);
  IPAddress ap_ip;
  IPAddress ap_mask;
  if (!ap_ip.fromString(subnet_ + ".1")) {
    ap_ip.fromString("192.168.42.1");
  }
  ap_mask.fromString("255.255.255.0");
  WiFi.softAPConfig(ap_ip, ap_ip, ap_mask); // gateway == AP ip; DHCP serves .2-.6
  const String s = ssid();
  const std::uint8_t ch = channel();
  bool ok;
  if (cam_pass_.length() >= 8) {
    ok = WiFi.softAP(s.c_str(), cam_pass_.c_str(), ch, /*ssid_hidden=*/0, kApMaxStations);
  } else {
    // OPEN AP fallback when no PSK is provisioned (the proven rig ran open; depot may set
    // cam_pass).
    ok = WiFi.softAP(s.c_str(), nullptr, ch, /*ssid_hidden=*/0, kApMaxStations);
  }
  WiFi.setSleep(false); // AP host: never idle-sleep the radio
  tune_driver();
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  ap_up_ = ok;
  return ok;
}

std::uint8_t SoftAp::station_count() { return WiFi.softAPgetStationNum(); }

std::vector<StationEntry> SoftAp::station_snapshot() {
  std::vector<StationEntry> out;
  wifi_sta_list_t wl;
  esp_netif_sta_list_t nl;
  if (esp_wifi_ap_get_sta_list(&wl) != ESP_OK || esp_netif_get_sta_list(&wl, &nl) != ESP_OK) {
    return out;
  }
  for (int s = 0; s < nl.num && static_cast<int>(out.size()) < kSubnetScanMax; ++s) {
    StationEntry e;
    char macbuf[18];
    const std::uint8_t *m = nl.sta[s].mac;
    std::snprintf(macbuf, sizeof(macbuf), "%02x:%02x:%02x:%02x:%02x:%02x", m[0], m[1], m[2], m[3],
                  m[4], m[5]);
    e.mac = macbuf;
    const std::uint32_t ip = nl.sta[s].ip.addr; // lwip network byte order
    if (ip != 0) {                              // associated but no lease yet => leave ip empty
      char ipbuf[16];
      std::snprintf(ipbuf, sizeof(ipbuf), "%u.%u.%u.%u", static_cast<unsigned>(ip & 0xFF),
                    static_cast<unsigned>((ip >> 8) & 0xFF),
                    static_cast<unsigned>((ip >> 16) & 0xFF),
                    static_cast<unsigned>((ip >> 24) & 0xFF));
      e.ip = ipbuf;
    }
    out.push_back(e);
  }
  return out;
}

} // namespace eunomia::transport
