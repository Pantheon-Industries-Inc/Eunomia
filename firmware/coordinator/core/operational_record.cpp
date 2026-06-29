#include "operational_record.h"

#include <string>

namespace eunomia::core {

namespace {

void json_escape_into(std::string &out, const std::string &in) {
  for (char c : in) {
    switch (c) {
    case '"':
      out += "\\\"";
      break;
    case '\\':
      out += "\\\\";
      break;
    case '\n':
      out += "\\n";
      break;
    case '\r':
      out += "\\r";
      break;
    default:
      if (static_cast<unsigned char>(c) >= 0x20) {
        out.push_back(c);
      }
      break;
    }
  }
}

void json_str_field(std::string &out, const char *key, const std::string &value) {
  out += ",\"";
  out += key;
  out += "\":\"";
  json_escape_into(out, value);
  out.push_back('"');
}

void json_int_field(std::string &out, const char *key, std::int64_t value) {
  out += ",\"";
  out += key;
  out += "\":";
  out += std::to_string(value);
}

} // namespace

std::string serialize_episode_started(const Assignment &a, const TakeContext &t) {
  std::string out;
  out.reserve(256);
  out += "{\"T\":\"E\",\"st\":\"start\"";
  json_int_field(out, "o", t.episode_ordinal);
  json_int_field(out, "t", static_cast<std::int64_t>(t.started_unix));
  json_str_field(out, "k", a.kit_id);
  json_str_field(out, "e", t.episode_id);
  json_str_field(out, "sid", a.session_id);
  json_str_field(out, "op", a.operator_id);
  json_str_field(out, "stn", a.station_id);
  json_str_field(out, "tid", a.task_id);
  if (!a.rotation_id.empty()) {
    json_str_field(out, "rv", a.rotation_id);
  }
  json_str_field(out, "ts", a.task_source);
  out.push_back('}');
  return out;
}

std::string serialize_episode_stopped(const TakeContext &t, const std::string &kit_id) {
  std::string out;
  out.reserve(128);
  out += "{\"T\":\"E\",\"st\":\"stop\"";
  json_int_field(out, "o", t.episode_ordinal);
  json_int_field(out, "t", static_cast<std::int64_t>(t.stopped_unix));
  json_str_field(out, "k", kit_id);
  json_str_field(out, "e", t.episode_id);
  json_str_field(out, "r", t.stop_reason);
  json_int_field(out, "a", t.archive);
  json_int_field(out, "rs", t.recording_suspect);
  out.push_back('}');
  return out;
}

std::string serialize_episode_discarded(const TakeContext &t, const std::string &kit_id) {
  std::string out;
  out.reserve(96);
  out += "{\"T\":\"E\",\"st\":\"discard\"";
  json_int_field(out, "o", t.episode_ordinal);
  json_int_field(out, "t", static_cast<std::int64_t>(t.stopped_unix));
  json_str_field(out, "k", kit_id);
  json_str_field(out, "e", t.episode_id);
  out.push_back('}');
  return out;
}

std::string serialize_session_signin(const Assignment &a, const std::string &session_id,
                                     std::int64_t wallclock) {
  std::string out;
  out.reserve(192);
  out += "{\"T\":\"S\",\"st\":\"signin\"";
  json_int_field(out, "t", wallclock);
  json_str_field(out, "k", a.kit_id);
  json_str_field(out, "f", a.fob_id);
  json_str_field(out, "s", a.fob_session_id);
  json_str_field(out, "sid", session_id);
  json_str_field(out, "op", a.operator_id);
  json_str_field(out, "site", a.site_id);
  out.push_back('}');
  return out;
}

std::string serialize_station_assignment(const Assignment &a, std::int64_t wallclock,
                                         const std::string &session_id) {
  std::string out;
  out.reserve(256);
  out += "{\"T\":\"A\"";
  json_int_field(out, "t", wallclock);
  json_str_field(out, "k", a.kit_id);
  json_str_field(out, "stn", a.station_id);
  json_str_field(out, "tid", a.task_id);
  json_str_field(out, "tn", a.task_name);
  if (!a.rotation_id.empty()) {
    json_str_field(out, "rv", a.rotation_id);
  }
  json_str_field(out, "ts", a.task_source);
  json_str_field(out, "sid", session_id);
  out.push_back('}');
  return out;
}

} // namespace eunomia::core
