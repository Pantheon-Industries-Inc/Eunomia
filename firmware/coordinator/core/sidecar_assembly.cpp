#include "sidecar_assembly.h"

#include <cstdio>

namespace eunomia::core {

namespace {

// Strip the chars that would break a double-quoted shell KEY="value" line discardd later sources
// (mirrors discardd's clean_env_val: " \ ` $ CR LF). Lossy but safe; task prompts are plain text.
std::string clean_env_val(const std::string &in) {
  std::string out;
  out.reserve(in.size());
  for (char c : in) {
    if (c == '"' || c == '\\' || c == '`' || c == '$' || c == '\r' || c == '\n') {
      continue;
    }
    out.push_back(c);
  }
  return out;
}

void env_line(std::string &dst, const char *key, const std::string &value) {
  dst.append(key);
  dst.append("=\"");
  dst.append(clean_env_val(value));
  dst.append("\"\n");
}

std::string fmt_double(double v) {
  char buf[32];
  std::snprintf(buf, sizeof buf, "%.3f", v);
  return std::string(buf);
}

} // namespace

eunomia::Sidecar assemble_sidecar(const Assignment &a, const TakeContext &t, const CameraInfo &c) {
  eunomia::Sidecar s;
  // ---- top-level (versioning + ordering spine) ----
  s.schema = "eunomia-sidecar/v1";
  s.record_format_version = 1;
  s.seq = c.seq; // per-card filename seq (camera-owned)
  s.global_episode_seq =
      c.global_episode_seq; // NAND swap-proof ordinal (camera-owned, PRIMARY spine)

  // ---- identity (kit/side from §3.3 precedence; task from §3.5) ----
  s.camera_id = c.camera_id; // ← NAND (provenance; never decides the kit)
  s.kit_id = a.kit_id;       // ← FOB
  s.side = c.side;           // ← CAMERA NAND
  s.operator_id = a.operator_id;
  s.station_id = a.station_id;
  s.task_id = a.task_id;
  s.task_name = a.task_name;
  s.session_id = a.session_id;
  s.episode_id = t.episode_id;
  s.rotation_id = a.rotation_id;
  s.prompt = a.prompt;
  s.task_source = a.task_source;
  s.episode_ordinal = t.episode_ordinal; // fob label ordinal (distinct from global_episode_seq)
  s.bimanual_episode_id = t.bimanual_episode_id;
  s.display_id = t.display_id;
  s.calibration_id = c.calibration_id;
  s.record_settings = c.record_settings;
  s.mount = c.mount;
  s.assignment_source = a.assignment_source;

  // ---- timing (fob-sourced; camera_clock left empty — poison/provenance-only) ----
  s.started_unix = t.started_unix;
  s.stopped_unix = t.stopped_unix;
  s.start_skew_ms = t.start_skew_ms;

  // ---- provenance / capture-stack ----
  s.camera_firmware = c.camera_firmware;
  s.fob_id = a.fob_id;
  s.fob_build = a.fob_build;
  s.kit_version = c.kit_version;
  s.site_id = a.site_id;
  s.modality = a.modality;

  // ---- outcome ----
  s.stop_reason = t.stop_reason;
  s.archive = t.archive;
  s.recording_suspect = t.recording_suspect;

  // ---- files ----
  s.back = c.back;
  return s;
}

std::string project_assignment_env(const Assignment &a, const TakeContext &t) {
  // Identity (kit/side) is NAND-resident and wins on the camera; the fob pushes ONLY
  // task/assignment.
  std::string out;
  env_line(out, "OPERATOR_ID", a.operator_id);
  env_line(out, "STATION_ID", a.station_id);
  env_line(out, "TASK_ID", a.task_id);
  env_line(out, "TASK_NAME", a.task_name);
  env_line(out, "PROMPT", a.prompt);
  env_line(out, "ROTATION_ID", a.rotation_id);
  env_line(out, "SESSION_ID", a.session_id);
  env_line(out, "EPISODE_ID", t.episode_id);
  env_line(out, "BIMANUAL_EPISODE_ID", t.bimanual_episode_id);
  env_line(out, "SITE_ID", a.site_id);
  env_line(out, "FOB_ID", a.fob_id);
  env_line(out, "FOB_BUILD", a.fob_build);
  env_line(out, "ASSIGNMENT_SOURCE", a.assignment_source);
  return out;
}

std::string project_stop_env(const TakeContext &t) {
  // Bound to the take by EP_BIMANUAL_EPISODE_ID so a stale stop file is never mis-applied
  // (discardd).
  std::string out;
  env_line(out, "EP_BIMANUAL_EPISODE_ID", t.bimanual_episode_id);
  env_line(out, "STOP_REASON", t.stop_reason);
  env_line(out, "START_SKEW_MS", fmt_double(t.start_skew_ms));
  env_line(out, "CAM_STARTED_UNIX", fmt_double(t.started_unix));
  env_line(out, "CAM_STOPPED_UNIX", fmt_double(t.stopped_unix));
  env_line(out, "ARCHIVE", t.archive ? "1" : "0");
  return out;
}

} // namespace eunomia::core
