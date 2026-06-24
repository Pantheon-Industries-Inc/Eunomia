// Off-target (host) conformance test for the Run 0a `ping` codegen proof.
//
// Parses the SAME golden fixtures as the Python conformance test
// (contracts/conformance/fixtures/ping/{valid,invalid}/), using the GENERATED C++
// header — proving the C++ target agrees with the JSON Schema + Python validator.
// This is also the off-target unit-test harness stub (the firmware core is hardware-free
// and host-testable; the one-machine rule).
#include <unity.h>

#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

#include "eunomia_ping.h"

namespace fs = std::filesystem;

static std::string read_file(const fs::path &p) {
  std::ifstream f(p);
  std::stringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

static int check_dir(const fs::path &dir, bool expect_parse) {
  int n = 0;
  for (const auto &entry : fs::directory_iterator(dir)) {
    if (entry.path().extension() != ".json")
      continue;
    eunomia::Ping p;
    bool ok = eunomia::parse_ping(read_file(entry.path()), p);
    TEST_ASSERT_EQUAL_MESSAGE(expect_parse, ok, entry.path().filename().string().c_str());
    n++;
  }
  return n;
}

void test_valid_fixtures_parse() {
  int n = check_dir(fs::path(EUNOMIA_FIXTURES_DIR) / "valid", true);
  TEST_ASSERT_GREATER_THAN_MESSAGE(0, n, "no valid fixtures found");
}

void test_invalid_fixtures_rejected() {
  int n = check_dir(fs::path(EUNOMIA_FIXTURES_DIR) / "invalid", false);
  TEST_ASSERT_GREATER_THAN_MESSAGE(0, n, "no invalid fixtures found");
}

void test_roundtrip() {
  eunomia::Ping in{42, 1.5};
  eunomia::Ping out;
  TEST_ASSERT_TRUE(eunomia::parse_ping(eunomia::serialize_ping(in), out));
  TEST_ASSERT_EQUAL_INT64(in.seq, out.seq);
  TEST_ASSERT_EQUAL_DOUBLE(in.sent_unix, out.sent_unix);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_valid_fixtures_parse);
  RUN_TEST(test_invalid_fixtures_rejected);
  RUN_TEST(test_roundtrip);
  return UNITY_END();
}
