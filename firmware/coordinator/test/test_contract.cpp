// Off-target (host) conformance test for the Run 0b contract C++ targets.
//
// Parses the SAME golden fixtures as the Python conformance test
// (contracts/conformance/fixtures/<entity>/{valid,warn}/) using the GENERATED C++ headers —
// proving the C++ target agrees with the JSON Schema + the stdlib overlay on the structural layer
// it owns. SCOPE (OQ-5): the C++ header is a flat field-BAG (presence + type of hard scalar/string
// leaves, looked up by key); it does NOT model nesting, enums, non-empty, the conditional, or the
// cross-field rules — those are the Python/JSON-Schema layers. So this test asserts: valid/ + warn/
// PARSE (all hard leaves present), and a missing-hard-field record is REJECTED.
#include <unity.h>

#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

#include "eunomia_sidecar.h"
#include "eunomia_telemetry_event.h"

namespace fs = std::filesystem;

static std::string read_file(const fs::path &p) {
  std::ifstream f(p);
  std::stringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

template <typename T, bool (*Parse)(const std::string &, T &)>
static int check_dir(const fs::path &dir, bool expect_parse) {
  int n = 0;
  for (const auto &entry : fs::directory_iterator(dir)) {
    if (entry.path().extension() != ".json")
      continue;
    T v;
    bool ok = Parse(read_file(entry.path()), v);
    TEST_ASSERT_EQUAL_MESSAGE(expect_parse, ok, entry.path().filename().string().c_str());
    n++;
  }
  return n;
}

static const fs::path ROOT = fs::path(EUNOMIA_FIXTURES_DIR);

void test_sidecar_valid_and_warn_parse() {
  int n = check_dir<eunomia::Sidecar, &eunomia::parse_sidecar>(ROOT / "sidecar" / "valid", true);
  n += check_dir<eunomia::Sidecar, &eunomia::parse_sidecar>(ROOT / "sidecar" / "warn", true);
  TEST_ASSERT_GREATER_THAN_MESSAGE(0, n, "no sidecar valid/warn fixtures found");
}

void test_telemetry_valid_and_warn_parse() {
  int n = check_dir<eunomia::TelemetryEvent, &eunomia::parse_telemetry_event>(
      ROOT / "telemetry_event" / "valid", true);
  n += check_dir<eunomia::TelemetryEvent, &eunomia::parse_telemetry_event>(
      ROOT / "telemetry_event" / "warn", true);
  TEST_ASSERT_GREATER_THAN_MESSAGE(0, n, "no telemetry valid/warn fixtures found");
}

void test_missing_hard_field_rejected() {
  eunomia::Sidecar s;
  TEST_ASSERT_FALSE(eunomia::parse_sidecar("{\"seq\":1}", s)); // no schema (hard string)
  eunomia::TelemetryEvent e;
  TEST_ASSERT_FALSE(eunomia::parse_telemetry_event("{\"kit_id\":\"k\"}", e)); // no schema/event
}

void test_roundtrip() {
  eunomia::Sidecar in;
  in.schema = "eunomia-sidecar/v1";
  in.seq = 7;
  in.global_episode_seq = 100;
  in.camera_id = "cam_A";
  in.kit_id = "kit_07";
  in.side = "left";
  in.operator_id = "op";
  in.station_id = "5";
  in.task_id = "t";
  in.task_name = "n";
  in.session_id = "s";
  in.episode_id = "eid";
  in.rotation_id = "r";
  in.prompt = "p";
  in.task_source = "none";
  in.back = "VID.insv";
  eunomia::Sidecar out;
  TEST_ASSERT_TRUE(eunomia::parse_sidecar(eunomia::serialize_sidecar(in), out));
  TEST_ASSERT_EQUAL_INT64(in.seq, out.seq);
  TEST_ASSERT_EQUAL_STRING(in.kit_id.c_str(), out.kit_id.c_str());
  TEST_ASSERT_EQUAL_STRING(in.side.c_str(), out.side.c_str());
  TEST_ASSERT_EQUAL_STRING(in.back.c_str(), out.back.c_str());
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_sidecar_valid_and_warn_parse);
  RUN_TEST(test_telemetry_valid_and_warn_parse);
  RUN_TEST(test_missing_hard_field_rejected);
  RUN_TEST(test_roundtrip);
  return UNITY_END();
}
