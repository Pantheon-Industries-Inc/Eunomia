#include "provisioning.h"

#include <cctype>

namespace eunomia::transport {

namespace {
std::string trim(const std::string &s) {
  std::size_t a = 0, b = s.size();
  while (a < b && std::isspace(static_cast<unsigned char>(s[a]))) {
    ++a;
  }
  while (b > a && std::isspace(static_cast<unsigned char>(s[b - 1]))) {
    --b;
  }
  return s.substr(a, b - a);
}

std::string lower(const std::string &s) {
  std::string o;
  o.reserve(s.size());
  for (char c : s) {
    o.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
  }
  return o;
}

void apply(ProvisioningInfo &info, const std::string &key, const std::string &val) {
  const std::string k = lower(key);
  if (k == "mac") {
    info.mac = val;
  } else if (k == "ap_ssid" || k == "ap") {
    info.ap_ssid = val;
  } else if (k == "ip") {
    info.ip = val;
  } else if (k == "body_serial" || k == "serial") {
    info.body_serial = val;
  } else if (k == "insv_serial" || k == "insv") {
    info.insv_serial = val;
  } else if (k == "side") {
    info.side = val;
  }
  // unknown keys ignored (forward-compatible with the in-flight daemon — OQ-8)
}
} // namespace

ProvisioningInfo parse_provisioning_push(const std::string &payload) {
  ProvisioningInfo info;
  // Split on newlines or ';'; each token is key=value.
  std::size_t start = 0;
  while (start <= payload.size()) {
    std::size_t end = payload.size();
    for (std::size_t i = start; i < payload.size(); ++i) {
      if (payload[i] == '\n' || payload[i] == ';') {
        end = i;
        break;
      }
    }
    const std::string tok = payload.substr(start, end - start);
    const std::size_t eq = tok.find('=');
    if (eq != std::string::npos) {
      apply(info, trim(tok.substr(0, eq)), trim(tok.substr(eq + 1)));
    }
    if (end >= payload.size()) {
      break;
    }
    start = end + 1;
  }
  info.valid = !info.mac.empty();
  return info;
}

} // namespace eunomia::transport
