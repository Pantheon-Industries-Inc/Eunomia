// Pantheon X3 WiFi-OSC Fob - ESP32 firmware that triggers two (or more) Insta360
// X3 cameras over WiFi and writes a per-episode metadata sidecar onto each
// camera's SD card, next to the clip it just recorded.
//
// This is the on-device port of the host coordinator
// (x3_root/../data/styx/x3-wifi-coordinator/scripts/coordinator.py). The cameras
// run the hidcap telnet+OSC firmware; one camera is the WiFi AP hub and the
// others STA-join it, so all cameras + this fob sit on one little camera-hosted
// network (192.168.42.x). The fob does exactly what coordinator.py does:
//   1. join the hub camera's WiFi AP (STA),
//   2. discover the cameras on the subnet via OSC /osc/info,
//   3. on GRABAR: verify each camera's SD (OSC /osc/state cardState=="pass"),
//      then POST OSC camera.startCapture to every camera (near-simultaneous),
//   4. on DETENER: POST camera.stopCapture, read each clip's filename from the
//      response, and write a pantheon_episode_v1 sidecar JSON next to the clip on
//      each SD card over the camera's passwordless telnet (:23).
//
// WHY THIS REPLACES THE OLD BLE FOB: OSC stopCapture returns the EXACT clip
// filename, so the fob binds task/station/operator/timestamp DIRECTLY to each
// clip (the SD-card sidecar). That removes the dependency on the fragile
// positional trigger-log order-join for WiFi-captured footage - the label
// travels with the card. The fob still keeps a local episode log on LittleFS
// (and an optional uplink-AP upload) as redundant ground truth.
//
// Production-parity features carried over from the BLE fob:
//   - NVS-persisted identity/assignment: kit_id, operator_id, current station#
//     + prompt. The operator keys a table# on the fob; it persists across power
//     cycles until changed.
//   - Episode log on LittleFS: monotonic ordinal in NVS, START/STOP/delete lines.
//   - The CYD touchscreen IS the whole operator UI (REGISTRO -> MESA -> MAIN).
//   - No-SD guard: a take is refused unless every camera reports cardState=pass.
//
// SINGLE RADIO: the ESP32 has one 2.4GHz radio. The fob lives on the camera hub
// AP to trigger. The camera AP has no internet, so the OPTIONAL episode-log
// upload to the dashboard briefly switches to the uplink AP during an idle,
// touch-quiet window and switches back. The sidecar is the primary metadata
// channel, so a missing uplink never loses labels.

#include <Arduino.h>
#include <Preferences.h>
#include <LittleFS.h>
#include <WiFi.h>          // episode-log upload (burst; same SoC radio as BLE)
#include <HTTPClient.h>
#include <WiFiClientSecure.h>  // HTTPS POST to a public endpoint (Tailscale Funnel / Cloudflare)
#include <ArduinoJson.h>       // JSON for upload/help/telemetry payloads
#include <time.h>              // configTime / time() for NTP wallclock
#include <esp_system.h>        // esp_random() for the per-boot fob_session_id
#include <esp_wifi.h>          // SoftAP power-save/inactivity tuning
#include <esp_netif.h>         // AP station list (MAC+IP) - OSC-free camera discovery
#include <map>
#include <time.h>
#include <sys/time.h>   // settimeofday, struct timeval (serial/NTP time)
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

// ---- UI state shared by ALL builds --------------------------------------------
// The screen-less esp32dev build still references the current screen + a redraw
// request from fireShutterToggle()/setup(); only the actual rendering below is
// TFT-only. Keeping these out of the PANTHEON_HAS_TFT guard lets both envs build.
// SCREEN_CONFIRM_ID: after the typed kit# matches local NVS identity, show
//   "Are you <name>?" with SI/NO so a mis-typed kit number is caught before any
//   data is logged under the wrong person.
// SCREEN_CONFIRM: the post-STOP decision screen: the operator stops a take with one
//   DETENER press, then chooses GUARDAR (keep) or DESCARTAR (delete) - replacing the
//   old two-button "stop=keep / descartar=stop+delete" model on MAIN.
enum UiScreen : uint8_t { SCREEN_PROVISION, SCREEN_MESA, SCREEN_MAIN, SCREEN_CONFIRM, SCREEN_CONFIRM_ID };
static UiScreen g_screen = SCREEN_MAIN;

// Identity copied from depot-provisioned NVS for the local "Are you <name>?"
// confirmation screen. The operator UI never depends on WiFi to resolve identity.
static String   g_verifKit;      // canonical kit_id from verify
static String   g_verifOp;       // operator_id from verify
static String   g_verifName;     // operator display name (the thing being confirmed)

// Provenance of the just-stopped take, captured at DETENER and committed on the
// operator's GUARDAR/DESCARTAR choice (or the confirm-screen auto-save timeout).
static int      g_pendSent      = 0;     // cams that acked the STOP shutter
static int      g_pendTotal     = 0;     // cams connected at STOP
static bool     g_pendStopLogged = false;// stop line durably written for current confirm screen
static uint32_t g_confirmStartMs = 0;    // when SCREEN_CONFIRM was shown (auto-save timer)
static volatile bool g_forceRender = false;   // request one redraw (TFT builds act on it)

// Per-SESSION take counter. Incremented/zeroed from NON-TFT code (fireShutterToggle,
// the table-change reset, the SD-confirm abort), and DISPLAYED by the TFT build as
// "TOMA #n". The global g_cfg.ordinal is a lifetime, NVS-persisted index that also
// counts discarded takes - misleading as an operator "how many have I done" readout.
// g_sessionTakes resets at boot and on a table change, so "TOMA #n" means "takes
// started at THIS table this session". Ingest still keys on the global ordinal; this
// is purely cosmetic. MUST live outside the PANTHEON_HAS_TFT guard so the screen-less
// esp32dev build (which still runs the increment/reset logic) links.
static uint32_t g_sessionTakes = 0;

#ifdef PANTHEON_HAS_TFT
// CYD (ESP32-2432S028R) onboard 2.8" 320x240 ILI9341 TFT. Pins + driver are set
// via build_flags in the [env:cyd] section of platformio.ini (TFT_eSPI). The
// status screen turns the fob into a self-contained trigger box: it shows the
// kit/station, how many cameras are connected, and the recording state, with no
// separate tablet needed. Touch (XPT2046) is a later phase.
#include <TFT_eSPI.h>
#include <SPI.h>
// NOTE: the GFXFF FreeSansBold fonts are already bundled by TFT_eSPI when
// LOAD_GFXFF is defined; we reference &FreeSansBold##pt7b directly. Do NOT
// #include the font headers - they lack include guards and double-define.
static TFT_eSPI tft;
static bool g_tftReady = false;
static uint32_t g_uiSig = 0xFFFFFFFFu;        // last-drawn UI signature; redraw only on change (kills idle flashing)
static uint32_t strHash(const String& s) { uint32_t h = 2166136261u; for (size_t i = 0; i < s.length(); i++) { h ^= (uint8_t)s[i]; h *= 16777619u; } return h; }

// ---- multi-screen UI state: provision / mesa keypad / main ----
// The tablet is scrapped; this fob screen is the WHOLE operator UI. Flow:
//   PROVISION (local kit# confirmation) -> MESA (local table# entry) -> MAIN
//   (the trigger box). MESA is re-openable from MAIN.
// Both PROVISION and MESA are kit/table-NUMBER-only (operators cannot type
// letters, and a picker list does not scale to Mexico's many tables), so the SAME
// numeric keypad lives directly on each - there is no keyboard or list screen.
// (UiScreen + g_screen are declared above the PANTHEON_HAS_TFT guard so the
// screen-less build can reference them too.)

// SCREEN_PROVISION transient state: the operator types a kit NUMBER (e.g. "1")
// on the on-screen numeric keypad; local NVS identity resolves it to a canonical
// kit_id ("kit_1") and operator_id.
static String g_provKit;                // typed kit number
static String g_provErr;                // error line (Spanish/English)

// SCREEN_MESA transient state: the operator types a table NUMBER on the SAME
// numeric keypad as provisioning. ENTRAR accepts it locally and returns to MAIN.
static String g_mesaNum;                // typed table number
static String g_mesaErr;                // verify/error line (Spanish/English)

// CYD resistive touch (XPT2046) lives on its OWN SPI bus, separate from the TFT
// (the TFT is on HSPI pins 12-15). Read it directly over VSPI - no library to
// version-mismatch. IRQ (GPIO36) goes LOW while the panel is touched.
static const int T_CLK = 25, T_MISO = 39, T_MOSI = 32, T_CS = 33, T_IRQ = 36;
static SPIClass touchSPI(VSPI);

static uint16_t xptRead(uint8_t cmd) {
  touchSPI.beginTransaction(SPISettings(2000000, MSBFIRST, SPI_MODE0));
  digitalWrite(T_CS, LOW);
  touchSPI.transfer(cmd);
  uint16_t hi = touchSPI.transfer(0x00);
  uint16_t lo = touchSPI.transfer(0x00);
  digitalWrite(T_CS, HIGH);
  touchSPI.endTransaction();
  return ((hi << 8) | lo) >> 3;   // 12-bit sample
}

// Pressure-based touch detect (does NOT rely on the PENIRQ pin, which on this
// CYD variant was filtering out every tap). Reads the XPT2046 Z1/Z2 pressure
// channels; a real press makes Z large. Also returns averaged raw X/Y. The Z
// threshold is tuned from the [touchdbg] serial logs. 2026-06-17.
static const int kTouchZThresh = 1000;
static bool touchRaw(uint16_t& rx, uint16_t& ry, uint16_t& rz) {
  uint16_t z1 = xptRead(0xB0);
  uint16_t z2 = xptRead(0xC0);
  int z = (int)z1 + (4095 - (int)z2);   // higher = harder press
  if (z < 0) z = 0;
  rz = (uint16_t)z;
  uint32_t sx = 0, sy = 0;
  for (int i = 0; i < 4; i++) { sx += xptRead(0xD0); sy += xptRead(0x90); }
  rx = sx / 4; ry = sy / 4;
  return z > kTouchZThresh;
}

// Calibrated raw->screen mapping (2026-06-17, corner taps). Axes are SWAPPED on
// this CYD: screen horizontal = raw Y channel, screen vertical = raw X channel;
// both non-inverted. rawX ~620..3280 top..bottom, rawY ~465..3540 left..right.
static int touchScreenX(uint16_t ry) { long v = ((long)ry - 465) * 320 / 3075; return v < 0 ? 0 : (v > 319 ? 319 : (int)v); }
static int touchScreenY(uint16_t rx) { long v = ((long)rx - 620) * 240 / 2660; return v < 0 ? 0 : (v > 239 ? 239 : (int)v); }
#endif

#ifndef PANTHEON_PIN_BUTTON
#define PANTHEON_PIN_BUTTON 0
#endif
#ifndef PANTHEON_PIN_LED
#define PANTHEON_PIN_LED 2
#endif

// ---------------------------------------------------------------------------
// X3 OSC (Open Spherical Camera) API + camera-hosted network
// ---------------------------------------------------------------------------
// The hidcap firmware exposes the standard OSC HTTP API on port 80 and a
// passwordless busybox telnet on :23. The cameras form their own little network:
// one camera runs its AP as the hub (192.168.42.1) and the others STA-join it
// (192.168.42.2-6). The fob is a WiFi STA on that hub AP. See
// reference/NETWORK.md + reference/OSC_API.md in the x3-wifi-coordinator handoff.
#define FOB_FW_VERSION "3.8.3-fast-guard"
// FOB-AS-AP topology: the fob hosts its OWN 2.4GHz SoftAP (ESP32 is 2.4GHz-only)
// and the cameras STA-join the fob. The X3 SoftAP comes up uncontrollably on 5GHz
// (ap_start.sh auto-channel prefers 5GHz, ignores AP_CHANNEL), which a 2.4GHz fob
// can never see - so we invert the topology instead of patching camera firmware.
// OSC + telnet are plain IP, so the trigger/sidecar code path is unchanged; only
// the radio bring-up flips from STA-join to SoftAP-host. The fob is 192.168.42.1
// and the cameras get .2-.6 from the fob's DHCP.
static const uint8_t  kApChannel     = 6;    // default 2.4GHz channel (used when kit has no number)
static const uint16_t kApInactiveSec = 65535; // PANTHEON persistence: ~18h = effectively NEVER idle-deauth a station (was 300s; PM-off cams go app-quiet and got kicked every 5min)
static const uint8_t  kApMaxStations = 4;    // left+right cams + headroom (operator test devices)
static const uint16_t kCamHttpPort   = 80;   // OSC
static const uint16_t kCamTelnetPort = 23;   // passwordless root busybox telnet
static const char*    kOscExecPath   = "/osc/commands/execute";
static const char*    kOscInfoPath   = "/osc/info";
static const char*    kOscStatePath  = "/osc/state";
// SD-card mount on the camera (where telnet writes the sidecar). The clip's OSC
// _localFileUrl (e.g. /DCIM/Camera01/VID_..._002.insv) is appended to this.
static const char*    kCamSdRoot     = "/tmp/SD0";
// We scan hub-subnet hosts .1 .. kSubnetScanMax for cameras. A kit is 2 cams;
// allow headroom for a hub + a few stations.
static const int      kSubnetScanMax = 6;
// NOTE: the per-clip .pantheon.json sidecar is written BY discardd on each
// camera (schema "pantheon-x3-sidecar/v2"), NOT by the fob. The fob only injects
// current_assignment.env / current_stop.env that discardd sources. See oncam/discardd.

static const char* kEpisodeLogPath = "/episodes.jsonl";
static const char* kTriggerSchema  = "pantheon-trigger-episode/v1";

// ---------------------------------------------------------------------------
// Persistent config (NVS) - identity + current assignment + ordinal + allowlist
// ---------------------------------------------------------------------------
struct FobConfig {
  String kitId;        // join key for ingest (e.g. "kit_2")
  String operatorId;   // fixed-bound to the kit (e.g. "op002")
  String operatorName; // cached display name for offline setup confirmation
  String station;      // current table# (operator keys this; persists)
  String prompt;       // current task prompt for that table
  String allowlist;    // comma-joined lowercase camera SERIALS locked to this kit;
                       // empty = accept any camera discovered on the hub subnet.
                       // (ship_gate/allow_n: final ship needs allow_n == cam count)
  String siteId;       // depot-provisioned site/plant id for per-site rollups
                       // (injected into the on-card sidecar via current_assignment.env)
  uint32_t ordinal;    // last START ordinal (monotonic, persisted)
  bool kitConfirmed;   // operator locally confirmed REGISTRO for this kit
  // Camera hub AP: the WiFi network the cameras host (one cam is the AP). The fob
  // STA-joins this to trigger over OSC. The PSK is provisioned at the depot and
  // stored in NVS - NEVER hardcoded in source.
  String camSsid;
  String camPass;
  String camSubnet;    // /24 prefix the cameras live on, e.g. "192.168.42"
  // OPTIONAL uplink AP for shipping the redundant episode log to the dashboard.
  // The camera AP has no internet, so an upload briefly switches to this AP and
  // switches back. The SD-card sidecar is the primary metadata channel, so this
  // is best-effort: a missing uplink never loses labels.
  String wifiSsid;
  String wifiPass;
  String uploadUrl;    // base, e.g. https://erics-macbook-pro.tailc7b2a4.ts.net/api/trigger-log
  String upToken;      // shared secret sent as X-Trigger-Token (locks the public endpoint)
};
static FobConfig g_cfg;
static Preferences g_prefs;
static uint32_t g_upOff = 0;   // bytes of /episodes.jsonl already uploaded (persisted in NVS)
// Random per-boot id stamped on every trigger-log line. If a fob is swapped for a
// spare mid-day, both fobs may emit ordinals 1..N for the SAME kit/day; ingest keys
// trigger starts on (kit_id, fob_session_id, ordinal) so the two sequences never
// collide/overwrite in the order-join. Set once at boot (setup), never persisted.
static String g_fobSession;
static String makeFobSession() {
  char buf[9];
  snprintf(buf, sizeof(buf), "%08x", (unsigned)esp_random());
  return String(buf);
}
// Stable per-DEVICE id for the on-card sidecar's fob_id (which physical fob
// triggered a take). Derived from the ESP32 efuse MAC so it survives reboots and
// is identical across power cycles, unlike the per-boot g_fobSession. Used to
// scope/quarantine episodes by the fob that produced them.
static String fobHwId() {
  uint64_t mac = ESP.getEfuseMac();
  char buf[16];
  snprintf(buf, sizeof(buf), "fob_%06x", (unsigned)(mac & 0xFFFFFFu));
  return String(buf);
}

// ---------------------------------------------------------------------------
// Concurrency: WiFi I/O runs on a dedicated core-0 worker task so the UI/touch
// loop (core 1) NEVER blocks on a multi-second WiFi associate/POST. Mutexes:
//   g_fsMutex   - serializes LittleFS access (the episode log is appended from
//                 the loop, the button task, AND the NimBLE host CE81 callback,
//                 and read by the WiFi worker - concurrent opens on one file are
//                 not safe, so every open goes through this lock).
//   g_wifiMutex - guarantees a single owner of the shared 2.4GHz radio at a time
//                 (background upload/telemetry/help, plus rare fallback provisioning
//                 verification) so two paths never fight over WiFi.begin()/mode().
//   g_camMutex  - serializes g_cams, which is mutated by NimBLE callbacks and read
//                 from loop/UI/serial paths.
// ---------------------------------------------------------------------------
static SemaphoreHandle_t g_fsMutex   = nullptr;
static SemaphoreHandle_t g_wifiMutex = nullptr;
static SemaphoreHandle_t g_camMutex  = nullptr;
static inline void fsLock()   { if (g_fsMutex)   xSemaphoreTake(g_fsMutex, portMAX_DELAY); }
static inline void fsUnlock() { if (g_fsMutex)   xSemaphoreGive(g_fsMutex); }
static inline void wifiLock()   { if (g_wifiMutex) xSemaphoreTake(g_wifiMutex, portMAX_DELAY); }
static inline void wifiUnlock() { if (g_wifiMutex) xSemaphoreGive(g_wifiMutex); }
static inline void camLock()  { if (g_camMutex)  xSemaphoreTake(g_camMutex, portMAX_DELAY); }
static inline void camUnlock(){ if (g_camMutex)  xSemaphoreGive(g_camMutex); }
// Bounded lock for rare UI-loop fallback verification. Normal kit/table operation
// is local-first; this is only for unprovisioned or mismatched identity recovery.
// A timed take fails fast instead of blocking the whole UI behind background WiFi.
static inline bool wifiTryLock(uint32_t ms) {
  return g_wifiMutex ? (xSemaphoreTake(g_wifiMutex, pdMS_TO_TICKS(ms)) == pdTRUE) : true;
}

// WiFi worker job queue (core 0). Fire-and-forget jobs; the loop never waits.
// Normal operator flow is local-first. Setup screens no longer enqueue WiFi jobs.
enum WifiJobType : uint8_t { WJOB_UPLOAD = 1, WJOB_TELEM = 2, WJOB_HELP = 3,
                             WJOB_WIFIDOWN = 5 };
static QueueHandle_t g_wifiQ = nullptr;

// Call-lead ("Llamar al lider") async result, set by the worker, rendered by the
// loop's overlay manager. The loop shows "LLAMANDO..." the instant the button is
// pressed and flips to the honest result (notified vs only-saved) when the worker
// finishes - all without ever blocking the touch loop.
static volatile bool g_helpDone   = false;   // worker finished the POST (best-effort; UI no longer waits on it)
static volatile int  g_helpCode   = -1;      // HTTP status (200 == lead pinged live)

static void cfgLoad() {
  g_prefs.begin("pantheon-fob", false);
  g_cfg.kitId      = g_prefs.getString("kit", "");
  g_cfg.operatorId = g_prefs.getString("op", "");
  g_cfg.operatorName = g_prefs.getString("opname", "");
  g_cfg.station    = g_prefs.getString("station", "");
  g_cfg.prompt     = g_prefs.getString("prompt", "");
  g_cfg.allowlist  = g_prefs.getString("allow", "");
  g_cfg.siteId     = g_prefs.getString("site", "");
  g_cfg.ordinal    = g_prefs.getUInt("ordinal", 0);
  g_cfg.kitConfirmed = g_prefs.getBool("kitok", false);
  g_cfg.camSsid    = g_prefs.getString("cssid", "");
  g_cfg.camPass    = g_prefs.getString("cpass", "");
  g_cfg.camSubnet  = g_prefs.getString("csub", "192.168.42");
  g_cfg.wifiSsid   = g_prefs.getString("wssid", "");
  g_cfg.wifiPass   = g_prefs.getString("wpass", "");
  g_cfg.uploadUrl  = g_prefs.getString("upurl", "");
  g_cfg.upToken    = g_prefs.getString("uptok", "");
  g_upOff          = g_prefs.getUInt("uploff", 0);
}
static void cfgPutStr(const char* k, const String& v) { g_prefs.putString(k, v); }
static void cfgPutOrdinal(uint32_t v) { g_cfg.ordinal = v; g_prefs.putUInt("ordinal", v); }
static void cfgPutKitConfirmed(bool v) { g_cfg.kitConfirmed = v; g_prefs.putBool("kitok", v); }

// ---------------------------------------------------------------------------
// Wall-clock. The ESP32 has no battery-backed RTC; serial tools or NTP set Unix
// time ("time=<unix>"). Until then wallclock is "" (the ingest
// order-join uses ordinal order, not wallclock - wallclock is only a sanity
// check, exactly as on the Pi bridge), and we always log ms_since_boot.
// ---------------------------------------------------------------------------
static bool g_timeSet = false;

static void setUnixTime(uint32_t unixSecs) {
  struct timeval tv; tv.tv_sec = unixSecs; tv.tv_usec = 0;
  settimeofday(&tv, nullptr);
  g_timeSet = unixSecs > 1700000000UL;  // sanity: after 2023-11
}

static String isoNow() {
  if (!g_timeSet) return String("");
  time_t now = time(nullptr);
  if (now < 1700000000L) return String("");
  struct tm t; gmtime_r(&now, &t);
  char buf[24];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &t);
  return String(buf);
}

// ---------------------------------------------------------------------------
// Globals - camera roster discovered over OSC on the hub subnet
// ---------------------------------------------------------------------------
// A camera the fob has discovered (answered /osc/info) on the hub subnet. The
// roster is rebuilt by the discovery task and read by the UI/trigger paths, so
// every access goes through g_camMutex. `online` clears when a camera stops
// answering; `cardOk` is the last /osc/state cardState=="pass" reading.
struct Cam {
  String   ip;          // e.g. "192.168.42.1"
  String   serial;      // OSC serialNumber (e.g. "IAQEB2601KHF6C")
  String   fw;          // OSC firmwareVersion
  bool     online;      // answered /osc/info within the last discovery sweep
  bool     cardOk;      // last /osc/state cardState reading was "pass"
  uint32_t cardSeenMs;  // millis() of the last successful /osc/state (0 == never)
  String   lastClip;    // last clip filename from stopCapture (_localFileUrl)
  uint32_t lastSeenMs;  // millis() of the last successful /osc/info
};
static Cam g_cam[kSubnetScanMax];
static volatile int  g_connCount = 0;   // # cameras currently online (word-atomic read)
static volatile bool g_anyRec    = false; // fob-authoritative record state (touch/button toggle)
// Both cams of a kit must be up to record (GO/NO-GO). Same 2-cam gate as the BLE
// fob: a one-sided take is useless and desyncs labeling.
static const int kMinCams = 2;

// START GO/NO-GO gate. The BLE fob made the trigger PHYSICALLY un-pressable
// whenever the kit wasn't in a known-good state (a cam dropped off BLE). The
// WiFi system has THREE persistent NO-GO states, and we mirror that hard gating:
// the renderer draws the button LOCKED and the touch handler ignores the tap for
// any of them, so the operator gets honest, immediate feedback instead of mashing
// a green button into a failure splash. (Card readiness is a press-TIME OSC check,
// not a persistent state, so it stays inside fireShutterToggle - GRABAR must be
// pressable to perform it.)
enum StartGate : uint8_t {
  GATE_OK = 0,      // all persistent preconditions met - GRABAR is live
  GATE_CAMS,        // fewer than both cams online over OSC
  GATE_UPLINK,      // single radio borrowed by the dashboard uplink window
  GATE_SAVING,      // prior take's discardd sidecars not yet confirmed on-card
};
// True between a STOP that recorded clips and the moment discardd's
// .pantheon.json sidecars are confirmed on every card. Set in camStopAll, cleared
// by priorSidecarsReady (also re-checked cheaply by the idle discovery worker so
// the lock clears on its own, with no operator action). Volatile: written by the
// trigger/discovery paths, read by the UI render + touch.
static volatile bool g_sidecarsPending = false;
// startGate() is defined further down, after g_wifiActive/g_uiDirty are declared.

// Physical-button (BOOT) presses are detected on buttonTask (a SEPARATE FreeRTOS
// task) but must not touch the TFT from there. buttonTask sets a request here;
// loop() services it (sends the command / toggles record) and g_camMutex protects
// the camera map against NimBLE callback mutations. (concurrency hardening 2026-06-19)
enum BtnReq : uint8_t { BTN_NONE = 0, BTN_SHUTTER, BTN_POWEROFF, BTN_MODE };
static volatile uint8_t g_btnReq = BTN_NONE;

// START CONFIRMATION (the "no SD card" trap). The START gate proves both cams are
// BLE-connected AND received the shutter notify - but neither proves a cam can
// actually WRITE: a cam with no (or full) SD card beeps an error and never records,
// so the operator performs a whole take into the void. There is NO reliable
// pre-start SD telemetry on this firmware (the BE80 capture-status read is an
// unverified stub), so the only trustworthy signal is the cam's OWN CE81
// record-state edge: an SD-less / errored cam NEVER emits rec=1. We therefore keep
// the instant DETENER flip on START (responsive), but arm a background watcher -
// BOTH cams must report rec=1 within kStartConfirmMs or the take is treated as
// failed (stop the cams, VOID the ordinal, alarm the operator to check the card).
// The window is generous because the X3's record-state notify lags the real start
// by ~1-2s (LESSONS #8); too-short would false-abort healthy takes, so we bias long.
static const uint32_t kStartConfirmMs = 4000;
static volatile bool     g_startConfirmPending  = false;
static volatile uint32_t g_startConfirmDeadline = 0;
static volatile int      g_startRecAcks         = 0;   // # cams reporting rec=1 since this START

// BLE link supervision timeout (units of 10ms). LONG while recording so a brief
// radio gap can't drop a cam mid-take (a dropped cam = lost / order-desynced
// footage); SHORTER while idle so a cam that powers off / leaves range registers
// OFFLINE on the board faster (the old flat 6s made a vanished cam take ~6s).
//
// WHY IDLE IS 3s, NOT 1s (hard-won, 2026-06-19): a dropped cam's RECONNECT is slow
// and NOT fixable from the fob - a still-powered cam that loses the link falls into
// the camera's low-duty-cycle background scan and takes ~29s to find us again
// (firmware-owned; measured on the bench). The wake-on-BLE iBeacon does NOT help
// here - the legacy bridge proved iBeacon-churn at partial-connect STARVES the
// missing cam's connect window, so it refuses to wake while any cam is up. Given
// reconnect costs ~29s, a too-tight idle timeout is a bad trade: normal in-range
// jitter >Ns would drop a healthy cam and strand it offline for ~29s. 3s detects a
// real offline fast enough while riding out transient gaps. Retuned on connect +
// every record start/stop, and reconciled in loop() (see setCamSupervision).
static const uint16_t kSupervRecCs  = 600;   // 6.0s while recording (drop-proof)
static const uint16_t kSupervIdleCs = 300;   // 3.0s while idle (fast-ish offline, jitter-safe)
// True while WiFi owns the shared 2.4GHz radio (between a successful wifiUp and
// wifiDown). BLE advertising is parked for this window so association is fast;
// the advertising watchdog must stand down while it is set.
static volatile bool g_wifiActive = false;
// True once the fob's 2.4GHz SoftAP is up (cameras STA-join this). Cleared when the
// radio is borrowed for the STA uplink window, re-asserted by apEnsureUp().
static volatile bool g_apUp = false;
// Event-driven discovery kick: when the SoftAP sees a station connect/disconnect,
// re-probe cameras immediately (don't wait for the periodic poll).
static volatile bool g_discoveryKick = false;
// Last time a START was REFUSED because fewer than both cams were connected.
// Drives the "waiting for cameras" lock hint on the UI. A refused start never
// advances the ordinal, so a press before both cams connect cannot create a
// phantom episode that desyncs the ingest order-join. (ordinal hardening 2026-06-18)
static volatile uint32_t g_lastBlockedMs = 0;

// TFT is owned EXCLUSIVELY by the loop task (core 1). publishStatus() is also
// called from the NimBLE host task (connect/disconnect/CE81) and the button task,
// and drawing the TFT from those tasks raced the loop's draws on the shared HSPI
// bus -> the SPI transaction mutex was given by the wrong task (assert/crash).
// Those paths now only SET this flag; the loop renders. (2026-06-18)
static volatile bool g_uiDirty = false;

// Single source of truth for "can a take START right now" used by BOTH the
// renderer and the touch handler so the visual lock and the tap behaviour can
// never disagree. Order = severity/most-actionable first. Defined here (not next
// to the enum) so g_wifiActive/g_sidecarsPending are already declared.
static StartGate startGate() {
  if (g_connCount < kMinCams) return GATE_CAMS;
  if (g_wifiActive)           return GATE_UPLINK;
  if (g_sidecarsPending)      return GATE_SAVING;
  return GATE_OK;
}

// ---------------------------------------------------------------------------
// Live per-cam telemetry cache (TASK 5). The dashboard wants battery % + SD free
// per camera. We cache the latest reading per SIDE ("left"/"right") and POST it
// on the next idle WiFi window (same path that ships the episode log). The two
// cams of a kit are bound to sides by MAC allowlist position: allowlist entry 0
// = left, entry 1 = right (the depot pairs them in that order). online/recording
// are always live (the fob already knows them from g_cams + CE81 + its own
// toggle); battery_pct / sd_* come from the BE80 poll when enabled (see
// PANTHEON_TELEM_BLE) and are -1 / 0 until a real reading lands.
// ---------------------------------------------------------------------------
struct CamTelem {
  String  side;          // "left" | "right" (resolved from allowlist order)
  String  serial;        // best-effort camera serial / MAC (filled on connect)
  int     battery_pct;   // 0..100, or -1 if unknown
  int     sd_free_pct;   // 0..100, or -1 if unknown
  long    sd_free_mb;    // MB free, or -1 if unknown
  long    sd_total_mb;   // MB total, or -1 if unknown
  bool    recording;     // live
  bool    online;        // live (a cam is connected on this side)
  uint32_t lastUpdateMs; // millis() of the last refresh
};
static CamTelem g_telem[2] = {
  {"left",  "", -1, -1, -1, -1, false, false, 0},
  {"right", "", -1, -1, -1, -1, false, false, 0},
};
// Telemetry poll/POST cadence: only while idle (never mid-record; the shared
// 2.4GHz radio is BLE-dedicated during a take). 45s sits in the requested
// 30-60s band and lines up with the 30s heartbeat / episode-log upload window.
static const uint32_t kTelemPeriodMs = 45000;

// WiFi association timeout for wifiUp(). The loop is single-threaded: while we
// block here waiting to associate, a button press is NOT serviced, so a shorter
// value bounds how long an idle WiFi window can stall the trigger path. Operator
// kit/table entry is local-first and never calls WiFi; this only affects background
// upload/help/telemetry while idle.
static const uint32_t kWifiAssocTimeoutMs = 8000;

struct WifiTarget {
  bool found;
  int32_t rssi;
  int32_t channel;
  uint8_t bssid[6];
};

static String fmtBssid(const uint8_t* b) {
  char buf[18];
  snprintf(buf, sizeof(buf), "%02X:%02X:%02X:%02X:%02X:%02X",
           b[0], b[1], b[2], b[3], b[4], b[5]);
  return String(buf);
}

static WifiTarget scanBestWifiTarget(const String& ssid) {
  WifiTarget best = {};
  best.found = false;
  best.rssi = -999;
  best.channel = 0;
  if (ssid.length() == 0) return best;

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(false, false);
  delay(80);
  int n = WiFi.scanNetworks(false, true);  // sync scan, include hidden SSIDs
  Serial.printf("[wifi] scan found %d networks; selecting ssid='%s'\n",
                n, ssid.c_str());
  for (int i = 0; i < n; i++) {
    if (WiFi.SSID(i) != ssid) continue;
    int32_t rssi = WiFi.RSSI(i);
    if (!best.found || rssi > best.rssi) {
      best.found = true;
      best.rssi = rssi;
      best.channel = WiFi.channel(i);
      const uint8_t* b = WiFi.BSSID(i);
      if (b) memcpy(best.bssid, b, 6);
    }
  }
  WiFi.scanDelete();
  if (best.found) {
    Serial.printf("[wifi] selected bssid=%s ch=%ld rssi=%ld\n",
                  fmtBssid(best.bssid).c_str(), (long)best.channel, (long)best.rssi);
  } else {
    Serial.printf("[wifi] ssid='%s' not found in scan; falling back to generic begin\n",
                  ssid.c_str());
  }
  return best;
}

// ---------------------------------------------------------------------------
// MAC allowlist
// ---------------------------------------------------------------------------
static String lc(const String& s) { String o = s; o.toLowerCase(); return o; }

static bool macAllowed(const String& addr) {
  if (g_cfg.allowlist.length() == 0) return true;        // empty = allow all
  String needle = lc(addr);
  String hay = lc(g_cfg.allowlist);
  // comma-delimited membership test (addresses are fixed-width, no false subs).
  int start = 0;
  while (start < (int)hay.length()) {
    int comma = hay.indexOf(',', start);
    if (comma < 0) comma = hay.length();
    String tok = hay.substring(start, comma); tok.trim();
    if (tok.length() && tok == needle) return true;
    start = comma + 1;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Episode log (LittleFS JSONL) - the field analogue of pantheon-bled's
// EpisodeLogger. One line per fired action. trigger_join.py consumes it.
// ---------------------------------------------------------------------------
static String jsonEscape(const String& s) {
  String o; o.reserve(s.length() + 4);
  for (size_t i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '"' || c == '\\') { o += '\\'; o += c; }
    else if (c == '\n') o += "\\n";
    else if (c == '\r') o += "\\r";
    else if ((uint8_t)c < 0x20) { /* drop other control chars */ }
    else o += c;
  }
  return o;
}

// Sanitize a value for safe inclusion in a KEY="value" line of an env file the
// camera's /bin/sh will `source`. Strips exactly the chars that would break a
// double-quoted shell value (" \ ` $) plus CR/LF. Lossy but safe; mirrors
// discardd's clean_env_val() so a malicious/odd prompt can't inject commands.
static String shClean(const String& s) {
  String o; o.reserve(s.length());
  for (size_t i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '"' || c == '\\' || c == '`' || c == '$' || c == '\n' || c == '\r') continue;
    o += c;
  }
  return o;
}

// JSON array of the cameras that were online at trigger time (serials if known,
// else IPs). Goes into the episode-log start line as provenance.
static String camsJsonArray() {
  String a = "[";
  bool first = true;
  camLock();
  for (int i = 0; i < kSubnetScanMax; i++) {
    if (!g_cam[i].online) continue;
    String id = g_cam[i].serial.length() ? g_cam[i].serial : g_cam[i].ip;
    if (!first) a += ",";
    a += "\"" + jsonEscape(id) + "\"";
    first = false;
  }
  camUnlock();
  a += "]";
  return a;
}

// Returns true only if the full line was durably written. Callers that advance
// persistent state (the NVS ordinal) MUST gate that advance on a true return so
// NVS never gets ahead of the on-disk log (which would desync the order-join).
static bool appendEpisodeLine(const String& line) {
  fsLock();
  File f = LittleFS.open(kEpisodeLogPath, FILE_APPEND);
  if (!f) { Serial.println("[log] open failed"); fsUnlock(); return false; }
  size_t want = line.length() + 1;            // line + newline
  size_t wrote = f.print(line);
  wrote += f.print("\n");
  f.flush();
  f.close();
  fsUnlock();
  if (wrote < want) { Serial.println("[log] SHORT WRITE (flash full?)"); return false; }
  return true;
}

// emit a START line and bump+persist the ordinal. Returns the new ordinal.
static uint32_t logStart(int sent, int total) {
  uint32_t ord = g_cfg.ordinal + 1;
  String iso = isoNow();
  String line = "{";
  line += "\"schema\":\"" + String(kTriggerSchema) + "\",";
  line += "\"event\":\"start\",";
  line += "\"kit_id\":\"" + jsonEscape(g_cfg.kitId) + "\",";
  line += "\"fob_session_id\":\"" + g_fobSession + "\",";
  line += "\"ordinal\":" + String(ord) + ",";
  line += "\"wallclock\":\"" + iso + "\",";
  line += "\"ms\":" + String(millis()) + ",";
  line += "\"station\":\"" + jsonEscape(g_cfg.station) + "\",";
  line += "\"prompt\":\"" + jsonEscape(g_cfg.prompt) + "\",";
  line += "\"operator_id\":\"" + jsonEscape(g_cfg.operatorId) + "\",";
  line += "\"cams\":" + camsJsonArray() + ",";
  line += "\"sent\":" + String(sent) + ",\"total\":" + String(total);
  line += "}";
  // Durable-before-bump: persist the NVS ordinal ONLY after the START line is on
  // disk. If the append fails (e.g. flash full), do NOT advance - an NVS ordinal
  // with no matching log line would mislabel EVERY later episode in the join.
  if (!appendEpisodeLine(line)) {
    Serial.println("[ep] START append FAILED - ordinal NOT advanced");
    return g_cfg.ordinal;            // unchanged; this take stays unlabeled (needs_review)
  }
  cfgPutOrdinal(ord);
  Serial.printf("[ep] START ordinal=%u station=%s\n", ord, g_cfg.station.c_str());
  return ord;
}

// ---------------------------------------------------------------------------
// Per-take state. discardd (on each camera) owns the authoritative
// .pantheon.json sidecar; the fob's job is to INJECT the per-take metadata
// discardd cannot know on its own - the shared bimanual_episode_id (so the L/R
// clips pair with NO ingest join), the operator/station/task assignment, and at
// STOP the outcome + cross-cam timing - by writing two env files onto each card:
//   <SD>/PANTHEON/current_assignment.env  (before startCapture)
//   <SD>/PANTHEON/current_stop.env        (after stopCapture)
// which discardd sources when it stamps the sidecar for the clip.
// ---------------------------------------------------------------------------
struct TakeCam {
  String   ip;
  String   serial;
  String   clip;          // OSC _localFileUrl from stopCapture
  uint32_t startedUnix;   // fob-clock unix at this cam's startCapture ack
  uint32_t startedMs;     // millis() at this cam's startCapture ack (for skew)
  uint32_t stoppedUnix;   // fob-clock unix at this cam's stopCapture ack
  bool     started;
  bool     stopped;
  bool     sidecarOk;     // discardd's .pantheon.json confirmed present (gate)
};
static TakeCam g_take[kSubnetScanMax];
static int     g_takeN = 0;          // cams in the current take
static String  g_bimanualId;         // shared L/R pairing id for the current take
static String  g_episodeId;          // per-take episode id (= prospective ordinal)
static int     g_startSkewMs = -1;   // measured spread between cam startCapture acks

// Build the JSON array of per-camera STOP detail from the current take: each
// cam's serial, recorded clip, and whether discardd's sidecar was confirmed
// on-card. This is the failure backstop - if a card's sidecar never lands, this
// line (uploaded via /api/trigger-log) is the only off-card record of the clip.
static String takeCamsDetailJson() {
  String a = "[";
  for (int i = 0; i < g_takeN; i++) {
    if (i) a += ",";
    a += "{\"serial\":\"" + jsonEscape(g_take[i].serial) + "\",";
    a += "\"clip\":\"" + jsonEscape(g_take[i].clip) + "\",";
    a += "\"sidecar_ok\":" + String(g_take[i].sidecarOk ? "true" : "false") + "}";
  }
  a += "]";
  return a;
}

static bool logStop(int sent, int total) {
  // Completeness: how many of the take's cams recorded a clip / have a sidecar.
  int clips = 0, sidecars = 0;
  for (int i = 0; i < g_takeN; i++) {
    if (g_take[i].clip.length()) clips++;
    if (g_take[i].sidecarOk) sidecars++;
  }
  String line = "{\"schema\":\"" + String(kTriggerSchema) + "\",\"event\":\"stop\",";
  line += "\"kit_id\":\"" + jsonEscape(g_cfg.kitId) + "\",";
  line += "\"fob_session_id\":\"" + g_fobSession + "\",";
  line += "\"bimanual_episode_id\":\"" + jsonEscape(g_bimanualId) + "\",";
  line += "\"ordinal\":" + String(g_cfg.ordinal) + ",";
  line += "\"sent\":" + String(sent) + ",\"total\":" + String(total) + ",";
  line += "\"start_skew_ms\":" + String(g_startSkewMs) + ",";
  line += "\"cams\":" + takeCamsDetailJson() + ",";
  line += "\"clips\":" + String(clips) + ",\"sidecars\":" + String(sidecars) + ",";
  line += "\"expected\":" + String(g_takeN) + ",";
  // wallclock is best-effort (empty until NTP syncs); ms is ALWAYS present, so the
  // join can reconstruct stop-time / duration from the START's synced wallclock +
  // (stop.ms - start.ms) even when this wallclock is "".
  line += "\"wallclock\":\"" + isoNow() + "\",";
  line += "\"ms\":" + String(millis()) + "}";
  if (!appendEpisodeLine(line)) {
    Serial.printf("[ep] STOP append FAILED ordinal=%u sent=%d/%d\n", g_cfg.ordinal, sent, total);
    return false;
  }
  Serial.printf("[ep] STOP ordinal=%u sent=%d/%d\n", g_cfg.ordinal, sent, total);
  return true;
}

// operator pressed DELETE on the fob -> void the most-recent START ordinal.
static bool logDelete() {
  if (g_cfg.ordinal < 1) return false;
  String line = "{\"schema\":\"" + String(kTriggerSchema) + "\",\"event\":\"delete\",";
  line += "\"kit_id\":\"" + jsonEscape(g_cfg.kitId) + "\",";
  line += "\"fob_session_id\":\"" + g_fobSession + "\",";
  line += "\"ordinal\":" + String(g_cfg.ordinal) + ",";
  line += "\"wallclock\":\"" + isoNow() + "\",";
  line += "\"ms\":" + String(millis()) + "}";
  if (!appendEpisodeLine(line)) {
    Serial.printf("[ep] DELETE append FAILED ordinal=%u\n", g_cfg.ordinal);
    return false;
  }
  Serial.printf("[ep] DELETE ordinal=%u\n", g_cfg.ordinal);
  return true;
}

// ---------------------------------------------------------------------------
// WiFi burst upload of the episode log to the dashboard (which rsyncs it to
// Pluto for the ingest order-join). Ship only the bytes appended since the last
// successful upload (g_upOff, persisted in NVS), then drop WiFi so the single
// 2.4GHz radio is BLE-dedicated again. Caller guarantees we're idle (never
// mid-recording), so the brief WiFi window can't jitter an active take.
// Returns true on success or nothing-to-send.
// ---------------------------------------------------------------------------
// Backend endpoints hang off the same host as the upload URL:
// uploadUrl == "<base>/api/trigger-log".
static String apiBase() {
  String b = g_cfg.uploadUrl;
  int i = b.indexOf("/api/trigger-log");
  if (i > 0) b = b.substring(0, i);
  while (b.endsWith("/")) b.remove(b.length() - 1);
  return b;
}

// Associate the STA radio to a given AP. No BLE coexistence anymore: the radio is
// WiFi-only, so we can hold a sustained STA link to the camera hub for the whole
// session. Selects the strongest matching BSSID, retries with a full radio reset,
// and (for the internet-facing uplink AP) forces public DNS + lazy NTP. Returns
// true if connected. `forUplink` controls DNS/NTP (the camera AP has no internet).
static bool wifiJoin(const String& ssid, const String& pass, bool forUplink,
                     bool doNtp, int maxAttempts = 2, uint32_t assocMs = kWifiAssocTimeoutMs) {
  if (ssid.length() == 0) return false;
  g_apUp = false;                         // going to STA tears down our SoftAP
  WiFi.persistent(false);                 // don't wear flash writing creds each connect
  WiFi.setSleep(true);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  WifiTarget target = scanBestWifiTarget(ssid);
  for (int attempt = 1; attempt <= maxAttempts; attempt++) {
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(true);
    WiFi.setTxPower(WIFI_POWER_19_5dBm);
    if (forUplink) {
      // .ts.net / public hosts: guest resolvers can't resolve, force public DNS.
      WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE,
                  IPAddress(8, 8, 8, 8), IPAddress(1, 1, 1, 1));
    } else {
      WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE);  // DHCP from the camera AP
    }
    delay(60);
    if (target.found) WiFi.begin(ssid.c_str(), pass.c_str(), target.channel, target.bssid, true);
    else              WiFi.begin(ssid.c_str(), pass.c_str());
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < assocMs) delay(200);
    if (WiFi.status() == WL_CONNECTED) break;
    Serial.printf("[wifi] assoc '%s' attempt %d/%d failed (status=%d); resetting radio\n",
                  ssid.c_str(), attempt, maxAttempts, (int)WiFi.status());
    WiFi.disconnect(false, false);
    delay(300);
  }
  if (WiFi.status() != WL_CONNECTED) return false;
  delay(forUplink ? 350 : 120);           // let DHCP/route settle
  if (forUplink && doNtp && !g_timeSet) {
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    uint32_t t1 = millis();
    while (time(nullptr) < 1700000000UL && millis() - t1 < 4000) delay(100);
    if (time(nullptr) > 1700000000UL) { g_timeSet = true; Serial.println("[wifi] NTP time synced"); }
  }
  Serial.printf("[wifi] up ssid=%s ip=%s rssi=%ld ch=%d bssid=%s\n", ssid.c_str(),
                WiFi.localIP().toString().c_str(), (long)WiFi.RSSI(),
                WiFi.channel(), WiFi.BSSIDstr().c_str());
  return true;
}

// The SSID the fob BROADCASTS for the cameras to STA-join. Per-kit unique so 12
// rigs in one room never cross-join. Explicit cam_ssid override wins; otherwise
// derived from the kit id (PANTHEON-<kit>), falling back to the fob hwid when
// unprovisioned so the AP is still uniquely addressable.
static String apSsid() {
  if (g_cfg.camSsid.length()) return g_cfg.camSsid;
  if (g_cfg.kitId.length())   return "PANTHEON-" + g_cfg.kitId;
  return "PANTHEON-" + fobHwId();
}

// 2.4GHz has only THREE non-overlapping channels (1/6/11). In a Mexico room with
// up to 12 kits each hosting its OWN SoftAP, putting them all on ch6 guarantees
// co-channel contention/drops. Spread kits deterministically across the usable
// channels by the trailing kit number so neighbours rarely share a channel. Falls
// back to kApChannel for a kit id without a number.
//
// ch11 DROPPED (2026-06-24, kit_56): the ESP32 SoftAP reports `[ap] up ... ch=11`
// but NO client can discover or associate (verified: neither the Mac nor either
// camera could find/join PANTHEON-kit_56 on ch11, while ch1/ch6 work on the same
// hardware). Until the ch11 SoftAP issue is root-caused, the n%3==2 slot maps to
// ch6 instead of 11. This keeps kit_57->ch1 and kit_55->ch6 unchanged.
static uint8_t apChannel() {
  const uint8_t chans[3] = {1, 6, 6};
  long n = -1;
  int us = g_cfg.kitId.lastIndexOf('_');
  String tail = (us >= 0) ? g_cfg.kitId.substring(us + 1) : g_cfg.kitId;
  if (tail.length()) {
    char* end = nullptr;
    long v = strtol(tail.c_str(), &end, 10);
    if (end && *end == '\0') n = v;
  }
  if (n < 0) return kApChannel;
  return chans[(uint8_t)(n % 3)];
}

// Tune ESP32 SoftAP retention for long-lived camera STA clients.
static void apTuneDriver() {
  const wifi_interface_t apIf =
#ifdef WIFI_IF_AP
      WIFI_IF_AP;
#else
      (wifi_interface_t)ESP_IF_WIFI_AP;
#endif
  // AP-side modem sleep can trigger flaky idle deauths with chatty camera clients.
  esp_err_t ePs = esp_wifi_set_ps(WIFI_PS_NONE);
  esp_err_t eInactive = esp_wifi_set_inactive_time(apIf, kApInactiveSec);
  wifi_config_t apCfg;
  memset(&apCfg, 0, sizeof(apCfg));
  esp_err_t eGet = esp_wifi_get_config(apIf, &apCfg);
  esp_err_t eSet = ESP_FAIL;
  uint8_t before = 0;
  if (eGet == ESP_OK) {
    before = apCfg.ap.max_connection;
    apCfg.ap.max_connection = kApMaxStations;
    eSet = esp_wifi_set_config(apIf, &apCfg);
  }
  Serial.printf("[ap] tune ps=%d inactive=%d max_conn %u->%u get=%d set=%d\n",
                (int)ePs, (int)eInactive, (unsigned)before, (unsigned)kApMaxStations,
                (int)eGet, (int)eSet);
}

static void onWiFiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  (void)info;
#if defined(ARDUINO_EVENT_WIFI_AP_STACONNECTED) && defined(ARDUINO_EVENT_WIFI_AP_STADISCONNECTED)
  if (event == ARDUINO_EVENT_WIFI_AP_STACONNECTED ||
      event == ARDUINO_EVENT_WIFI_AP_STADISCONNECTED) {
    g_discoveryKick = true;
    g_uiDirty = true;  // reflect AP station churn on-screen promptly
  }
#endif
}

// Ensure the fob's 2.4GHz SoftAP is up so the cameras can STA-join it and we can
// trigger over OSC. Idempotent: a no-op when already hosting. NOT taken while the
// uplink window owns the radio (g_wifiActive) - that borrow tears the AP down and
// uplinkDown() brings it back. Replaces the old camera-AP STA join: there is no
// association to fail, so the flaky assoc/scan/reconnect loop is gone entirely.
static bool apEnsureUp() {
  if (g_wifiActive) return false;                       // uplink borrow in progress
  // "Healthy" requires more than the AP mode bit: a wedged/crashed SoftAP driver
  // can keep the mode bit set while the netif is gone (softAPIP()==0.0.0.0), which
  // is exactly the silent failure that drops all cams. Treat a zero IP as down so
  // we fall through and actually re-create the AP. Only fires on real failure
  // (the IP is otherwise the static .1 we configured), so no mid-record churn.
  bool apHealthy = g_apUp && ((int)WiFi.getMode() & (int)WIFI_AP) &&
                   ((uint32_t)WiFi.softAPIP() != 0);
  if (apHealthy) return true;
  if (g_apUp && ((uint32_t)WiFi.softAPIP() == 0))
    Serial.println("[ap] WEDGED (mode bit set but IP=0) -> forcing re-up");
  WiFi.persistent(false);
  WiFi.mode(WIFI_AP);
  IPAddress apIp, apMask;
  if (!apIp.fromString(g_cfg.camSubnet + ".1")) apIp.fromString("192.168.42.1");
  apMask.fromString("255.255.255.0");
  WiFi.softAPConfig(apIp, apIp, apMask);                // gateway == AP ip; DHCP serves .2-.6
  String ssid = apSsid();
  uint8_t ch = apChannel();
  // Explicit params (don't rely on defaults): ssid_hidden=0 so the AP ALWAYS
  // beacons (a hidden AP is invisible to passive scans and to operators), and
  // max_connection set at CREATION (more reliable than a post-hoc set_config,
  // which can require an AP restart to take). 2 cams + headroom.
  bool ok;
  if (g_cfg.camPass.length() >= 8)
    ok = WiFi.softAP(ssid.c_str(), g_cfg.camPass.c_str(), ch, /*ssid_hidden=*/0, /*max_connection=*/kApMaxStations);
  else
    ok = WiFi.softAP(ssid.c_str(), nullptr, ch, /*ssid_hidden=*/0, /*max_connection=*/kApMaxStations); // open AP (PSK too short) - dev fallback
  WiFi.setSleep(false);                                 // AP host: do not idle-sleep the radio
  apTuneDriver();                                       // esp-idf AP retention knobs
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  g_apUp = ok;
  Serial.printf("[ap] %s ssid='%s' ip=%s ch=%d sta=%d\n", ok ? "up" : "FAIL",
                ssid.c_str(), WiFi.softAPIP().toString().c_str(), (int)ch,
                WiFi.softAPgetStationNum());
  return ok;
}

static void wifiDown() {
  WiFi.disconnect(false, false);
  delay(50);
  WiFi.setSleep(true);
}

// Borrow the single radio for the internet uplink AP (the cameras are briefly
// unreachable). g_wifiActive blocks the trigger path while borrowed. Refuses
// mid-record so a take is never interrupted. On any failure we always hop back to
// the camera hub. Returns true if the uplink AP associated.
static bool uplinkUp(bool doNtp, uint32_t assocMs = kWifiAssocTimeoutMs) {
  if (g_anyRec) return false;                 // never steal the radio from a live take
  // PANTHEON persistence: NEVER borrow the radio / tear down the SoftAP. The AP
  // teardown drops EVERY camera (a periodic-drop mechanism). The SD sidecar is the
  // primary metadata channel, so skipping the cloud uplink loses no labels. Keep a
  // rock-stable always-on AP instead. (Re-enable by removing this return.)
  return false;
  if (g_cfg.wifiSsid.length() == 0) return false;
  g_wifiActive = true;                        // cameras temporarily unreachable
  g_uiDirty = true;                           // MAIN -> "ESPERA / Subiendo datos" immediately
  if (!wifiJoin(g_cfg.wifiSsid, g_cfg.wifiPass, /*forUplink=*/true, doNtp, 2, assocMs)) {
    g_wifiActive = false;
    g_uiDirty = true;                         // borrow aborted -> unlock GRABAR again
    apEnsureUp();                             // bring our SoftAP back for the cameras
    return false;
  }
  return true;
}

// Release the uplink and bring the fob's SoftAP back up for the cameras.
static void uplinkDown() {
  wifiDown();
  g_wifiActive = false;
  g_uiDirty = true;          // radio back on the cams -> GRABAR can unlock
  apEnsureUp();
}

// One HTTPS (or http) request to apiBase()+path with the trigger token.
// Returns the HTTP status (or <0 on transport error); fills resp with the body.
// Assumes wifiUp() already succeeded.
static int apiRequest(const char* method, const String& path,
                      const String& body, const char* contentType, String& resp,
                      int attempts = 2, int timeoutMs = 7000) {
  String url = apiBase() + path;
  int code = 0;
  // Retry transient transport/TLS failures (e.g. SSL EOF -29312 when the first
  // request races a freshly-(re)connected stack). A real HTTP response (code>0,
  // even a 4xx) stops the loop; only code<=0 transport errors are retried.
  // attempts/timeoutMs are tunable so interactive callers (kit/table verify) can
  // bound their worst case tighter than the background upload path.
  for (int attempt = 1; attempt <= attempts; attempt++) {
    HTTPClient http;
    WiFiClientSecure tls;
    if (url.startsWith("https")) {
      tls.setInsecure();
      // CRITICAL: the TLS HANDSHAKE has its OWN timeout that DEFAULTS TO 120s and is
      // NOT bounded by http.setTimeout() (which only caps the response READ). A slow
      // Tailscale-funnel handshake was blocking ~7s before the read even started -
      // that's how a "3s-budgeted" verify hung ~10s. Bound the handshake too (arg is
      // in SECONDS, min 1). FLOOR, don't ceil: a ~1.45s interactive budget must cap
      // the handshake at 1s, not round UP to 2s and overrun the 3s verify ceiling.
      // A cold handshake that needs >1s just fails retryably (and the radio is warm
      // for the retry); background uploads pass timeoutMs>=7000 so they're unaffected.
      tls.setHandshakeTimeout(timeoutMs >= 1000 ? (timeoutMs / 1000) : 1);
      tls.setTimeout(timeoutMs);
      http.begin(tls, url);
    }
    else http.begin(url);
    http.setConnectTimeout(timeoutMs);   // bound TCP connect (separate from read)
    http.setTimeout(timeoutMs);          // bound the response read so a hung server can't stall
    http.addHeader("Content-Type", contentType);
    if (g_cfg.upToken.length()) http.addHeader("X-Trigger-Token", g_cfg.upToken);
    code = (!strcmp(method, "GET")) ? http.GET()
                                    : http.POST((uint8_t*)body.c_str(), body.length());
    resp = (code > 0) ? http.getString() : String("");
    http.end();
    Serial.printf("[api] %s %s -> %d (try %d)\n", method, path.c_str(), code, attempt);
    if (code > 0) break;
    delay(500);
  }
  return code;
}

static bool wifiUploadBurst() {
  if (g_cfg.wifiSsid.length() == 0 || g_cfg.uploadUrl.length() == 0) return false;
  if (g_cfg.ordinal == 0 && g_upOff == 0) return true; // no episodes yet; avoid noisy read-open failures
  // Read the new bytes under the FS lock, then RELEASE it before the network
  // POST so a concurrent episode append (loop / button / CE81 callback) is never
  // blocked on the multi-second upload.
  fsLock();
  File f = LittleFS.open(kEpisodeLogPath, FILE_READ);
  if (!f) { fsUnlock(); return false; }
  size_t total = f.size();
  if (total <= g_upOff) { f.close(); fsUnlock(); return true; }     // nothing new to ship
  f.seek(g_upOff);
  String payload; payload.reserve(total - g_upOff);
  while (f.available()) payload += (char)f.read();
  f.close();
  fsUnlock();

  Serial.printf("[wifi] ship %u new bytes...\n", (unsigned)payload.length());
  if (!uplinkUp(true)) { Serial.println("[wifi] uplink connect failed (check wifi_ssid/wifi_pass)"); return false; }
  String url = g_cfg.uploadUrl;
  if (!url.endsWith("/")) url += "/";
  url += (g_cfg.kitId.length() ? g_cfg.kitId : String("unknown"));
  Serial.printf("[wifi] POST -> %s\n", url.c_str());
  HTTPClient http;
  WiFiClientSecure tls;
  if (url.startsWith("https")) { tls.setInsecure(); http.begin(tls, url); }
  else http.begin(url);
  http.addHeader("Content-Type", "application/x-ndjson");
  if (g_cfg.upToken.length()) http.addHeader("X-Trigger-Token", g_cfg.upToken);
  int code = http.POST((uint8_t*)payload.c_str(), payload.length());
  bool ok = false;
  if (code >= 200 && code < 300) {
    g_upOff = total; g_prefs.putUInt("uploff", g_upOff);
    Serial.printf("[wifi] OK HTTP %d, offset now %u\n", code, (unsigned)g_upOff);
    ok = true;
  } else {
    Serial.printf("[wifi] upload FAILED HTTP %d\n", code);
  }
  http.end();
  uplinkDown();
  return ok;
}

// ---------------------------------------------------------------------------
// Per-cam telemetry (TASK 5): cache + POST. The BLE read of battery/SD is
// gated behind PANTHEON_TELEM_BLE (see the BE80 block) because it cannot be
// validated with the cams off and needs the fob to act as a BLE client on the
// camera's BE80 service. The cache + POST below are LIVE regardless: they always
// carry the online/recording state the fob already knows, so the dashboard gets
// a real per-cam presence/record signal tonight, and battery/SD fill in as soon
// as the BE80 poll is verified + enabled on hardware.
// ---------------------------------------------------------------------------

// refreshLiveTelem: update the LIVE fields (online / recording / serial) of the
// per-side telemetry cache from the OSC camera roster. Each online camera is
// mapped to a side by its serial's position in the allowlist (entry 0 = left,
// 1 = right; the depot locks them in that order); if no allowlist match, falls
// back to roster order. battery/SD are not read in this build (kept at -1).
static void refreshLiveTelem() {
  bool seen[2] = {false, false};
  int fallbackIdx = 0;
  camLock();
  for (int c = 0; c < kSubnetScanMax; c++) {
    if (!g_cam[c].online) continue;
    // serial position in the allowlist -> side index
    int si = -1;
    if (g_cfg.allowlist.length()) {
      String hay = lc(g_cfg.allowlist), needle = lc(g_cam[c].serial);
      int idx = 0, start = 0;
      while (start < (int)hay.length()) {
        int comma = hay.indexOf(',', start); if (comma < 0) comma = hay.length();
        String tok = hay.substring(start, comma); tok.trim();
        if (tok.length()) { if (tok == needle) { si = (idx <= 1) ? idx : -1; break; } idx++; }
        start = comma + 1;
      }
    }
    if (si < 0) si = (fallbackIdx <= 1) ? fallbackIdx : 1;   // roster-order fallback
    fallbackIdx++;
    if (si < 0 || si > 1) continue;
    g_telem[si].online = true;
    g_telem[si].recording = g_anyRec;
    if (g_cam[c].serial.length()) g_telem[si].serial = g_cam[c].serial;
    g_telem[si].lastUpdateMs = millis();
    seen[si] = true;
  }
  camUnlock();
  for (int i = 0; i < 2; i++) {
    if (!seen[i]) { g_telem[i].online = false; g_telem[i].recording = false; }
  }
}

// postCamTelemetry: ship the cached per-cam telemetry to the dashboard over the
// uplink AP. Matches the dashboard contract BYTE-FOR-BYTE:
//   POST /api/cam-telemetry/<kit_id>   header X-Trigger-Token: <upToken>
//   {"kit_id":"..","ts":"..","cams":[{"side":"left","serial":"..",
//     "battery_pct":N,"sd_free_pct":N,"sd_free_mb":N,"sd_total_mb":N,
//     "recording":false,"online":true}, {"side":"right",..}]}
// ts is ISO8601 when the clock is set, else millis() since boot. Caller must be
// idle (the uplink borrow refuses mid-record). Returns true on a 2xx.
static bool postCamTelemetry() {
  if (g_cfg.uploadUrl.length() == 0) return false;
  refreshLiveTelem();   // make sure online/recording are current before shipping
  String ts = isoNow();
  if (ts.length() == 0) ts = String(millis());
  String body = "{";
  body += "\"kit_id\":\"" + jsonEscape(g_cfg.kitId) + "\",";
  body += "\"ts\":\"" + ts + "\",";
  body += "\"cams\":[";
  for (int i = 0; i < 2; i++) {
    if (i) body += ",";
    CamTelem& c = g_telem[i];
    body += "{";
    body += "\"side\":\"" + c.side + "\",";
    body += "\"serial\":\"" + jsonEscape(c.serial) + "\",";
    body += "\"battery_pct\":" + String(c.battery_pct) + ",";
    body += "\"sd_free_pct\":" + String(c.sd_free_pct) + ",";
    body += "\"sd_free_mb\":" + String(c.sd_free_mb) + ",";
    body += "\"sd_total_mb\":" + String(c.sd_total_mb) + ",";
    body += "\"recording\":" + String(c.recording ? "true" : "false") + ",";
    body += "\"online\":" + String(c.online ? "true" : "false");
    body += "}";
  }
  body += "]}";

  if (!uplinkUp(false)) return false;
  String resp;
  String kit = g_cfg.kitId.length() ? g_cfg.kitId : String("unknown");
  int code = apiRequest("POST", "/api/cam-telemetry/" + kit, body, "application/json", resp);
  uplinkDown();
  return code >= 200 && code < 300;
}

// telemetryTick: the idle-only telemetry cadence. Refresh live fields, then POST
// over the uplink AP. NEVER runs mid-record (the caller gates on !g_anyRec).
static void telemetryTick() {
  refreshLiveTelem();
  postCamTelemetry();
}

// ---------------------------------------------------------------------------
// WiFi worker (core 0). All multi-second WiFi work runs HERE, never on the UI
// loop. The loop posts a job to g_wifiQ and keeps sampling touch at 125Hz. Each
// job takes g_wifiMutex so serial diagnostics/manual uploads never collide with
// the background upload/telemetry/help paths.
// ---------------------------------------------------------------------------
static void wifiEnqueue(WifiJobType t) {
  if (!g_wifiQ) return;
  uint8_t j = (uint8_t)t;
  xQueueSend(g_wifiQ, &j, 0);   // non-blocking; if full, drop (the next tick re-queues)
}

// The call-lead POST, run on the worker. Sets the async result the UI overlay
// reads. wifiUp() itself refuses while recording (g_anyRec guard), so a call
// made mid-take is logged locally and reported as "saved" without touching WiFi.
static void doHelpPost() {
  int code = -1;
  wifiLock();
  // Borrow the radio for the uplink AP (the cameras are briefly unreachable). The
  // worker runs on core 0 and NEVER blocks the touch loop. NTP skipped so the ping
  // is ASAP (clock syncs on the next upload). uplinkUp() refuses mid-record, so a
  // call made during a take is logged locally and ships with the episode log.
  if (uplinkUp(false, 2500)) {
    JsonDocument doc;
    doc["kit_id"] = g_cfg.kitId;
    doc["operator_id"] = g_cfg.operatorId;
    doc["station"] = g_cfg.station;
    String body; serializeJson(doc, body);
    String resp;
    code = apiRequest("POST", "/api/help", body, "application/json", resp, 3, 6000);
    uplinkDown();
  }
  wifiUnlock();
  g_helpCode = code;
  g_helpDone = true;
}

static void wifiTask(void* arg) {
  (void)arg;
  uint8_t job;
  for (;;) {
    if (xQueueReceive(g_wifiQ, &job, portMAX_DELAY) != pdTRUE) continue;
    switch ((WifiJobType)job) {
      case WJOB_UPLOAD:
        wifiLock(); wifiUploadBurst(); wifiUnlock();
        break;
      case WJOB_TELEM:
#ifdef PANTHEON_TELEM_RELAY
        wifiLock(); telemetryTick(); wifiUnlock();
#endif
        break;
      case WJOB_HELP:
        doHelpPost();
        break;
      case WJOB_WIFIDOWN:
        // Release any uplink borrow and return to the camera hub AP.
        wifiLock(); uplinkDown(); wifiUnlock();
        break;
    }
  }
}

// ---------------------------------------------------------------------------
// Discovery worker (core 0). Keeps the radio associated to the camera hub AP and
// periodically re-probes the hub subnet over OSC so g_connCount/g_cam track which
// cameras are reachable. Skipped while recording (the trigger path owns the radio
// and we don't want a scan delaying the stop) and while the uplink borrow is up.
// Takes the WiFi mutex so it never collides with an upload/telemetry/help window.
// ---------------------------------------------------------------------------
// Defined below; forward-declared so the discovery worker (which appears first)
// can reference them.
static void discoverCams();
static void publishStatus();
static void refreshSidecarsPending();
static const uint32_t kDiscoveryPeriodMs = 5000;   // steady-state idle subnet rescan cadence
static const uint32_t kDiscoveryFastMs   = 700;    // greedy bring-up when <2 cams online

// GENTLE-OSC tuning (2026-06-22). The X3's OSC server (cherokee) over the fob's
// 2.4GHz SoftAP is fragile under rapid/concurrent TCP: a burst of /osc/state +
// startCapture across both cams momentarily DROPS the marginal links (proven on
// bench - even a read-only state burst dropped both cams). So EVERY fob->cam OSC
// request is serialized (one cam at a time) and followed by a settle gap, and the
// no-SD guard trusts the discovery poll's last-known cardOk instead of firing a
// fresh blocking query at press time (one timeout there = a spurious "REVISA SD").
static const uint32_t kOscGapMs    = 150;     // settle after each OSC req (never back-to-back)
static const uint32_t kCardPollMs  = 12000;   // discovery refreshes each cam's cardOk this often
static const uint32_t kCardFreshMs = 30000;   // guard trusts last-known cardOk up to this age
// ONLINE grace (2026-06-22): a single missed /osc/info probe over the marginal
// SoftAP must NOT flip a cam offline (it flapped cams between 1 and 2). A cam that
// answered within this window stays counted online through a transient miss - same
// "ride out transient gaps" logic as the BLE supervision idle timeout. Kept short
// so a GENUINELY dropped cam still clears within ~2 sweeps (else GRABAR proceeds on
// a dead cam -> startCapture short -> rollback/ERROR).
static const uint32_t kOnlineGraceMs = 12000;
static void discoveryTask(void* arg) {
  (void)arg;
  for (;;) {
    if (!g_anyRec && !g_wifiActive) {
      wifiLock();
      apEnsureUp();       // (re)assert our SoftAP so the cameras can stay joined
      discoverCams();
      // If a prior take's sidecars are still owed, re-check them cheaply so the
      // MAIN "GUARDANDO" lock clears itself once discardd has written them.
      refreshSidecarsPending();
      wifiUnlock();
      publishStatus();    // refresh the board with the new online count
    }
    uint32_t waitMs = (g_connCount < kMinCams) ? kDiscoveryFastMs : kDiscoveryPeriodMs;
    // Sleep in short slices so AP connect/disconnect events can kick discovery NOW.
    for (uint32_t slept = 0; slept < waitMs; slept += 100) {
      if (g_discoveryKick) break;
      delay(100);
    }
    g_discoveryKick = false;
  }
}

// ---------------------------------------------------------------------------
// OSC (HTTP) client + telnet sidecar writer - the direct port of coordinator.py
// ---------------------------------------------------------------------------
// One HTTP request to a camera's OSC endpoint (port 80). `post` true => POST with
// `body` (json); false => GET. Retries only transport errors (code<=0); a real
// HTTP status (even 4xx) stops. Returns true on a 2xx and fills `out`.
static bool oscHttp(const String& ip, const String& path, bool post,
                    const String& body, String& out, int timeoutMs, int tries) {
  for (int t = 0; t < tries; t++) {
    HTTPClient http; WiFiClient client;
    String url = "http://" + ip + ":" + String(kCamHttpPort) + path;
    if (!http.begin(client, url)) { delay(150); continue; }
    http.setConnectTimeout(timeoutMs);
    http.setTimeout(timeoutMs);
    int code;
    if (post) {
      http.addHeader("Content-Type", "application/json");
      code = http.POST((uint8_t*)body.c_str(), body.length());
    } else {
      code = http.GET();
    }
    out = (code > 0) ? http.getString() : String("");
    http.end();
    // Settle gap after EVERY request: the X3 cherokee is single-threaded and drops
    // the SoftAP link if hit back-to-back, so guarantee breathing room before the
    // caller (or the retry below) opens the next TCP session to any camera.
    delay(kOscGapMs);
    if (code >= 200 && code < 300) return true;
    if (code > 0) { Serial.printf("[osc] %s -> HTTP %d\n", path.c_str(), code); return false; }
    delay(250);
  }
  return false;
}

// OSC commands/execute {"name":..,"parameters":..}. params may be empty.
static bool oscExec(const String& ip, const char* name, const String& params,
                    String& out, int timeoutMs = 8000, int tries = 3) {
  String body = String("{\"name\":\"") + name + "\"";
  if (params.length()) body += ",\"parameters\":" + params;
  body += "}";
  return oscHttp(ip, kOscExecPath, true, body, out, timeoutMs, tries);
}

// ★ OSC OFF-BY-ONE WORKAROUND (proven on hardware 2026-06-22). The X3's OSC server
// returns each HTTP response ONE REQUEST BEHIND: the COMMAND executes (the camera
// really does start/stop recording - verified by a 63MB clip landing on the card),
// but its result arrives as the response to a SUBSEQUENT request. A bare
// startCapture therefore returns a STALE body, so the fob couldn't confirm the start
// or read stopCapture's clip URL ("clip=(none)", spurious HTTP 400). Workaround: after
// POSTing the command, flush with cheap /osc/state reads until a response carries our
// command's "name" - THAT body is the command's true result. Self-aligning (reads
// until names match), so it survives a queue deeper than one. Fills `result`.
static bool oscExecConfirmed(const String& ip, const char* name, const String& params,
                             String& result, int timeoutMs = 8000, int flushes = 6) {
  String body = String("{\"name\":\"") + name + "\"";
  if (params.length()) body += ",\"parameters\":" + params;
  body += "}";
  String tmp;
  oscHttp(ip, kOscExecPath, true, body, tmp, timeoutMs, 1);   // send command; its reply is stale
  String needle = String("\"") + name + "\"";
  for (int i = 0; i < flushes; i++) {
    if (oscHttp(ip, kOscStatePath, true, "{}", tmp, timeoutMs, 1) && tmp.indexOf(needle) >= 0) {
      result = tmp; return true;                              // matched our command's true result
    }
    delay(kOscGapMs);
  }
  result = tmp;
  return false;
}

// /osc/info (GET): identify a camera. Fills serial + firmware. Fast, single try.
static bool oscInfo(const String& ip, String& serial, String& fw, int timeoutMs = 1500) {
  String out;
  if (!oscHttp(ip, kOscInfoPath, false, "", out, timeoutMs, 1)) return false;
  JsonDocument doc;
  if (deserializeJson(doc, out)) return false;
  serial = String((const char*)(doc["serialNumber"] | ""));
  fw     = String((const char*)(doc["firmwareVersion"] | ""));
  return serial.length() > 0;
}

// /osc/state (POST {}): returns cardOk (cardState=="pass") + battery 0..100.
static bool oscState(const String& ip, bool& cardOk, int& batteryPct, int timeoutMs = 6000) {
  String out;
  // Lag-tolerant (off-by-one): flush until a response actually carries a state body
  // (_cardState), skipping any stale lagged response from a prior command.
  bool got = false;
  for (int i = 0; i < 5; i++) {
    if (oscHttp(ip, kOscStatePath, true, "{}", out, timeoutMs, 1) && out.indexOf("_cardState") >= 0) {
      got = true; break;
    }
    delay(kOscGapMs);
  }
  if (!got) return false;
  JsonDocument doc;
  if (deserializeJson(doc, out)) return false;
  const char* cs = doc["state"]["_cardState"] | "";
  cardOk = (strcmp(cs, "pass") == 0);
  float b = doc["state"]["batteryLevel"] | -1.0f;
  batteryPct = (b >= 0) ? (int)(b * 100.0f + 0.5f) : -1;
  return true;
}

// ★ FIRE-AND-FORGET OSC (2026-06-23). Deliver ONE command and do NOT wait for the
// response. WHY: the X3 returns responses one request behind (off-by-one), so the
// reply to THIS request never comes until the NEXT one - meaning HTTPClient's POST
// blocked the FULL timeout (up to 8s) waiting for a reply that wasn't coming, which
// serialized multi-cam start/stop by ~8s/cam (the stop-stagger). The COMMAND itself
// executes on receipt (proven: clean startCapture lands a clip), so we just send the
// raw request, flush + brief grace so the cam reads it, then close - no read. Each
// fire is now ~connect+~120ms instead of up to 8s, so both cams start/stop within ms.
// Still ONE request per cam, fully serialized under wifiLock (no concurrent OSC).
// Clip filename is recovered over TELNET, never from the (useless) OSC response.
static bool oscSendNoWait(const String& ip, const String& body, int connectMs = 1500) {
  WiFiClient c;
  if (!c.connect(ip.c_str(), kCamHttpPort, connectMs)) { delay(kOscGapMs); return false; }
  String req = String("POST ") + kOscExecPath + " HTTP/1.1\r\n"
             + "Host: " + ip + ":" + String(kCamHttpPort) + "\r\n"
             + "Content-Type: application/json\r\n"
             + "Content-Length: " + String(body.length()) + "\r\n"
             + "Connection: close\r\n\r\n" + body;
  c.print(req);
  c.flush();          // push the bytes onto the wire
  delay(120);         // let the cam receive + read the full request before we close
  c.stop();           // graceful close (FIN) - cam has the command; we don't read the reply
  delay(kOscGapMs);
  return true;        // delivered (connected + wrote)
}

static bool oscFire(const String& ip, const char* name) {
  bool ok = oscSendNoWait(ip, String("{\"name\":\"") + name + "\"}");
  Serial.printf("[fire] %s %s -> sent=%d\n", ip.c_str(), name, ok ? 1 : 0);
  return ok;
}

static bool oscStartCapture(const String& ip) { return oscFire(ip, "camera.startCapture"); }
static bool oscStopCapture(const String& ip)  { return oscFire(ip, "camera.stopCapture"); }

// ★ ARM VIDEO MODE (proven fix 2026-06-22). The X3 boots refusing OSC startCapture
// ("disabledCommand: Currently camera is not in video mode") even though the UI shows
// video; camera.setOptions captureMode=video first ARMS it. Sent fire-and-forget too.
static bool oscArmVideo(const String& ip) {
  bool ok = oscSendNoWait(ip, "{\"name\":\"camera.setOptions\",\"parameters\":{\"options\":{\"captureMode\":\"video\"}}}");
  Serial.printf("[fire] %s setOptions(captureMode=video) -> sent=%d\n", ip.c_str(), ok ? 1 : 0);
  return ok;
}

// Minimal telnet client (mirrors coordinator.py telnet_cmd): refuse all option
// negotiation, run one command, return its stdout. The camera runs a passwordless
// root busybox telnetd on :23. Returns the captured output up to a done marker.
static bool telnetCmd(const String& ip, const String& cmd, String& out, int timeoutMs = 15000) {
  WiFiClient s;
  if (!s.connect(ip.c_str(), kCamTelnetPort, timeoutMs)) return false;
  s.setTimeout(timeoutMs);
  uint32_t deadline = millis() + timeoutMs;
  // drain the login/negotiation banner, answering IAC DO/WILL with WONT/DONT.
  auto pumpNegotiate = [&]() {
    uint8_t resp[64]; int rn = 0;
    while (s.available()) {
      int b = s.read();
      if (b == 0xFF && s.available() >= 2) {
        int c = s.read(), opt = s.read();
        if (rn + 3 <= (int)sizeof(resp)) {
          if (c == 0xFD) { resp[rn++] = 0xFF; resp[rn++] = 0xFC; resp[rn++] = opt; }       // DO -> WONT
          else if (c == 0xFB) { resp[rn++] = 0xFF; resp[rn++] = 0xFE; resp[rn++] = opt; }  // WILL -> DONT
        }
      }
    }
    if (rn) s.write(resp, rn);
  };
  delay(400);
  pumpNegotiate();
  String full = cmd + "\necho __X3_DONE__\n";
  s.print(full);
  out = "";
  while (millis() < deadline) {
    while (s.available()) {
      int b = s.read();
      if (b == 0xFF && s.available() >= 2) { s.read(); s.read(); continue; }  // skip IAC seq
      out += (char)b;
    }
    if (out.indexOf("__X3_DONE__") >= 0) break;
    if (!s.connected() && !s.available()) break;
    delay(20);
  }
  s.stop();
  int m = out.indexOf("__X3_DONE__");
  if (m >= 0) out = out.substring(0, m);
  return true;
}

// Write an arbitrary file onto a camera's SD card over telnet using a mkdir -p +
// quoted heredoc (nothing is shell-expanded on the camera). Returns true once the
// camera echoes WROTE. Used to inject the discardd env files
// (current_assignment.env / current_stop.env) onto each card; the per-clip
// .pantheon.json sidecar itself is written BY discardd on-camera, not by the fob.
static bool telnetWriteFile(const String& ip, const String& fullPath, const String& body) {
  int slash = fullPath.lastIndexOf('/');
  String dir = (slash > 0) ? fullPath.substring(0, slash) : String("/");
  String cmd = "mkdir -p '" + dir + "'\ncat > '" + fullPath + "' <<'X3EOF'\n" + body +
               "\nX3EOF\nsync\necho WROTE " + fullPath;
  for (int attempt = 0; attempt < 3; attempt++) {
    String out;
    if (telnetCmd(ip, cmd, out) && out.indexOf("WROTE") >= 0) return true;
    delay(400);
  }
  return false;
}

// ---------------------------------------------------------------------------
// Camera discovery + trigger orchestration (the on-device coordinator)
// ---------------------------------------------------------------------------
// (kDiscoveryPeriodMs is defined above, before discoveryTask which uses it.)

// Rebuild the camera roster from the SoftAP's DHCP/association table - NO OSC.
//
// ★ ROOT-CAUSE FIX (2026-06-22): the old discoverCams PROBED each camera over OSC
// (/osc/info + /osc/state) every few seconds. That continuous background OSC is what
// CRASHED the X3's single-threaded cherokee server: the fob serial log showed the
// "Connection reset by peer" storm BEGINNING BEFORE GRABAR was ever pressed - cherokee
// was already dead from discovery polling, while a 12s grace window still reported
// cams=2 on screen. Pressing record then hit a dead server (startCapture 200 but no
// recording; stopCapture HTTP 400). The cameras NEVER lost WiFi - only their OSC died.
//
// The fob is the DHCP server, so association is knowable with ZERO OSC: read the AP
// station list (MAC+leased IP) straight from esp_netif. The ONLY OSC the fob now ever
// emits is at GRABAR/DETENER (the guard's one oscState + startCapture/stopCapture),
// exactly like the Step-1 proof that recorded a real clip. No background OSC, ever.
// Runs on the discovery worker (core 0). Caller holds the WiFi lock.
static void discoverCams() {
  if (!apEnsureUp()) return;
  wifi_sta_list_t       wl;
  esp_netif_sta_list_t  nl;
  bool got = (esp_wifi_ap_get_sta_list(&wl) == ESP_OK) &&
             (esp_netif_get_sta_list(&wl, &nl) == ESP_OK);
  int online = 0;
  camLock();
  for (int i = 0; i < kSubnetScanMax; i++) g_cam[i].online = false;
  if (got) {
    for (int s = 0; s < nl.num && online < kSubnetScanMax; s++) {
      uint32_t ip = nl.sta[s].ip.addr;   // lwip stores network byte order; &0xFF == 1st octet
      if (ip == 0) continue;             // associated but no DHCP lease yet - skip
      char buf[16];
      snprintf(buf, sizeof(buf), "%u.%u.%u.%u",
               (unsigned)(ip & 0xFF), (unsigned)((ip >> 8) & 0xFF),
               (unsigned)((ip >> 16) & 0xFF), (unsigned)((ip >> 24) & 0xFF));
      g_cam[online].ip = String(buf);
      g_cam[online].online = true;
      g_cam[online].lastSeenMs = millis();
      online++;
    }
  }
  camUnlock();
  g_connCount = online;
}

// Snapshot the currently-online cameras (ip+serial) for a trigger operation.
struct CamRef { String ip; String serial; };
static int snapshotOnline(CamRef* out, int cap) {
  int n = 0;
  camLock();
  for (int i = 0; i < kSubnetScanMax && n < cap; i++) {
    if (g_cam[i].online) { out[n].ip = g_cam[i].ip; out[n].serial = g_cam[i].serial; n++; }
  }
  camUnlock();
  return n;
}

// Verify the kit's cameras have a usable SD card before a take. Fills nOk/nTot
// (nOk = stations that confirmed a card, nTot = stations probed). Returns true
// when at least kMinCams confirm a card — NOT when every station does (see the
// ghost-station note at the pass condition below).
//
// TIMEOUT-TOLERANT (2026-06-22): the old version did a FRESH blocking oscState()
// per cam right here at press time. Over the marginal SoftAP one such query times
// out intermittently (1-2 of 4 on the bench) - and a single timeout flipped the
// guard false, throwing a spurious "REVISA SD" when the cards were actually fine.
// We now trust the discovery poll's last-known cardOk while it's FRESH, and only
// fall back to ONE gentle fresh read when it's stale - and even that read FAILING
// (transport timeout) does NOT fail the take: we keep the last-known value. A cam
// only blocks when we have a definite, recent not-"pass" reading.
static bool camCardCheckAll(int& nOk, int& nTot) {
  // Card check over TELNET, not OSC. The old oscState probe (and the off-by-one flush
  // workaround) is what crashed the X3 cherokee. The SD is mounted at /tmp/SD0 ONLY
  // when a card is present, so `grep SD0 /proc/mounts` over telnet (port 23) is a
  // reliable, cherokee-safe readiness check that also satisfies the "never startCapture
  // a card-less cam (it crashes cherokee)" rule. wifiLock for serialization with the
  // discovery worker; wifiLock outer, camLock inner (same order as discovery).
  // FAST + RETRY-TOLERANT (2026-06-23): short 1500ms telnet timeout (was 6000) so a
  // momentarily-slow cam can't add seconds to the start, and a single RETRY so one slow
  // response doesn't throw a spurious "REVISA SD" (the false-positive Victor hit). discardd
  // already gates on a present card (card_ready.json) + locks video mode, so this is now a
  // light backstop against a truly card-less cam, not the primary gate.
  wifiLock();
  CamRef c[kSubnetScanMax];
  int n = snapshotOnline(c, kSubnetScanMax);
  nOk = 0; nTot = n;
  for (int i = 0; i < n; i++) {
    bool ok = false;
    for (int try_ = 0; try_ < 2 && !ok; try_++) {
      String out;
      if (telnetCmd(c[i].ip, "grep -q SD0 /proc/mounts && echo PCARDOK", out, 1500) &&
          out.indexOf("PCARDOK") >= 0) ok = true;
    }
    if (ok) nOk++;
    delay(kOscGapMs);
  }
  // PASS when at least the kit's kMinCams cameras confirm a card — NOT every
  // associated station. A camera whose battery was pulled dies without a clean
  // Wi-Fi disconnect, so it lingers as a GHOST in the AP station table for ~18h
  // (kApInactiveSec) with a now-dead IP; under the old `nOk == nTot` its telnet
  // timed out and threw a false "REVISA SD" until the fob was power-cycled (hit in
  // live collection 2026-06-24, kit_57 battery swap). Counting only real cards
  // makes a ghost (and a phantom Mac on the AP) harmless. A genuinely card-less
  // real camera still blocks, because nOk then stays below kMinCams. (2026-06-24)
  bool allPass = nOk >= kMinCams;
  wifiUnlock();
  return allPass;
}

static const char* kCamPantheonDir = "/tmp/SD0/PANTHEON";  // discardd ROOT on the card

// Mint a take's shared bimanual_episode_id. SAME value written to BOTH cams so
// ingest pairs the two clips by exact id. Unique per take across fob swaps:
// fob hwid + per-boot session + the prospective ordinal.
static String makeBimanualId(uint32_t prospectiveOrdinal) {
  return fobHwId() + "-" + g_fobSession + "-" + String(prospectiveOrdinal);
}

// Build current_assignment.env body for discardd. Identity (camera_id/kit_id/
// side) is NEVER here - discardd reads that from NAND. We only inject the
// per-take assignment + pairing + capture-stack provenance.
static String buildAssignmentEnv(const String& bimanualId, const String& episodeId) {
  String b;
  b += "OPERATOR_ID=\""        + shClean(g_cfg.operatorId)   + "\"\n";
  b += "OPERATOR_NAME=\""      + shClean(g_cfg.operatorName) + "\"\n";
  b += "STATION_ID=\""         + shClean(g_cfg.station)      + "\"\n";
  b += "PROMPT=\""             + shClean(g_cfg.prompt)       + "\"\n";
  b += "TASK_NAME=\""          + shClean(g_cfg.prompt)       + "\"\n";
  b += "SESSION_ID=\""         + shClean(g_fobSession)       + "\"\n";
  b += "SITE_ID=\""            + shClean(g_cfg.siteId)       + "\"\n";
  b += "EPISODE_ID=\""         + shClean(episodeId)          + "\"\n";
  b += "BIMANUAL_EPISODE_ID=\""+ shClean(bimanualId)         + "\"\n";
  b += "FOB_ID=\""             + shClean(fobHwId())          + "\"\n";
  b += "FOB_BUILD=\""          + shClean(String(FOB_FW_VERSION)) + "\"\n";
  b += "ASSIGNMENT_SOURCE=\"fob_wifi\"\n";
  return b;
}

// Build current_stop.env body. Bound to the take by EP_BIMANUAL_EPISODE_ID so
// discardd never applies a stale stop file to the wrong clip. Timing is per-cam.
// archive=1 marks the take for the archive bucket (operator DESCARTAR) WITHOUT
// deleting it on-card.
static String buildStopEnv(const String& bimanualId, const String& stopReason,
                           int skewMs, uint32_t startedUnix, uint32_t stoppedUnix,
                           int archive) {
  String b;
  b += "EP_BIMANUAL_EPISODE_ID=\"" + shClean(bimanualId)  + "\"\n";
  b += "STOP_REASON=\""            + shClean(stopReason)   + "\"\n";
  b += "START_SKEW_MS=\""          + String(skewMs)        + "\"\n";
  b += "CAM_STARTED_UNIX=\""       + String(startedUnix)   + "\"\n";
  b += "CAM_STOPPED_UNIX=\""       + String(stoppedUnix)   + "\"\n";
  b += "ARCHIVE=\""                + String(archive)       + "\"\n";
  return b;
}

// Derive the discardd sidecar path for an OSC clip url. discardd names the
// sidecar VID_<ts>_<seq>.pantheon.json (no lens index) in DCIM, regardless of
// which lens file (00/10) the OSC url points at. Returns "" if it can't parse.
static String sidecarPathForClip(const String& clip) {
  String base = clip.substring(clip.lastIndexOf('/') + 1);   // VID_<date>_<time>_<NN>_<seq>.insv
  if (!base.startsWith("VID_")) return String();
  // tokens: VID, <date>, <time>, <NN>, <seq>.<ext>
  int p1 = base.indexOf('_', 4);            // after VID_<date>
  int p2 = (p1 > 0) ? base.indexOf('_', p1 + 1) : -1;   // after <time>
  int p3 = (p2 > 0) ? base.indexOf('_', p2 + 1) : -1;   // after <NN>
  if (p1 < 0 || p2 < 0 || p3 < 0) return String();
  String ts  = base.substring(4, p2);       // <date>_<time>
  String rest = base.substring(p3 + 1);     // <seq>.<ext>
  int dot = rest.indexOf('.');
  String seq = (dot > 0) ? rest.substring(0, dot) : rest;
  if (ts.length() == 0 || seq.length() == 0) return String();
  return String(kCamSdRoot) + "/DCIM/Camera01/VID_" + ts + "_" + seq + ".pantheon.json";
}

// Inject current_assignment.env on EVERY online camera, then fire startCapture.
// Records per-cam start time + computes the cross-cam start skew. Populates
// g_take/g_takeN. Returns the count that acked startCapture.
static int camStartAll(const String& bimanualId, const String& episodeId) {
  // Hold wifiLock across the ENTIRE start burst (telnet env-writes + startCapture to
  // both cams) so the discovery task cannot poll OSC concurrently - concurrent TCP to
  // the X3 cherokee is the proven crash trigger. This is the gap that crashed it: the
  // trigger fired before g_anyRec was set, while discovery was still polling.
  wifiLock();
  uint32_t _t0 = millis();
  CamRef c[kSubnetScanMax];
  int n = snapshotOnline(c, kSubnetScanMax);
  g_takeN = n;
  for (int i = 0; i < n; i++) {
    g_take[i].ip = c[i].ip; g_take[i].serial = c[i].serial;
    g_take[i].clip = ""; g_take[i].startedUnix = 0; g_take[i].startedMs = 0;
    g_take[i].stoppedUnix = 0; g_take[i].started = false; g_take[i].stopped = false;
    g_take[i].sidecarOk = false;
  }
  // Assignment FIRST (so discardd has the label for the clip it's about to make).
  // SERIALIZED + SPACED: telnet write then a settle gap, one cam at a time.
  String env = buildAssignmentEnv(bimanualId, episodeId);
  for (int i = 0; i < n; i++) {
    String path = String(kCamPantheonDir) + "/current_assignment.env";
    if (!telnetWriteFile(c[i].ip, path, env))
      Serial.printf("[inject] %s assignment FAILED\n", c[i].ip.c_str());
    delay(kOscGapMs);
  }
  Serial.printf("[t] assignment-telnet phase = %lums\n", (unsigned long)(millis() - _t0));
  delay(kOscGapMs);   // let the links breathe between the telnet phase and OSC start
  // No per-take arm: discardd locks video mode on the camera.
  // SYNCHRONIZED START: open a socket to each cam (connects are serial - a slow cam is
  // fine), THEN write startCapture to ALL back-to-back so both cameras receive it within
  // ~ms instead of up to ~1s apart. Safe: each request hits a DIFFERENT camera's cherokee
  // (the crash was only ever concurrent requests to the SAME cam), so near-simultaneous
  // CROSS-cam delivery is fine - and it's what gives tight start sync.
  uint32_t _tS = millis();
  WiFiClient scl[kSubnetScanMax];
  bool conn[kSubnetScanMax];
  for (int i = 0; i < n; i++) conn[i] = scl[i].connect(c[i].ip.c_str(), kCamHttpPort, 1500);
  uint32_t mark = millis();
  const char* sbody = "{\"name\":\"camera.startCapture\"}";
  for (int i = 0; i < n; i++) {
    if (!conn[i]) continue;
    String req = "POST " + String(kOscExecPath) + " HTTP/1.1\r\nHost: " + c[i].ip +
                 "\r\nContent-Type: application/json\r\nContent-Length: " + String((int)strlen(sbody)) +
                 "\r\nConnection: close\r\n\r\n" + sbody;
    scl[i].print(req);                 // <-- back-to-back writes = synchronized delivery
  }
  for (int i = 0; i < n; i++) if (conn[i]) scl[i].flush();
  delay(120);                          // grace: let the cams read the full request before close
  int started = 0;
  for (int i = 0; i < n; i++) {
    if (conn[i]) {
      scl[i].stop();
      g_take[i].started = true;
      g_take[i].startedMs = mark;
      g_take[i].startedUnix = (uint32_t)time(nullptr);
      started++;
    }
  }
  g_startSkewMs = 0;                    // both startCaptures delivered together
  Serial.printf("[t] sync-start phase = %lums ; started=%d ; camStartAll total = %lums\n",
                (unsigned long)(millis() - _tS), started, (unsigned long)(millis() - _t0));
  wifiUnlock();
  return started;
}

// Stop every camera in the take, read back each clip filename, and inject
// current_stop.env (outcome + per-cam timing) onto each card. The fob does NOT
// write the sidecar - discardd reads these env files and stamps it. Returns the
// number of cameras that acked stopCapture; `stopEnvs` gets the count of cards
// that took the stop file.
static int camStopAll(const String& stopReason, int& stopEnvs) {
  // Same mutual exclusion as camStartAll: the stop burst must not overlap a discovery
  // OSC sweep, or the concurrent TCP crashes cherokee right as the take ends.
  //
  // TWO PASSES to kill the stop stagger. The old single-pass loop did the ENTIRE stop
  // sequence (stopCapture -> 400ms finalize -> telnet ls -> telnet stop-env) for cam[0]
  // before even sending cam[1]'s stopCapture, so the first cam ended several seconds
  // before the second. Now PASS 1 stops BOTH cams back-to-back (only the OSC gap apart,
  // ~150ms), then PASS 2 does the slower telnet bookkeeping - whose stagger is harmless
  // because recording already stopped on both. Still fully serialized (no concurrent OSC).
  wifiLock();
  int stopped = 0; stopEnvs = 0;

  // PASS 1: stop every camera near-simultaneously (just the OSC stopCapture).
  for (int i = 0; i < g_takeN; i++) {
    if (!oscStopCapture(g_take[i].ip)) continue;   // off-by-one body ignored; transport-only
    g_take[i].stopped = true;
    g_take[i].stoppedUnix = (uint32_t)time(nullptr);
    stopped++;
  }
  // Let the clips finalize on-card once (not per-cam) before we read filenames.
  delay(400);

  // PASS 2: per-cam telnet bookkeeping (clip filename + current_stop.env). Any stagger
  // here is invisible - both cameras already stopped recording in PASS 1.
  for (int i = 0; i < g_takeN; i++) {
    if (!g_take[i].stopped) continue;
    // Recover the clip filename over TELNET (the OSC stopCapture response is off-by-one).
    String clip, lsout;
    if (telnetCmd(g_take[i].ip,
          "ls -t /tmp/SD0/DCIM/Camera01/ 2>/dev/null | grep VID_ | head -1", lsout, 8000)) {
      int v = lsout.indexOf("VID_");
      if (v >= 0) {
        int e = v;
        while (e < (int)lsout.length()) {
          char ch = lsout[e];
          if (ch == '\r' || ch == '\n' || ch == ' ' || ch == '\t') break;
          e++;
        }
        clip = lsout.substring(v, e);
      }
    }
    g_take[i].clip = clip;
    if (clip.length()) g_sidecarsPending = true;   // a clip exists; its sidecar is owed
    camLock();
    for (int k = 0; k < kSubnetScanMax; k++) if (g_cam[k].ip == g_take[i].ip) g_cam[k].lastClip = clip;
    camUnlock();
    String body = buildStopEnv(g_bimanualId, stopReason, g_startSkewMs,
                               g_take[i].startedUnix, g_take[i].stoppedUnix, 0);
    String path = String(kCamPantheonDir) + "/current_stop.env";
    if (telnetWriteFile(g_take[i].ip, path, body)) {
      stopEnvs++;
      Serial.printf("[osc] %s stop-env OK clip=%s\n", g_take[i].ip.c_str(),
                    clip.length() ? clip.c_str() : "(none)");
    } else {
      Serial.printf("[osc] %s stop-env FAILED clip=%s\n", g_take[i].ip.c_str(),
                    clip.length() ? clip.c_str() : "(none)");
    }
    delay(kOscGapMs);
  }
  wifiUnlock();
  return stopped;
}

// Race gate: confirm discardd has written the .pantheon.json sidecar for every
// clip of the JUST-finished take before allowing the next START. discardd stamps
// the sidecar a moment after stopCapture; starting the next take too fast could
// otherwise leave the previous clip unlabeled. Polls each card over telnet up to
// blockMs. Marks g_take[i].sidecarOk. Returns true iff all clipped cams are ready.
static bool priorSidecarsReady(uint32_t blockMs) {
  if (g_takeN == 0) { g_sidecarsPending = false; return true; }
  uint32_t deadline = millis() + blockMs;
  for (;;) {
    bool allOk = true; bool anyToCheck = false;
    for (int i = 0; i < g_takeN; i++) {
      if (g_take[i].clip.length() == 0) continue;   // nothing recorded -> nothing to wait on
      anyToCheck = true;
      if (g_take[i].sidecarOk) continue;
      String sc = sidecarPathForClip(g_take[i].clip);
      if (sc.length() == 0) { g_take[i].sidecarOk = true; continue; }  // unparseable -> don't block
      String out;
      if (telnetCmd(g_take[i].ip, "test -f '" + sc + "' && echo SC_OK || echo SC_NO", out)
          && out.indexOf("SC_OK") >= 0) {
        g_take[i].sidecarOk = true;
      } else {
        allOk = false;
      }
    }
    if (!anyToCheck || allOk) { g_sidecarsPending = false; return true; }
    if (millis() >= deadline) { g_sidecarsPending = true; return false; }
    delay(150);
  }
}

// One non-blocking sidecar-readiness pass for the idle discovery worker: re-checks
// the pending take's sidecars ONCE (no wait loop) so the MAIN "GUARDANDO" lock
// clears on its own a few seconds after discardd writes them, with no operator
// action. Cheap because it only runs while g_sidecarsPending is already true.
static void refreshSidecarsPending() {
  if (!g_sidecarsPending) return;
  bool was = g_sidecarsPending;
  priorSidecarsReady(0);
  if (was != g_sidecarsPending) g_forceRender = true;   // lock cleared -> redraw MAIN
}

// Mark the just-finished take for ARCHIVE on each card WITHOUT deleting it. We
// keep the footage so we can see exactly what was discarded and archive it after
// ingest. Re-write current_stop.env with stop_reason=operator_discard + ARCHIVE=1
// (same bimanual id so discardd binds it to this take), then fire
// /tmp/archive.trigger so discardd re-stamps the sidecar archive=1. With on-card
// bimanual-id pairing the old "void the fob ordinal" trick no longer hides a clip
// from ingest, so the disposition must travel on the card. Best-effort; the fob's
// LittleFS delete line remains the off-card record.
static int camMarkArchive() {
  int fired = 0;
  for (int i = 0; i < g_takeN; i++) {
    if (g_take[i].clip.length() == 0) continue;   // nothing recorded on this cam
    String body = buildStopEnv(g_bimanualId, "operator_discard", g_startSkewMs,
                               g_take[i].startedUnix, g_take[i].stoppedUnix, 1);
    String path = String(kCamPantheonDir) + "/current_stop.env";
    bool envOk = telnetWriteFile(g_take[i].ip, path, body);
    String out;
    bool trigOk = telnetCmd(g_take[i].ip, "touch /tmp/archive.trigger && echo ARC_OK", out)
                  && out.indexOf("ARC_OK") >= 0;
    if (envOk && trigOk) {
      fired++;
      Serial.printf("[osc] %s archive mark fired (kept)\n", g_take[i].ip.c_str());
    } else {
      Serial.printf("[osc] %s archive mark FAILED env=%d trig=%d\n",
                    g_take[i].ip.c_str(), (int)envOk, (int)trigOk);
    }
  }
  return fired;
}

// Toggle recording from the fob: send the shutter to both cams AND flip the
// fob's authoritative record state + episode log. Used by the touchscreen and
// the physical button. The cameras report rec=1 on start but never a clean rec=0
// on stop, so the fob owns the toggle rather than inferring stop from the cams.
static void publishStatus();   // fwd (defined below)
static String buildStatusJson();  // fwd (defined below) - serial status echo
static void renderUI();        // fwd (defined below) - lets START flip to DETENER
                               // BEFORE the blocking logStart() flash/NVS write
#ifdef PANTHEON_HAS_TFT
static void confirmSplash(uint16_t bg, const char* big, const char* sub);  // fwd (START-fail alarm)
#endif
static volatile uint32_t g_startUnix = 0;   // START wallclock (unix) for the sidecar stamp
static void fireShutterToggle() {
  if (!g_anyRec) {
    // START GATE: refuse unless both cams of the kit are online over OSC. A
    // one-sided / phantom start would record into the void and mislabel.
    if (g_wifiActive) {
      Serial.println("[trigger] BLOCKED start: radio borrowed by uplink");
      g_lastBlockedMs = millis();
      g_forceRender = true;
      publishStatus();
      return;
    }
    if (g_connCount < kMinCams) {
      Serial.printf("[trigger] BLOCKED start: only %d/%d cams online\n", (int)g_connCount, kMinCams);
      g_lastBlockedMs = millis();
      g_forceRender = true;
      publishStatus();
      return;
    }
    // NO-SD GUARD (pre-start): every online camera must report cardState=="pass".
    // An SD-less / full X3 errors and never records, so check the cards over OSC
    // BEFORE we start - the on-device equivalent of coordinator.py's card check.
    int nOk = 0, nTot = 0;
    if (!camCardCheckAll(nOk, nTot)) {
      Serial.printf("[trigger] BLOCKED start: card check %d/%d pass\n", nOk, nTot);
      g_lastBlockedMs = millis();
#ifdef PANTHEON_HAS_TFT
      confirmSplash(tft.color565(205, 35, 35), "REVISA SD", "Tarjeta no lista");
      g_screen = SCREEN_MAIN;
#endif
      g_forceRender = true;
      publishStatus();
      return;
    }
    // RACE GATE: the previous take's clips must have their discardd
    // .pantheon.json sidecars on-card before we start the next take. Starting too
    // fast could leave the prior clip unlabeled. Wait briefly; refuse if not ready.
    if (!priorSidecarsReady(4000)) {
      Serial.println("[trigger] BLOCKED start: prior sidecar(s) not yet written");
      g_lastBlockedMs = millis();
#ifdef PANTHEON_HAS_TFT
      confirmSplash(tft.color565(205, 35, 35), "ESPERA", "Guardando toma previa");
      g_screen = SCREEN_MAIN;
#endif
      g_forceRender = true;
      publishStatus();
      return;
    }
    // Stamp the take from the fob clock (X3 clocks are unreliable) and fire.
    // Mint the shared L/R pairing id + episode id for THIS take (prospective
    // ordinal; logStart commits it). Both cams get the same bimanual id.
    g_startUnix = (uint32_t)time(nullptr);
    g_episodeId  = String(g_cfg.ordinal + 1);
    g_bimanualId = makeBimanualId(g_cfg.ordinal + 1);
    int started = camStartAll(g_bimanualId, g_episodeId);
    if (started < kMinCams) {
      // Not every camera acked startCapture: roll back so no one-sided clip is left
      // rolling, and refuse the take (no ordinal advance). stop_reason=error.
      Serial.printf("[trigger] BLOCKED start: only %d/%d cams started\n", started, kMinCams);
      int se; camStopAll("error", se);   // best-effort stop of any that started
      g_lastBlockedMs = millis();
#ifdef PANTHEON_HAS_TFT
      confirmSplash(tft.color565(205, 35, 35), "ERROR", "Camara no inicio");
      g_screen = SCREEN_MAIN;
#endif
      g_forceRender = true;
      publishStatus();
      return;
    }
    g_anyRec = true;
    renderUI();                    // flip to DETENER immediately (before the flash write)
    uint32_t prevOrd = g_cfg.ordinal;
    logStart(started, g_connCount);
    if (g_cfg.ordinal == prevOrd) {
      // START log append FAILED (flash full / FS error): roll the take back.
      Serial.println("[trigger] START log append FAILED - rolling back (no take committed)");
      int se; camStopAll("error", se);
      g_anyRec = false;
#ifdef PANTHEON_HAS_TFT
      confirmSplash(tft.color565(205, 35, 35), "ERROR", "Memoria llena - reintenta");
      g_screen = SCREEN_MAIN;
#endif
      g_forceRender = true;
      publishStatus();
      return;
    }
    g_sessionTakes++;
  } else {
    // STOP is ALWAYS allowed. Stop every camera, read each clip filename, and inject
    // current_stop.env (outcome + per-cam timing) onto each card - discardd reads it
    // and stamps the authoritative sidecar. Then hand off to GUARDAR/DESCARTAR; the
    // operator's choice sets the final stop_reason and whether logStop keeps it.
    int stopEnvs = 0;
    int stopped = camStopAll("operator_stop", stopEnvs);
    g_anyRec = false;
    // Best-effort: give discardd a moment to stamp the sidecars so the STOP log
    // records accurate sidecar_ok. The authoritative re-check is the next START gate.
    priorSidecarsReady(1500);
    Serial.printf("[trigger] STOP stopped=%d stop-envs=%d\n", stopped, stopEnvs);
    g_pendSent = stopEnvs; g_pendTotal = stopped; g_pendStopLogged = false;
#ifdef PANTHEON_HAS_TFT
    g_screen = SCREEN_CONFIRM;
    g_confirmStartMs = millis();
    g_forceRender = true;
#else
    // Headless build has no decision screen: keep-by-default (log the stop).
    logStop(stopEnvs, stopped);
#endif
  }
  publishStatus();
}

#ifdef PANTHEON_HAS_TFT
// Full-screen confirmation flash (mirrors the LLAMAR blue splash): fill the panel
// with the action color + a big centered word, then hold ~1.1s so the operator
// gets unmistakable feedback before the loop restores MAIN. The brief blocking
// hold is safe here (the take is already stopped, so nothing is mid-record) and
// doubles as a release guard so lifting off GUARDAR/DESCARTAR can't bleed into a
// MAIN tap.
static void confirmSplash(uint16_t bg, const char* big, const char* sub) {
  if (!g_tftReady) return;
  tft.fillScreen(bg);
  tft.setTextColor(TFT_WHITE, bg);
  tft.setTextDatum(MC_DATUM);
  tft.setFreeFont(&FreeSansBold18pt7b); tft.drawString(big, 160, 108);
  tft.setFreeFont(&FreeSansBold9pt7b);  tft.drawString(sub, 160, 148);
  tft.setTextDatum(TL_DATUM);
  delay(1100);
}

// SCREEN_CONFIRM choices (the take is already stopped; g_pendSent/g_pendTotal hold
// its stop provenance). GUARDAR keeps it (log the stop); DESCARTAR voids the latest
// START ordinal so the ingest order-join drops it. Both return to MAIN.
static void saveTake() {
  if (!g_pendStopLogged) {
    if (!logStop(g_pendSent, g_pendTotal)) {
      Serial.println("[ui] SAVE failed: stop log not durable");
      confirmSplash(tft.color565(205, 35, 35), "ERROR", "No guardado - reintenta");
      g_screen = SCREEN_CONFIRM; g_confirmStartMs = millis(); g_forceRender = true;
      publishStatus();
      return;
    }
    g_pendStopLogged = true;
  }
  Serial.println("[ui] SAVE (take kept)");
  confirmSplash(tft.color565(0, 150, 70), "GUARDADO", "Saved");
  g_screen = SCREEN_MAIN; g_forceRender = true;
  publishStatus();
}
static void deleteTake() {
  if (!g_pendStopLogged) {
    if (!logStop(g_pendSent, g_pendTotal)) {
      Serial.println("[ui] DELETE failed: stop log not durable");
      confirmSplash(tft.color565(205, 35, 35), "ERROR", "No guardado - reintenta");
      g_screen = SCREEN_CONFIRM; g_confirmStartMs = millis(); g_forceRender = true;
      publishStatus();
      return;
    }
    g_pendStopLogged = true;
  }
  if (!logDelete()) {
    Serial.println("[ui] DELETE failed: delete log not durable");
    confirmSplash(tft.color565(205, 35, 35), "ERROR", "No borrado - reintenta");
    g_screen = SCREEN_CONFIRM; g_confirmStartMs = millis(); g_forceRender = true;
    publishStatus();
    return;
  }
  // Mark the take for archive on each card (KEEP footage; ingest routes it to the
  // archive bucket so we retain a record of what was discarded).
  int marked = camMarkArchive();
  Serial.printf("[ui] DESCARTAR (voided ordinal + archive-marked on %d cam(s), footage kept)\n", marked);
  confirmSplash(tft.color565(205, 35, 35), "DESCARTADO", "Archivado");
  g_screen = SCREEN_MAIN; g_forceRender = true;
  publishStatus();
}

// (The old MAIN-screen BORRAR / deleteLastTake was removed: MAIN now has only the
// GRABAR/DETENER toggle + LLAMAR. Deleting a take happens exclusively on the
// post-STOP decision screen via DESCARTAR -> deleteTake(), so there is one stop path.)

// SCREEN_CONFIRM_ID choices. YES commits the verified identity to NVS and moves on
// to the Mesa picker; NO discards it and returns to the kit-number keypad so the
// operator can re-enter (guards against a mis-typed kit number).
static void identityYes() {
  g_cfg.kitId = g_verifKit; g_cfg.operatorId = g_verifOp; g_cfg.operatorName = g_verifName;
  cfgPutStr("kit", g_cfg.kitId); cfgPutStr("op", g_cfg.operatorId); cfgPutStr("opname", g_cfg.operatorName);
  cfgPutKitConfirmed(true);
  Serial.printf("[prov] CONFIRMED identity kit=%s op=%s name=%s\n",
                g_cfg.kitId.c_str(), g_cfg.operatorId.c_str(), g_cfg.operatorName.c_str());
  g_mesaNum = ""; g_mesaErr = "";
  g_screen = SCREEN_MESA; g_forceRender = true;
}
static void identityNo() {
  Serial.println("[prov] identity REJECTED -> back to kit entry");
  cfgPutKitConfirmed(false);
  g_verifKit = ""; g_verifOp = ""; g_verifName = "";
  g_provKit = ""; g_provErr = "";   // clear the typed kit number for a fresh entry
  g_screen = SCREEN_PROVISION; g_forceRender = true;
}

// Single full-screen CALL flash - the exact same pattern as the save/delete
// confirmSplash: fill yellow, draw a big black word, hold ~1.1s, then the caller
// restores MAIN. ONE screen. The previous design flashed a "LLAMANDO" screen and
// THEN (async) a separate "EN COLA"/"NOTIFICADO" result - that brief first screen
// was the ~10ms flicker. Outcome no longer needs its own screen: the help event
// is logged + the POST queued regardless, so one clean flash matches GUARDADO.
static void drawPhoneIcon(int cx, int cy, uint16_t color, uint16_t bg);   // fwd (defined w/ renderMain)
static void callSplash() {
  if (!g_tftReady) return;
  const uint16_t C_CALL = tft.color565(245, 205, 0);   // yellow == LLAMAR button
  tft.fillScreen(C_CALL);
  tft.setTextColor(TFT_BLACK, C_CALL);
  tft.setTextDatum(MC_DATUM);
  tft.setFreeFont(&FreeSansBold18pt7b); tft.drawString("LLAMANDO", 160, 110);
  tft.setFreeFont(&FreeSansBold9pt7b);  tft.drawString("Llamando al lider", 160, 152);
  drawPhoneIcon(40,  110, TFT_BLACK, C_CALL);   // flanking handsets either side of the word
  drawPhoneIcon(280, 110, TFT_BLACK, C_CALL);
  tft.setTextDatum(TL_DATUM);
  delay(1100);
}

// Call the team lead ("Llamar al lider"). Logs a local help event (ships with the
// episode log so the lead is recoverable even if the live ping never lands) and
// queues a best-effort POST /api/help on the WiFi worker (the lead's dashboard
// bell). The POST runs on the core-0 worker; the UI just shows one clean splash.
static void callLead() {
  appendEpisodeLine(String("{\"schema\":\"") + kTriggerSchema +
    "\",\"event\":\"help\",\"kit_id\":\"" + jsonEscape(g_cfg.kitId) +
    "\",\"station\":\"" + jsonEscape(g_cfg.station) + "\",\"ms\":" + String(millis()) + "}");
  Serial.println("[ui] CALL LEAD (help event logged, POST queued)");
  g_helpDone = false; g_helpCode = -1;
  wifiEnqueue(WJOB_HELP);         // best-effort background POST (worker, core 0)
  callSplash();                   // single blocking flash (mirrors save/delete)
  g_screen = SCREEN_MAIN; g_forceRender = true;
  publishStatus();
}
#endif

// ---------------------------------------------------------------------------
// Config-line parser: the BLE config char and the serial console both send
// "key=value;key=value" lines. Keys: station, prompt, op, kit, time, allow,
// allowclear, cmd(=delete|dumplog|clearlog|status). Persisted to NVS.
// ---------------------------------------------------------------------------
static void dumpLog() {
  fsLock();
  File f = LittleFS.open(kEpisodeLogPath, FILE_READ);
  if (!f) { Serial.println("[log] (empty)"); fsUnlock(); return; }
  Serial.println("---BEGIN episodes.jsonl---");
  while (f.available()) Serial.write(f.read());
  Serial.println("---END episodes.jsonl---");
  f.close();
  fsUnlock();
}

static void clearLog() {
  fsLock();
  LittleFS.remove(kEpisodeLogPath);
  fsUnlock();
  Serial.println("[log] cleared");
}

static void resetOrdinal() {
  clearLog();
  cfgPutOrdinal(0);
  g_upOff = 0;
  g_prefs.putUInt("uploff", 0);
  Serial.println("[ep] ordinal reset to 0");
}

static void publishStatus();  // fwd

// Count comma-delimited allowlist entries. 0 == "allow all" (UNPROVISIONED:
// any X3 in range can connect to this fob -> cross-talk risk in a room full of
// kits). The depot must drive this to exactly the kit's camera count (2, or
// more if spare bodies are pre-authorized) before the fob ships. Surfaced in
// publishStatus() as "allow_n" so provisioning tooling/dashboard can VERIFY a
// fob is isolated and refuse to ship an allow-all unit.
static int countAllow() {
  String h = g_cfg.allowlist; h.trim();
  if (h.length() == 0) return 0;
  int n = 1;
  for (size_t i = 0; i < h.length(); i++) if (h[i] == ',') n++;
  return n;
}

// lockToConnectedCams: snapshot the SERIALS of the cameras CURRENTLY online (over
// OSC) into the persisted allowlist, in discovery (host) order. This is the one-tap
// depot binding step: power the kit's two X3s on the hub AP, confirm both are
// discovered, then send cmd=lockcams -> the allowlist records exactly this kit's
// two serials. The serial order (entry 0 = left, 1 = right) is what refreshLiveTelem
// uses to map each camera to a side. Deliberately explicit (depot-issued); refuses
// when fewer than kMinCams are online (that would persist a partial/empty list).
static void lockToConnectedCams() {
  CamRef c[kSubnetScanMax];
  int n = snapshotOnline(c, kSubnetScanMax);
  if (n < kMinCams) {
    Serial.printf("[allow] lockcams: need >=%d online cams, have %d - refusing\n", kMinCams, n);
    return;
  }
  // The L2 discovery sweep knows each cam's IP+MAC but NOT its serial (zero
  // background OSC), so c[i].serial is empty here and the old code persisted an
  // EMPTY allowlist (allow_n stayed 0 -> lockcams was a no-op). lockcams is a
  // deliberate depot action with both cams idle, so do a ONE-SHOT /osc/info per
  // cam to learn the serial, fully serialized under wifiLock (no concurrent OSC,
  // safe). Refuse to persist a partial list. (Fixed 2026-06-24, kit_56.)
  String list; int got = 0;
  wifiLock();
  for (int i = 0; i < n; i++) {
    String s = c[i].serial; s.trim();
    for (int tries = 0; !s.length() && tries < 2; tries++) {
      String fw; if (oscInfo(c[i].ip, s, fw)) s.trim();
    }
    if (!s.length()) continue;
    if (list.length()) list += ",";
    list += s; got++;
  }
  wifiUnlock();
  if (got < kMinCams) {
    Serial.printf("[allow] lockcams: learned only %d/%d serials over /osc/info - refusing\n", got, n);
    return;
  }
  g_cfg.allowlist = list;
  cfgPutStr("allow", list);
  Serial.printf("[allow] lockcams: locked to %d online cam(s): %s\n",
                countAllow(), list.c_str());
}

static void applyKV(const String& key, const String& val) {
  if (key == "station")      { g_cfg.station = val; cfgPutStr("station", val); }
  else if (key == "prompt")  { g_cfg.prompt = val; cfgPutStr("prompt", val); }
  else if (key == "op")      { g_cfg.operatorId = val; cfgPutStr("op", val); }
  else if (key == "opname")  { g_cfg.operatorName = val; cfgPutStr("opname", val); }
  else if (key == "kit")     {
    // Depot provisioning is a new handoff boundary. Never let stale local
    // REGISTRO/MESA/allowlist state from a previous fob use skip setup.
    g_cfg.kitId = val; cfgPutStr("kit", val);
    cfgPutKitConfirmed(false);
    g_cfg.station = ""; g_cfg.prompt = ""; g_cfg.allowlist = "";
    cfgPutStr("station", ""); cfgPutStr("prompt", ""); cfgPutStr("allow", "");
    // FOB-AS-AP: the SoftAP SSID defaults to PANTHEON-<kit>. Clear any stale
    // cam_ssid override so a depot re-provision tracks the new kit (an explicit
    // cam_ssid= later in the same line still wins, since kit is applied first).
    g_cfg.camSsid = ""; cfgPutStr("cssid", "");
    resetOrdinal();
#ifdef PANTHEON_HAS_TFT
    g_provKit = ""; g_provErr = ""; g_mesaNum = ""; g_mesaErr = "";  // TFT keypad state
#endif
    g_screen = SCREEN_PROVISION; g_forceRender = true;
    Serial.printf("[prov] depot kit=%s -> force REGISTRO/MESA before MAIN\n", val.c_str());
  }
  else if (key == "allow")   { g_cfg.allowlist = val; cfgPutStr("allow", val); }
  else if (key == "allowclear") { g_cfg.allowlist = ""; cfgPutStr("allow", ""); }
  else if (key == "cam_ssid")  { g_cfg.camSsid = val; cfgPutStr("cssid", val); }
  else if (key == "cam_pass")  { g_cfg.camPass = val; cfgPutStr("cpass", val); }
  else if (key == "cam_subnet"){ g_cfg.camSubnet = val; cfgPutStr("csub", val); }
  else if (key == "wifi_ssid") { g_cfg.wifiSsid = val; cfgPutStr("wssid", val); }
  else if (key == "wifi_pass") { g_cfg.wifiPass = val; cfgPutStr("wpass", val); }
  else if (key == "upload_url"){ g_cfg.uploadUrl = val; cfgPutStr("upurl", val); }
  else if (key == "upload_token"){ g_cfg.upToken = val; cfgPutStr("uptok", val); }
  else if (key == "time")    { setUnixTime((uint32_t)strtoul(val.c_str(), nullptr, 10)); }
  else if (key == "cmd") {
    if (val == "delete")        logDelete();
    else if (val == "dumplog")  dumpLog();
    else if (val == "clearlog") clearLog();
    else if (val == "resetordinal") resetOrdinal(); // depot: clean a fob before shipment without losing identity/allowlist
    else if (val == "status")   { publishStatus(); Serial.println(buildStatusJson()); }  // echo to serial for depot ship-gate / provision.py
    else if (val == "shutter")  { g_btnReq = BTN_SHUTTER; }   // serial GRABAR/DETENER toggle (bench testing)
    else if (val == "firetest") {                              // bench: raw start/stop to each cam, NO gates
      CamRef fc[kSubnetScanMax]; int fn = snapshotOnline(fc, kSubnetScanMax);
      Serial.printf("[firetest] %d cams; ARM+START\n", fn);
      wifiLock();
      for (int i = 0; i < fn; i++) { oscArmVideo(fc[i].ip); delay(kOscGapMs); }
      delay(kOscGapMs);
      for (int i = 0; i < fn; i++) oscStartCapture(fc[i].ip);   // each logs [fire]
      wifiUnlock();
      Serial.println("[firetest] rolling 6s");
      delay(6000);
      wifiLock();
      for (int i = 0; i < fn; i++) oscStopCapture(fc[i].ip);    // each logs [fire]
      wifiUnlock();
      Serial.println("[firetest] done");
    }
    else if (val == "lockcams") lockToConnectedCams();   // depot: isolate to connected cams
    else if (val == "testlog")  logStart(0, 0);   // synthetic episode for upload testing
    else if (val == "wifinow")  {                  // force an immediate WiFi upload
      wifiLock();
      wifiUploadBurst();
      wifiUnlock();
    }
    else if (val == "wifitest") {                  // test the uplink AP association path
      if (g_anyRec) {
        Serial.println("[wifitest] skipped: recording");
      } else {
        wifiLock();
        bool ok = uplinkUp(false, kWifiAssocTimeoutMs);
        Serial.printf("[wifitest] %s status=%d ip=%s rssi=%ld ch=%d bssid=%s\n",
                      ok ? "OK" : "FAIL", (int)WiFi.status(),
                      WiFi.localIP().toString().c_str(), (long)WiFi.RSSI(),
                      WiFi.channel(), WiFi.BSSIDstr().c_str());
        uplinkDown();   // returns to the camera hub AP
        wifiUnlock();
      }
    }
    else if (val == "wifiscan") {                  // list visible 2.4GHz networks + auth type
      if (g_anyRec) { Serial.println("[wifiscan] skipped: recording"); return; }
      wifiLock();
      WiFi.persistent(false);
      WiFi.mode(WIFI_STA);
      WiFi.setSleep(true);
      WiFi.setTxPower(WIFI_POWER_19_5dBm);
      int n = WiFi.scanNetworks(false, true);
      Serial.printf("[wifiscan] %d networks (enc: 0=open 2=wpa 3=wpa2 4=wpa/wpa2 5=enterprise 6=wpa3):\n", n);
      for (int i = 0; i < n; i++)
        Serial.printf("  '%s' rssi=%d enc=%d\n", WiFi.SSID(i).c_str(), WiFi.RSSI(i), (int)WiFi.encryptionType(i));
      WiFi.scanDelete();
      g_apUp = false;     // scan put us in STA; force the SoftAP back up
      apEnsureUp();       // restore the fob's SoftAP after the scan
      wifiUnlock();
    }
  } else {
    Serial.printf("[cfg] unknown key %s\n", key.c_str());
  }
}

static void parseConfigLine(const String& lineIn) {
  String line = lineIn; line.trim();
  if (line.length() == 0) return;
  int start = 0;
  while (start < (int)line.length()) {
    int semi = line.indexOf(';', start);
    if (semi < 0) semi = line.length();
    String pair = line.substring(start, semi);
    int eq = pair.indexOf('=');
    if (eq > 0) {
      String k = pair.substring(0, eq); k.trim();
      String v = pair.substring(eq + 1); v.trim();
      applyKV(k, v);
    }
    start = semi + 1;
  }
  publishStatus();
}

// ---------------------------------------------------------------------------
// Status characteristic (read/notify) - lets depot tools confirm current
// assignment + ordinal without a round trip to ingest.
// ---------------------------------------------------------------------------
#ifdef PANTHEON_HAS_TFT
// Draw the fob status screen on the CYD TFT. Called from publishStatus(), so it
// refreshes on every connect/disconnect/record-edge/config change, plus the loop
// heartbeat. Landscape (rotation 1) = 320x240.
// UI layout + touch regions (screen px, rotation 1, 320x240). The loop touch
// handler hit-tests these same constants.
static const int TOG_Y0 = 68, TOG_Y1 = 150;     // big GRABAR/DETENER toggle
static const int ROW_Y0 = 158, ROW_Y1 = 233;    // bottom row: full-width LLAMAR
static const int MID = (TOG_Y0 + TOG_Y1) / 2;

// ---- Rolling task prompt ----------------------------------------------------
// The prompt band sits between the header and the GRABAR toggle - one line tall
// on a 320px-wide screen. A static prompt longer than ~the screen width was
// truncated to "...", so the operator could only ever read the first ~30% of the
// task (useless). Instead we MARQUEE long prompts: the loop advances g_promptScroll
// a few times a second and redraws ONLY this band (no full-screen flicker), so the
// whole instruction rolls past and is fully readable. Short prompts draw static.
static const int  PROMPT_Y   = 44;     // text baseline-ish y for the prompt band
static const int  PROMPT_VIS = 34;     // approx chars visible across the band at 9pt
static int        g_promptScroll   = 0;
static uint32_t   g_promptScrollMs = 0;

// Bilingual rolling prompt. The station prompt may carry BOTH languages as
// "English | Espanol" (also accepts " / " as the separator); the English half
// renders WHITE and the Spanish half AMBER, trailing it. A single-language
// prompt (no separator) just renders white. Long prompts MARQUEE (the loop
// advances g_promptScroll); the visible window is drawn as runs of constant
// color so the two languages keep their colors as they roll past. Colour is
// decided by character index range (no per-char buffer) so this stays cheap.
static void drawPromptBand() {
  // Clear just the band (header above ends ~y36; toggle below starts at TOG_Y0).
  tft.fillRect(0, PROMPT_Y - 4, 320, (TOG_Y0 - 2) - (PROMPT_Y - 4), TFT_BLACK);
  if (!g_cfg.prompt.length()) return;
  tft.setTextDatum(TL_DATUM);
  tft.setFreeFont(&FreeSansBold9pt7b);
  const uint16_t C_EN = TFT_WHITE;
  const uint16_t C_ES = tft.color565(255, 190, 40);   // amber = Spanish

  // Split EN | ES on the first '|' (else " / "). ES trails EN.
  String en = g_cfg.prompt, es = "";
  int sep = g_cfg.prompt.indexOf('|'); int seplen = 1;
  if (sep < 0) { sep = g_cfg.prompt.indexOf(" / "); seplen = 3; }
  if (sep >= 0) {
    en = g_cfg.prompt.substring(0, sep); en.trim();
    es = g_cfg.prompt.substring(sep + seplen); es.trim();
  }
  const String gap = "     ";
  String track = en;
  int esStart = -1, esEnd = -1;
  if (es.length()) { esStart = track.length() + gap.length(); track += gap + es; esEnd = track.length(); }
  bool scroll = ((int)track.length() > PROMPT_VIS);
  if (scroll) track += gap;                 // wrap spacer so the loop reads cleanly
  int n = track.length();
  int start = scroll ? (g_promptScroll % n) : 0;
  int len = scroll ? PROMPT_VIS : n;

  auto colorAt = [&](int idx) -> uint16_t {
    return (esStart >= 0 && idx >= esStart && idx < esEnd) ? C_ES : C_EN;
  };
  int x = 6, i = 0;
  while (i < len) {
    uint16_t c = colorAt((start + i) % n);
    String run;
    while (i < len) {
      int j = (start + i) % n;
      if (colorAt(j) != c) break;
      run += track[j]; i++;
    }
    tft.setTextColor(c, TFT_BLACK);
    tft.drawString(run, x, PROMPT_Y);
    x += tft.textWidth(run);
  }
}

// Small padlock glyph (shackle + body + keyhole), drawn centered at (cx,cy) in
// foreground color fg over background bg. Used on the LOCKED GRABAR button so the
// operator immediately sees that recording is disabled until both cams connect.
static void drawLockGlyph(int cx, int cy, uint16_t fg, uint16_t bg) {
  tft.drawRoundRect(cx - 9, cy - 18, 18, 20, 9, fg);   // shackle (outer)
  tft.drawRoundRect(cx - 8, cy - 18, 16, 20, 8, fg);   // shackle (inner, thicker line)
  tft.fillRoundRect(cx - 14, cy - 6, 28, 22, 4, fg);   // body (covers shackle bottom)
  tft.fillCircle(cx, cy + 3, 3, bg);                   // keyhole
  tft.fillRect(cx - 1, cy + 3, 3, 7, bg);
}
// Telephone handset (horizontal receiver): a round earpiece on the left and a round
// mouthpiece on the right, joined by a handle that DIPS between them. The earlier
// version put symmetric caps on a straight diagonal bar - which read as a dumbbell.
// Keeping both ear/mouth blobs on the SAME side of a dipping U-handle is what reads
// unmistakably as a phone. Drawn from filled smooth circles + anti-aliased wide
// lines (rounded caps); bg is the surface colour behind it (for AA blending).
static void drawPhoneIcon(int cx, int cy, uint16_t color, uint16_t bg) {
  // Vertical receiver (rotated 90deg CCW): earpiece + mouthpiece stacked on the
  // RIGHT, handle arching to the LEFT between them.
  const float w = 5.0f;                                  // handle stroke width
  tft.fillSmoothCircle(cx + 4, cy + 10, 4, color, bg);   // earpiece (bottom)
  tft.fillSmoothCircle(cx + 4, cy - 10, 4, color, bg);   // mouthpiece (top)
  tft.drawWideLine(cx + 1, cy + 10, cx - 6, cy + 4, w, color, bg);   // lower side of the arch
  tft.drawWideLine(cx - 6, cy + 4,  cx - 6, cy - 4, w, color, bg);   // left of the handle
  tft.drawWideLine(cx - 6, cy - 4,  cx + 1, cy - 10, w, color, bg);  // upper side of the arch
}
// ---- MAIN operator screen (fully bilingual: Spanish big, English small) ----
static void renderMain() {
  const uint16_t C_GREEN = tft.color565(0, 150, 70);
  const uint16_t C_RED   = tft.color565(205, 35, 35);
  // LLAMAR = YELLOW (caution) on purpose: it sits right under the green GRABAR /
  // red DETENER toggle, so it must be far from BOTH green and red - yellow can't be
  // confused with either and draws the eye for a help call. Black text + black phone
  // icons give max contrast on yellow. The call splash reuses this same yellow.
  const uint16_t C_CALL  = tft.color565(245, 205, 0);
  uint16_t cams = g_connCount;
  // CAMS readout is a GO/NO-GO light: GREEN only when BOTH cams are up (you can
  // record); RED for 0/2 AND 1/2 (you cannot - a one-sided take is useless). No
  // amber middle state - "not both" is a hard stop, so it must read as red.
  uint16_t camCol = (cams >= 2) ? C_GREEN : C_RED;
  tft.fillScreen(TFT_BLACK);
  // header: MESA (tap to RE-PICK the table) + CAMS
  tft.setTextDatum(TL_DATUM); tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setFreeFont(&FreeSansBold12pt7b);
  char hdr[28]; snprintf(hdr, sizeof(hdr), "MESA %s", g_cfg.station.length() ? g_cfg.station.c_str() : "--");
  tft.drawString(hdr, 6, 8);
  tft.setTextDatum(TR_DATUM); tft.setTextColor(camCol, TFT_BLACK);
  tft.setFreeFont(&FreeSansBold9pt7b);
  char cb[16]; snprintf(cb, sizeof(cb), "CAMS %u/2", (unsigned)cams);
  tft.drawString(cb, 314, 6);
  tft.setTextColor(tft.color565(205,205,205), TFT_BLACK);   // was near-invisible grey
  tft.drawString("toca 2x=cambiar mesa", 314, 26, 2);  // DOUBLE-tap = change table (stray-tap guard)
  // prompt (task instructions for the current table); rolls if longer than the
  // band so the operator can read the WHOLE task (the loop drives the marquee).
  drawPromptBand();
  // big GRABAR/DETENER toggle (Spanish big, English sub).
  // GO/NO-GO hardening: when NOT recording, the toggle is LOCKED (BRIGHT RED +
  // padlock) for ANY persistent NO-GO state (no both cams / radio borrowed by the
  // uplink / prior take still saving its sidecars). The touch handler ignores a
  // tap in this state, so - exactly like the BLE fob - the operator physically
  // cannot start a take that would be phantom/one-sided or race the previous one.
  // Each reason shows its OWN sub-line so the wait is honest, not a mystery.
  // While recording the button stays active (DETENER) so the operator can always
  // stop, even if a cam dropped mid-take (surfaced as a warning sub-line).
  StartGate gate = startGate();
  bool lockedStart = (!g_anyRec && gate != GATE_OK);
  uint16_t bg = (g_anyRec || lockedStart) ? C_RED : C_GREEN;
  tft.fillRoundRect(8, TOG_Y0, 304, TOG_Y1 - TOG_Y0, 10, bg);
  tft.setTextColor(TFT_WHITE, bg); tft.setTextDatum(MC_DATUM);
  if (lockedStart) {
    // "ESPERA" dead-centre with a padlock on EACH side (symmetric), then a
    // reason-specific ES/EN sub-line pair. Kept well inside the 304px button.
    const char* es = "Esperando 2 camaras";
    const char* en = "waiting for both cams";
    if      (gate == GATE_UPLINK) { es = "Subiendo datos..."; en = "uploading, espera"; }
    else if (gate == GATE_SAVING) { es = "Guardando toma previa"; en = "saving previous take"; }
    tft.setFreeFont(&FreeSansBold18pt7b);
    tft.drawString("ESPERA", 160, MID - 12);
    drawLockGlyph(52,  MID - 12, TFT_WHITE, bg);
    drawLockGlyph(268, MID - 12, TFT_WHITE, bg);
    tft.setFreeFont(&FreeSansBold9pt7b);
    tft.drawString(es, 160, MID + 12);
    tft.drawString(en, 160, MID + 30, 2);
  } else {
    tft.setFreeFont(&FreeSansBold18pt7b);
    tft.drawString(g_anyRec ? "DETENER" : "GRABAR", 160, MID - 6);
    tft.setFreeFont(&FreeSansBold9pt7b);
    if (g_anyRec && cams < kMinCams) {
      // Recording continues (the operator must be able to stop), but a cam fell
      // off mid-take - the take is compromised. Say so loudly under DETENER.
      tft.setTextColor(tft.color565(255, 220, 120), bg);
      tft.drawString("!  1/2 - una camara cayo", 160, MID + 24);
      tft.setTextColor(TFT_WHITE, bg);
    } else {
      tft.drawString(g_anyRec ? "Stop recording" : "Start recording", 160, MID + 24);
    }
  }
  // bottom row: a SINGLE full-width LLAMAR (call lead). The UI is intentionally
  // just two controls - the GRABAR/DETENER toggle and LLAMAR. Deleting a take is no
  // longer a MAIN-screen action: it lives only on the post-STOP decision screen
  // (DETENER -> GUARDAR / DESCARTAR), so there is exactly one stop path.
  tft.fillRoundRect(8, ROW_Y0, 304, ROW_Y1 - ROW_Y0, 8, C_CALL);
  tft.setTextColor(TFT_BLACK, C_CALL); tft.setTextDatum(MC_DATUM);   // black on yellow = max contrast
  tft.setFreeFont(&FreeSansBold12pt7b);
  tft.drawString("LLAMAR", 160, ROW_Y0 + 24);
  tft.drawString("Call team lead", 160, ROW_Y0 + 52, 2);
  drawPhoneIcon(64,  ROW_Y0 + 30, TFT_BLACK, C_CALL);   // flanking handsets, clear of the text
  drawPhoneIcon(256, ROW_Y0 + 30, TFT_BLACK, C_CALL);
  tft.setTextDatum(TL_DATUM);
}

// ---- CONFIRM screen: post-STOP GUARDAR (keep) / DESCARTAR (delete) ----
static void renderConfirm() {
  const uint16_t C_GREEN = tft.color565(0, 150, 70);
  const uint16_t C_RED   = tft.color565(205, 35, 35);
  tft.fillScreen(TFT_BLACK);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(TFT_WHITE, TFT_BLACK); tft.setFreeFont(&FreeSansBold12pt7b);
  // Per-SESSION take number (resets at boot / table change), NOT the lifetime
  // NVS ordinal - so "TOMA #n" reads as "nth take at this table this session".
  char hdr[28]; snprintf(hdr, sizeof(hdr), "TOMA #%u DETENIDA", (unsigned)g_sessionTakes);
  tft.drawString(hdr, 160, 22);
  tft.setTextColor(tft.color565(205,205,205), TFT_BLACK);
  tft.drawString("Take stopped - guardar o borrar?", 160, 48, 2);
  // GUARDAR (green, top) - the safe default (also taken on timeout).
  tft.fillRoundRect(8, 66, 304, 78, 10, C_GREEN);
  tft.setTextColor(TFT_WHITE, C_GREEN);
  tft.setFreeFont(&FreeSansBold18pt7b); tft.drawString("GUARDAR", 160, 96);
  tft.setFreeFont(&FreeSansBold9pt7b);  tft.drawString("Save take", 160, 126);
  // DESCARTAR (red, bottom).
  tft.fillRoundRect(8, 152, 304, 80, 10, C_RED);
  tft.setTextColor(TFT_WHITE, C_RED);
  tft.setFreeFont(&FreeSansBold18pt7b); tft.drawString("DESCARTAR", 160, 182);
  tft.setFreeFont(&FreeSansBold9pt7b);  tft.drawString("Delete take", 160, 212);
  tft.setTextDatum(TL_DATUM);
}

// ---- CONFIRM-ID screen: "Are you <name>?" SI / NO (provisioning safety) ----
static void renderConfirmId() {
  const uint16_t C_GREEN = tft.color565(0, 150, 70);
  const uint16_t C_RED   = tft.color565(205, 35, 35);
  tft.fillScreen(TFT_BLACK);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(TFT_WHITE, TFT_BLACK); tft.setFreeFont(&FreeSansBold12pt7b);
  tft.drawString("CONFIRMA / Confirm", 160, 18);
  // Operator name - the thing being confirmed. Size to fit 300px: 18pt for short
  // names, drop to 12pt for long ones (measured with the real font metrics).
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setFreeFont(&FreeSansBold18pt7b);
  if (tft.textWidth(g_verifName) > 300) tft.setFreeFont(&FreeSansBold12pt7b);
  tft.drawString(g_verifName, 160, 64);
  tft.setTextColor(tft.color565(210,210,210), TFT_BLACK);   // was too faint
  char sub[28]; snprintf(sub, sizeof(sub), "Kit %s  -  eres tu?", g_provKit.c_str());
  tft.drawString(sub, 160, 104, 2);
  // SI (green = yes, left) | NO (red = no, right) - big edge-tolerant targets.
  tft.fillRoundRect(8, 138, 150, 94, 10, C_GREEN);
  tft.setTextColor(TFT_WHITE, C_GREEN);
  tft.setFreeFont(&FreeSansBold18pt7b); tft.drawString("SI", 83, 172);
  tft.drawString("Soy yo", 83, 206, 2);
  tft.fillRoundRect(162, 138, 150, 94, 10, C_RED);
  tft.setTextColor(TFT_WHITE, C_RED);
  tft.setFreeFont(&FreeSansBold18pt7b); tft.drawString("NO", 237, 172);
  tft.drawString("Otro numero", 237, 206, 2);
  tft.setTextDatum(TL_DATUM);
}

// ---- PROVISION screen: one-time local kit-NUMBER confirmation ----
// Big numeric keypad drawn DIRECTLY on this screen (operators cannot type
// letters). Layout on 320x240, rotation 1:
//   - Paired bilingual header (Spanish primary, English sub at the same left x).
//   - Typed kit number shown LARGE just under the header.
//   - 3-col x 4-row keypad, big edge-tolerant buttons:
//       [1 2 3] [4 5 6] [7 8 9] [DEL 0 ENTRAR]
//   - Error line (g_provErr) below the keypad.
// Keypad grid (these constants drive both render and the loop hit-test). 3 cols
// x 4 rows. Column left edges x = {8,114,220}, button width KP_BW=98 (gap 8).
// Row top edges y = {86,124,162,200}, button height KP_BH=34 (pitch KP_DY=38).
// The hit-test is column-from-x / row-from-y with edge tolerance via division,
// so taps in the inter-button gaps still land on the nearest key.
static const int KP_X0 = 8;            // column 0 left edge
static const int KP_DX = 106;          // column pitch
static const int KP_BW = 98;           // button width
static const int KP_Y0 = 86;           // row 0 top edge
static const int KP_DY = 38;           // row pitch
static const int KP_BH = 34;           // button height
static const char* KP_LABEL[4][3] = {
  {"1","2","3"},
  {"4","5","6"},
  {"7","8","9"},
  {"DEL","0","ENTRAR"},
};
// Shared numeric-entry screen body (provision + mesa). Header line is FULL WIDTH
// (title left at x8, ATRAS right at x232) so the title never collides with the
// number; the typed number sits in its OWN field box below; then the 3x4 keypad.
// 320x240, rotation 1. Vertical: title 6-26, line2 38-54, num box 52-82, keypad
// 86-234 - no overlaps; everything stays on-screen.
static void renderNumEntry(const char* title, const char* hint, const char* numLabel,
                           const String& num, const String& err, bool showBack) {
  const uint16_t C_GREEN = tft.color565(0, 150, 70);
  const uint16_t C_AMBER = tft.color565(155, 100, 20);
  const uint16_t C_KEY   = tft.color565(55, 55, 65);
  const uint16_t C_BLUE  = tft.color565(45, 95, 170);
  const uint16_t C_BOX   = tft.color565(90, 90, 90);
  tft.fillScreen(TFT_BLACK);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(TFT_WHITE, TFT_BLACK); tft.setFreeFont(&FreeSansBold12pt7b);
  tft.drawString(title, 8, 6);
  if (showBack) {
    tft.fillRoundRect(212, 4, 104, 40, 6, C_BLUE);   // big top-right target
    tft.setTextColor(TFT_WHITE, C_BLUE); tft.setTextDatum(MC_DATUM);
    tft.setFreeFont(&FreeSansBold12pt7b); tft.drawString("ATRAS", 264, 24);
    tft.setTextDatum(TL_DATUM);
  }
  if (err.length()) {                                // line 2: error (red) or hint (grey)
    tft.setTextColor(tft.color565(230, 70, 70), TFT_BLACK);
    String e = err; if (e.length() > 34) e = e.substring(0, 32) + "..";
    tft.drawString(e, 8, 38, 2);
  } else {
    tft.setTextColor(tft.color565(205, 205, 205), TFT_BLACK);
    tft.drawString(hint, 8, 38, 2);
  }
  (void)numLabel;                                    // label is conveyed by the title + hint; box shows only the number
  tft.drawRoundRect(8, 52, 180, 32, 6, C_BOX);       // number field (x8-188: stays clear of the ATRAS hit zone x>=196)
  tft.setTextColor(TFT_WHITE, TFT_BLACK); tft.setFreeFont(&FreeSansBold18pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.drawString(num.length() ? num : String("_"), 98, 68);   // big + centered -> never overruns the box edge
  tft.setTextDatum(MC_DATUM);                        // 3x4 numeric keypad
  for (int r = 0; r < 4; r++) {
    int y = KP_Y0 + r * KP_DY;
    for (int c = 0; c < 3; c++) {
      int x = KP_X0 + c * KP_DX;
      const char* lab = KP_LABEL[r][c];
      bool isDel = (r == 3 && c == 0), isEnter = (r == 3 && c == 2);
      uint16_t bg = isEnter ? C_GREEN : (isDel ? C_AMBER : C_KEY);
      tft.fillRoundRect(x, y, KP_BW, KP_BH, 6, bg);
      tft.setTextColor(TFT_WHITE, bg);
      if (isDel || isEnter) tft.drawString(lab, x + KP_BW / 2, y + KP_BH / 2, 2);
      else { tft.setFreeFont(&FreeSansBold18pt7b); tft.drawString(lab, x + KP_BW / 2, y + KP_BH / 2 - 2); }
    }
  }
  tft.setTextDatum(TL_DATUM);
}

static void renderProvision() {
  // REGISTRO is the root of setup: no ATRAS (no back-to-recording). You move forward
  // with ENTRAR -> MESA; MESA's ATRAS returns here to re-enter the kit.
  renderNumEntry("REGISTRO", "Numero de kit / Kit number", "Kit #",
                 g_provKit, g_provErr, false);
}

// ---- MESA screen: type-the-number numeric keypad -> local station selection ----
// Mexico has many tables, so a picker list does not scale: the operator types the
// table number on the SAME 3x4 numeric keypad as provisioning (reuses KP_* /
// KP_LABEL / keypadHit). Layout on 320x240, rotation 1:
//   - Title "ELIGE MESA" (Spanish primary) + "Pick table" (English sub).
//   - ATRAS back button top-right (always available).
//   - Typed table number shown LARGE just under the header.
//   - Error line (g_mesaErr) in the gap ABOVE the keypad (the screen is only
//     240px tall, so below the keypad would be off the bottom edge).
//   - Keypad: [1 2 3] [4 5 6] [7 8 9] [DEL 0 ENTRAR].
static void renderMesa() {
  // ATRAS always -> back to the kit/operator (REGISTRO) screen.
  // Hint kept SHORT: the full "Numero de mesa / Table number" ran under the ATRAS
  // button (x>=212) at font2. "Mesa / Table number" clears it with margin.
  renderNumEntry("ELIGE MESA", "Mesa / Table number", "Mesa #",
                 g_mesaNum, g_mesaErr, true);
}

static String canonicalKitEntry(const String& typed) {
  String s = typed; s.trim();
  if (s.startsWith("kit_")) return s;
  return "kit_" + s;
}

static int kitNumericSuffix(const String& kit) {
  String s = kit; s.trim();
  if (s.startsWith("kit_")) s = s.substring(4);
  if (s.length() == 0) return -1;
  for (size_t i = 0; i < s.length(); i++) if (!isDigit(s[i])) return -1;
  return s.toInt();
}

static bool kitIdsMatch(const String& typedKit, const String& storedKit) {
  if (typedKit == storedKit) return true;
  int typedNum = kitNumericSuffix(typedKit);
  int storedNum = kitNumericSuffix(storedKit);
  return typedNum >= 0 && storedNum >= 0 && typedNum == storedNum;
}

static void acceptLocalStation(const String& station, const String& prompt) {
  String newStation = station; newStation.trim();
  if (newStation.length() == 0) return;
  bool stationChanged = (newStation != g_cfg.station);
  if (stationChanged) g_sessionTakes = 0;
  g_cfg.station = newStation;
  if (prompt.length()) g_cfg.prompt = prompt;
  else if (stationChanged || g_cfg.prompt.length() == 0) g_cfg.prompt = "Mesa " + newStation + " | Table " + newStation;
  cfgPutStr("station", g_cfg.station);
  cfgPutStr("prompt", g_cfg.prompt);
  Serial.printf("[mesa] LOCAL station=%s prompt=\"%s\"\n",
                g_cfg.station.c_str(), g_cfg.prompt.c_str());
  g_screen = SCREEN_MAIN;
  g_forceRender = true;
}

// Accept ANY typed kit NUMBER locally: the typed number IS the identity
// (kit_id = "kit_<n>"). There is no burned-in NVS match and no operator gate, so
// a fresh / NVS-wiped fob can NEVER dead-end at REGISTRO. The typed value still
// gets a SI/NO confirm on SCREEN_CONFIRM_ID before it is committed to NVS.
static void provisionVerify() {
  g_provErr = "";
  if (g_provKit.length() == 0) {
    g_provErr = "Escribe el numero de kit / Enter kit number";
    return;
  }
  String typedKit = canonicalKitEntry(g_provKit);
  g_verifKit = typedKit;
  g_verifOp = g_cfg.operatorId;   // keep any depot-set operator id (may be empty)
  g_verifName = g_cfg.operatorName.length() ? g_cfg.operatorName
              : (g_cfg.operatorId.length() ? g_cfg.operatorId : typedKit);
  Serial.printf("[prov] LOCAL accept kit_id=%s op=%s name=%s\n",
                g_verifKit.c_str(), g_verifOp.c_str(), g_verifName.c_str());
  g_screen = SCREEN_CONFIRM_ID;
  g_forceRender = true;
}

// Accept the typed table NUMBER locally and advance to MAIN immediately. Field
// recording must not depend on live WiFi/API. A cached prompt is preserved when
// re-confirming the current table; a new table gets a generic prompt until the
// next provisioning/table sync updates it.
static void mesaVerify() {
  g_mesaErr = "";
  if (g_mesaNum.length() == 0) {
    g_mesaErr = "Escribe el numero de mesa / Enter table number";
    return;
  }
  String typed = g_mesaNum; typed.trim();
  if (typed == g_cfg.station && g_cfg.prompt.length()) {
    // Re-confirming the current table is entirely local. Never make an operator
    // stare at a network verifier just to return to MAIN.
    acceptLocalStation(typed, g_cfg.prompt);
    return;
  }
  // Field operation must not depend on live WiFi. Accept the typed table locally
  // immediately; the static prompt can be improved later by provisioning/table
  // sync, but losing DETENER/recording control is never acceptable.
  acceptLocalStation(typed, "");
  return;
}

// Numeric keypad hit-test for SCREEN_PROVISION. Returns the row/col of the key
// under (sx,sy), edge-tolerant: x below the grid clamps to col 0, x past the
// right edge clamps to col 2, likewise for rows. Returns false only if the tap
// is above the keypad's top edge (the header region). Caller maps row/col to a
// digit / DEL / ENTRAR via KP_LABEL.
static bool keypadHit(int sx, int sy, int& row, int& col) {
  if (sy < KP_Y0) return false;                       // header area, not a key
  int r = (sy - KP_Y0) / KP_DY;
  if (r < 0) r = 0; if (r > 3) r = 3;
  int c = (sx - KP_X0) / KP_DX;
  if (c < 0) c = 0; if (c > 2) c = 2;
  row = r; col = c;
  return true;
}

// dispatcher: main uses the change-guard; the other screens redraw only on
// request (g_forceRender, set after a tap/screen-change/transient overlay).
static void renderUI() {
  if (!g_tftReady) return;
  if (g_screen != SCREEN_MAIN) {
    // PROVISION + MESA redraw only on request (g_forceRender), set after every
    // tap / screen-change / transient overlay - so the keypad never idle-flashes
    // but always reflects the latest typed kit number.
    if (!g_forceRender) return;
    g_forceRender = false;
    if      (g_screen == SCREEN_PROVISION)   renderProvision();
    else if (g_screen == SCREEN_CONFIRM)     renderConfirm();
    else if (g_screen == SCREEN_CONFIRM_ID)  renderConfirmId();
    else                                     renderMesa();   // SCREEN_MESA
    return;
  }
  // NOTE: the MAIN screen does NOT draw the ordinal (the take # lives on the CONFIRM
  // screen), so the ordinal MUST NOT be in this signature. It used to be, which made
  // GRABAR flash TWICE: render #1 (flip to DETENER) ran before logStart() bumped the
  // ordinal, then render #2 (same pixels) fired only because the ordinal changed the
  // sig. Sig must reflect ONLY what MAIN actually draws: cam count, record state,
  // station, prompt.
  // Sig must reflect ONLY what MAIN draws: cam count, record state, station,
  // prompt - PLUS the GO/NO-GO gate (the lock button text depends on the reason:
  // cams / uplink / saving), so a change in the lock reason repaints the button.
  uint32_t sig = (uint32_t)g_connCount
               ^ (g_anyRec ? 0x80000000u : 0)
               ^ ((uint32_t)startGate() << 24)
               ^ (strHash(g_cfg.station) * 3u)
               ^ (strHash(g_cfg.prompt) * 7u);
  if (sig == g_uiSig && !g_forceRender) return;
  g_uiSig = sig; g_forceRender = false;
  renderMain();
}
#else
static void renderUI() {}
#endif

// Build the status JSON. Shared by publishStatus() (BLE notify) and the serial
// `cmd=status` echo so the depot ship-gate / provision.py can read allow_n etc.
// over USB (the BLE notify is invisible to a serial tool). No g_statusChar guard:
// the string is always valid even before the BLE service exists.
static String buildStatusJson() {
  String s = "{";
  s += "\"kit_id\":\"" + jsonEscape(g_cfg.kitId) + "\",";
  s += "\"operator_id\":\"" + jsonEscape(g_cfg.operatorId) + "\",";
  s += "\"operator_name\":\"" + jsonEscape(g_cfg.operatorName) + "\",";
  s += "\"station\":\"" + jsonEscape(g_cfg.station) + "\",";
  s += "\"prompt\":\"" + jsonEscape(g_cfg.prompt) + "\",";
  s += "\"ordinal\":" + String(g_cfg.ordinal) + ",";
  s += "\"cams\":" + String(g_connCount) + ",";
  s += "\"allow_n\":" + String(countAllow()) + ",";   // 0 = UNPROVISIONED (allow-all)
  // cam_ssid is the 2.4GHz SoftAP the FOB broadcasts for the cameras to STA-join
  // (NOT a secret - it's broadcast). ap_sta is how many cameras are currently
  // associated to that AP. The AP password is deliberately NOT echoed.
  s += "\"cam_ssid\":\"" + jsonEscape(apSsid()) + "\",";
  s += "\"cam_subnet\":\"" + jsonEscape(g_cfg.camSubnet) + "\",";
  s += "\"ap_up\":" + String(g_apUp ? "true" : "false") + ",";
  s += "\"ap_ch\":" + String((int)apChannel()) + ",";
  s += "\"ap_sta\":" + String(WiFi.softAPgetStationNum()) + ",";
  s += "\"fw\":\"" FOB_FW_VERSION "\",";
  s += "\"kit_confirmed\":" + String(g_cfg.kitConfirmed ? "true" : "false") + ",";
  s += "\"recording\":" + String(g_anyRec ? "true" : "false") + ",";
  s += "\"ready\":" + String(g_connCount >= 2 ? "true" : "false") + ",";   // both cams up: GRABAR unlocked
  s += "\"time_set\":" + String(g_timeSet ? "true" : "false");
  s += "}";
  return s;
}

static void publishStatus() {
  // Defer the actual TFT draw to the loop task (see g_uiDirty): this function is
  // called from the discovery/button/worker tasks, which must NOT touch the SPI
  // bus. Status is read over USB serial (cmd=status -> buildStatusJson) now that
  // there is no BLE status characteristic.
  g_uiDirty = true;
}

// ---------------------------------------------------------------------------
// Button input - debounced short/long/triple press (shutter/power-off/mode).
// The shutter just toggles record; the episode log is driven by CE81 edges,
// NOT by this, so a physical camera-button press is still logged correctly.
// ---------------------------------------------------------------------------
static const uint32_t kDebounceMs      = 30;
static const uint32_t kLongPressMs     = 3000;
static const uint32_t kTripleWindowMs  = 1500;
static const uint32_t kShortPressMaxMs = 800;

void buttonTask(void* arg) {
  pinMode(PANTHEON_PIN_BUTTON, INPUT_PULLUP);
  pinMode(PANTHEON_PIN_LED, OUTPUT);
  int last = HIGH;
  uint32_t lastEdgeMs = 0, pressStartMs = 0, lastBlinkMs = 0;
  uint32_t recentPresses[3] = {0, 0, 0};
  bool ledOn = false;

  for (;;) {
    uint32_t now = millis();
    int cur = digitalRead(PANTHEON_PIN_BUTTON);
    // Blink while NOT READY (fewer than both cams connected); solid when the
    // full kit is up. A start is gated on both cams, so the blink tells the
    // operator the GRABAR button is locked. (ordinal hardening 2026-06-18)
    if (g_connCount < 2) {
      if (now - lastBlinkMs > 500) { ledOn = !ledOn; digitalWrite(PANTHEON_PIN_LED, ledOn); lastBlinkMs = now; }
    } else {
      digitalWrite(PANTHEON_PIN_LED, HIGH);
    }
    if (cur != last && (now - lastEdgeMs) > kDebounceMs) {
      lastEdgeMs = now;
      if (cur == LOW) {
        pressStartMs = now;
      } else {
        uint32_t held = now - pressStartMs;
        if (held >= kLongPressMs) {
          Serial.printf("[btn] LONG (%lu ms) -> power-off\n", (unsigned long)held);
          g_btnReq = BTN_POWEROFF;   // serviced on loop (no g_cams access off-loop)
        } else if (held <= kShortPressMaxMs) {
          if (g_anyRec) {
            Serial.println("[btn] SHORT while recording -> stop now");
            g_btnReq = BTN_SHUTTER;   // STOP must not wait for triple-press disambiguation
            recentPresses[0] = recentPresses[1] = recentPresses[2] = 0;
            last = cur;
            continue;
          }
          recentPresses[0] = recentPresses[1];
          recentPresses[1] = recentPresses[2];
          recentPresses[2] = now;
          if (recentPresses[0] != 0 && (now - recentPresses[0]) <= kTripleWindowMs) {
            Serial.println("[btn] TRIPLE -> mode cycle");
            g_btnReq = BTN_MODE;   // serviced on loop
            recentPresses[0] = recentPresses[1] = recentPresses[2] = 0;
          } else {
            uint32_t fireAt = now + kTripleWindowMs;
            while (millis() < fireAt) {
              if (recentPresses[0] && recentPresses[1] && recentPresses[2]
                  && (millis() - recentPresses[0]) <= kTripleWindowMs) { fireAt = 0; break; }
              delay(20);
            }
            if (fireAt != 0) {
              Serial.println("[btn] SHORT -> shutter (toggle record)");
              g_btnReq = BTN_SHUTTER;   // serviced on loop (fireShutterToggle touches g_cams + TFT)
            }
          }
        }
      }
      last = cur;
    }
    delay(5);
  }
}

// ---------------------------------------------------------------------------
// Serial console: depot provisioning + log shipping. Same "key=value;..." lines
// as the config char, so `kit=kit_2;op=op002` at the depot provisions a fob,
// and `cmd=dumplog` ships the JSONL over USB. See README "Shipping the log".
// ---------------------------------------------------------------------------
static String g_serialBuf;
void pollSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (g_serialBuf.length()) { parseConfigLine(g_serialBuf); g_serialBuf = ""; }
    } else {
      g_serialBuf += c;
      if (g_serialBuf.length() > 512) g_serialBuf = "";  // overrun guard
    }
  }
}

// ---------------------------------------------------------------------------
// setup() / loop()
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.println("Pantheon X3 WiFi-OSC fob (production) starting");
  g_fobSession = makeFobSession();   // per-boot id for fob-swap ordinal disambiguation
  Serial.printf("[boot] fob_session_id=%s\n", g_fobSession.c_str());

  // Concurrency primitives FIRST: BLE/host callbacks (which append to the episode
  // log) and the WiFi worker can run as soon as their tasks exist, so the FS lock
  // and the WiFi mutex/queue must be live before anything that uses them.
  g_fsMutex   = xSemaphoreCreateMutex();
  g_wifiMutex = xSemaphoreCreateMutex();
  g_camMutex  = xSemaphoreCreateMutex();
  g_wifiQ     = xQueueCreate(6, sizeof(uint8_t));

  if (!LittleFS.begin(true)) Serial.println("[fs] LittleFS mount failed");
  cfgLoad();
  Serial.printf("[cfg] kit=%s op=%s station=%s ordinal=%u allow=%s\n",
                g_cfg.kitId.c_str(), g_cfg.operatorId.c_str(),
                g_cfg.station.c_str(), g_cfg.ordinal, g_cfg.allowlist.c_str());

  // Boot screen choice: a fob must pass local REGISTRO confirmation once, then
  // MESA, before MAIN. Operator identity is NOT tracked on the fob (no-gate model:
  // the typed kit number IS the identity), so a confirmed kit + table boots
  // straight to MAIN; only a never-confirmed fob lands on REGISTRO.
  if (g_cfg.kitId.length() == 0 || !g_cfg.kitConfirmed) {
    g_screen = SCREEN_PROVISION;
  } else if (g_cfg.station.length() == 0) {
    g_screen = SCREEN_MESA;
  } else {
    g_screen = SCREEN_MAIN;
  }
#ifdef PANTHEON_HAS_TFT
  g_forceRender = true;   // draw the chosen boot screen on the first publishStatus/loop
#endif

#ifdef PANTHEON_HAS_TFT
  tft.init();
  tft.setRotation(1);              // landscape 320x240
  tft.fillScreen(TFT_BLACK);
  g_tftReady = true;
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.drawString("PANTHEON X3 FOB", 8, 6, 4);
  tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft.drawString("starting...", 8, 60, 4);
  Serial.println("[tft] display init");
  // touch panel (XPT2046 on its own VSPI bus)
  pinMode(T_CS, OUTPUT); digitalWrite(T_CS, HIGH);
  pinMode(T_IRQ, INPUT);
  touchSPI.begin(T_CLK, T_MISO, T_MOSI, T_CS);
  Serial.println("[tft] touch init (XPT2046 on VSPI)");
#endif

  // WiFi-OSC: no BLE stack. The single 2.4GHz radio is dedicated to STA mode and
  // stays associated to the camera hub AP so the fob can trigger over OSC; it is
  // only briefly borrowed for the internet uplink AP during idle upload windows.
  WiFi.onEvent(onWiFiEvent);   // kick discovery immediately on AP STA churn
  publishStatus();
  // FOB-AS-AP: host our own 2.4GHz SoftAP immediately so the cameras can STA-join.
  apEnsureUp();
  Serial.printf("[ap] hosting ssid='%s' subnet=%s.x ch=%d (cams STA-join this)\n",
                apSsid().c_str(), g_cfg.camSubnet.c_str(), (int)apChannel());
  if (g_cfg.camPass.length() < 8)
    Serial.println("[ap] WARNING: cam_pass < 8 chars -> AP is OPEN (set cam_pass via serial)");

  xTaskCreatePinnedToCore(buttonTask, "btn", 4096, nullptr, 1, nullptr, 1);
  // WiFi worker on core 0 (the loop/UI runs on core 1). All multi-second uplink
  // associate/POST work happens here so touch never stalls. 12KB stack gives TLS
  // (WiFiClientSecure/mbedtls) + HTTPClient + JSON comfortable headroom.
  xTaskCreatePinnedToCore(wifiTask, "wifi", 12288, nullptr, 1, nullptr, 0);
  // Discovery worker on core 0: keeps the camera AP linked + re-probes the hub
  // subnet over OSC. 8KB stack covers HTTPClient + ArduinoJson for the OSC parse.
  xTaskCreatePinnedToCore(discoveryTask, "disc", 8192, nullptr, 1, nullptr, 0);
}

// Touch-idle gate: wifiUp() blocks the single-threaded loop (incl. touch) for up
// to the assoc timeout, so we only open a WiFi window (upload/telemetry) when the
// operator has NOT touched the screen for kUiQuietMs. A freeze then only ever
// lands during a lull, never while they are actively tapping.
static uint32_t g_lastTouchMs = 0;
static const uint32_t kUiQuietMs = 6000;

void loop() {
  pollSerial();
  static uint32_t last = 0;
  uint32_t now = millis();

  // Service a physical-button request set by buttonTask. Done HERE on the loop so
  // TFT redraw stays single-owner; g_camMutex protects camera-map access.
  if (g_btnReq != BTN_NONE) {
    uint8_t req = g_btnReq;
    g_btnReq = BTN_NONE;
    // Physical BOOT button mirrors the touch GRABAR/DETENER gate: STOP is always
    // allowed, but a START is refused (no-op + redraw) in any NO-GO state so the
    // hardware button can't bypass the GO/NO-GO lock either.
    if      (req == BTN_SHUTTER)  { if (g_anyRec || startGate() == GATE_OK) fireShutterToggle();
                                    else { g_lastBlockedMs = now; g_forceRender = true; g_uiDirty = true; } }
    else if (req == BTN_POWEROFF) Serial.println("[btn] power-off ignored (wifi-osc build)");
    else if (req == BTN_MODE)     Serial.println("[btn] mode ignored (wifi-osc build)");
  }

#ifdef PANTHEON_HAS_TFT
  // Service deferred redraws requested by non-loop tasks (BLE connect/disconnect/
  // CE81 record edges, the button task). All TFT drawing happens HERE on the loop.
  if (g_uiDirty) { g_uiDirty = false; renderUI(); }

  // Recording is non-preemptible. The operator must always have DETENER available;
  // no WiFi/setup/table path is allowed to strand them away from MAIN mid-take.
  if (g_anyRec && g_screen != SCREEN_MAIN) {
    Serial.printf("[ui] forced MAIN while recording (was screen=%d)\n", (int)g_screen);
    g_screen = SCREEN_MAIN;
    g_forceRender = true;
    renderUI();
  }

  // The Mesa screen is now a type-the-number keypad (no list fetch on entry); it
  // just shows the keypad and resolves the typed number via mesaVerify() on ENTRAR.

  // Touch dispatch. Firm-press + lockout (one press = one action). Map
  // raw->screen with the calibrated transform, then route by current screen.
  {
    // Touch detection with HYSTERESIS + a debounced release latch. The recurring
    // "single tap registers as double" bug came from a SINGLE pressure threshold:
    // on the noisy XPT2046 resistive panel rz dips mid-press, which looked like a
    // finger-lift and re-fired the SAME continuous press as a second tap (e.g. STOP
    // -> CONFIRM, then the same press hits GUARDAR and dismisses it instantly).
    // Fix that can't be defeated by noise: FIRE only above kPressHi, and only re-arm
    // after pressure stays below the LOWER kReleaseLo for kRelSamples consecutive
    // samples (a genuine lift). A momentary dip between the two thresholds, or a
    // single-sample drop, can no longer fake a release - so one press = one action.
    static const int kPressHi    = 220;  // must EXCEED to fire a tap
    static const int kReleaseLo  = 90;   // must stay BELOW this to count as lifted (hysteresis gap)
    static const int kRelSamples = 3;    // consecutive sub-kReleaseLo samples = real lift (~24ms @ 8ms loop)
    static bool s_down = false;          // true = a press is in progress / not yet released
    static int  s_relCount = 0;          // consecutive below-release-threshold samples
    static uint32_t lastFireMs = 0;
    uint16_t rx, ry, rz;
    touchRaw(rx, ry, rz);
    if (rz > kPressHi) g_lastTouchMs = now;  // finger contact -> defer WiFi windows (keep touch responsive)
    // Re-arm ONLY on a debounced release (low threshold held for several samples).
    if (rz < kReleaseLo) { if (++s_relCount >= kRelSamples) s_down = false; }
    else                 { s_relCount = 0; }
    if (rz > kPressHi && !s_down && now - lastFireMs > 200) {  // RISING edge -> exactly one action per press
      s_down = true; lastFireMs = now;
      int sx = touchScreenX(ry), sy = touchScreenY(rx);
      Serial.printf("[touch] screen=%d sx=%d sy=%d rz=%u\n", (int)g_screen, sx, sy, (unsigned)rz);
      if (g_screen == SCREEN_MAIN) {
        // While recording, the ONLY valid touch action is DETENER. Header/table
        // changes and LLAMAR are disabled so a noisy/stray touch can never trap
        // an operator away from the stop/delete flow.
        if (g_anyRec) {
          if (sy >= TOG_Y0 && sy <= TOG_Y1) fireShutterToggle();   // DETENER -> SCREEN_CONFIRM
        } else if (sy < TOG_Y0) {
          // header = re-pick table. GUARDED against the kick bug: a single (often stray)
          // header tap - common right after a WiFi-radio window drops the cams / freezes
          // touch sampling - must NOT throw the operator out of the record screen.
          // Require a DELIBERATE DOUBLE-tap within 1.5s; a lone tap only arms and stays
          // on SCREEN_MAIN. The header hint reads "toca 2x" so the action is discoverable.
          static uint32_t s_hdrArmMs = 0;
          if (s_hdrArmMs && now - s_hdrArmMs < 1500) {
            s_hdrArmMs = 0;
            g_screen = SCREEN_MESA; g_forceRender = true;          // confirmed -> re-pick mesa
          } else {
            s_hdrArmMs = now;                                      // arm only; stay on MAIN
          }
        } else if (sy <= TOG_Y1) {
          // GRABAR is PHYSICALLY un-pressable in any NO-GO state (no both cams /
          // uplink borrow / prior take still saving) - same hard gate as the BLE
          // fob. A locked tap is a no-op (the button already shows the reason); we
          // only nudge a redraw so any just-changed state repaints immediately.
          if (startGate() == GATE_OK) fireShutterToggle();         // GRABAR (then SD check)
          else { g_lastBlockedMs = now; g_forceRender = true; }
        } else if (sy >= ROW_Y0) {
          callLead();                                              // full-width LLAMAR
        }
        renderUI();
      } else if (g_screen == SCREEN_CONFIRM) {
        // Post-STOP decision: top half = GUARDAR (keep), bottom half = DESCARTAR
        // (delete). Split at the gap between the two buttons (y=148).
        if (sy < 148) saveTake();
        else          deleteTake();
        renderUI();
      } else if (g_screen == SCREEN_CONFIRM_ID) {
        // "Are you <name>?": left = SI (commit + Mesa), right = NO (re-enter kit).
        // Only react in the button band (y>=138) so a stray top tap does nothing.
        if (sy >= 138) { if (sx < 160) identityYes(); else identityNo(); }
        renderUI();
      } else if (g_screen == SCREEN_PROVISION) {
        // REGISTRO is the root of setup: NO ATRAS here. The only way forward is to
        // enter a kit number and press ENTRAR (-> MESA). This removes the confusing
        // "ATRAS jumps to the recording UI" path entirely.
        // Numeric keypad: rows [1 2 3][4 5 6][7 8 9][DEL 0 ENTRAR]. Digit taps
        // append to the kit-number string; DEL backspaces; ENTRAR verifies.
        int kr, kc;
        if (keypadHit(sx, sy, kr, kc)) {
          if (kr == 3 && kc == 0) {                                   // DEL
            if (g_provKit.length()) g_provKit.remove(g_provKit.length() - 1);
          } else if (kr == 3 && kc == 2) {                            // ENTRAR
            provisionVerify();
          } else {                                                    // a digit
            const char* lab = KP_LABEL[kr][kc];
            if (g_provKit.length() < 9) g_provKit += lab[0];          // single digit char
          }
        }
        g_forceRender = true; renderUI();
      } else if (g_screen == SCREEN_MESA) {
        if (sy < 86 && sx >= 196) {                                      // ATRAS: big top-right zone (above the keypad)
          g_screen = SCREEN_PROVISION;   // ATRAS always -> back to the kit/operator screen
        } else {
          // Numeric keypad: rows [1 2 3][4 5 6][7 8 9][DEL 0 ENTRAR]. Digit taps
          // append to the table-number string; DEL backspaces; ENTRAR verifies.
          int kr, kc;
          if (keypadHit(sx, sy, kr, kc)) {
            if (kr == 3 && kc == 0) {                                   // DEL
              if (g_mesaNum.length()) g_mesaNum.remove(g_mesaNum.length() - 1);
            } else if (kr == 3 && kc == 2) {                            // ENTRAR
              mesaVerify();
            } else {                                                    // a digit
              const char* lab = KP_LABEL[kr][kc];
              if (g_mesaNum.length() < 9) g_mesaNum += lab[0];          // single digit char
            }
          }
        }
        g_forceRender = true; renderUI();
      }
    }
  }
  // Rolling prompt: advance the marquee + redraw ONLY the prompt band (no full
  // redraw, no flicker) so a long task instruction rolls past and is fully
  // readable. Only on the main screen, only when the prompt overflows the band.
  if (g_tftReady && g_screen == SCREEN_MAIN
      && (int)g_cfg.prompt.length() > PROMPT_VIS
      && now - g_promptScrollMs > 240) {
    g_promptScrollMs = now;
    g_promptScroll++;
    drawPromptBand();
  }

  // CONFIRM auto-save: if the operator walks off without choosing GUARDAR/
  // DESCARTAR, default to KEEP after 45s so the fob never gets stuck off MAIN
  // (and footage is preserved - a wrong keep can be deleted at ingest, a wrong
  // delete cannot be undone). Choosing keep-by-default is the safe bias.
  // SIGNED elapsed compare: g_confirmStartMs is set with a FRESH millis() inside the
  // touch handler, which runs LATER in this same loop iteration than the top-of-loop
  // `now` (the screen redraw alone is ~80ms). So now < g_confirmStartMs right after a
  // stop, and an unsigned (now - start) underflows to ~4.29e9 > 45000 -> the auto-save
  // fired INSTANTLY, dismissing the GUARDAR/DESCARTAR screen on a single press. Casting
  // to int32_t makes a negative elapsed stay negative (not a huge unsigned).
  if (g_screen == SCREEN_CONFIRM && (int32_t)(millis() - g_confirmStartMs) > 45000) {
    Serial.println("[ui] CONFIRM timeout -> auto-SAVE");
    saveTake();
    renderUI();
  }
#endif

  // Setup screens are local-first. Do not pre-warm WiFi just because the operator
  // is entering kit/table numbers: WiFi shares the radio with BLE and must never
  // be part of the control path. If a stale build left WiFi active from setup,
  // drop it as soon as we return to MAIN.
  {
    static UiScreen s_lastScreen = SCREEN_MAIN;
    if (g_screen != s_lastScreen) {
      bool nowSetup = (g_screen == SCREEN_PROVISION || g_screen == SCREEN_MESA ||
                       g_screen == SCREEN_CONFIRM_ID);
      bool wasSetup = (s_lastScreen == SCREEN_PROVISION || s_lastScreen == SCREEN_MESA ||
                       s_lastScreen == SCREEN_CONFIRM_ID);
      if (!nowSetup && wasSetup && g_wifiActive) wifiEnqueue(WJOB_WIFIDOWN);
      s_lastScreen = g_screen;
    }
  }

  // Camera discovery + the OSC trigger path run on the discovery worker (core 0),
  // not here - the loop stays free for touch. No BLE reconcilers / advertising
  // watchdog exist anymore.
  if (now - last > 30000) {
    Serial.printf("[hb] uptime=%lus cams=%d ordinal=%u rec=%d ssid=%s ip=%s\n",
                  (unsigned long)(now / 1000), (int)g_connCount, g_cfg.ordinal, g_anyRec ? 1 : 0,
                  WiFi.SSID().c_str(), WiFi.localIP().toString().c_str());
    last = now;
    renderUI();   // periodic refresh (events already redraw via publishStatus)
    // Ship new episode-log lines to the dashboard. The upload now runs on the
    // core-0 WiFi worker (never blocks touch); we still only enqueue when idle and
    // touch-quiet so a WiFi window can't be UP at the instant a take starts (the
    // worker also re-checks g_anyRec via wifiUp()). Cheap no-op when nothing new.
    // MAIN only: setup screens are local-first and should not create WiFi work.
    // Also require BOTH cams already online: the uplink borrows the single radio
    // (AP drops), so stealing it while a cam is missing would block that cam's
    // greedy reconnect. Upload only from a fully-connected, idle, quiet state.
    if (!g_anyRec && g_connCount >= kMinCams && g_screen == SCREEN_MAIN
        && now - g_lastTouchMs > kUiQuietMs) wifiEnqueue(WJOB_UPLOAD);
  }

  // Per-cam telemetry relay (TASK 5): refresh + POST battery/SD/online/recording
  // to the dashboard at ~kTelemPeriodMs, IDLE ONLY. GATED OFF by default: the
  // POST calls wifiUp() which blocks this single-threaded loop (so the touch
  // poll above goes dead during the window, and worse when WiFi is flaky). It is
  // also unverified (the BE80 battery/SD read is stubbed) and the live dashboard
  // does not consume it yet, so there is no reason to freeze the UI for it.
  // Enable with -DPANTHEON_TELEM_RELAY=1 once it is wanted + WiFi is moved off the
  // trigger/UI loop.
#ifdef PANTHEON_TELEM_RELAY
  static uint32_t lastTelem = 0;
  if (now - lastTelem > kTelemPeriodMs) {
    lastTelem = now;
    if (!g_anyRec && now - g_lastTouchMs > kUiQuietMs) wifiEnqueue(WJOB_TELEM);
  }
#endif
  // 8ms ~= 125Hz touch sampling (was 50ms/20Hz). Cheap: redraws are gated by a
  // UI signature, so the idle loop just polls touch + yields to the RTOS.
  delay(8);
}
