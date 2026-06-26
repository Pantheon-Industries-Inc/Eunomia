// Off-target (host) tests for firmware/coordinator/transport/proto/ — the F2 correctness proof, no
// rig.
//
// Covers, against a MOCK OSC/telnet server (in-process MockConn) + the F1 core seams:
//   * THE TWO HARD RULES at the wire level: OSC is fire-and-forget (the body is NEVER read), and
//     start() pushes current_assignment.env THEN fires camera.startCapture DIRECTLY (no per-take
//     arm).
//   * L2-ONLY presence: the MAC→side map + registry derive presence from the station table with NO
//     socket/OSC at all.
//   * Seam conformance: the X3 adapter satisfies CaptureDevicePort; the Coordinator drives it end
//   to
//     end; the durable ordinal honors persist-before-advance under a forced NVS-write failure.
//   * OQ-1 (env-projection): the adapter's start() pushes the env core::project_assignment_env
//   emits
//     for the CURRENT take (episode_id present), proving take() is populated before start() (zero
//     core change).
//   * OQ-10 (env-key conformance): core's projected key set covers every key discardd sources (with
//     the one flagged gap — OPERATOR_NAME — asserted as the known divergence).
//   * The NVS 15-char-key mapping + the SD-daemon provisioning parser.
#include <unity.h>

#include <cstdint>
#include <string>
#include <vector>

#include "conn.h"
#include "coordinator.h"
#include "nvs_keys.h"
#include "presence.h"
#include "provisioning.h"
#include "sidecar_assembly.h"
#include "x3_capture_device.h"
#include "x3_protocol.h"

using namespace eunomia::transport;
using eunomia::core::Assignment;
using eunomia::core::Clock;
using eunomia::core::Coordinator;
using eunomia::core::PersistentStore;
using eunomia::core::project_assignment_env;
using eunomia::core::project_stop_env;
using eunomia::core::Rng;
using eunomia::core::TakeContext;

namespace {

// ---- the mock OSC/telnet server (in-process; deterministic, no real sockets) -------------------
// One MockConn stands in for one camera's :80 (OSC) + :23 (telnet) — each request opens/closes it
// fresh, exactly as WiFiClient is used. It RECORDS every connection's port + written bytes and
// every read (with its port), and SCRIPTS telnet responses so telnet_run completes.
class MockConn : public Conn {
public:
  bool fail_connect = false;

  bool connect(const std::string &host, std::uint16_t port, std::uint32_t) override {
    if (fail_connect) {
      return false;
    }
    host_ = host;
    port_ = port;
    tx_.clear();
    rx_.clear();
    rx_pos_ = 0;
    gen_done_ = false;
    connected_ = true;
    if (port == kTelnetPort) {
      // a tiny telnet banner with an IAC DO (TERMINAL-TYPE) so the negotiation path is exercised
      rx_.push_back(0xFF);
      rx_.push_back(0xFD);
      rx_.push_back(0x18);
    }
    return true;
  }
  bool connected() override { return connected_; }
  int available() override { return static_cast<int>(rx_.size() - rx_pos_); }
  int read() override {
    if (rx_pos_ >= rx_.size()) {
      return -1;
    }
    reads_.push_back(port_); // record the port every byte was read on (HARD RULE 1 check)
    return rx_[rx_pos_++];
  }
  std::size_t write(const std::uint8_t *data, std::size_t n) override {
    tx_.append(reinterpret_cast<const char *>(data), n);
    if (port_ == kTelnetPort && !gen_done_ && tx_.find("__X3_DONE__") != std::string::npos) {
      script_telnet_response();
      gen_done_ = true;
    }
    if (port_ == kOscPort && !gen_done_ && tx_.find("GET /osc/info") != std::string::npos) {
      script_info_response(); // depot lockcams path only — osc_fire (POST) never triggers this
      gen_done_ = true;
    }
    return n;
  }
  void flush() override {}
  void stop() override {
    if (connected_) {
      sent_.push_back({port_, tx_});
      connected_ = false;
    }
  }

  // ---- assertions ----
  std::vector<std::string> osc_commands() const { // "name" of each OSC post (port 80)
    std::vector<std::string> names;
    for (const auto &s : sent_) {
      if (s.first != kOscPort) {
        continue;
      }
      const std::size_t k = s.second.find("\"name\":\"");
      if (k == std::string::npos) {
        continue;
      }
      const std::size_t b = k + 8;
      const std::size_t e = s.second.find('"', b);
      names.push_back(s.second.substr(b, e - b));
    }
    return names;
  }
  std::vector<std::string> telnet_writes() const {
    std::vector<std::string> v;
    for (const auto &s : sent_) {
      if (s.first == kTelnetPort) {
        v.push_back(s.second);
      }
    }
    return v;
  }
  std::vector<std::uint16_t> connect_ports() const {
    std::vector<std::uint16_t> v;
    for (const auto &s : sent_) {
      v.push_back(s.first);
    }
    return v;
  }
  bool any_read_on(std::uint16_t port) const {
    for (auto p : reads_) {
      if (p == port) {
        return true;
      }
    }
    return false;
  }

private:
  void script_telnet_response() {
    std::string body;
    if (tx_.find("grep VID_") != std::string::npos) {
      body = "VID_20260624_120000_00_000001.insv\n"; // ls -t clip name
    } else if (tx_.find("PCARDOK") != std::string::npos) {
      body = "PCARDOK\n";
    } else if (tx_.find("archive.trigger") != std::string::npos) {
      body = "ARC_OK\n";
    } else {
      body = "WROTE\n"; // a cat>file heredoc write
    }
    body += "__X3_DONE__\n";
    for (char c : body) {
      rx_.push_back(static_cast<std::uint8_t>(c));
    }
  }

  void script_info_response() {
    const std::string resp = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n"
                             "{\"serialNumber\":\"IAQEB2601KHF6C\",\"firmwareVersion\":\"1.1.6\"}";
    for (char c : resp) {
      rx_.push_back(static_cast<std::uint8_t>(c));
    }
  }

  std::string host_;
  std::uint16_t port_ = 0;
  bool connected_ = false;
  std::string tx_;
  std::vector<std::uint8_t> rx_;
  std::size_t rx_pos_ = 0;
  bool gen_done_ = false;
  std::vector<std::pair<std::uint16_t, std::string>> sent_;
  std::vector<std::uint16_t> reads_;
};

class NoopDelayer : public Delayer {
public:
  void delay_ms(std::uint32_t) override {}
};

// A canned env provider (the device just pushes whatever bytes it returns).
class CannedEnv : public EnvProvider {
public:
  std::string assignment_env() override { return "EPISODE_ID=\"canned\"\n"; }
  std::string stop_env() override { return "STOP_REASON=\"operator\"\n"; }
};

// ---- the F1 core seam fakes (mirror test_core) ----
class FakeClock : public Clock {
public:
  std::int64_t secs = 1700000000;
  std::int64_t unix_seconds() override { return secs; }
  double unix_seconds_frac() override { return static_cast<double>(secs); }
  std::uint64_t monotonic_millis() override { return 0; }
};
class CounterRng : public Rng {
public:
  std::uint8_t next = 0;
  void fill(std::uint8_t *out, std::size_t n) override {
    for (std::size_t i = 0; i < n; ++i) {
      out[i] = next++;
    }
  }
};
class FakeStore : public PersistentStore {
public:
  std::map<std::string, std::int64_t> kv;
  bool fail_next = false;
  std::int64_t read_i64(const std::string &k, std::int64_t fb) override {
    auto it = kv.find(k);
    return it == kv.end() ? fb : it->second;
  }
  bool write_i64(const std::string &k, std::int64_t v) override {
    if (fail_next) {
      fail_next = false;
      return false;
    }
    kv[k] = v;
    return true;
  }
};

// The OQ-1 provider: projects the env from the live coordinator take() + the app's Assignment. The
// coordinator is bound AFTER construction to break the device↔coordinator↔provider construction
// cycle (the real app glue does the same).
class CoordEnv : public EnvProvider {
public:
  explicit CoordEnv(Assignment a) : a_(std::move(a)) {}
  void bind(const Coordinator *c) { c_ = c; }
  std::string assignment_env() override { return project_assignment_env(a_, c_->take()); }
  std::string stop_env() override { return project_stop_env(c_->take()); }

private:
  const Coordinator *c_ = nullptr;
  Assignment a_;
};

} // namespace

// ================================================================================================

// ---- HARD RULE 1 at the wire: osc_fire writes + flushes + closes, NEVER reads ----
void test_osc_fire_is_fire_and_forget() {
  MockConn c;
  NoopDelayer d;
  const bool ok = osc_fire(c, d, "192.168.42.2", osc_command_json("camera.startCapture"));
  TEST_ASSERT_TRUE(ok);
  // exactly one port-80 connection carrying camera.startCapture, and ZERO reads on it.
  const auto cmds = c.osc_commands();
  TEST_ASSERT_EQUAL(1, static_cast<int>(cmds.size()));
  TEST_ASSERT_EQUAL_STRING("camera.startCapture", cmds[0].c_str());
  TEST_ASSERT_FALSE(c.any_read_on(kOscPort)); // the off-by-one body is NEVER read
}

void test_osc_fire_no_connect_returns_false() {
  MockConn c;
  c.fail_connect = true;
  NoopDelayer d;
  TEST_ASSERT_FALSE(osc_fire(c, d, "192.168.42.2", osc_command_json("camera.stopCapture")));
}

// ---- DEPOT lockcams path: osc_info reads the serial (one-shot, NOT on the trigger/presence path)
// ----
void test_osc_info_reads_serial() {
  MockConn c;
  NoopDelayer d;
  std::string serial;
  TEST_ASSERT_TRUE(osc_info(c, d, "192.168.42.2", serial));
  TEST_ASSERT_EQUAL_STRING("IAQEB2601KHF6C", serial.c_str());
}

// ---- telnet clip recovery + sidecar path derivation ----
void test_telnet_clip_recover_and_sidecar_path() {
  MockConn c;
  NoopDelayer d;
  std::string out;
  TEST_ASSERT_TRUE(telnet_run(c, d, "192.168.42.2", build_ls_clip_cmd(), out));
  const std::string clip = parse_clip_from_ls(out);
  TEST_ASSERT_EQUAL_STRING("VID_20260624_120000_00_000001.insv", clip.c_str());
  const std::string sc = sidecar_path_for_clip(clip);
  TEST_ASSERT_EQUAL_STRING("/tmp/SD0/DCIM/Camera01/VID_20260624_120000_000001.pantheon.json",
                           sc.c_str());
}

void test_sidecar_path_rejects_non_vid() {
  TEST_ASSERT_TRUE(sidecar_path_for_clip("/tmp/SD0/DCIM/Camera01/IMG_123.jpg").empty());
  TEST_ASSERT_TRUE(sidecar_path_for_clip("").empty());
}

// ---- HARD RULE 2 + ordering: start() = assignment env (telnet) THEN startCapture (OSC), no arm
// ----
void test_x3_start_env_then_startcapture_no_arm() {
  CameraRegistry reg;
  reg.set_map(MacSideMap::from_allowlist("aa:aa:aa:aa:aa:aa,bb:bb:bb:bb:bb:bb"));
  reg.update({{"aa:aa:aa:aa:aa:aa", "192.168.42.2"}, {"bb:bb:bb:bb:bb:bb", "192.168.42.3"}});
  MockConn c;
  NoopDelayer d;
  CannedEnv env;
  X3CaptureDevice left("left", reg, c, d, env);

  left.start();

  // connection order: telnet (:23, assignment write) BEFORE OSC (:80, startCapture)
  const auto ports = c.connect_ports();
  TEST_ASSERT_EQUAL(2, static_cast<int>(ports.size()));
  TEST_ASSERT_EQUAL_UINT16(kTelnetPort, ports[0]);
  TEST_ASSERT_EQUAL_UINT16(kOscPort, ports[1]);
  // the telnet write targeted current_assignment.env
  const auto tw = c.telnet_writes();
  TEST_ASSERT_EQUAL(1, static_cast<int>(tw.size()));
  TEST_ASSERT_TRUE(tw[0].find("current_assignment.env") != std::string::npos);
  // exactly ONE OSC command = startCapture; NO setOptions/arm; no body read
  const auto cmds = c.osc_commands();
  TEST_ASSERT_EQUAL(1, static_cast<int>(cmds.size()));
  TEST_ASSERT_EQUAL_STRING("camera.startCapture", cmds[0].c_str());
  TEST_ASSERT_FALSE(c.any_read_on(kOscPort));
}

void test_x3_stop_readback_and_write_sidecar() {
  CameraRegistry reg;
  reg.set_map(MacSideMap::from_allowlist("aa:aa:aa:aa:aa:aa"));
  reg.update({{"aa:aa:aa:aa:aa:aa", "192.168.42.2"}});
  MockConn c;
  NoopDelayer d;
  CannedEnv env;
  X3CaptureDevice left("left", reg, c, d, env);

  left.stop();
  const auto stop_cmds = c.osc_commands();
  TEST_ASSERT_EQUAL(1, static_cast<int>(stop_cmds.size()));
  TEST_ASSERT_EQUAL_STRING("camera.stopCapture", stop_cmds[0].c_str());
  TEST_ASSERT_FALSE(c.any_read_on(kOscPort));

  const std::string clip = left.read_back_filename();
  TEST_ASSERT_EQUAL_STRING("VID_20260624_120000_00_000001.insv", clip.c_str());

  // write_sidecar with archive=0 → one telnet stop-env write, NO archive trigger
  eunomia::Sidecar rec;
  rec.archive = 0;
  left.write_sidecar(rec);
  bool saw_stop_env = false, saw_arc = false;
  for (const auto &w : c.telnet_writes()) {
    if (w.find("current_stop.env") != std::string::npos) {
      saw_stop_env = true;
    }
    if (w.find("archive.trigger") != std::string::npos) {
      saw_arc = true;
    }
  }
  TEST_ASSERT_TRUE(saw_stop_env);
  TEST_ASSERT_FALSE(saw_arc);
}

void test_x3_write_sidecar_archive_fires_trigger() {
  CameraRegistry reg;
  reg.set_map(MacSideMap::from_allowlist("aa:aa:aa:aa:aa:aa"));
  reg.update({{"aa:aa:aa:aa:aa:aa", "192.168.42.2"}});
  MockConn c;
  NoopDelayer d;
  CannedEnv env;
  X3CaptureDevice left("left", reg, c, d, env);
  eunomia::Sidecar rec;
  rec.archive = 1; // DESCARTAR
  left.write_sidecar(rec);
  bool saw_arc = false;
  for (const auto &w : c.telnet_writes()) {
    if (w.find("archive.trigger") != std::string::npos) {
      saw_arc = true;
    }
  }
  TEST_ASSERT_TRUE(saw_arc);
}

void test_x3_not_present_is_noop() {
  CameraRegistry reg; // empty: no present sides
  MockConn c;
  NoopDelayer d;
  CannedEnv env;
  X3CaptureDevice left("left", reg, c, d, env);
  left.start();
  left.stop();
  TEST_ASSERT_EQUAL(0, static_cast<int>(c.connect_ports().size())); // nothing fired
}

// ---- L2-only presence: MAC→side map + registry, NO socket ----
void test_presence_mac_side_map_and_registry() {
  MacSideMap m = MacSideMap::from_allowlist("AA:AA:AA:AA:AA:AA, bb:bb:bb:bb:bb:bb");
  TEST_ASSERT_EQUAL_STRING("left", m.side_for("aa:aa:aa:aa:aa:aa").c_str()); // case-insensitive
  TEST_ASSERT_EQUAL_STRING("right", m.side_for("BB:BB:BB:BB:BB:BB").c_str());
  TEST_ASSERT_TRUE(m.side_for("cc:cc:cc:cc:cc:cc").empty());

  CameraRegistry reg;
  reg.set_map(m);
  // both present (with leases)
  reg.update({{"aa:aa:aa:aa:aa:aa", "192.168.42.2"}, {"bb:bb:bb:bb:bb:bb", "192.168.42.3"}});
  TEST_ASSERT_EQUAL(2, static_cast<int>(reg.present().size()));
  TEST_ASSERT_EQUAL_STRING("192.168.42.2", reg.ip_for("left").c_str());
  TEST_ASSERT_TRUE(reg.is_present("right"));
  // right loses its lease (associated, no IP) → one-sided
  reg.update({{"aa:aa:aa:aa:aa:aa", "192.168.42.2"}, {"bb:bb:bb:bb:bb:bb", ""}});
  TEST_ASSERT_EQUAL(1, static_cast<int>(reg.present().size()));
  TEST_ASSERT_FALSE(reg.is_present("right"));
  // an unmapped MAC never counts (foreign cam isolation)
  reg.update({{"cc:cc:cc:cc:cc:cc", "192.168.42.4"}});
  TEST_ASSERT_EQUAL(0, static_cast<int>(reg.present().size()));
}

void test_empty_allowlist_yields_no_sides() {
  CameraRegistry reg; // no map set
  reg.update({{"aa:aa:aa:aa:aa:aa", "192.168.42.2"}});
  TEST_ASSERT_EQUAL(0, static_cast<int>(reg.present().size())); // GRABAR stays safely locked (OQ-9)
}

// ---- NVS 15-char-key mapping ----
void test_nvs_key_mapping() {
  const std::string mapped = nvs_key_for(kOrdinalLogicalKey); // "fob_episode_ordinal" (19 chars)
  TEST_ASSERT_EQUAL_STRING("ord", mapped.c_str());
  TEST_ASSERT_TRUE(mapped.size() <= kNvsKeyMax);
  TEST_ASSERT_EQUAL_STRING("station", nvs_key_for("station").c_str()); // short passes through
  TEST_ASSERT_TRUE(nvs_key_for("a_very_long_unforeseen_key").size() <= kNvsKeyMax);
}

// ---- SD-daemon provisioning parser (PROVISIONAL format; OQ-8) ----
void test_provisioning_parse() {
  const ProvisioningInfo i = parse_provisioning_push(
      "mac=aa:bb:cc:dd:ee:ff;ip=192.168.42.2;body_serial=IAQEB123;insv_serial=IXSEB456;side=left");
  TEST_ASSERT_TRUE(i.valid);
  TEST_ASSERT_EQUAL_STRING("aa:bb:cc:dd:ee:ff", i.mac.c_str());
  TEST_ASSERT_EQUAL_STRING("192.168.42.2", i.ip.c_str());
  TEST_ASSERT_EQUAL_STRING("IAQEB123", i.body_serial.c_str());
  TEST_ASSERT_EQUAL_STRING("left", i.side.c_str());
  TEST_ASSERT_FALSE(parse_provisioning_push("garbage").valid); // no mac → not valid
}

// ---- INTEGRATION: the Coordinator drives the X3 adapters; the two hard rules + OQ-1 hold ----
void test_coordinator_two_hard_rules_and_oq1() {
  CameraRegistry reg;
  reg.set_map(MacSideMap::from_allowlist("aa:aa:aa:aa:aa:aa,bb:bb:bb:bb:bb:bb"));
  reg.update({{"aa:aa:aa:aa:aa:aa", "192.168.42.2"}, {"bb:bb:bb:bb:bb:bb", "192.168.42.3"}});
  MockConn cl, cr;
  NoopDelayer d;
  FakeClock clock;
  CounterRng rng;
  FakeStore store;
  StationTablePresence presence(reg);

  Assignment a;
  a.kit_id = "kit_2";
  a.operator_id = "op002";
  a.station_id = "5";

  CoordEnv env(a); // OQ-1: projects from coord.take() at start() time (coordinator bound below)
  X3CaptureDevice left("left", reg, cl, d, env);
  X3CaptureDevice right("right", reg, cr, d, env);
  Coordinator coord({&clock, &rng, &store, &presence, nullptr},
                    {{"left", &left}, {"right", &right}}, 2);
  env.bind(&coord); // breaks the device↔coordinator↔provider construction cycle
  coord.set_assignment(a);

  const std::string eid = coord.mint_episode_id();
  TEST_ASSERT_TRUE(coord.trigger({"left", "right"}));

  // ordinal advanced to 1 (persisted before advance)
  TEST_ASSERT_EQUAL(1, static_cast<int>(coord.take().episode_ordinal));
  TEST_ASSERT_EQUAL(1, static_cast<int>(store.read_i64("fob_episode_ordinal", -1)));

  // both cams: assignment env (telnet) THEN startCapture (OSC), no read on :80
  for (MockConn *m : {&cl, &cr}) {
    const auto cmds = m->osc_commands();
    TEST_ASSERT_EQUAL(1, static_cast<int>(cmds.size()));
    TEST_ASSERT_EQUAL_STRING("camera.startCapture", cmds[0].c_str());
    TEST_ASSERT_FALSE(m->any_read_on(kOscPort));
    const auto ports = m->connect_ports();
    TEST_ASSERT_EQUAL_UINT16(kTelnetPort, ports[0]); // env first
    TEST_ASSERT_EQUAL_UINT16(kOscPort, ports[1]);    // then fire
  }
  // OQ-1 proof: the assignment env pushed to the card carries the CURRENT take's episode_id — so
  // coord.take() was populated BEFORE start() ran (zero core change).
  bool eid_in_env = false;
  for (const auto &w : cl.telnet_writes()) {
    if (w.find("EPISODE_ID=\"" + eid + "\"") != std::string::npos) {
      eid_in_env = true;
    }
  }
  TEST_ASSERT_TRUE(eid_in_env);
}

// ---- seam conformance: persist-before-advance under a forced NVS-write failure ----
void test_persist_before_advance_under_nvs_failure() {
  CameraRegistry reg;
  reg.set_map(MacSideMap::from_allowlist("aa:aa:aa:aa:aa:aa,bb:bb:bb:bb:bb:bb"));
  reg.update({{"aa:aa:aa:aa:aa:aa", "192.168.42.2"}, {"bb:bb:bb:bb:bb:bb", "192.168.42.3"}});
  MockConn cl, cr;
  NoopDelayer d;
  FakeClock clock;
  CounterRng rng;
  FakeStore store;
  store.fail_next = true; // the durable ordinal write will fail
  StationTablePresence presence(reg);
  CannedEnv env;
  X3CaptureDevice left("left", reg, cl, d, env);
  X3CaptureDevice right("right", reg, cr, d, env);
  Coordinator coord({&clock, &rng, &store, &presence, nullptr},
                    {{"left", &left}, {"right", &right}}, 2);
  Assignment a;
  a.kit_id = "kit_2";
  coord.set_assignment(a);

  TEST_ASSERT_FALSE(coord.trigger({"left", "right"}));                  // rolled back
  TEST_ASSERT_EQUAL(0, static_cast<int>(coord.take().episode_ordinal)); // ordinal NOT burned
  // F6 fire-then-commit: the startCapture WAS fired (the fire confirms first), THEN the durable
  // commit (advance) failed, so each cam is rolled back with a stopCapture — no one-sided clip left
  // rolling. (This is the Victor-faithful order; before F6 the abort happened before the fire.)
  for (MockConn *m : {&cl, &cr}) {
    const auto cmds = m->osc_commands();
    TEST_ASSERT_EQUAL(2, static_cast<int>(cmds.size()));
    TEST_ASSERT_EQUAL_STRING("camera.startCapture", cmds[0].c_str());
    TEST_ASSERT_EQUAL_STRING("camera.stopCapture", cmds[1].c_str());
  }
}

// ---- F6: start_confirmed() returns the startCapture connect-ack; void start() routes through it
// (no double-fire); HARD RULE 2 (no OSC body read) holds; no-connect → false (under-confirm) ----
void test_x3_start_confirmed_connect_ack() {
  CameraRegistry reg;
  reg.set_map(MacSideMap::from_allowlist("aa:aa:aa:aa:aa:aa,bb:bb:bb:bb:bb:bb"));
  reg.update({{"aa:aa:aa:aa:aa:aa", "192.168.42.2"}, {"bb:bb:bb:bb:bb:bb", "192.168.42.3"}});
  NoopDelayer d;
  CannedEnv env;

  // connect-ack TRUE: a normal fire confirms (the startCapture socket connected + wrote).
  MockConn ok;
  X3CaptureDevice left("left", reg, ok, d, env);
  TEST_ASSERT_TRUE(left.start_confirmed());
  const auto cmds = ok.osc_commands();
  TEST_ASSERT_EQUAL(1, static_cast<int>(cmds.size())); // exactly one startCapture
  TEST_ASSERT_EQUAL_STRING("camera.startCapture", cmds[0].c_str());
  TEST_ASSERT_FALSE(ok.any_read_on(kOscPort)); // HARD RULE 2: the fire never reads the OSC body

  // void start() routes through the SAME single fire (no double-fire).
  MockConn ok2;
  X3CaptureDevice left2("left", reg, ok2, d, env);
  left2.start();
  TEST_ASSERT_EQUAL(1, static_cast<int>(ok2.osc_commands().size()));

  // connect-ack FALSE: the OSC socket never connects → start_confirmed() is false (the fire did not
  // land on this cam — core counts it as a cam that did not start).
  MockConn bad;
  bad.fail_connect = true;
  X3CaptureDevice right("right", reg, bad, d, env);
  TEST_ASSERT_FALSE(right.start_confirmed());
}

// ---- OQ-10: core's projected env keys cover everything discardd sources (with the flagged gap)
// ----
void test_env_key_conformance_with_discardd() {
  Assignment a;
  a.operator_id = "op002";
  a.station_id = "5";
  a.task_id = "t1";
  a.task_name = "fold";
  a.prompt = "fold the towel";
  a.rotation_id = "r1";
  a.session_id = "sess1";
  a.site_id = "mx";
  a.fob_id = "fob_abc";
  a.fob_build = "3.8.3";
  a.assignment_source = "fob_wifi";
  TakeContext t;
  t.episode_id = "eid";
  t.bimanual_episode_id = "bid";
  t.archive = 0;

  const std::string asn = project_assignment_env(a, t);
  // every key discardd SOURCES from current_assignment.env (oncam/discardd load_envs) is emitted:
  const char *required[] = {
      "OPERATOR_ID=", "STATION_ID=", "TASK_ID=",          "TASK_NAME=",           "PROMPT=",
      "ROTATION_ID=", "SESSION_ID=", "EPISODE_ID=",       "BIMANUAL_EPISODE_ID=", "SITE_ID=",
      "FOB_ID=",      "FOB_BUILD=",  "ASSIGNMENT_SOURCE="};
  for (const char *k : required) {
    TEST_ASSERT_TRUE_MESSAGE(asn.find(k) != std::string::npos, k);
  }
  // KNOWN, FLAGGED gap (OQ-10): discardd reads OPERATOR_NAME (into its discards/episode_files JSONL
  // ledgers, NOT the v2 sidecar). core's project_assignment_env does NOT emit it. This assertion
  // DOCUMENTS the divergence; adding OPERATOR_NAME is a core/ change, out of F2 scope (flagged).
  TEST_ASSERT_TRUE(asn.find("OPERATOR_NAME=") == std::string::npos);
  // discardd reads SESSION_ID (never FOB_SESSION_ID) — the key matches; the value is the
  // operational session (OQ-7), which is the intended shift semantic.

  const std::string stp = project_stop_env(t);
  const char *stop_required[] = {"EP_BIMANUAL_EPISODE_ID=", "STOP_REASON=",      "START_SKEW_MS=",
                                 "CAM_STARTED_UNIX=",       "CAM_STOPPED_UNIX=", "ARCHIVE="};
  for (const char *k : stop_required) {
    TEST_ASSERT_TRUE_MESSAGE(stp.find(k) != std::string::npos, k);
  }
}

void setUp() {}
void tearDown() {}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_osc_fire_is_fire_and_forget);
  RUN_TEST(test_osc_fire_no_connect_returns_false);
  RUN_TEST(test_osc_info_reads_serial);
  RUN_TEST(test_telnet_clip_recover_and_sidecar_path);
  RUN_TEST(test_sidecar_path_rejects_non_vid);
  RUN_TEST(test_x3_start_env_then_startcapture_no_arm);
  RUN_TEST(test_x3_stop_readback_and_write_sidecar);
  RUN_TEST(test_x3_write_sidecar_archive_fires_trigger);
  RUN_TEST(test_x3_not_present_is_noop);
  RUN_TEST(test_presence_mac_side_map_and_registry);
  RUN_TEST(test_empty_allowlist_yields_no_sides);
  RUN_TEST(test_nvs_key_mapping);
  RUN_TEST(test_provisioning_parse);
  RUN_TEST(test_coordinator_two_hard_rules_and_oq1);
  RUN_TEST(test_persist_before_advance_under_nvs_failure);
  RUN_TEST(test_x3_start_confirmed_connect_ack);
  RUN_TEST(test_env_key_conformance_with_discardd);
  return UNITY_END();
}
