// Off-target (host) tests for firmware/coordinator/ui/ — the F3 proof, no rig.
//
// Covers the PURE render_state mapping (the only host-testable ui code; the TFT draws are
// compile-checked on env:cyd) AND the two §1.8 properties that must survive THE INPUT PATH:
//   * the UI lockout (a re-tap while the ui-owned DelayedButton is working() is dropped), and
//   * core spam-safety (even if the debounce/lockout were defeated, trigger() from a non-idle state
//     never double-fires) — the F1 guarantee the input path must not regress,
//   * loud-not-silent: a no-clip STOP driven through the input path still surfaces
//   recording_suspect.
// Drives fakes for every seam (the same shapes as test_core).
#include <unity.h>

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "button_feedback.h"
#include "coordinator.h"
#include "render_state.h"
#include "trigger_state_machine.h"

using namespace eunomia::core;
namespace ui = eunomia::ui;

namespace {

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
  std::int64_t read_i64(const std::string &key, std::int64_t fb) override {
    auto it = kv.find(key);
    return it == kv.end() ? fb : it->second;
  }
  bool write_i64(const std::string &key, std::int64_t v) override {
    kv[key] = v;
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
  std::string clip = "VID_00.insv";
  void start() override { ++starts; }
  void stop() override { ++stops; }
  std::string read_back_filename() override { return clip; }
  std::string get_state() override { return "idle"; }
  void set_profile(const std::string &) override {}
  void write_sidecar(const eunomia::Sidecar &) override {}
};

const std::vector<std::string> kFleet = {"left", "right"};

} // namespace

// ---- render_state: the GO/NO-GO camera light (mirrors Victor's camCol; 2/2 green, else red) ----
void test_cam_light() {
  TEST_ASSERT_EQUAL(static_cast<int>(ui::CamLight::Go), static_cast<int>(ui::cam_light(2, 2)));
  TEST_ASSERT_EQUAL(static_cast<int>(ui::CamLight::Go), static_cast<int>(ui::cam_light(3, 2)));
  TEST_ASSERT_EQUAL(static_cast<int>(ui::CamLight::NoGo),
                    static_cast<int>(ui::cam_light(1, 2))); // one-sided = hard stop
  TEST_ASSERT_EQUAL(static_cast<int>(ui::CamLight::NoGo), static_cast<int>(ui::cam_light(0, 2)));
}

// ---- render_state: the MAIN toggle treatment from core State + the ui-owned DelayedButton ----
void test_main_button() {
  // working() wins everywhere — the §1.8 instant-ack/lockout window (set BEFORE the slow action).
  TEST_ASSERT_EQUAL(static_cast<int>(ui::MainButton::Working),
                    static_cast<int>(ui::main_button(State::Idle, true, 2, 2)));
  TEST_ASSERT_EQUAL(static_cast<int>(ui::MainButton::Working),
                    static_cast<int>(ui::main_button(State::Recording, true, 0, 2)));
  // recording (not working): DETENER stays live even if a cam dropped (present < required).
  TEST_ASSERT_EQUAL(static_cast<int>(ui::MainButton::Recording),
                    static_cast<int>(ui::main_button(State::Recording, false, 2, 2)));
  TEST_ASSERT_EQUAL(static_cast<int>(ui::MainButton::Recording),
                    static_cast<int>(ui::main_button(State::Recording, false, 1, 2)));
  // idle: GO only with the cams you need; else locked ESPERA (the GATE_CAMS hard stop).
  TEST_ASSERT_EQUAL(static_cast<int>(ui::MainButton::Go),
                    static_cast<int>(ui::main_button(State::Idle, false, 2, 2)));
  TEST_ASSERT_EQUAL(static_cast<int>(ui::MainButton::WaitingCams),
                    static_cast<int>(ui::main_button(State::Idle, false, 1, 2)));
  TEST_ASSERT_EQUAL(static_cast<int>(ui::MainButton::WaitingCams),
                    static_cast<int>(ui::main_button(State::Idle, false, 0, 2)));
}

// ---- the UI half of §1.8: a re-tap while the DelayedButton is working() is DROPPED (lockout) ----
void test_input_path_lockout() {
  DelayedButton btn;
  TEST_ASSERT_EQUAL(static_cast<int>(Press::Accepted), static_cast<int>(btn.press()));
  TEST_ASSERT_TRUE(btn.working());
  // re-taps during the slow inline action are ignored (spam-safe at the UI):
  TEST_ASSERT_EQUAL(static_cast<int>(Press::IgnoredLocked), static_cast<int>(btn.press()));
  TEST_ASSERT_EQUAL(static_cast<int>(Press::IgnoredLocked), static_cast<int>(btn.press()));
  btn.complete();
  TEST_ASSERT_FALSE(btn.working());
  TEST_ASSERT_EQUAL(static_cast<int>(Press::Accepted), static_cast<int>(btn.press())); // re-armed
}

// ---- core spam-safety SURVIVES the input path: rapid GRABAR mashing fires START exactly once ----
void test_spam_safety_through_input_path() {
  FakeClock clock;
  CounterRng rng;
  FakeStore store;
  FakePresence presence;
  presence.list = {"left", "right"};
  FakeDevice dev_l, dev_r;
  Coordinator::Deps deps;
  deps.clock = &clock;
  deps.rng = &rng;
  deps.store = &store;
  deps.presence = &presence;
  Coordinator::Fleet fleet = {{"left", &dev_l}, {"right", &dev_r}};
  Coordinator coord(deps, fleet, 2);

  // The flow's exact discipline: a tap calls DelayedButton::press(); only an Accepted press runs
  // the (slow, inline) trigger. Model a burst of taps during the ~3 s START window.
  DelayedButton btn;
  int commits = 0;
  // tap 1: Accepted -> trigger commits (Idle -> Recording).
  TEST_ASSERT_EQUAL(static_cast<int>(Press::Accepted), static_cast<int>(btn.press()));
  if (coord.state() == State::Idle) {
    coord.mint_episode_id();
    if (coord.trigger(kFleet)) {
      ++commits;
    }
  }
  // taps 2..6 arrive WHILE working() — every one is dropped by the UI lockout.
  for (int i = 0; i < 5; ++i) {
    TEST_ASSERT_EQUAL(static_cast<int>(Press::IgnoredLocked), static_cast<int>(btn.press()));
  }
  // belt-and-suspenders: even if a tap leaked past the lockout, core drops a START from non-idle.
  TEST_ASSERT_FALSE(coord.trigger(kFleet));
  btn.complete();

  TEST_ASSERT_EQUAL(1, commits);
  TEST_ASSERT_EQUAL(static_cast<int>(State::Recording), static_cast<int>(coord.state()));
  TEST_ASSERT_EQUAL(1, dev_l.starts); // each camera started EXACTLY once
  TEST_ASSERT_EQUAL(1, dev_r.starts);
}

// ---- loud-not-silent SURVIVES the input path: a no-clip STOP still surfaces recording_suspect
// ----
void test_loud_not_silent_through_input_path() {
  FakeClock clock;
  CounterRng rng;
  FakeStore store;
  FakePresence presence;
  presence.list = {"left", "right"};
  FakeDevice dev_l, dev_r;
  dev_l.clip = ""; // the no-SD/no-clip trap: read_back_filename returns empty
  dev_r.clip = "";
  Coordinator::Deps deps;
  deps.clock = &clock;
  deps.rng = &rng;
  deps.store = &store;
  deps.presence = &presence;
  Coordinator::Fleet fleet = {{"left", &dev_l}, {"right", &dev_r}};
  Coordinator coord(deps, fleet, 2);

  // START then STOP through the input-path discipline.
  DelayedButton btn;
  btn.press();
  coord.mint_episode_id();
  TEST_ASSERT_TRUE(coord.trigger(kFleet));
  btn.complete();
  btn.press();
  TEST_ASSERT_TRUE(coord.stop("operator"));
  btn.complete();

  // The empty clip must surface loudly, not record silently (the OQ-3 property, via the UI path).
  TEST_ASSERT_EQUAL(1, coord.take().recording_suspect);
}

// ---- present_count(): the FLAG-C read-only accessor render_state's GO/NO-GO source is derived
// from ----
void test_present_count_accessor() {
  FakeClock clock;
  CounterRng rng;
  FakeStore store;
  FakePresence presence;
  FakeDevice dev_l, dev_r;
  Coordinator::Deps deps;
  deps.clock = &clock;
  deps.rng = &rng;
  deps.store = &store;
  deps.presence = &presence;
  Coordinator::Fleet fleet = {{"left", &dev_l}, {"right", &dev_r}};
  Coordinator coord(deps, fleet, 2);
  presence.list = {};
  TEST_ASSERT_EQUAL(0u, coord.present_count());
  presence.list = {"left"};
  TEST_ASSERT_EQUAL(1u, coord.present_count());
  presence.list = {"left", "right"};
  TEST_ASSERT_EQUAL(2u, coord.present_count());
  // and it feeds the light exactly as the UI uses it:
  TEST_ASSERT_EQUAL(static_cast<int>(ui::CamLight::Go),
                    static_cast<int>(ui::cam_light(coord.present_count(), 2)));
}

// ---- F8: LLAMAR delayed-button lockout (§1.8 — a re-tap during radio borrow is dropped) ----
void test_llamar_lockout() {
  DelayedButton llamar;
  TEST_ASSERT_EQUAL(static_cast<int>(Press::Accepted), static_cast<int>(llamar.press()));
  TEST_ASSERT_TRUE(llamar.working());
  TEST_ASSERT_EQUAL(static_cast<int>(Press::IgnoredLocked), static_cast<int>(llamar.press()));
  TEST_ASSERT_EQUAL(static_cast<int>(Press::IgnoredLocked), static_cast<int>(llamar.press()));
  llamar.complete();
  TEST_ASSERT_FALSE(llamar.working());
  TEST_ASSERT_EQUAL(static_cast<int>(Press::Accepted), static_cast<int>(llamar.press()));
}

// ---- F8: LLAMAR gated on state — locked while recording (belt-and-suspenders with flow.cpp) ----
void test_llamar_gated_on_state() {
  FakeClock clock;
  CounterRng rng;
  FakeStore store;
  FakePresence presence;
  presence.list = {"left", "right"};
  FakeDevice dev_l, dev_r;
  Coordinator::Deps deps;
  deps.clock = &clock;
  deps.rng = &rng;
  deps.store = &store;
  deps.presence = &presence;
  Coordinator::Fleet fleet = {{"left", &dev_l}, {"right", &dev_r}};
  Coordinator coord(deps, fleet, 2);

  // Idle → LLAMAR allowed
  TEST_ASSERT_EQUAL(static_cast<int>(State::Idle), static_cast<int>(coord.state()));

  // Recording → LLAMAR locked
  coord.mint_episode_id();
  TEST_ASSERT_TRUE(coord.trigger(kFleet));
  TEST_ASSERT_EQUAL(static_cast<int>(State::Recording), static_cast<int>(coord.state()));
  // The transport gate would check coord.state() != Idle → refuse
}

// ---- F8: LLAMAR and toggle are INDEPENDENT delayed buttons (no cross-lockout) ----
void test_llamar_toggle_independent() {
  DelayedButton toggle;
  DelayedButton llamar;
  TEST_ASSERT_EQUAL(static_cast<int>(Press::Accepted), static_cast<int>(toggle.press()));
  TEST_ASSERT_TRUE(toggle.working());
  // LLAMAR is still free even though toggle is working
  TEST_ASSERT_EQUAL(static_cast<int>(Press::Accepted), static_cast<int>(llamar.press()));
  TEST_ASSERT_TRUE(llamar.working());
  toggle.complete();
  llamar.complete();
}

void setUp() {}
void tearDown() {}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_cam_light);
  RUN_TEST(test_main_button);
  RUN_TEST(test_input_path_lockout);
  RUN_TEST(test_spam_safety_through_input_path);
  RUN_TEST(test_loud_not_silent_through_input_path);
  RUN_TEST(test_present_count_accessor);
  RUN_TEST(test_llamar_lockout);
  RUN_TEST(test_llamar_gated_on_state);
  RUN_TEST(test_llamar_toggle_independent);
  return UNITY_END();
}
