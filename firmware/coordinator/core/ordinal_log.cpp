#include "ordinal_log.h"

namespace eunomia::core {

namespace {

// Escape a string value for inclusion in a double-quoted JSON string (the log line is JSONL). Ids
// are constrained (UUIDs / hex / depot ids) but defensive escaping is cheap and keeps the line
// parseable no matter what a depot value carries.
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
      } // drop other control chars
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

} // namespace

std::string serialize_ordinal_entry(const OrdinalLogEntry &e) {
  std::string out;
  out.reserve(140);
  out += "{\"T\":\"O\",\"o\":";
  out += std::to_string(e.ordinal);
  out += ",\"t\":";
  out += std::to_string(e.wallclock_unix);
  json_str_field(out, "k", e.kit_id);
  json_str_field(out, "f", e.fob_id);
  json_str_field(out, "s", e.fob_session_id);
  json_str_field(out, "e", e.episode_id);
  out.push_back('}');
  return out;
}

SegmentedEpisodeLog::SegmentedEpisodeLog(LogSegment &a, LogSegment &b, std::size_t seg_bytes)
    : seg_{&a, &b}, seg_bytes_(seg_bytes == 0 ? 1 : seg_bytes) {}

void SegmentedEpisodeLog::begin() {
  // The active (newest) segment is the smaller one: it grows from empty after each switch while the
  // other holds the prior full segment. Equal/both-empty → segment 0. Survives a battery swap.
  active_ = (seg_[1]->size() < seg_[0]->size()) ? 1 : 0;
}

void SegmentedEpisodeLog::append(const std::string &jsonl_line) {
  const std::size_t need = jsonl_line.size() + 1; // + newline
  if (seg_[active_]->size() > 0 && seg_[active_]->size() + need > seg_bytes_) {
    // Active full: switch to the other (older) segment and clear it — drops the oldest window.
    // O(1).
    active_ ^= 1;
    seg_[active_]->clear();
  }
  seg_[active_]->append(jsonl_line);
}

std::size_t SegmentedEpisodeLog::bytes() const { return seg_[0]->size() + seg_[1]->size(); }

} // namespace eunomia::core
