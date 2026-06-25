#include "presence.h"

#include <cctype>

namespace eunomia::transport {

namespace {
std::string lower(const std::string &s) {
  std::string o;
  o.reserve(s.size());
  for (char c : s) {
    o.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
  }
  return o;
}
} // namespace

MacSideMap MacSideMap::from_allowlist(const std::string &csv) {
  MacSideMap m;
  // The first two non-empty entries bind to left/right (the depot pairs them in that order). Extra
  // entries (pre-authorized spare bodies) are allowed but bind to no side — they pass isolation but
  // are not triggerable until they take a left/right slot.
  std::size_t start = 0;
  int idx = 0;
  while (start <= csv.size()) {
    const std::size_t comma = csv.find(',', start);
    const std::size_t end = (comma == std::string::npos) ? csv.size() : comma;
    std::string tok = csv.substr(start, end - start);
    // trim
    while (!tok.empty() && (tok.front() == ' ' || tok.front() == '\t')) {
      tok.erase(tok.begin());
    }
    while (!tok.empty() && (tok.back() == ' ' || tok.back() == '\t')) {
      tok.pop_back();
    }
    if (!tok.empty()) {
      const char *side = (idx == 0) ? "left" : (idx == 1) ? "right" : "";
      if (side[0] != '\0') {
        m.entries_.emplace_back(lower(tok), side);
      }
      ++idx;
    }
    if (comma == std::string::npos) {
      break;
    }
    start = comma + 1;
  }
  return m;
}

std::string MacSideMap::side_for(const std::string &mac) const {
  const std::string needle = lower(mac);
  for (const auto &e : entries_) {
    if (e.first == needle) {
      return e.second;
    }
  }
  return std::string();
}

void CameraRegistry::update(const std::vector<StationEntry> &stations) {
  for (auto &kv : slots_) {
    kv.second.present = false; // clear; re-mark from the fresh snapshot
  }
  for (const auto &st : stations) {
    if (st.ip.empty()) {
      continue; // associated but no DHCP lease yet — skip (Victor's discoverCams)
    }
    const std::string side = map_.side_for(st.mac);
    if (side.empty()) {
      continue; // an associated MAC not bound to a side (foreign / spare)
    }
    Slot &slot = slots_[side];
    slot.ip = st.ip;
    slot.present = true;
  }
}

std::string CameraRegistry::ip_for(const std::string &side) const {
  const auto it = slots_.find(side);
  return (it != slots_.end() && it->second.present) ? it->second.ip : std::string();
}

bool CameraRegistry::is_present(const std::string &side) const {
  const auto it = slots_.find(side);
  return it != slots_.end() && it->second.present;
}

std::vector<std::string> CameraRegistry::present() const {
  std::vector<std::string> out;
  for (const auto &kv : slots_) { // std::map iterates sorted → deterministic order
    if (kv.second.present) {
      out.push_back(kv.first);
    }
  }
  return out;
}

} // namespace eunomia::transport
