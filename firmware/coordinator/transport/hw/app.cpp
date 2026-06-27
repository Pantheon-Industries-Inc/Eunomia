#include "app.h"

#include <Arduino.h>
#include <LittleFS.h>
#include <WiFi.h>
#include <cstdio>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <string>
#include <time.h>
#include <vector>

#include "boot_uplink.h"
#include "clock_rng.h"
#include "conn.h"
#include "coordinator.h"
#include "episode_log.h"
#include "heap_health.h"
#include "nvs_store.h"
#include "presence.h"
#include "provisioning_rx.h"
#include "sidecar_assembly.h"
#include "softap.h"
#include "uplink.h"
#include "wifi_conn.h"
#include "x3_capture_device.h"
#include "x3_protocol.h"

#ifdef PANTHEON_HAS_TFT
#include "flow.h" // the ui/ composition (F3); behind the guard so the headless esp32 build excludes it
#endif

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
BootUplink g_boot_uplink;
LittleFsEpisodeLog g_episode_log; // the durable §1.7 ordinal-join backup (begin() after LittleFS)
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

// The live L2 present count, cached by the discovery task (the lock owner) for the lock-free UI
// read (Victor's g_connCount pattern). The UI loop (core 1) must NOT read the registry directly
// while the discovery worker (core 0) mutates it. Computed via Coordinator::present_count() (F3
// FLAG-C). Frozen during a take (discovery skips while recording), exactly as Victor's periodic
// refresh does.
volatile std::uint32_t g_present_cached = 0;

// F7: WiFi.onEvent discovery kick — on AP STA connect/disconnect, break the discovery task's sleep
// so presence updates within <1s instead of worst-case 700ms+700ms polling (Victor's onWiFiEvent).
volatile bool g_discovery_kick = false;

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
    // Low-heap watchdog (F5, by construction): refuse a START when the largest contiguous block is
    // below the floor — firing the OSC/WiFi mallocs into a fragmented heap is what strands the cams
    // at cams:0 (Victor's reactive finding). A loud refusal + power-cycle beats a silent wedge.
    // STOP is never gated (the Recording branch below always runs). Gates on largest_free_block,
    // not total free (the fragmentation predictor).
    const auto largest = static_cast<std::size_t>(ESP.getMaxAllocHeap());
    if (!eunomia::core::heap_ok(largest)) {
      Serial.printf(
          "[heap] LOW MEMORY (largest=%u floor=%u) - START refused; power-cycle the fob\n",
          static_cast<unsigned>(largest), static_cast<unsigned>(eunomia::core::kHeapFloorBytes));
      return;
    }
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
  // Heap health (F5): largest_free_block is the fragmentation predictor the watchdog gates on; free
  // is total; min is the low-water mark since boot. log_bytes is the durable ordinal-log size. The
  // `ordinal` field is now the TRUE durable counter (FLAG-D: it used to print the RAM log count,
  // which read 0 after every battery swap). Serial-only — network exposure rides F7 (no contract
  // change here).
  const auto &br = g_boot_uplink.result();
  Serial.printf("{\"kit_id\":\"%s\",\"operator_id\":\"%s\",\"station\":\"%s\",\"cams\":%u,"
                "\"ordinal\":%lld,\"time_set\":%s,\"ntp_synced\":%s,"
                "\"boot_uplink\":{\"attempted\":%s,\"associated\":%s,\"ntp\":%s,\"config\":%s},"
                "\"ap_ssid\":\"%s\",\"ap_ch\":%u,\"sides\":\"%s\","
                "\"free_heap\":%u,\"min_heap\":%u,\"largest_free_block\":%u,"
                "\"log_bytes\":%lu,\"fob_build\":\"%s\"}\n",
                g_assignment.kit_id.c_str(), g_assignment.operator_id.c_str(),
                g_assignment.station_id.c_str(), static_cast<unsigned>(g_registry.present().size()),
                g_coord ? static_cast<long long>(g_coord->current_ordinal()) : 0,
                g_clock.time_set() ? "true" : "false", br.ntp_synced ? "true" : "false",
                br.attempted ? "true" : "false", br.associated ? "true" : "false",
                br.ntp_synced ? "true" : "false", br.config_fetched ? "true" : "false",
                g_softap.ssid().c_str(), static_cast<unsigned>(g_softap.channel()),
                g_store.sides_csv().c_str(), static_cast<unsigned>(ESP.getFreeHeap()),
                static_cast<unsigned>(ESP.getMinFreeHeap()),
                static_cast<unsigned>(ESP.getMaxAllocHeap()),
                static_cast<unsigned long>(g_episode_log.bytes()), kFobBuild);
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
  } else if (key == "wssid" || key == "wpass" || key == "upurl") {
    Preferences p;
    p.begin("pantheon-fob", false);
    p.putString(key.c_str(), val);
    p.end();
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

#ifdef PANTHEON_HAS_TFT
// ---- the ui/ composition root (F3): UiHost over the coordinator + the wifi-locked operator
// actions. ui/ depends only on core + this seam; the wiring (transport knowing ui) lives HERE, at
// the root. ----
eunomia::ui::Flow *g_flow = nullptr;

std::string canonical_kit(const char *k) {
  std::string s = (k != nullptr) ? k : "";
  return s.rfind("kit_", 0) == 0 ? s : "kit_" + s;
}

void set_identity(const char *key, const String &val) {
  Preferences p;
  p.begin("pantheon-fob", false);
  p.putString(key, val);
  p.end();
  reload_assignment();
}

// DESCARTAR = void+keep: mark archive=1 and RE-PUSH current_stop.env so discardd routes it to
// archive (the take is already stopped + the archive=0 stop-env pushed by toggle_record's STOP
// branch).
void ui_discard_take() {
  if (g_coord == nullptr) {
    return;
  }
  lock_wifi();
  g_coord->mark_archive();
  eunomia::Sidecar rec;
  rec.archive = g_coord->take().archive; // now 1
  for (const auto &side : kFleetSides) {
    g_coord->write_sidecar(side, rec);
  }
  unlock_wifi();
  Serial.println("[ui] DESCARTAR (archive=1 re-pushed)");
}

class AppUiHost : public eunomia::ui::UiHost {
public:
  State core_state() override { return g_coord != nullptr ? g_coord->state() : State::Idle; }
  bool last_start_failed() override {
    // F6: the last trigger() rolled back (cams present but the fire didn't confirm, or the durable
    // commit failed). Drives the brief "START FALLO" notice so a rolled-back take reads as a
    // FAILURE, not a mis-press (loud-not-silent).
    return g_coord != nullptr && g_coord->last_outcome() == eunomia::core::GateOutcome::StartFailed;
  }
  std::size_t present_count() override { return g_present_cached; }
  std::size_t required_cameras() override { return 2; }
  const char *station() override { return g_assignment.station_id.c_str(); }
  const char *prompt() override { return g_assignment.prompt.c_str(); }
  const char *kit_id() override { return g_assignment.kit_id.c_str(); }
  bool kit_provisioned() override { return !g_assignment.kit_id.empty(); }
  bool time_set() override { return g_clock.time_set(); }
  const char *clock_hhmm() override {
    if (!g_clock.time_set()) {
      return nullptr;
    }
    time_t now = time(nullptr);
    struct tm t;
    localtime_r(&now, &t);
    static char buf[6];
    std::snprintf(buf, sizeof(buf), "%02d:%02d", t.tm_hour, t.tm_min);
    return buf;
  }
  void record_toggle() override { toggle_record(); }
  void save_take() override { Serial.println("[ui] GUARDAR (take kept; stop-env already pushed)"); }
  void discard_take() override { ui_discard_take(); }
  void set_kit(const char *k) override { set_identity("kit", String(canonical_kit(k).c_str())); }
  void sign_in(const char *op) override { set_identity("op", String(op)); }
  void select_table(const char *t) override {
    Preferences p;
    p.begin("pantheon-fob", false);
    p.putString("station", t);
    p.putString("prompt", String("Mesa ") + t + " | Table " + t);
    p.end();
    reload_assignment();
  }
  void call_lead() override {
    // KEEP the local help-event log; the dashboard "bell" POST is DEFERRED to the god's-view live
    // uplink (SPEC §1.10) — the radio-borrow POST path is code-disabled (DisabledUplink). (F3
    // FLAG-E.)
    Serial.printf("[ui] CALL LEAD (help logged: kit=%s station=%s; dashboard POST deferred)\n",
                  g_assignment.kit_id.c_str(), g_assignment.station_id.c_str());
  }
};
#endif // PANTHEON_HAS_TFT

// F7: kick discovery on AP STA connect/disconnect (Victor's onWiFiEvent). Registered in app_setup()
// after the SoftAP is up. The handler runs in the WiFi event task context — keep it minimal.
void on_wifi_event(WiFiEvent_t event, WiFiEventInfo_t) {
#if defined(ARDUINO_EVENT_WIFI_AP_STACONNECTED) && defined(ARDUINO_EVENT_WIFI_AP_STADISCONNECTED)
  if (event == ARDUINO_EVENT_WIFI_AP_STACONNECTED ||
      event == ARDUINO_EVENT_WIFI_AP_STADISCONNECTED) {
    g_discovery_kick = true;
  }
#else
  (void)event;
#endif
}

void discovery_task(void *) {
  for (;;) {
    // Refresh L2 presence only between takes — never churn the radio mid-burst (Victor's
    // discoveryTask skip-while-recording). The trigger burst holds g_wifi_lock; this would
    // otherwise block on it.
    if (g_coord && g_coord->state() == State::Idle) {
      const std::uint64_t staleness = (g_coord->state() == State::Recording)
                                          ? eunomia::transport::kStalenessRecordingMs
                                          : eunomia::transport::kStalenessIdleMs;
      g_registry.set_staleness_ms(staleness);
      lock_wifi();
      g_softap.ensure_up();
      g_registry.update(g_softap.station_snapshot(), static_cast<std::uint64_t>(millis()));
      g_present_cached = static_cast<std::uint32_t>(g_coord->present_count()); // FLAG-C (lock held)
      g_prov_rx.poll(); // gated (OQ-8) — no-op unless PANTHEON_SD_DAEMON_RX
      unlock_wifi();
    }
    // Periodic heap-health warn (F5) so degradation is visible in the soak BETWEEN takes, not only
    // when a START is refused. Rate-limited to ~30 s so a low-heap box does not spam the serial
    // log.
    const auto largest = static_cast<std::size_t>(ESP.getMaxAllocHeap());
    if (largest < eunomia::core::kHeapWarnBytes) {
      static std::uint32_t last_warn_ms = 0;
      const std::uint32_t now = millis();
      if (now - last_warn_ms > 30000) {
        last_warn_ms = now;
        Serial.printf("[heap] WARN largest=%u free=%u min=%u (warn<%u)\n",
                      static_cast<unsigned>(largest), static_cast<unsigned>(ESP.getFreeHeap()),
                      static_cast<unsigned>(ESP.getMinFreeHeap()),
                      static_cast<unsigned>(eunomia::core::kHeapWarnBytes));
      }
    }
    // F7: on AP STA connect/disconnect, skip the 700ms sleep — re-poll immediately.
    if (g_discovery_kick) {
      g_discovery_kick = false;
      vTaskDelay(pdMS_TO_TICKS(50)); // brief yield to let the WiFi stack settle
      continue;
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
  if (!LittleFS.begin(true)) { // format-on-fail; the durable ordinal-log lives here (F5)
    Serial.println("[fs] LittleFS mount failed");
  }
  g_episode_log.begin(); // recover the active segment from flash (survives a battery swap)
  reload_assignment();   // load identity BEFORE constructing the coordinator (sets g_assignment)

  // Construct the Coordinator now that NVS is open (DurableOrdinal reads the real persisted
  // ordinal). Named Deps/Fleet so the derived→base seam pointers convert unambiguously.
  Coordinator::Deps deps;
  deps.clock = &g_clock;
  deps.rng = &g_rng;
  deps.store = &g_store;
  deps.presence = &g_presence;
  deps.telemetry = &g_uplink;
  deps.episode_log = &g_episode_log; // the durable §1.7 ordinal-join backup (F5)
  Coordinator::Fleet fleet = {{"left", &g_left}, {"right", &g_right}};
  static Coordinator coord(deps, fleet, 2);
  g_coord = &coord;
  g_env.bind(&coord);
  coord.set_assignment(g_assignment);
  // F6: register the fire-confirm side-channel so trigger() confirms each startCapture
  // (connect-ack) and rolls back an under-confirmed take. The concrete X3CaptureDevices implement
  // StartConfirmable.
  coord.set_confirmer("left", &g_left);
  coord.set_confirmer("right", &g_right);
  char sess[9];
  coord.set_fob_session_id(fob_session_hex(sess)); // per-boot fob-swap disambiguator (OQ-7)

  // F7: boot-uplink — STA → NTP → task-config fetch → teardown, BEFORE the SoftAP comes up.
  // At boot no cameras are connected, so STA doesn't tear down any AP.
  {
    // (A) heap before boot-uplink
    Serial.printf("[boot-uplink] heap before: largest=%u free=%u\n",
                  static_cast<unsigned>(ESP.getMaxAllocHeap()),
                  static_cast<unsigned>(ESP.getFreeHeap()));
    const String wssid = g_store.uplink_ssid();
    const String wpass = g_store.uplink_pass();
    const String upurl = g_store.uplink_url();
    g_boot_uplink.configure(std::string(wssid.c_str()), std::string(wpass.c_str()),
                            std::string(upurl.c_str()), g_assignment.kit_id);
    g_boot_uplink.run();
    // (B) heap after boot-uplink (STA torn down, before SoftAP)
    Serial.printf("[boot-uplink] heap after: largest=%u free=%u\n",
                  static_cast<unsigned>(ESP.getMaxAllocHeap()),
                  static_cast<unsigned>(ESP.getFreeHeap()));
  }

  // SoftAP + the depot-provisioned MAC→side map (lockcams populates `sides`).
  g_softap.configure(String(g_assignment.kit_id.c_str()), g_store.cam_pass(), String("192.168.42"));
  g_softap.ensure_up();
  WiFi.onEvent(on_wifi_event); // F7: kick discovery on AP STA connect/disconnect
  g_registry.set_map(MacSideMap::from_allowlist(std::string(g_store.sides_csv().c_str())));
  g_registry.set_staleness_ms(kStalenessIdleMs); // F7: 3s idle staleness window
  g_prov_rx.begin();                             // gated (OQ-8)
  // (C) heap after SoftAP — the steady-state baseline
  Serial.printf("[boot-uplink] heap steady: largest=%u free=%u\n",
                static_cast<unsigned>(ESP.getMaxAllocHeap()),
                static_cast<unsigned>(ESP.getFreeHeap()));

  // The core-0 discovery worker (UI/input stays on core 1 — the dedicated-core split).
  xTaskCreatePinnedToCore(discovery_task, "disc", 8192, nullptr, 1, nullptr, 0);
  Serial.printf("[boot] kit=%s ssid=%s ch=%u sides=%s time_set=%s\n", g_assignment.kit_id.c_str(),
                g_softap.ssid().c_str(), static_cast<unsigned>(g_softap.channel()),
                g_store.sides_csv().c_str(), g_clock.time_set() ? "true" : "false");

#ifdef PANTHEON_HAS_TFT
  // The CYD touchscreen (F3): the UI render + touch loop lives on core 1 (this loop); the discovery
  // worker is on core 0 — the dedicated-core split. ui posts inputs through AppUiHost.
  static AppUiHost ui_host;
  static eunomia::ui::Flow ui_flow(ui_host);
  ui_flow.begin();
  g_flow = &ui_flow;
  Serial.println("[boot] ui/ (CYD touchscreen) up");
#endif
}

void app_loop() {
  poll_serial();
#ifdef PANTHEON_HAS_TFT
  if (g_flow != nullptr) {
    g_flow->tick(millis()); // touch + render on core 1 (the BOOT-button path is headless-only)
  }
#else
  poll_button(); // headless (esp32): BOOT button = GRABAR/DETENER (no screen)
#endif
  delay(8); // ~125 Hz input poll; OSC/telnet run on this core but are fire-and-forget (fast)
}

} // namespace eunomia::transport
