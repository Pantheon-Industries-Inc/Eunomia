// firmware/coordinator/transport/proto/ — the X3 hidcap wire protocol (OSC :80 + telnet :23), pure.
//
// Adapted from Victor's `main.cpp` (`oscSendNoWait`/`oscFire`, `telnetCmd`/`telnetWriteFile`,
// `sidecarPathForClip`, the `ls -t … grep VID_ … head -1` recover). THE TWO HARD RULES are enforced
// here at the wire level: OSC is fire-and-forget (the body is NEVER read — the X3's off-by-one
// response, §1.3) and there is no per-take arm (start = a direct `camera.startCapture`).
// Serialization
// (`wifiLock`) + L2-only presence live one layer up (the worker + the registry); these functions
// just produce/consume bytes on an injected Conn.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_PROTO_X3_PROTOCOL_H
#define EUNOMIA_COORDINATOR_TRANSPORT_PROTO_X3_PROTOCOL_H

#include <cstdint>
#include <string>

#include "conn.h"

namespace eunomia::transport {

inline constexpr std::uint16_t kOscPort = 80;
inline constexpr std::uint16_t kTelnetPort = 23;
inline constexpr const char *kOscExecPath = "/osc/commands/execute";
inline constexpr const char *kCamPantheonDir = "/tmp/SD0/PANTHEON"; // discardd ROOT on the card
inline constexpr const char *kClipDir = "/tmp/SD0/DCIM/Camera01";
inline constexpr const char *kAssignmentEnvPath = "/tmp/SD0/PANTHEON/current_assignment.env";
inline constexpr const char *kStopEnvPath = "/tmp/SD0/PANTHEON/current_stop.env";
inline constexpr std::uint32_t kOscGraceMs = 120; // let the cam read the full request before close
inline constexpr std::uint32_t kOscGapMs = 150;   // settle after each OSC req (never back-to-back)

// ---- OSC (HTTP :80) ----

// {"name":"<name>"} — the OSC commands/execute body (no per-take parameters; HARD RULE 2).
std::string osc_command_json(const char *name);

// The raw HTTP/1.1 POST bytes for an OSC command (Connection: close), as Victor's oscSendNoWait
// builds inline. Exposed for testing the exact wire format.
std::string build_osc_post(const std::string &ip, const std::string &json_body);

// ★ FIRE-AND-FORGET (HARD RULE 1): connect → write the request → flush → grace → stop. The response
// body is NEVER read (the X3 OSC reply is off-by-one and useless; reading it blocks the full
// timeout). Returns true once delivered (connected + written). On no-connect, settles the gap and
// returns false.
bool osc_fire(Conn &conn, Delayer &d, const std::string &ip, const std::string &json_body,
              std::uint32_t connect_ms = 1500);

// DEPOT-ONLY one-shot OSC GET /osc/info that READS the body to parse "serialNumber" (Victor's
// 2026-06-24 lockcams fix: the L2 sweep knows IP+MAC but not the serial). This is the ONLY OSC read
// in transport, and it is NEVER on the trigger/presence path — it runs only at `cmd=lockcams`
// (depot, both cams idle, serialized under wifiLock), so it does NOT violate HARD RULE 1 (no
// CONCURRENT / background OSC). Fills `serial_out`; returns true iff a serialNumber was parsed.
bool osc_info(Conn &conn, Delayer &d, const std::string &ip, std::string &serial_out,
              std::uint32_t connect_ms = 1500, int max_polls = 100, std::uint32_t poll_ms = 20);

// ---- telnet (:23, passwordless busybox) ----

// `mkdir -p '<dir>' ; cat > '<path>' <<'X3EOF' … sync ; echo WROTE <path>` — Victor's
// telnetWriteFile body. Nothing is shell-expanded on the camera (quoted heredoc); the value is
// pre-sanitized by core's clean_env_val. Success iff the camera echoes "WROTE".
std::string build_write_file_cmd(const std::string &full_path, const std::string &body);

// `ls -t <clipdir> 2>/dev/null | grep VID_ | head -1` — recover the just-written clip name.
std::string build_ls_clip_cmd();

// `grep -q SD0 /proc/mounts && echo PCARDOK` — the cherokee-safe card-readiness check (telnet, NOT
// the OSC /osc/state probe that crashed the X3). Success iff the output carries "PCARDOK".
std::string build_card_check_cmd();

// `touch /tmp/archive.trigger && echo ARC_OK` — fired on DESCARTAR so discardd re-stamps archive=1.
std::string build_archive_trigger_cmd();

// Run ONE command over a telnet session on `conn`: connect, drain the IAC banner (answer DO→WONT /
// WILL→DONT), send `cmd\necho __X3_DONE__\n`, collect stdout up to the marker, close. Fills `out`
// (marker-trimmed). Returns false only if the connect failed. Driven entirely off the injected Conn
// + Delayer so it is host-testable against a scripted MockConn.
bool telnet_run(Conn &conn, Delayer &d, const std::string &ip, const std::string &cmd,
                std::string &out, std::uint32_t connect_ms = 15000, int max_polls = 750,
                std::uint32_t poll_ms = 20);

// Extract the `VID_…` token from `ls` output (first whitespace-bounded run starting at "VID_"); ""
// if none. Port of Victor's camStopAll clip-recover loop.
std::string parse_clip_from_ls(const std::string &ls_out);

// Derive discardd's sidecar path for an OSC/clip filename:
// <clipdir>/VID_<ts>_<seq>.pantheon.json (no lens index). "" if the name can't be parsed.
std::string sidecar_path_for_clip(const std::string &clip);

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_PROTO_X3_PROTOCOL_H
