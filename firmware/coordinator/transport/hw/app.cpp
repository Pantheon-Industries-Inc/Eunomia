#include "app.h"

#include <Arduino.h>
#include <cstdio>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <vector>

#include "clock_rng.h"
#include "conn.h"
#include "coordinator.h"
#include "nvs_store.h"
#include "presence.h"
#include "provisioning_rx.h"
#include "sidecar_assembly.h"
#include "softap.h"
#include "uplink.h"
#include "wifi_conn.h"
#include "x3_capture_device.h"
#include "x3_protocol.h"

#ifndef PANTHEON_PIN_BUTTON
#define PANTHEON_PIN_BUTTON 0 // BOOT button on most ESP32 dev boards / the CYD
#endif

namespace eunomia::transport {

using eunomia::core::Assignment;
using eunomia::core::Coordinator;
using eunomia::core::project_assignment_env;
using eunomia::core::project_stop_env;
using eunomia::core::State;

namespace {

// ---- the app's EnvProvider (OQ-1 option A): project the core-owned env from the LIVE take ----
class AppEnvProvider : public EnvProvider {
public:
  explicit AppEnvProvider(const Assignment &a) : a_(a) {}
  void bind(const Coordinator *c) { c_ = c; }
  std::string assignment_env() override {
    return c_ ? project_assignment_env(a_, c_->take()) : std::string();
  }
  std::string stop_env() override { return c_ ? project_stop_env(c_->take()) : std::string(); }

private:
  const Assignment &a_;
  const Coordinator *c_ = nullptr;
};

// ---- the seam instances (file-scope; the headless fob's whole state) ----
EspClock g_clock;
EspRng g_rng;
NvsStore g_store;
SoftAp g_softap;
CameraRegistry g_registry;
StationTablePresence g_presence(g_registry);
DisabledUplink g_uplink;
WifiConn g_conn_left, g_conn_right, g_conn_lock;
ArduinoDelayer g_delayer;
Assignment g_assignment;
AppEnvProvider g_env(g_assignment);
X3CaptureDevice g_left("left", g_registry, g_conn_left, g_delayer, g_env);
X3CaptureDevice g_right("right", g_registry, g_conn_right, g_delayer, g_env);
ProvisioningReceiver g_prov_rx;

// The Coordinator is constructed in app_setup() AFTER g_store.begin() so the DurableOrdinal reads
// the real NVS value (a global ctor would run before Arduino/NVS init and read a stale 0).
Coordinator *g_coord = nullptr;
SemaphoreHandle_t g_wifi_lock = nullptr;
const std::vector<std::string> kFleetSides = {"left", "right"};

void lock_wifi() {
  if (g_wifi_lock) {
    xSemaphoreTake(g_wifi_lock, portMAX_DELAY);
  }
}
void unlock_wifi() {
  if (g_wifi_lock) {
    xSemaphoreGive(g_wifi_lock);
  }
}

void reload_assignment() {
  g_assignment = g_store.load_assignment();
  if (g_coord) {
    g_coord->set_assignment(g_assignment);
  }
}

// GRABAR/DETENER toggle. The OSC/telnet burst is serialized under g_wifi_lock (HARD RULE 1) and is
// fast because every OSC is fire-and-forget. start() fires startCapture DIRECTLY (HARD RULE 2).
void toggle_record() {
  if (!g_coord) {
    return;
  }
  if (g_coord->state() == State::Idle) {
    lock_wifi();
    g_coord->mint_episode_id();
    const bool ok = g_coord->trigger(kFleetSides); // present-gated; fires the present sides only
    unlock_wifi();
    Serial.printf("[trigger] START ok=%d ordinal=%lld sent=%u\n", ok ? 1 : 0,
                  static_cast<long long>(g_coord->take().episode_ordinal),
                  static_cast<unsigned>(g_coord->last_sent()));
  } else if (g_coord->state() == State::Recording) {
    lock_wifi();
    g_coord->stop(
        "operator"); // fires both stops, recovers clips, sets recording_suspect on absence
    eunomia::Sidecar rec;
    rec.archive = g_coord->take().archive; // 0 normally; DESCARTAR (mark_archive) would set 1
    for (const auto &side : kFleetSides) {
      g_coord->write_sidecar(side, rec); // push current_stop.env per side (option C)
    }
    unlock_wifi();
    Serial.println("[trigger] STOP (stop-env pushed)");
  }
}

// Depot binding (`cmd=lockcams`): snapshot present stations (MAC+IP, discovery order), learn each
// serial via a ONE-SHOT /osc/info (Victor's f96b97a fix — depot, idle, serialized; NOT background
// OSC), then persist BOTH the MAC→side map (our L2 presence binding — OQ-2 B) and the serial
// allowlist (Victor's cross-talk isolation / ship-gate). Refuses a partial list.
void lockcams() {
  lock_wifi();
  std::vector<StationEntry> stations = g_softap.station_snapshot();
  std::vector<std::string> macs;
  std::vector<std::string> serials;
  for (const auto &st : stations) {
    if (st.ip.empty()) {
      continue; // no lease — not a real present cam
    }
    std::string serial;
    for (int tries = 0; serial.empty() && tries < 2; ++tries) {
      osc_info(g_conn_lock, g_delayer, st.ip, serial);
    }
    if (serial.empty()) {
      continue; // could not learn the serial — skip (refuse a partial list below)
    }
    macs.push_back(st.mac);
    serials.push_back(serial);
    if (macs.size() >= 2) {
      break; // left + right
    }
  }
  unlock_wifi();
  if (macs.size() < 2) {
    Serial.printf("[allow] lockcams: only %u cam(s) with a serial - refusing\n",
                  static_cast<unsigned>(macs.size()));
    return;
  }
  const String sides_csv = String(macs[0].c_str()) + "," + String(macs[1].c_str());
  const String allow_csv = String(serials[0].c_str()) + "," + String(serials[1].c_str());
  g_store.set_sides_csv(sides_csv);
  g_store.set_allow_csv(allow_csv);
  g_registry.set_map(MacSideMap::from_allowlist(std::string(sides_csv.c_str())));
  Serial.printf("[allow] lockcams: sides=%s allow_n=2\n", sides_csv.c_str());
}

void print_status() {
  Serial.printf(
      "{\"kit_id\":\"%s\",\"operator_id\":\"%s\",\"station\":\"%s\",\"cams\":%u,"
      "\"ordinal\":%lld,\"time_set\":%s,\"ap_ssid\":\"%s\",\"ap_ch\":%u,\"sides\":\"%s\"}\n",
      g_assignment.kit_id.c_str(), g_assignment.operator_id.c_str(),
      g_assignment.station_id.c_str(), static_cast<unsigned>(g_registry.present().size()),
      g_coord ? static_cast<long long>(g_coord->ordinal_log().size()) : 0,
      g_clock.time_set() ? "true" : "false", g_softap.ssid().c_str(),
      static_cast<unsigned>(g_softap.channel()), g_store.sides_csv().c_str());
}

void apply_kv(const String &key, const String &val) {
  if (key == "cmd") {
    if (val == "shutter") {
      toggle_record();
    } else if (val == "lockcams") {
      lockcams();
    } else if (val == "status") {
      print_status();
    }
  } else if (key == "time") {
    g_clock.set_unix_time(static_cast<std::uint32_t>(strtoul(val.c_str(), nullptr, 10)));
  } else if (key == "kit" || key == "op" || key == "station" || key == "prompt" || key == "site") {
    const char *nvs = (key == "op") ? "op" : key.c_str();
    Preferences p;
    p.begin("pantheon-fob", false);
    p.putString(nvs, val);
    p.end();
    reload_assignment();
  }
}

void poll_serial() {
  static String buf;
  while (Serial.available()) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      String line = buf;
      buf = "";
      line.trim();
      int start = 0;
      while (start < static_cast<int>(line.length())) {
        int semi = line.indexOf(';', start);
        if (semi < 0) {
          semi = line.length();
        }
        String pair = line.substring(start, semi);
        const int eq = pair.indexOf('=');
        if (eq > 0) {
          String k = pair.substring(0, eq);
          String v = pair.substring(eq + 1);
          k.trim();
          v.trim();
          apply_kv(k, v);
        }
        start = semi + 1;
      }
    } else {
      buf += c;
      if (buf.length() > 256) {
        buf = "";
      }
    }
  }
}

// BOOT-button short-press = GRABAR/DETENER (the headless input until ui/ lands in F3).
void poll_button() {
  static int last = HIGH;
  static std::uint32_t press_ms = 0;
  static std::uint32_t last_edge = 0;
  const std::uint32_t now = millis();
  const int cur = digitalRead(PANTHEON_PIN_BUTTON);
  if (cur != last && (now - last_edge) > 30) { // 30 ms debounce
    last_edge = now;
    if (cur == LOW) {
      press_ms = now;
    } else if (now - press_ms <= 800) { // short press
      toggle_record();
    }
    last = cur;
  }
}

void discovery_task(void *) {
  for (;;) {
    // Refresh L2 presence only between takes — never churn the radio mid-burst (Victor's
    // discoveryTask skip-while-recording). The trigger burst holds g_wifi_lock; this would
    // otherwise block on it.
    if (g_coord && g_coord->state() == State::Idle) {
      lock_wifi();
      g_softap.ensure_up();
      g_registry.update(g_softap.station_snapshot());
      g_prov_rx.poll(); // gated (OQ-8) — no-op unless PANTHEON_SD_DAEMON_RX
      unlock_wifi();
    }
    vTaskDelay(pdMS_TO_TICKS(700));
  }
}

char *fob_session_hex(char *buf8) { // 8 hex chars + NUL (Victor's makeFobSession)
  std::snprintf(buf8, 9, "%08x", static_cast<unsigned>(esp_random()));
  return buf8;
}

} // namespace

void app_setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.println("Eunomia coordinator (transport, headless) starting");

  g_wifi_lock = xSemaphoreCreateMutex();
  pinMode(PANTHEON_PIN_BUTTON, INPUT_PULLUP);

  g_store.begin();
  reload_assignment(); // load identity BEFORE constructing the coordinator (sets g_assignment)

  // Construct the Coordinator now that NVS is open (DurableOrdinal reads the real persisted
  // ordinal). Named Deps/Fleet so the derived→base seam pointers convert unambiguously.
  Coordinator::Deps deps;
  deps.clock = &g_clock;
  deps.rng = &g_rng;
  deps.store = &g_store;
  deps.presence = &g_presence;
  deps.telemetry = &g_uplink;
  Coordinator::Fleet fleet = {{"left", &g_left}, {"right", &g_right}};
  static Coordinator coord(deps, fleet, 2);
  g_coord = &coord;
  g_env.bind(&coord);
  coord.set_assignment(g_assignment);
  char sess[9];
  coord.set_fob_session_id(fob_session_hex(sess)); // per-boot fob-swap disambiguator (OQ-7)

  // SoftAP + the depot-provisioned MAC→side map (lockcams populates `sides`).
  g_softap.configure(String(g_assignment.kit_id.c_str()), g_store.cam_pass(), String("192.168.42"));
  g_softap.ensure_up();
  g_registry.set_map(MacSideMap::from_allowlist(std::string(g_store.sides_csv().c_str())));
  g_prov_rx.begin(); // gated (OQ-8)

  // The core-0 discovery worker (UI/input stays on core 1 — the dedicated-core split).
  xTaskCreatePinnedToCore(discovery_task, "disc", 8192, nullptr, 1, nullptr, 0);
  Serial.printf("[boot] kit=%s ssid=%s ch=%u sides=%s\n", g_assignment.kit_id.c_str(),
                g_softap.ssid().c_str(), static_cast<unsigned>(g_softap.channel()),
                g_store.sides_csv().c_str());
}

void app_loop() {
  poll_serial();
  poll_button();
  delay(8); // ~125 Hz input poll; OSC/telnet run on this core but are fire-and-forget (fast)
}

} // namespace eunomia::transport
