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
#include "heap_health.h"
#include "operational_record.h"
#include "ordinal_log.h"
#include "sidecar_assembly.h"
#include "task_config.h"
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

// Durable ordinal-log fake: records the appended lines + total bytes (the append-after-fire proof).
class FakeEpisodeLog : public EpisodeLogStore {
public:
  std::vector<std::string> lines;
  void append(const std::string &line) override {
    lines.push_back(line);
    bytes_ += line.size() + 1;
  }
  std::size_t bytes() const override { return bytes_; }

private:
  std::size_t bytes_ = 0;
};

// String-backed LogSegment — the off-target storage the ping-pong rotation runs on (the SAME core
// logic the LittleFS impl runs, over RAM strings instead of files), so rotation is rig-free
// testable.
class StringSegment : public LogSegment {
public:
  std::string buf;
  void append(const std::string &line) override {
    buf += line;
    buf.push_back('\n');
  }
  void clear() override { buf.clear(); }
  std::size_t size() const override { return buf.size(); }
};

// A device that ALSO confirms its fire via the F6 StartConfirmable side-channel. `ack` controls the
// connect-ack; counts confirmed fires + the void start() (to prove core uses the confirmer path,
// not the fallback) + stops (for the rollback assertions). Registered via
// Coordinator::set_confirmer.
class FakeConfirmableDevice : public eunomia::CaptureDevicePort, public StartConfirmable {
public:
  bool ack = true;
  int confirmed_fires = 0;
  int void_starts = 0;
  int stops = 0;
  void start() override { ++void_starts; }
  bool start_confirmed() override {
    ++confirmed_fires;
    return ack;
  }
  void stop() override { ++stops; }
  std::string read_back_filename() override { return "VID_00.insv"; }
  std::string get_state() override { return "idle"; }
  void set_profile(const std::string &) override {}
  void write_sidecar(const eunomia::Sidecar &) override {}
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

// ---- F6: fire-confirm rollback — cams PRESENT but the fire under-confirms → no commit, stop the
// fired cams, StartFailed; the ordinal is never advanced so it is REUSED on the next good press
// ----
void test_fire_confirm_rollback_partial_start() {
  FakeClock clk;
  CounterRng rng;
  FakeStore store;
  FakePresence pres;
  FakeConfirmableDevice left;
  FakeConfirmableDevice right;
  FakeEpisodeLog log;
  Coordinator co({&clk, &rng, &store, &pres, nullptr, &log}, {{"left", &left}, {"right", &right}},
                 2);
  co.set_confirmer("left", &left);
  co.set_confirmer("right", &right);
  const std::vector<std::string> cams{"left", "right"};
  pres.list = {"left", "right"}; // BOTH present at L2 (the presence gate passes)

  left.ack = true;
  right.ack = false; // right's startCapture never connects → the fire under-confirms
  TEST_ASSERT_FALSE(co.trigger(cams));
  TEST_ASSERT_EQUAL(static_cast<int>(GateOutcome::StartFailed),
                    static_cast<int>(co.last_outcome()));
  TEST_ASSERT_EQUAL(static_cast<int>(State::Idle), static_cast<int>(co.state())); // rolled back
  TEST_ASSERT_EQUAL_INT64(0, co.take().episode_ordinal);                          // NO commit
  TEST_ASSERT_EQUAL(0, store.writes);         // advance() never even attempted (no burn)
  TEST_ASSERT_EQUAL(1, left.confirmed_fires); // both fires were attempted...
  TEST_ASSERT_EQUAL(1, right.confirmed_fires);
  TEST_ASSERT_EQUAL(0, left.void_starts); // ...via the confirmer, never the void fallback
  TEST_ASSERT_EQUAL(1, left.stops);       // and the started cam was stopped (no clip rolling)
  TEST_ASSERT_EQUAL(1, right.stops);
  TEST_ASSERT_EQUAL(0u, log.lines.size()); // no orphaned DURABLE log line (F5 + F6 rollback)

  // The next press with both cams confirming REUSES ordinal 1 (no skip/burn — the DurableOrdinal
  // invariant survives the rollback).
  left.ack = true;
  right.ack = true;
  TEST_ASSERT_TRUE(co.trigger(cams));
  TEST_ASSERT_EQUAL(static_cast<int>(GateOutcome::Committed), static_cast<int>(co.last_outcome()));
  TEST_ASSERT_EQUAL_INT64(1, co.take().episode_ordinal);
  TEST_ASSERT_EQUAL(1, store.writes);
  // F9: ordinal entry + episode_started = 2 durable lines per committed START
  TEST_ASSERT_EQUAL(2u, log.lines.size());
}

// ---- F6: fire CONFIRMS but the durable commit fails → roll back the fire too, never burn an
// ordinal (the fire-then-commit "commit failed after a good fire" branch) ----
void test_fire_confirmed_but_commit_fails_rolls_back() {
  FakeClock clk;
  CounterRng rng;
  FakeStore store;
  FakePresence pres;
  FakeConfirmableDevice left;
  FakeConfirmableDevice right;
  FakeEpisodeLog log;
  Coordinator co({&clk, &rng, &store, &pres, nullptr, &log}, {{"left", &left}, {"right", &right}},
                 2);
  co.set_confirmer("left", &left);
  co.set_confirmer("right", &right);
  const std::vector<std::string> cams{"left", "right"};
  pres.list = {"left", "right"};
  store.fail_next = true; // the durable ordinal write fails AFTER both fires confirm

  TEST_ASSERT_FALSE(co.trigger(cams));
  TEST_ASSERT_EQUAL(static_cast<int>(GateOutcome::StartFailed),
                    static_cast<int>(co.last_outcome()));
  TEST_ASSERT_EQUAL_INT64(0, co.take().episode_ordinal); // not committed
  TEST_ASSERT_EQUAL(1, left.confirmed_fires);            // the fire DID happen (both acked)
  TEST_ASSERT_EQUAL(1, right.confirmed_fires);
  TEST_ASSERT_EQUAL(1, left.stops); // then rolled back
  TEST_ASSERT_EQUAL(1, right.stops);
  TEST_ASSERT_EQUAL(0u, log.lines.size()); // no orphaned DURABLE log line on commit-failure
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

// ---- the compact JSONL line carries the order-join keys (de-dup on kit/session/ordinal) ----
void test_serialize_ordinal_entry() {
  OrdinalLogEntry e;
  e.ordinal = 42;
  e.wallclock_unix = 1700000000;
  e.kit_id = "kit_07";
  e.fob_id = "fobA";
  e.fob_session_id = "1a2b3c4d";
  e.episode_id = "eid-123";
  const std::string line = serialize_ordinal_entry(e);
  TEST_ASSERT_TRUE(line.find("\"T\":\"O\"") != std::string::npos); // F9: type discriminator
  TEST_ASSERT_TRUE(line.find("\"o\":42") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"t\":1700000000") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"k\":\"kit_07\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"s\":\"1a2b3c4d\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"e\":\"eid-123\"") != std::string::npos);
  TEST_ASSERT_EQUAL('}', line.back());
}

// ---- the durable log is BOUNDED + retains the recent window, and SURVIVES a battery swap ----
void test_segmented_episode_log_bounds() {
  StringSegment a;
  StringSegment b;
  SegmentedEpisodeLog log(a, b, 50); // 50-byte segments → max 100 bytes retained (ping-pong)
  log.begin();
  for (int i = 0; i < 100; ++i) {
    log.append("L" + std::to_string(i)); // far past one segment
  }
  TEST_ASSERT_TRUE(log.bytes() <= 100); // bounded: never exceeds 2·seg_bytes
  const std::string combined = a.buf + b.buf;
  TEST_ASSERT_TRUE(combined.find("L99\n") != std::string::npos); // newest retained
  TEST_ASSERT_TRUE(combined.find("L0\n") == std::string::npos);  // oldest dropped

  // A battery swap: a fresh log over the SAME (durable) segments recovers the active = smaller one,
  // keeps the retained window, and resumes appending — it is NOT wiped.
  const std::size_t survived = log.bytes();
  SegmentedEpisodeLog reopened(a, b, 50);
  reopened.begin();
  TEST_ASSERT_EQUAL(static_cast<int>(survived), static_cast<int>(reopened.bytes()));
  reopened.append("L100");
  TEST_ASSERT_TRUE((a.buf + b.buf).find("L100\n") != std::string::npos);
  TEST_ASSERT_TRUE(reopened.bytes() <= 100);
}

// ---- the low-heap watchdog floor: refuse a START below the largest-free-block floor ----
void test_heap_ok_floor() {
  TEST_ASSERT_TRUE(heap_ok(kHeapFloorBytes));      // at the floor → ok
  TEST_ASSERT_TRUE(heap_ok(kHeapFloorBytes + 1));  // above → ok
  TEST_ASSERT_FALSE(heap_ok(kHeapFloorBytes - 1)); // below → refuse
  TEST_ASSERT_FALSE(heap_ok(0));
}

// ---- the durable §1.7 backup is written AFTER the fleet fires, only for a COMMITTED START ----
void test_durable_log_append_after_fire() {
  FakeClock clk;
  CounterRng rng;
  FakeStore store;
  FakePresence pres;
  FakeEpisodeLog log;
  FakeDevice left;
  FakeDevice right;
  Coordinator co({&clk, &rng, &store, &pres, nullptr, &log}, {{"left", &left}, {"right", &right}},
                 2);
  Assignment a;
  a.kit_id = "kit_07";
  a.fob_id = "fobA";
  co.set_assignment(a);
  co.set_fob_session_id("sess1");
  const std::vector<std::string> cams{"left", "right"};

  pres.list = {}; // phantom → no commit → no durable line
  TEST_ASSERT_FALSE(co.trigger(cams));
  TEST_ASSERT_EQUAL(0, static_cast<int>(log.lines.size()));

  pres.list = {"left"}; // one-sided → refused → no durable line (no ordinal for a non-take)
  TEST_ASSERT_FALSE(co.trigger(cams));
  TEST_ASSERT_EQUAL(0, static_cast<int>(log.lines.size()));

  pres.list = {"left", "right"}; // commit → durable lines AFTER both fired
  TEST_ASSERT_TRUE(co.trigger(cams));
  TEST_ASSERT_EQUAL(1, left.starts);
  TEST_ASSERT_EQUAL(1, right.starts);
  // F9: ordinal entry + episode_started = 2 durable lines per committed START
  TEST_ASSERT_EQUAL(2, static_cast<int>(log.lines.size()));
  TEST_ASSERT_TRUE(log.lines[0].find("\"o\":1") != std::string::npos); // ordinal 1
  TEST_ASSERT_TRUE(log.lines[0].find("\"k\":\"kit_07\"") != std::string::npos);
  TEST_ASSERT_TRUE(log.lines[1].find("\"T\":\"E\"") != std::string::npos); // episode_started
  TEST_ASSERT_TRUE(log.bytes() > 0);
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

// ---- STOP finalize sets recording_suspect when a clip can't be recovered (the no-SD trap) ----
void test_stop_finalize_recording_suspect() {
  FakeClock clk;
  CounterRng rng;
  FakeStore store;
  FakePresence pres;
  FakeDevice left;
  FakeDevice right;
  Coordinator co({&clk, &rng, &store, &pres, nullptr, nullptr},
                 {{"left", &left}, {"right", &right}}, 2);
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

  co.flush_telemetry(); // no-op now (the dead god's-view queue was deleted) — must stay callable
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

// ---- F9: task-config parsing ----
void test_parse_task_config() {
  const std::string json = R"({
    "site_id": "sf",
    "assignments": [
      {"station_id":"3","task_id":"fold","task_name":"Fold Towel",
       "prompt":"Fold the towel","rotation_id":"A","task_version":2},
      {"station_id":"5","task_id":"pour","task_name":"Pour Water",
       "prompt":"Pour water","rotation_id":"B","task_version":1}
    ],
    "roster": ["101","102"],
    "fetched_at": "2026-06-27T08:15:00Z"
  })";
  const auto cfg = parse_task_config(json);
  TEST_ASSERT_TRUE(cfg.valid);
  TEST_ASSERT_EQUAL_STRING("sf", cfg.site_id.c_str());
  TEST_ASSERT_EQUAL(2, static_cast<int>(cfg.assignments.size()));
  TEST_ASSERT_EQUAL_STRING("3", cfg.assignments[0].station_id.c_str());
  TEST_ASSERT_EQUAL_STRING("fold", cfg.assignments[0].task_id.c_str());
  TEST_ASSERT_EQUAL_STRING("Fold Towel", cfg.assignments[0].task_name.c_str());
  TEST_ASSERT_EQUAL_STRING("A", cfg.assignments[0].rotation_id.c_str());
  TEST_ASSERT_EQUAL(2, cfg.assignments[0].task_version);
  TEST_ASSERT_EQUAL_STRING("5", cfg.assignments[1].station_id.c_str());
  TEST_ASSERT_EQUAL(2, static_cast<int>(cfg.roster.size()));
  TEST_ASSERT_EQUAL_STRING("101", cfg.roster[0].c_str());
  TEST_ASSERT_EQUAL_STRING("2026-06-27T08:15:00Z", cfg.fetched_at.c_str());
}

void test_parse_task_config_malformed() {
  const auto cfg = parse_task_config("{not valid json!!!");
  TEST_ASSERT_FALSE(cfg.valid);
}

void test_parse_task_config_empty() {
  const auto cfg = parse_task_config("");
  TEST_ASSERT_FALSE(cfg.valid);
}

void test_parse_task_config_missing_assignments() {
  const auto cfg = parse_task_config(R"({"site_id":"sf"})");
  TEST_ASSERT_FALSE(cfg.valid);
}

void test_parse_task_config_partial_assignment() {
  const std::string json = R"({
    "assignments": [
      {"station_id":"3","task_id":"fold","task_name":"Fold"},
      {"station_id":"","task_id":"bad"},
      {"task_id":"no_station"},
      {"station_id":"7","task_id":"pour","task_name":"Pour"}
    ]
  })";
  const auto cfg = parse_task_config(json);
  TEST_ASSERT_TRUE(cfg.valid);
  TEST_ASSERT_EQUAL(2, static_cast<int>(cfg.assignments.size()));
  TEST_ASSERT_EQUAL_STRING("3", cfg.assignments[0].station_id.c_str());
  TEST_ASSERT_EQUAL_STRING("7", cfg.assignments[1].station_id.c_str());
}

// ---- F9: station→task resolution ----
void test_resolve_assignment_found() {
  const std::string json = R"({
    "assignments": [
      {"station_id":"3","task_id":"fold","task_name":"Fold Towel","prompt":"Fold it",
       "rotation_id":"A","task_version":2},
      {"station_id":"5","task_id":"pour","task_name":"Pour Water","prompt":"Pour it"}
    ]
  })";
  const auto cfg = parse_task_config(json);
  const auto *sa = resolve_assignment(cfg, "5");
  TEST_ASSERT_NOT_NULL(sa);
  TEST_ASSERT_EQUAL_STRING("pour", sa->task_id.c_str());
  TEST_ASSERT_EQUAL_STRING("Pour Water", sa->task_name.c_str());
  TEST_ASSERT_EQUAL_STRING("Pour it", sa->prompt.c_str());
}

void test_resolve_assignment_not_found() {
  const std::string json = R"({"assignments":[{"station_id":"3","task_id":"fold"}]})";
  const auto cfg = parse_task_config(json);
  TEST_ASSERT_NULL(resolve_assignment(cfg, "99"));
}

void test_resolve_assignment_invalid_config() {
  TaskConfig cfg; // valid=false
  TEST_ASSERT_NULL(resolve_assignment(cfg, "3"));
}

// ---- F9: operational record serialization ----
void test_serialize_episode_started() {
  Assignment a;
  a.kit_id = "kit_07";
  a.operator_id = "101";
  a.station_id = "3";
  a.task_id = "fold";
  a.rotation_id = "A";
  a.task_source = "boot_config";
  a.session_id = "sess-1";
  TakeContext t;
  t.episode_id = "eid-abc";
  t.episode_ordinal = 42;
  t.started_unix = 1719475200;
  const std::string line = serialize_episode_started(a, t);
  TEST_ASSERT_TRUE(line.find("\"T\":\"E\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"st\":\"start\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"o\":42") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"k\":\"kit_07\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"e\":\"eid-abc\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"op\":\"101\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"stn\":\"3\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"tid\":\"fold\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"rv\":\"A\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"ts\":\"boot_config\"") != std::string::npos);
  TEST_ASSERT_EQUAL('}', line.back());
}

void test_serialize_episode_stopped() {
  TakeContext t;
  t.episode_id = "eid-abc";
  t.episode_ordinal = 42;
  t.stopped_unix = 1719475320;
  t.stop_reason = "operator";
  t.archive = 0;
  t.recording_suspect = 1;
  const std::string line = serialize_episode_stopped(t, "kit_07");
  TEST_ASSERT_TRUE(line.find("\"T\":\"E\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"st\":\"stop\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"r\":\"operator\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"a\":0") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"rs\":1") != std::string::npos);
  TEST_ASSERT_EQUAL('}', line.back());
}

void test_serialize_episode_discarded() {
  TakeContext t;
  t.episode_id = "eid-abc";
  t.episode_ordinal = 42;
  t.stopped_unix = 1719475325;
  const std::string line = serialize_episode_discarded(t, "kit_07");
  TEST_ASSERT_TRUE(line.find("\"T\":\"E\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"st\":\"discard\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"e\":\"eid-abc\"") != std::string::npos);
  TEST_ASSERT_EQUAL('}', line.back());
}

void test_serialize_session_signin() {
  Assignment a;
  a.kit_id = "kit_07";
  a.fob_id = "fobA";
  a.fob_session_id = "1a2b3c4d";
  a.operator_id = "101";
  a.site_id = "sf";
  const std::string line = serialize_session_signin(a, "sess-abc", 1719474000);
  TEST_ASSERT_TRUE(line.find("\"T\":\"S\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"st\":\"signin\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"sid\":\"sess-abc\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"op\":\"101\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"site\":\"sf\"") != std::string::npos);
  TEST_ASSERT_EQUAL('}', line.back());
}

void test_serialize_station_assignment() {
  Assignment a;
  a.kit_id = "kit_07";
  a.station_id = "3";
  a.task_id = "fold";
  a.task_name = "Fold Towel";
  a.rotation_id = "A";
  a.task_source = "boot_config";
  const std::string line = serialize_station_assignment(a, 1719474060, "sess-abc");
  TEST_ASSERT_TRUE(line.find("\"T\":\"A\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"stn\":\"3\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"tid\":\"fold\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"tn\":\"Fold Towel\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"ts\":\"boot_config\"") != std::string::npos);
  TEST_ASSERT_EQUAL('}', line.back());
}

void test_serialize_call_lead() {
  Assignment a;
  a.kit_id = "kit_07";
  a.operator_id = "101";
  a.station_id = "3";
  const std::string line = serialize_call_lead(a, 1719475500, "sess-abc");
  TEST_ASSERT_TRUE(line.find("\"T\":\"S\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"st\":\"call\"") != std::string::npos);
  TEST_ASSERT_TRUE(line.find("\"sid\":\"sess-abc\"") != std::string::npos);
  TEST_ASSERT_EQUAL('}', line.back());
}

// F9: the durable log now emits episode_started + episode_stopped operational records alongside the
// ordinal entry. Verify the full lifecycle produces the expected number and types of log lines.
void test_operational_records_in_durable_log() {
  FakeClock clk;
  CounterRng rng;
  FakeStore store;
  FakePresence pres;
  FakeEpisodeLog log;
  FakeDevice left;
  FakeDevice right;
  Coordinator co({&clk, &rng, &store, &pres, nullptr, &log}, {{"left", &left}, {"right", &right}},
                 2);
  Assignment a;
  a.kit_id = "kit_07";
  a.fob_id = "fobA";
  a.operator_id = "101";
  a.station_id = "3";
  a.task_id = "fold";
  a.task_source = "boot_config";
  a.session_id = "sess-1";
  co.set_assignment(a);
  co.set_fob_session_id("sess1");
  const std::vector<std::string> cams{"left", "right"};
  pres.list = {"left", "right"};

  // START → ordinal entry ("T":"O") + episode_started ("T":"E","st":"start")
  TEST_ASSERT_TRUE(co.trigger(cams));
  TEST_ASSERT_EQUAL(2, static_cast<int>(log.lines.size()));
  TEST_ASSERT_TRUE(log.lines[0].find("\"T\":\"O\"") != std::string::npos);
  TEST_ASSERT_TRUE(log.lines[1].find("\"T\":\"E\"") != std::string::npos);
  TEST_ASSERT_TRUE(log.lines[1].find("\"st\":\"start\"") != std::string::npos);
  TEST_ASSERT_TRUE(log.lines[1].find("\"tid\":\"fold\"") != std::string::npos);

  // STOP → episode_stopped ("T":"E","st":"stop")
  TEST_ASSERT_TRUE(co.stop("operator"));
  TEST_ASSERT_EQUAL(3, static_cast<int>(log.lines.size()));
  TEST_ASSERT_TRUE(log.lines[2].find("\"st\":\"stop\"") != std::string::npos);
  TEST_ASSERT_TRUE(log.lines[2].find("\"r\":\"operator\"") != std::string::npos);

  // DESCARTAR → episode_discarded ("T":"E","st":"discard")
  co.mark_archive();
  TEST_ASSERT_EQUAL(4, static_cast<int>(log.lines.size()));
  TEST_ASSERT_TRUE(log.lines[3].find("\"st\":\"discard\"") != std::string::npos);
}

// F9: verify a rolled-back START emits NO operational records (same as F5/F6 — no orphaned lines).
void test_operational_records_not_emitted_on_rollback() {
  FakeClock clk;
  CounterRng rng;
  FakeStore store;
  FakePresence pres;
  FakeEpisodeLog log;
  FakeConfirmableDevice left;
  FakeConfirmableDevice right;
  Coordinator co({&clk, &rng, &store, &pres, nullptr, &log}, {{"left", &left}, {"right", &right}},
                 2);
  co.set_confirmer("left", &left);
  co.set_confirmer("right", &right);
  const std::vector<std::string> cams{"left", "right"};
  pres.list = {"left", "right"};
  right.ack = false; // fire under-confirms → rollback
  TEST_ASSERT_FALSE(co.trigger(cams));
  TEST_ASSERT_EQUAL(0, static_cast<int>(log.lines.size())); // no lines at all
}

// F9: log budget — verify extended records fit in the 2×64 KB window for a full day.
void test_log_budget_extended_records() {
  StringSegment a;
  StringSegment b;
  const std::size_t seg = 64 * 1024;
  SegmentedEpisodeLog log(a, b, seg);
  log.begin();
  Assignment assign;
  assign.kit_id = "kit_07";
  assign.operator_id = "101";
  assign.station_id = "3";
  assign.task_id = "fold";
  assign.task_source = "boot_config";
  assign.session_id = "sess-1";
  TakeContext take;
  take.episode_id = "eid-00000000-0000-0000-0000-000000000000";
  take.episode_ordinal = 1;
  take.started_unix = 1719475200;
  take.stopped_unix = 1719475320;
  take.stop_reason = "operator";
  OrdinalLogEntry oe;
  oe.ordinal = 1;
  oe.wallclock_unix = 1719475200;
  oe.kit_id = "kit_07";
  oe.fob_id = "fobA";
  oe.fob_session_id = "1a2b3c4d";
  oe.episode_id = take.episode_id;
  // Simulate 256 takes (a full day)
  for (int i = 0; i < 256; ++i) {
    oe.ordinal = i + 1;
    take.episode_ordinal = i + 1;
    log.append(serialize_ordinal_entry(oe));
    log.append(serialize_episode_started(assign, take));
    log.append(serialize_episode_stopped(take, "kit_07"));
  }
  // Plus a few sign-in + assignment events
  for (int i = 0; i < 5; ++i) {
    log.append(serialize_session_signin(assign, "sess-1", 1719474000));
    log.append(serialize_station_assignment(assign, 1719474060, "sess-1"));
  }
  TEST_ASSERT_TRUE(log.bytes() <= 2 * seg);
  TEST_ASSERT_TRUE(log.bytes() > 0);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_state_machine_spam_safety);
  RUN_TEST(test_phantom_gate_function);
  RUN_TEST(test_coordinator_phantom_press_paths);
  RUN_TEST(test_fire_confirm_rollback_partial_start);
  RUN_TEST(test_fire_confirmed_but_commit_fails_rolls_back);
  RUN_TEST(test_button_feedback);
  RUN_TEST(test_episode_uuid_and_display);
  RUN_TEST(test_durable_ordinal_persist_before_advance);
  RUN_TEST(test_serialize_ordinal_entry);
  RUN_TEST(test_segmented_episode_log_bounds);
  RUN_TEST(test_heap_ok_floor);
  RUN_TEST(test_durable_log_append_after_fire);
  RUN_TEST(test_sidecar_assembly_validates);
  RUN_TEST(test_golden_sidecar_fixtures_parse);
  RUN_TEST(test_detect_drop_l2_only);
  RUN_TEST(test_stop_finalize_recording_suspect);
  RUN_TEST(test_env_projections);
  // F9: task-config parsing + resolution
  RUN_TEST(test_parse_task_config);
  RUN_TEST(test_parse_task_config_malformed);
  RUN_TEST(test_parse_task_config_empty);
  RUN_TEST(test_parse_task_config_missing_assignments);
  RUN_TEST(test_parse_task_config_partial_assignment);
  RUN_TEST(test_resolve_assignment_found);
  RUN_TEST(test_resolve_assignment_not_found);
  RUN_TEST(test_resolve_assignment_invalid_config);
  // F9: operational record serialization
  RUN_TEST(test_serialize_episode_started);
  RUN_TEST(test_serialize_episode_stopped);
  RUN_TEST(test_serialize_episode_discarded);
  RUN_TEST(test_serialize_session_signin);
  RUN_TEST(test_serialize_station_assignment);
  RUN_TEST(test_serialize_call_lead);
  // F9: operational records in coordinator lifecycle
  RUN_TEST(test_operational_records_in_durable_log);
  RUN_TEST(test_operational_records_not_emitted_on_rollback);
  RUN_TEST(test_log_budget_extended_records);
  return UNITY_END();
}
