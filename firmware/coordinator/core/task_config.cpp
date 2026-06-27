// NOLINTBEGIN(clang-analyzer-cplusplus.NewDeleteLeaks) — ArduinoJson's arena allocator triggers
// false positives; every JsonDocument call path is flagged. Safe to suppress file-wide: the
// JsonDocument owns its memory and frees it in its destructor.
#include "task_config.h"

#include <ArduinoJson.h>

namespace eunomia::core {

namespace {
constexpr std::size_t kMaxInputBytes = 8192;
} // namespace

TaskConfig parse_task_config(const std::string &json_body) {
  TaskConfig cfg;
  if (json_body.empty() || json_body.size() > kMaxInputBytes) {
    return cfg;
  }
  JsonDocument doc;
  const DeserializationError err = deserializeJson(doc, json_body);
  if (err) {
    return cfg;
  }
  if (!doc["assignments"].is<JsonArray>()) {
    return cfg;
  }
  cfg.site_id = doc["site_id"] | "";
  cfg.fetched_at = doc["fetched_at"] | "";
  for (JsonObject obj : doc["assignments"].as<JsonArray>()) {
    const char *sid = obj["station_id"];
    const char *tid = obj["task_id"];
    if (sid == nullptr || sid[0] == '\0' || tid == nullptr || tid[0] == '\0') {
      continue;
    }
    StationAssignment sa;
    sa.station_id = sid;
    sa.task_id = tid;
    sa.task_name = obj["task_name"] | "";
    sa.prompt = obj["prompt"] | "";
    sa.rotation_id = obj["rotation_id"] | "";
    sa.task_version = obj["task_version"] | 0;
    cfg.assignments.push_back(std::move(sa));
  }
  if (doc["roster"].is<JsonArray>()) {
    for (JsonVariant v : doc["roster"].as<JsonArray>()) {
      if (v.is<const char *>() && v.as<const char *>() != nullptr) {
        cfg.roster.push_back(v.as<const char *>());
      }
    }
  }
  cfg.valid = true;
  return cfg;
}

const StationAssignment *resolve_assignment(const TaskConfig &config,
                                            const std::string &station_id) {
  if (!config.valid) {
    return nullptr;
  }
  for (const auto &a : config.assignments) {
    if (a.station_id == station_id) {
      return &a;
    }
  }
  return nullptr;
}

} // namespace eunomia::core
// NOLINTEND(clang-analyzer-cplusplus.NewDeleteLeaks)
