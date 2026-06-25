// firmware/coordinator/core/ — eunomia-sidecar/v1 assembly + the env projections (OQ-2 option C).
//
// ONE source of truth (the coordinator-owned field set: Assignment + TakeContext) with TWO
// projections, never double-maintained:
//   1. assemble_sidecar()  → the eunomia::Sidecar v1 record: the coordinator's CONTRACT SURFACE
//      (what F1 conformance-validates off-target + feeds the god's-view/ordinal-join backup).
//   2. project_assignment_env() / project_stop_env() → the KEY="value" env files the fob pushes to
//      discardd over telnet (current_assignment.env at START, current_stop.env at STOP). On this
//      stack `write_sidecar` = push these; discardd materializes the on-card pantheon-x3-sidecar/v2
//      JSON (UNTOUCHED in F1). The v2→v1 reconciliation lands at ingest, joined by episode_id.
//
// Field ownership (CONTRACT §3.3/§3.5): the coordinator owns the fob-sourced fields (kit_id,
// operator/station/task/prompt/episode_id/timing/outcome/provenance); the camera-owned fields
// (camera_id, side←NAND, camera_firmware, kit_version, global_episode_seq, seq, files.back,
// record_settings) are supplied by discardd and carried here as CameraInfo for
// assembly/conformance.
#ifndef EUNOMIA_COORDINATOR_CORE_SIDECAR_ASSEMBLY_H
#define EUNOMIA_COORDINATOR_CORE_SIDECAR_ASSEMBLY_H

#include <cstdint>
#include <string>

#include "eunomia_sidecar.h"

namespace eunomia::core {

// The per-shift assignment context (identity/task ride from the fob; set after sign-in).
struct Assignment {
  std::string kit_id; // ← FOB (decides canonical naming + pairing; §3.3)
  std::string operator_id;
  std::string station_id;
  std::string task_id;
  std::string task_name;
  std::string prompt;
  std::string rotation_id;
  std::string session_id;
  std::string task_source = "none"; // nand_staged | sd_assignment | none (§3.5)
  std::string assignment_source;
  std::string site_id;
  std::string fob_id;
  std::string fob_build;
  std::string fob_session_id; // rides the ordinal-log + operational session, NOT the sidecar (OQ-7)
  std::string modality = "umi";
};

// The coordinator-owned per-take fields (minted/measured by the fob).
struct TakeContext {
  std::string episode_id;          // UUIDv4 pairing key (§7)
  std::string bimanual_episode_id; // fob-injected shared L/R id; binds current_stop.env
  std::int64_t episode_ordinal = 0;
  std::string display_id;
  double started_unix = 0;
  double stopped_unix = 0;
  double start_skew_ms = 0;
  std::string stop_reason; // operator | timer | card_full | battery | error | overheat
  std::int64_t archive = 0;
  std::int64_t recording_suspect = 0; // NET-NEW, coordinator-owned (the no-SD trap; §2.2)
};

// The camera-owned fields discardd supplies (NAND identity, self-read fw, the clip pointer).
struct CameraInfo {
  std::string camera_id;
  std::string side; // ← CAMERA NAND (left|right)
  std::string calibration_id;
  std::string mount;
  std::string camera_firmware;
  std::string kit_version;
  std::string record_settings;
  std::string back; // files.back — the actual clip the sidecar describes
  std::int64_t global_episode_seq = 0;
  std::int64_t seq = 0;
};

// Assemble the eunomia-sidecar/v1 record (the contract surface). schema/record_format_version are
// set.
eunomia::Sidecar assemble_sidecar(const Assignment &a, const TakeContext &t, const CameraInfo &c);

// current_assignment.env — the identity/task subset the fob pushes BEFORE START (discardd reads
// it).
std::string project_assignment_env(const Assignment &a, const TakeContext &t);

// current_stop.env — the outcome/timing the fob pushes at STOP, bound by EP_BIMANUAL_EPISODE_ID.
std::string project_stop_env(const TakeContext &t);

} // namespace eunomia::core

#endif // EUNOMIA_COORDINATOR_CORE_SIDECAR_ASSEMBLY_H
