#include "x3_protocol.h"

namespace eunomia::transport {

namespace {
constexpr const char *kDoneMarker = "__X3_DONE__";

std::string dirname_of(const std::string &full_path) {
  const std::size_t slash = full_path.find_last_of('/');
  return (slash == std::string::npos || slash == 0) ? std::string("/") : full_path.substr(0, slash);
}
} // namespace

std::string osc_command_json(const char *name) {
  std::string body = "{\"name\":\"";
  body += name;
  body += "\"}";
  return body;
}

std::string build_osc_post(const std::string &ip, const std::string &json_body) {
  std::string req = "POST ";
  req += kOscExecPath;
  req += " HTTP/1.1\r\nHost: ";
  req += ip;
  req += ":";
  req += std::to_string(kOscPort);
  req += "\r\nContent-Type: application/json\r\nContent-Length: ";
  req += std::to_string(json_body.size());
  req += "\r\nConnection: close\r\n\r\n";
  req += json_body;
  return req;
}

bool osc_fire(Conn &conn, Delayer &d, const std::string &ip, const std::string &json_body,
              std::uint32_t connect_ms) {
  if (!conn.connect(ip, kOscPort, connect_ms)) {
    d.delay_ms(kOscGapMs);
    return false;
  }
  const std::string req = build_osc_post(ip, json_body);
  conn.write(req);
  conn.flush();            // push the bytes onto the wire
  d.delay_ms(kOscGraceMs); // let the cam receive + read the full request before we close
  conn.stop(); // graceful close — the cam has the command; we do NOT read the (off-by-one) reply
  d.delay_ms(kOscGapMs);
  return true; // delivered (connected + wrote). NOTE: no conn.read() anywhere — HARD RULE 1.
}

bool osc_info(Conn &conn, Delayer &d, const std::string &ip, std::string &serial_out,
              std::uint32_t connect_ms, int max_polls, std::uint32_t poll_ms) {
  serial_out.clear();
  if (!conn.connect(ip, kOscPort, connect_ms)) {
    d.delay_ms(kOscGapMs);
    return false;
  }
  std::string req = "GET /osc/info HTTP/1.1\r\nHost: ";
  req += ip;
  req += "\r\nConnection: close\r\n\r\n";
  conn.write(req);
  conn.flush();
  std::string body;
  for (int poll = 0; poll < max_polls; ++poll) {
    while (conn.available() > 0) {
      body.push_back(static_cast<char>(conn.read()));
    }
    if (body.find("serialNumber") != std::string::npos) {
      break;
    }
    if (!conn.connected() && conn.available() <= 0) {
      break;
    }
    d.delay_ms(poll_ms);
  }
  conn.stop();
  d.delay_ms(kOscGapMs);
  // Parse "serialNumber":"<value>" without a JSON dep (core owns the only typed contract surface).
  const std::size_t k = body.find("\"serialNumber\"");
  if (k == std::string::npos) {
    return false;
  }
  const std::size_t q1 = body.find('"', body.find(':', k));
  if (q1 == std::string::npos) {
    return false;
  }
  const std::size_t q2 = body.find('"', q1 + 1);
  if (q2 == std::string::npos) {
    return false;
  }
  serial_out = body.substr(q1 + 1, q2 - q1 - 1);
  return !serial_out.empty();
}

std::string build_write_file_cmd(const std::string &full_path, const std::string &body) {
  std::string cmd = "mkdir -p '";
  cmd += dirname_of(full_path);
  cmd += "'\ncat > '";
  cmd += full_path;
  cmd += "' <<'X3EOF'\n";
  cmd += body;
  cmd += "\nX3EOF\nsync\necho WROTE ";
  cmd += full_path;
  return cmd;
}

std::string build_ls_clip_cmd() {
  std::string cmd = "ls -t ";
  cmd += kClipDir;
  cmd += "/ 2>/dev/null | grep VID_ | head -1";
  return cmd;
}

std::string build_card_check_cmd() { return "grep -q SD0 /proc/mounts && echo PCARDOK"; }

std::string build_archive_trigger_cmd() { return "touch /tmp/archive.trigger && echo ARC_OK"; }

bool telnet_run(Conn &conn, Delayer &d, const std::string &ip, const std::string &cmd,
                std::string &out, std::uint32_t connect_ms, int max_polls, std::uint32_t poll_ms) {
  out.clear();
  if (!conn.connect(ip, kTelnetPort, connect_ms)) {
    return false;
  }
  d.delay_ms(400); // let the login/negotiation banner arrive

  // Drain the IAC negotiation: answer DO(0xFD)→WONT(0xFC), WILL(0xFB)→DONT(0xFE), echoing the
  // option.
  std::string neg;
  while (conn.available() > 0) {
    const int b = conn.read();
    if (b == 0xFF && conn.available() >= 2) {
      const int c = conn.read();
      const int opt = conn.read();
      if (c == 0xFD) {
        neg.push_back(static_cast<char>(0xFF));
        neg.push_back(static_cast<char>(0xFC));
        neg.push_back(static_cast<char>(opt));
      } else if (c == 0xFB) {
        neg.push_back(static_cast<char>(0xFF));
        neg.push_back(static_cast<char>(0xFE));
        neg.push_back(static_cast<char>(opt));
      }
    }
  }
  if (!neg.empty()) {
    conn.write(neg);
  }

  std::string full = cmd;
  full += "\necho ";
  full += kDoneMarker;
  full += "\n";
  conn.write(full);

  for (int poll = 0; poll < max_polls; ++poll) {
    while (conn.available() > 0) {
      const int b = conn.read();
      if (b == 0xFF && conn.available() >= 2) {
        conn.read();
        conn.read();
        continue; // skip an inline IAC sequence
      }
      out.push_back(static_cast<char>(b));
    }
    if (out.find(kDoneMarker) != std::string::npos) {
      break;
    }
    if (!conn.connected() && conn.available() <= 0) {
      break;
    }
    d.delay_ms(poll_ms);
  }
  conn.stop();
  const std::size_t m = out.find(kDoneMarker);
  if (m != std::string::npos) {
    out = out.substr(0, m);
  }
  return true;
}

std::string parse_clip_from_ls(const std::string &ls_out) {
  const std::size_t v = ls_out.find("VID_");
  if (v == std::string::npos) {
    return std::string();
  }
  std::size_t e = v;
  while (e < ls_out.size()) {
    const char ch = ls_out[e];
    if (ch == '\r' || ch == '\n' || ch == ' ' || ch == '\t') {
      break;
    }
    ++e;
  }
  return ls_out.substr(v, e - v);
}

std::string sidecar_path_for_clip(const std::string &clip) {
  // discardd names the sidecar VID_<date>_<time>_<seq>.pantheon.json (no lens index), regardless of
  // which lens file (00/10) the clip points at. clip basename: VID_<date>_<time>_<NN>_<seq>.insv.
  const std::size_t slash = clip.find_last_of('/');
  const std::string base = (slash == std::string::npos) ? clip : clip.substr(slash + 1);
  if (base.rfind("VID_", 0) != 0) {
    return std::string();
  }
  const std::size_t p1 = base.find('_', 4); // after VID_<date>
  const std::size_t p2 = (p1 == std::string::npos) ? p1 : base.find('_', p1 + 1); // after <time>
  const std::size_t p3 = (p2 == std::string::npos) ? p2 : base.find('_', p2 + 1); // after <NN>
  if (p1 == std::string::npos || p2 == std::string::npos || p3 == std::string::npos) {
    return std::string();
  }
  const std::string ts = base.substr(4, p2 - 4); // <date>_<time>
  std::string rest = base.substr(p3 + 1);        // <seq>.<ext>
  const std::size_t dot = rest.find('.');
  const std::string seq = (dot == std::string::npos) ? rest : rest.substr(0, dot);
  if (ts.empty() || seq.empty()) {
    return std::string();
  }
  std::string path = kClipDir;
  path += "/VID_";
  path += ts;
  path += "_";
  path += seq;
  path += ".pantheon.json";
  return path;
}

} // namespace eunomia::transport
