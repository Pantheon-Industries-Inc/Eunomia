#include "x3_capture_device.h"

#include <utility>

#include "x3_protocol.h"

namespace eunomia::transport {

X3CaptureDevice::X3CaptureDevice(std::string side, CameraRegistry &reg, Conn &conn,
                                 Delayer &delayer, EnvProvider &env)
    : side_(std::move(side)), reg_(reg), conn_(conn), d_(delayer), env_(env) {}

void X3CaptureDevice::start() {
  const std::string ip = reg_.ip_for(side_);
  if (ip.empty()) {
    return; // not present at L2 — nothing to fire (core's gate already vetted presence)
  }
  // 1) Identity/assignment FIRST, so discardd has the label for the clip it's about to make. The
  // env
  //    CONTENT is core's (project_assignment_env via the provider); transport only pushes the
  //    bytes.
  std::string out;
  telnet_run(conn_, d_, ip, build_write_file_cmd(kAssignmentEnvPath, env_.assignment_env()), out);
  // 2) Fire startCapture DIRECTLY — NO per-take arm (discardd locks video mode). HARD RULE 2.
  osc_fire(conn_, d_, ip, osc_command_json("camera.startCapture"));
}

void X3CaptureDevice::stop() {
  const std::string ip = reg_.ip_for(side_);
  if (ip.empty()) {
    return;
  }
  osc_fire(conn_, d_, ip, osc_command_json("camera.stopCapture"));
}

std::string X3CaptureDevice::read_back_filename() {
  const std::string ip = reg_.ip_for(side_);
  if (ip.empty()) {
    return std::string();
  }
  std::string out;
  if (!telnet_run(conn_, d_, ip, build_ls_clip_cmd(), out)) {
    return std::string();
  }
  return parse_clip_from_ls(out); // "" → core sets recording_suspect (the §2.2 no-SD trap)
}

std::string X3CaptureDevice::get_state() {
  const std::string ip = reg_.ip_for(side_);
  if (ip.empty()) {
    return "absent";
  }
  std::string out;
  if (!telnet_run(conn_, d_, ip, build_card_check_cmd(), out)) {
    return "unknown";
  }
  return (out.find("PCARDOK") != std::string::npos) ? "card_ok" : "no_card";
}

void X3CaptureDevice::write_sidecar(const eunomia::Sidecar &record) {
  const std::string ip = reg_.ip_for(side_);
  if (ip.empty()) {
    return;
  }
  // On this stack write_sidecar = push current_stop.env (option C); discardd materializes the
  // on-card pantheon-x3-sidecar/v2 JSON. The bytes are core's project_stop_env (via the provider).
  std::string out;
  telnet_run(conn_, d_, ip, build_write_file_cmd(kStopEnvPath, env_.stop_env()), out);
  // DESCARTAR (archive==1): also fire the archive trigger so discardd re-stamps archive=1 + keeps
  // the footage. The record carries the disposition (set by Coordinator::mark_archive).
  if (record.archive != 0) {
    std::string arc;
    telnet_run(conn_, d_, ip, build_archive_trigger_cmd(), arc);
  }
}

} // namespace eunomia::transport
