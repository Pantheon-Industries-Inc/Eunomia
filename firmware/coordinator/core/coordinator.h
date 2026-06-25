// firmware/coordinator/core/ — the fob coordinator (the CoordinatorPort implementation).
//
// The pure, off-target-testable heart of the fob. Depends ONLY on contracts/_generated/cpp/ + the
// injected seams (seams.h) + the fleet of CaptureDevicePort adapters. The real
// OSC/telnet/SoftAP/NVS live in transport/ (Run F2); the native tests drive fakes. Owns:
//   * the spam-safe trigger state machine (START only from idle; STOP only from recording),
//   * the both-cams-present phantom-press gate (a START commits only when sent==2),
//   * episode_id (UUIDv4) + display_id + the durable fob episode_ordinal + fob_session_id,
//   * the fob-side ordinal-join ring buffer (the §1.7 backup),
//   * the eunomia-sidecar/v1 assembly (the option-C contract surface) + its env projections.
// (The delayed-button feedback STATE is a separate core primitive — button_feedback.h — OWNED and
// driven by ui/ (F3) around the slow inline action (there is no async trigger queue — the F2
// no-queue finding); embedding it in the synchronous trigger() would collapse the working-window,
// so it is not a Coordinator member.) THE TWO HARD RULES live in transport/ (F2); core/ is built to
// not violate them — it reads presence ONLY via the L2 PresenceSource (never OSC) and issues
// exactly one serialized fleet-trigger per START.
#ifndef EUNOMIA_COORDINATOR_CORE_COORDINATOR_H
#define EUNOMIA_COORDINATOR_CORE_COORDINATOR_H

#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include "episode.h"
#include "eunomia_capture_device_port.h"
#include "eunomia_coordinator_port.h"
#include "eunomia_sidecar.h"
#include "ordinal_log.h"
#include "seams.h"
#include "sidecar_assembly.h"
#include "trigger_state_machine.h"

namespace eunomia::core {

// The phantom-press gate outcome (CONTRACT §3.6 / SPEC §1.8). A START commits only when BOTH
// cameras are present at L2 (sent==2); 0 present = phantom (dropped); 1 present = one-sided (GRABAR
// locked).
enum class GateOutcome : std::uint8_t { Committed, PhantomDropped, OneSidedRefused };

// present_count == 0 → PhantomDropped; 0 < present_count < required → OneSidedRefused; else
// Committed.
GateOutcome evaluate_gate(std::size_t present_count, std::size_t required);

class Coordinator : public eunomia::CoordinatorPort {
public:
  struct Deps {
    Clock *clock = nullptr;
    Rng *rng = nullptr;
    PersistentStore *store = nullptr;
    PresenceSource *presence = nullptr;
    TelemetrySink *telemetry = nullptr; // optional opportunistic uplink (F2 transport)
  };
  using Fleet = std::vector<std::pair<std::string, eunomia::CaptureDevicePort *>>;

  Coordinator(Deps deps, Fleet fleet, std::size_t required_cameras = 2);

  // Per-shift identity/task context (set after sign-in).
  void set_assignment(const Assignment &a);
  void set_fob_session_id(const std::string &id) { assignment_.fob_session_id = id; }

  // ---- CoordinatorPort (the six seam operations, CONTRACT §1.6) ----
  std::string mint_episode_id() override;
  bool trigger(const std::vector<std::string> &cameras) override;
  std::string read_clip_filename(const std::string &camera) override;
  void write_sidecar(const std::string &camera, const eunomia::Sidecar &record) override;
  std::vector<std::string> detect_drop() override;
  void flush_telemetry() override;

  // ---- operator STOP / decision inputs (delayed buttons; not port ops) ----
  bool stop(const std::string &reason); // valid only from recording
  void mark_archive();                  // DESCARTAR = void+keep (archive=1)

  // ---- accessors for the UI + tests ----
  State state() const { return sm_.state(); }
  GateOutcome last_outcome() const { return last_outcome_; }
  std::size_t last_sent() const { return last_sent_; }
  // Live L2 present count for the UI GO/NO-GO color (read-only; polled each render frame). Reads
  // the L2 PresenceSource (never OSC) — the same source the gate uses. NOT detect_drop() (a
  // mutating port op): this is the per-frame presence read ui/ needs and the only core accessor F3
  // adds (FLAG-C).
  std::size_t present_count() const {
    return deps_.presence != nullptr ? deps_.presence->present().size() : 0;
  }
  const TakeContext &take() const { return take_; }
  const OrdinalLog &ordinal_log() const { return ordinal_log_; }
  std::size_t pending_telemetry() const { return pending_.size(); }

  // The current take's eunomia-sidecar/v1 record for `camera` (the contract surface; testable).
  eunomia::Sidecar assemble_current_sidecar(const CameraInfo &cam) const;

private:
  eunomia::CaptureDevicePort *device(const std::string &name) const;
  static bool contains(const std::vector<std::string> &v, const std::string &name);

  Deps deps_;
  Fleet fleet_;
  std::size_t required_cameras_;
  Assignment assignment_;
  TriggerStateMachine sm_;
  DurableOrdinal ordinal_;
  OrdinalLog ordinal_log_;

  std::string pending_episode_id_; // minted by mint_episode_id, consumed by trigger
  std::string pending_bimanual_id_;
  TakeContext take_; // the current/last take's coordinator-owned fields
  GateOutcome last_outcome_ = GateOutcome::PhantomDropped;
  std::size_t last_sent_ = 0;
  std::vector<std::string> pending_; // queued god's-view event lines (flushed in the idle gap)
};

} // namespace eunomia::core

#endif // EUNOMIA_COORDINATOR_CORE_COORDINATOR_H
