// firmware/coordinator/core/ — task-config parsing + station→task resolution (F9).
//
// Parses the JSON response from GET /api/task-config/{kit_id} (fetched at boot by F7's BootUplink)
// and resolves which task a station is assigned. The dashboard serves a projection of the
// contract's task_station_assignment + task catalog; the fob gets a flat list of station→task
// assignments. Server-driven when available, manual fallback when not. Pure + off-target testable
// (ArduinoJson is header-only).
#ifndef EUNOMIA_COORDINATOR_CORE_TASK_CONFIG_H
#define EUNOMIA_COORDINATOR_CORE_TASK_CONFIG_H

#include <string>
#include <vector>

namespace eunomia::core {

struct StationAssignment {
  std::string station_id;
  std::string task_id;
  std::string task_name;
  std::string prompt;
  std::string rotation_id;
  int task_version = 0;
};

struct TaskConfig {
  std::string site_id;
  std::vector<StationAssignment> assignments;
  std::vector<std::string> roster;
  std::string fetched_at;
  bool valid = false;
};

// Parse the raw JSON response body from the dashboard. Returns TaskConfig with valid=false on empty
// input, malformed JSON, or missing required fields. Skips individual assignments that lack
// station_id or task_id (warns on serial but does not fail the whole config). Bounded to 8 KB
// input.
TaskConfig parse_task_config(const std::string &json_body);

// Resolve the task assignment for a station_id. Returns nullptr if config is invalid or no
// assignment matches. Linear scan (the list is small: ~5–20 stations per site).
const StationAssignment *resolve_assignment(const TaskConfig &config,
                                            const std::string &station_id);

} // namespace eunomia::core

#endif // EUNOMIA_COORDINATOR_CORE_TASK_CONFIG_H
