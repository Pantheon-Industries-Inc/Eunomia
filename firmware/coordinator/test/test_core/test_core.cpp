// Off-target (host) tests for firmware/coordinator/core/ — the F1 correctness proof, no rig.
//
// Covers the headline guarantees: spam-safety (START dropped from every non-idle state; a burst →
// exactly one fire), the phantom-press gate (no commit unless sent==2; the 0/1/2 paths), the
// delayed-button instant-ack/lockout state, episode_id/display_id, the durable ordinal
// (persist-to-flash BEFORE advance), the ordinal-join ring bound, and the eunomia-sidecar/v1
// assembly validating against the generated parser + the golden fixtures. Drives fakes for every
// seam.
#include <unity.h>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "button_feedback.h"
#include "coordinator.h"
#include "episode.h"
#include "eunomia_sidecar.h"
#include "ordinal_log.h"
#include "sidecar_assembly.h"
#include "trigger_state_machine.h"

using namespace eunomia::core;

namespace {

class FakeClock : public Clock {
public:
  std::int64_t secs = 1700000000; // 2023-11-14T22:13:20Z
  std::int64_t unix_seconds() override { return secs; }
  double unix_seconds_frac() override { return static_cast<double>(secs); }
  std::uint64_t monotonic_millis() override { return mono; }
  std::uint64_t mono = 0;
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
  int writes = 0;
  std::int64_t read_i64(const std::string &key, std::int64_t fb) override {
    auto it = kv.find(key);
    return it == kv.end() ? fb : it->second;
  }
  bool write_i64(const std::string &key, std::int64_t v) override {
    if (fail_next) {
      fail_next = false;
      return false;
    }
    kv[key] = v;
    ++writes;
    return true;
  }
};

class FakePresence : public PresenceSource {
public:
  std::vector<std::string> list;
  std::vector<std::string> present() override { return list; }
};

class FakeDevice : public eunomia::CaptureDevicePort {
public:
  int starts = 0;
  int stops = 0;
  int wrote = 0;
  std::string clip = "VID_00.insv";
  void start() override { ++starts; }
  void stop() override { ++stops; }
  std::string read_back_filename() override { return clip; }
  std::string get_state() override { return "idle"; }
  void set_profile(const std::string &) override {}
  void write_sidecar(const eunomia::Sidecar &) override { ++wrote; }
};

class FakeSink : public TelemetrySink {
public:
  std::vector<std::string> sent;
  void send(const std::string &s) override { sent.push_back(s); }
};

} // namespace

// ---- spam-safety: START only from idle; STOP only from recording (the state-machine layer) ----
void test_state_machine_spam_safety() {
  TriggerStateMachine sm;
  TEST_ASSERT_EQUAL(static_cast<int>(Action::BeginStart), static_cast<int>(sm.offer(Input::Start)));
  TEST_ASSERT_EQUAL(static_cast<int>(Action::Ignored),
                    static_cast<int>(sm.offer(Input::Start))); // arming: dropped
  sm.begin_firing();
  TEST_ASSERT_EQUAL(static_cast<int>(Action::Ignored),
                    static_cast<int>(sm.offer(Input::Start))); // starting: dropped
  sm.on_started();
  TEST_ASSERT_EQUAL(static_cast<int>(Action::Ignored),
                    static_cast<int>(sm.offer(Input::Start))); // recording: dropped
  TEST_ASSERT_EQUAL(static_cast<int>(Action::BeginStop),
                    static_cast<int>(sm.offer(Input::Stop))); // recording → stopping
  TEST_ASSERT_EQUAL(static_cast<int>(Action::Ignored),
                    static_cast<int>(sm.offer(Input::Start))); // stopping: dropped
  TEST_ASSERT_EQUAL(static_cast<int>(Action::Ignored),
                    static_cast<int>(sm.offer(Input::Stop))); // stopping: STOP not valid
  sm.on_stopped();
  TEST_ASSERT_EQUAL(static_cast<int>(State::Idle), static_cast<int>(sm.state()));
  TEST_ASSERT_EQUAL(static_cast<int>(Action::Ignored),
                    static_cast<int>(sm.offer(Input::Stop))); // idle: STOP dropped
}

// ---- the phantom-press gate as a pure function (0/1/2 paths) ----
void test_phantom_gate_function() {
  TEST_ASSERT_EQUAL(static_cast<int>(GateOutcome::PhantomDropped),
                    static_cast<int>(evaluate_gate(0, 2)));
  TEST_ASSERT_EQUAL(static_cast<int>(GateOutcome::OneSidedRefused),
                    static_cast<int>(evaluate_gate(1, 2)));
  TEST_ASSERT_EQUAL(static_cast<int>(GateOutcome::Committed),
                    static_cast<int>(evaluate_gate(2, 2)));
  TEST_ASSERT_EQUAL(static_cast<int>(GateOutcome::Committed),
                    static_cast<int>(evaluate_gate(3, 2)));
}

// ---- the phantom-press gate via the Coordinator + the spam burst → exactly one fire ----
void test_coordinator_phantom_press_paths() {
  FakeClock clk;
  CounterRng rng;
  FakeStore store;
  FakePresence pres;
  FakeDevice left;
  FakeDevice right;
  Coordinator co({&clk, &rng, &store, &pres, nullptr}, {{"left", &left}, {"right", &right}}, 2);
  const std::vector<std::string> cams{"left", "right"};

  pres.list = {}; // 0 present → phantom, no advance, idle
  TEST_ASSERT_FALSE(co.trigger(cams));
  TEST_ASSERT_EQUAL(static_cast<int>(GateOutcome::PhantomDropped),
                    static_cast<int>(co.last_outcome()));
  TEST_ASSERT_EQUAL(static_cast<int>(State::Idle), static_cast<int>(co.state()));
  TEST_ASSERT_EQUAL(0, store.writes);
  TEST_ASSERT_EQUAL(0, left.starts);

  pres.list = {"left"}; // 1 present → one-sided refused (GRABAR locks), no advance
  TEST_ASSERT_FALSE(co.trigger(cams));
  TEST_ASSERT_EQUAL(static_cast<int>(GateOutcome::OneSidedRefused),
                    static_cast<int>(co.last_outcome()));
  TEST_ASSERT_EQUAL(0, store.writes);
  TEST_ASSERT_EQUAL(0, left.starts);

  pres.list = {"left", "right"}; // 2 present → commit, advance, fire both once
  TEST_ASSERT_TRUE(co.trigger(cams));
  TEST_ASSERT_EQUAL(static_cast<int>(GateOutcome::Committed), static_cast<int>(co.last_outcome()));
  TEST_ASSERT_EQUAL(static_cast<int>(State::Recording), static_cast<int>(co.state()));
  TEST_ASSERT_EQUAL(1, left.starts);
  TEST_ASSERT_EQUAL(1, right.starts);
  TEST_ASSERT_EQUAL_INT64(1, co.take().episode_ordinal);
  TEST_ASSERT_EQUAL(1, store.writes);

  // spam burst while recording → all dropped; still exactly one fire each; no ordinal advance
  TEST_ASSERT_FALSE(co.trigger(cams));
  TEST_ASSERT_FALSE(co.trigger(cams));
  TEST_ASSERT_EQUAL(1, left.starts);
  TEST_ASSERT_EQUAL(1, right.starts);
  TEST_ASSERT_EQUAL_INT64(1, co.take().episode_ordinal);
  TEST_ASSERT_EQUAL(1, store.writes);
}

// ---- delayed-button instant-ack + lockout (the same primitive for START/STOP/settings) ----
void test_button_feedback() {
  DelayedButton b;
  TEST_ASSERT_FALSE(b.working());
  TEST_ASSERT_EQUAL(static_cast<int>(Press::Accepted), static_cast<int>(b.press())); // instant ack
  TEST_ASSERT_TRUE(b.working());
  TEST_ASSERT_EQUAL(static_cast<int>(Press::IgnoredLocked),
                    static_cast<int>(b.press())); // lockout
  TEST_ASSERT_EQUAL(static_cast<int>(Press::IgnoredLocked), static_cast<int>(b.press()));
  TEST_ASSERT_TRUE(b.working());
  b.complete();
  TEST_ASSERT_FALSE(b.working());
  TEST_ASSERT_EQUAL(static_cast<int>(Press::Accepted), static_cast<int>(b.press())); // ready again
}

// ---- episode_id (UUIDv4) + display_id derivation + the calendar math ----
void test_episode_uuid_and_display() {
  CounterRng rng;
  const std::string a = mint_uuid_v4(rng);
  const std::string b = mint_uuid_v4(rng);
  TEST_ASSERT_EQUAL(36, static_cast<int>(a.size()));
  TEST_ASSERT_EQUAL('-', a[8]);
  TEST_ASSERT_EQUAL('-', a[13]);
  TEST_ASSERT_EQUAL('-', a[18]);
  TEST_ASSERT_EQUAL('-', a[23]);
  TEST_ASSERT_EQUAL('4', a[14]); // version nibble
  const char var = a[19];
  TEST_ASSERT_TRUE(var == '8' || var == '9' || var == 'a' || var == 'b'); // variant
  TEST_ASSERT_TRUE(a != b);                                               // unique

  int y = 0;
  int m = 0;
  int d = 0;
  ymd_from_unix(0, y, m, d);
  TEST_ASSERT_EQUAL(1970, y);
  TEST_ASSERT_EQUAL(1, m);
  TEST_ASSERT_EQUAL(1, d);
  ymd_from_unix(1700000000, y, m, d);
  TEST_ASSERT_EQUAL(2023, y);
  TEST_ASSERT_EQUAL(11, m);
  TEST_ASSERT_EQUAL(14, d);

  const std::string disp = make_display_id(1700000000, "op7", "5", 42);
  TEST_ASSERT_EQUAL_STRING("20231114_op7_5_000042", disp.c_str());
}

// ---- the durable ordinal: persist-to-flash BEFORE advance; never lose OR reuse a number ----
void test_durable_ordinal_persist_before_advance() {
  FakeStore store;
  DurableOrdinal ord(store, "k");
  TEST_ASSERT_EQUAL_INT64(0, ord.current());
  TEST_ASSERT_EQUAL_INT64(1, ord.advance());
  TEST_ASSERT_EQUAL_INT64(1, store.kv["k"]); // persisted before advance() returned
  TEST_ASSERT_EQUAL_INT64(1, ord.current());
  TEST_ASSERT_EQUAL_INT64(2, ord.advance());
  TEST_ASSERT_EQUAL_INT64(2, store.kv["k"]);

  store.fail_next = true;                    // simulate a flash-write failure
  TEST_ASSERT_EQUAL_INT64(0, ord.advance()); // unknown sentinel
  TEST_ASSERT_EQUAL_INT64(2, ord.current()); // did NOT advance (never burns a number)
  TEST_ASSERT_EQUAL_INT64(2, store.kv["k"]);
  TEST_ASSERT_EQUAL_INT64(3, ord.advance()); // recovers: resumes from 2 → 3 (no reuse)

  DurableOrdinal ord2(store, "k"); // a fresh counter over the same store resumes (battery swap)
  TEST_ASSERT_EQUAL_INT64(3, ord2.current());
  TEST_ASSERT_EQUAL_INT64(4, ord2.advance());
}

// ---- the fob-side ordinal-join ring buffer is self-bounding (drops the oldest) ----
void test_ordinal_log_ring_bounds() {
  OrdinalLog log(3);
  for (int i = 1; i <= 5; ++i) {
    OrdinalLogEntry e;
    e.ordinal = i;
    e.episode_id = "e" + std::to_string(i);
    log.append(e);
  }
  TEST_ASSERT_EQUAL(3, static_cast<int>(log.size()));
  TEST_ASSERT_EQUAL(3, static_cast<int>(log.capacity()));
  TEST_ASSERT_EQUAL_INT64(3, log.at(0).ordinal); // oldest retained
  TEST_ASSERT_EQUAL_INT64(5, log.at(2).ordinal); // newest
}

// ---- the eunomia-sidecar/v1 assembly validates against the generated parser ----
void test_sidecar_assembly_validates() {
  Assignment a;
  a.kit_id = "kit_07";
  a.operator_id = "op7";
  a.station_id = "5";
  a.task_id = "t";
  a.task_name = "n";
  a.prompt = "do x";
  a.rotation_id = "r";
  a.session_id = "s";
  a.task_source = "sd_assignment";
  a.site_id = "site1";
  a.fob_id = "fobA";
  a.fob_build = "3.8.3";
  a.modality = "umi";
  TakeContext t;
  t.episode_id = "eid";
  t.bimanual_episode_id = "bid";
  t.episode_ordinal = 42;
  t.display_id = "20231114_op7_5_000042";
  t.started_unix = 1700000000.25;
  t.stopped_unix = 1700000099.5;
  t.start_skew_ms = 12;
  t.stop_reason = "operator";
  CameraInfo c;
  c.camera_id = "camA";
  c.side = "left";
  c.kit_version = "0.10.0";
  c.global_episode_seq = 100;
  c.seq = 7;
  c.back = "VID_20231114_000_001.insv";
  c.record_settings = "{}";

  const eunomia::Sidecar s = assemble_sidecar(a, t, c);
  TEST_ASSERT_EQUAL_STRING("eunomia-sidecar/v1", s.schema.c_str());

  eunomia::Sidecar out;
  TEST_ASSERT_TRUE(eunomia::parse_sidecar(eunomia::serialize_sidecar(s), out));
  TEST_ASSERT_EQUAL_STRING("kit_07", out.kit_id.c_str());
  TEST_ASSERT_EQUAL_STRING("left", out.side.c_str());
  TEST_ASSERT_EQUAL_STRING("eid", out.episode_id.c_str());
  TEST_ASSERT_EQUAL_INT64(100, out.global_episode_seq);
  TEST_ASSERT_EQUAL_INT64(42, out.episode_ordinal);
  TEST_ASSERT_EQUAL_STRING("VID_20231114_000_001.insv", out.back.c_str());

  // a record missing a HARD leaf (no schema key) is rejected (the field-bag presence layer)
  eunomia::Sidecar bad;
  TEST_ASSERT_FALSE(eunomia::parse_sidecar("{\"seq\":1}", bad));
}

// ---- the assembly's target agrees with the golden conformance corpus (off-target) ----
void test_golden_sidecar_fixtures_parse() {
  namespace fs = std::filesystem;
  const fs::path root = fs::path(EUNOMIA_FIXTURES_DIR) / "sidecar";
  int n = 0;
  for (const char *sub : {"valid", "warn"}) {
    const fs::path dir = root / sub;
    if (!fs::exists(dir)) {
      continue;
    }
    for (const auto &entry : fs::directory_iterator(dir)) {
      if (entry.path().extension() != ".json") {
        continue;
      }
      std::ifstream f(entry.path());
      std::stringstream ss;
      ss << f.rdbuf();
      eunomia::Sidecar v;
      TEST_ASSERT_TRUE_MESSAGE(eunomia::parse_sidecar(ss.str(), v),
                               entry.path().filename().string().c_str());
      ++n;
    }
  }
  TEST_ASSERT_GREATER_THAN_MESSAGE(0, n, "no sidecar valid/warn fixtures found");
}

// ---- detect_drop is L2-only (the presence source), never an OSC poll ----
void test_detect_drop_l2_only() {
  FakeClock clk;
  CounterRng rng;
  FakeStore store;
  FakePresence pres;
  FakeDevice left;
  FakeDevice right;
  Coordinator co({&clk, &rng, &store, &pres, nullptr}, {{"left", &left}, {"right", &right}}, 2);
  pres.list = {"left"}; // right dropped at L2
  const auto dropped = co.detect_drop();
  TEST_ASSERT_EQUAL(1, static_cast<int>(dropped.size()));
  TEST_ASSERT_EQUAL_STRING("right", dropped[0].c_str());
  pres.list = {"left", "right"};
  TEST_ASSERT_EQUAL(0, static_cast<int>(co.detect_drop().size()));
}

// ---- STOP finalize sets recording_suspect when a clip can't be recovered; flush drains telemetry
// --
void test_stop_finalize_recording_suspect_and_flush() {
  FakeClock clk;
  CounterRng rng;
  FakeStore store;
  FakePresence pres;
  FakeSink sink;
  FakeDevice left;
  FakeDevice right;
  Coordinator co({&clk, &rng, &store, &pres, &sink}, {{"left", &left}, {"right", &right}}, 2);
  Assignment a;
  a.kit_id = "kit_07";
  a.fob_id = "fobA";
  co.set_assignment(a);
  const std::vector<std::string> cams{"left", "right"};
  pres.list = {"left", "right"};

  TEST_ASSERT_TRUE(co.trigger(cams));
  TEST_ASSERT_TRUE(co.stop("operator")); // fires both stops, finalizes
  TEST_ASSERT_EQUAL(1, left.stops);
  TEST_ASSERT_EQUAL(1, right.stops);
  TEST_ASSERT_EQUAL(static_cast<int>(State::Idle), static_cast<int>(co.state()));
  TEST_ASSERT_EQUAL_INT64(0, co.take().recording_suspect); // both clips recovered

  left.clip = ""; // a camera can't report a clip → the no-SD trap
  pres.list = {"left", "right"};
  TEST_ASSERT_TRUE(co.trigger(cams));
  TEST_ASSERT_TRUE(co.stop("operator"));
  TEST_ASSERT_EQUAL_INT64(1, co.take().recording_suspect);

  TEST_ASSERT_FALSE(co.stop("operator")); // STOP from idle refused

  TEST_ASSERT_TRUE(co.pending_telemetry() > 0);
  co.flush_telemetry();
  TEST_ASSERT_EQUAL(0, static_cast<int>(co.pending_telemetry()));
  TEST_ASSERT_TRUE(!sink.sent.empty());
}

// ---- the two env projections (the second projection of the single source) ----
void test_env_projections() {
  Assignment a;
  a.operator_id = "op7";
  a.station_id = "5";
  a.task_id = "t1";
  a.prompt = "do \"x\""; // a quote that must be stripped (clean_env_val)
  a.session_id = "s";
  a.fob_id = "fobA";
  a.fob_build = "3.8.3";
  a.assignment_source = "sd";
  TakeContext t;
  t.episode_id = "eid";
  t.bimanual_episode_id = "bid";
  t.stop_reason = "operator";
  t.started_unix = 1700000000.25;
  t.stopped_unix = 1700000099.5;
  t.start_skew_ms = 12;
  t.archive = 1;

  const std::string assign = project_assignment_env(a, t);
  TEST_ASSERT_TRUE(assign.find("OPERATOR_ID=\"op7\"") != std::string::npos);
  TEST_ASSERT_TRUE(assign.find("EPISODE_ID=\"eid\"") != std::string::npos);
  TEST_ASSERT_TRUE(assign.find("BIMANUAL_EPISODE_ID=\"bid\"") != std::string::npos);
  TEST_ASSERT_TRUE(assign.find("PROMPT=\"do x\"") != std::string::npos); // quote stripped

  const std::string stop = project_stop_env(t);
  TEST_ASSERT_TRUE(stop.find("EP_BIMANUAL_EPISODE_ID=\"bid\"") != std::string::npos);
  TEST_ASSERT_TRUE(stop.find("STOP_REASON=\"operator\"") != std::string::npos);
  TEST_ASSERT_TRUE(stop.find("ARCHIVE=\"1\"") != std::string::npos);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_state_machine_spam_safety);
  RUN_TEST(test_phantom_gate_function);
  RUN_TEST(test_coordinator_phantom_press_paths);
  RUN_TEST(test_button_feedback);
  RUN_TEST(test_episode_uuid_and_display);
  RUN_TEST(test_durable_ordinal_persist_before_advance);
  RUN_TEST(test_ordinal_log_ring_bounds);
  RUN_TEST(test_sidecar_assembly_validates);
  RUN_TEST(test_golden_sidecar_fixtures_parse);
  RUN_TEST(test_detect_drop_l2_only);
  RUN_TEST(test_stop_finalize_recording_suspect_and_flush);
  RUN_TEST(test_env_projections);
  return UNITY_END();
}
