#include "coordinator.h"

#include <utility>

namespace eunomia::core {

namespace {
constexpr char kOrdinalKey[] = "fob_episode_ordinal";
constexpr std::size_t kOrdinalLogCapacity = 512; // ≥2× the drain cadence (the ~2-day §1.7 window)

void queue_event(std::vector<std::string> &pending, const char *event, const TakeContext &t,
                 std::size_t sent) {
  // A tiny god's-view line (no poison camera time; the fob wallclock rides on started_unix).
  std::string line = "{\"event\":\"";
  line += event;
  line += "\",\"episode_id\":\"";
  line += t.episode_id;
  line += "\",\"ordinal\":";
  line += std::to_string(t.episode_ordinal);
  line += ",\"sent\":";
  line += std::to_string(sent);
  line += "}";
  pending.push_back(std::move(line));
}
} // namespace

GateOutcome evaluate_gate(std::size_t present_count, std::size_t required) {
  if (present_count == 0) {
    return GateOutcome::PhantomDropped;
  }
  if (present_count < required) {
    return GateOutcome::OneSidedRefused; // GRABAR locks at <2 cams; never a one-sided take
  }
  return GateOutcome::Committed;
}

Coordinator::Coordinator(Deps deps, Fleet fleet, std::size_t required_cameras)
    : deps_(deps), fleet_(std::move(fleet)), required_cameras_(required_cameras),
      ordinal_(*deps.store, kOrdinalKey), ordinal_log_(kOrdinalLogCapacity) {}

void Coordinator::set_assignment(const Assignment &a) { assignment_ = a; }

bool Coordinator::contains(const std::vector<std::string> &v, const std::string &name) {
  for (const auto &x : v) {
    if (x == name) {
      return true;
    }
  }
  return false;
}

eunomia::CaptureDevicePort *Coordinator::device(const std::string &name) const {
  for (const auto &entry : fleet_) {
    if (entry.first == name) {
      return entry.second;
    }
  }
  return nullptr;
}

std::string Coordinator::mint_episode_id() {
  // The UUIDv4 pairing key + a per-take bimanual id (the current_stop.env binding key). Both are
  // fob-minted and written identically to both arms. Stashed as pending for the next trigger().
  pending_episode_id_ = mint_uuid_v4(*deps_.rng);
  pending_bimanual_id_ = mint_uuid_v4(*deps_.rng);
  return pending_episode_id_;
}

bool Coordinator::trigger(const std::vector<std::string> &cameras) {
  // 1) Spam-safety: a START is acted on ONLY from idle (the second-trigger-mid-sequence drop).
  if (sm_.offer(Input::Start) != Action::BeginStart) {
    return false;
  }

  // 2) Phantom-press gate: presence is L2-ONLY (never OSC). Count the requested cams that are up.
  const std::vector<std::string> present = deps_.presence->present();
  std::size_t sent = 0;
  for (const auto &cam : cameras) {
    if (contains(present, cam)) {
      ++sent;
    }
  }
  last_sent_ = sent;
  const GateOutcome gate = evaluate_gate(sent, required_cameras_);
  if (gate != GateOutcome::Committed) {
    sm_.on_start_aborted(); // back to idle: NO ordinal advance (no commit)
    last_outcome_ = gate;
    return false;
  }

  // 3) Commit. Mint the episode if the app did not call mint_episode_id() first.
  if (pending_episode_id_.empty()) {
    mint_episode_id();
  }
  // Durable-before-advance: persist the ordinal BEFORE it advances. A flash failure returns 0 (the
  // unknown sentinel) and does NOT commit — never burns/reuses an ordinal (SPEC §1.8).
  const std::int64_t ord = ordinal_.advance();
  if (ord <= 0) {
    sm_.on_start_aborted();
    last_outcome_ = GateOutcome::PhantomDropped;
    return false;
  }

  take_ = TakeContext{};
  take_.episode_id = pending_episode_id_;
  take_.bimanual_episode_id = pending_bimanual_id_;
  take_.episode_ordinal = ord;
  take_.started_unix = deps_.clock->unix_seconds_frac();
  take_.display_id = make_display_id(deps_.clock->unix_seconds(), assignment_.operator_id,
                                     assignment_.station_id, ord);
  pending_episode_id_.clear();
  pending_bimanual_id_.clear();

  // The fob-side ordinal-join backup (the §1.7 fail-safe; lives on the fob, not the card).
  OrdinalLogEntry e;
  e.ordinal = ord;
  e.wallclock_unix = deps_.clock->unix_seconds();
  e.kit_id = assignment_.kit_id;
  e.fob_id = assignment_.fob_id;
  e.fob_session_id = assignment_.fob_session_id;
  e.episode_id = take_.episode_id;
  ordinal_log_.append(e);
  queue_event(pending_, "take_start", take_, sent);

  // 4) Fire the present cameras, serialized (the wifiLock serialization is transport's, F2).
  sm_.begin_firing(); // arming → starting (the ~3 s pipeline re-init window)
  for (const auto &cam : cameras) {
    if (contains(present, cam)) {
      if (auto *dev = device(cam)) {
        dev->start(); // startCapture directly — no per-take arm (HARD RULE 2)
      }
    }
  }
  sm_.on_started(); // starting → recording
  last_outcome_ = GateOutcome::Committed;
  return true;
}

std::string Coordinator::read_clip_filename(const std::string &camera) {
  auto *dev = device(camera);
  const std::string name = dev ? dev->read_back_filename() : std::string();
  // recording_suspect (NET-NEW, coordinator-owned): could not confirm a clip (the no-SD trap,
  // §2.2).
  if (name.empty()) {
    take_.recording_suspect = 1;
  }
  return name;
}

void Coordinator::write_sidecar(const std::string &camera, const eunomia::Sidecar &record) {
  // On this stack write_sidecar = push the env files (transport serializes the coordinator-owned
  // subset; discardd materializes the on-card JSON). The device adapter owns the telnet push.
  if (auto *dev = device(camera)) {
    dev->write_sidecar(record);
  }
}

std::vector<std::string> Coordinator::detect_drop() {
  // L2-ONLY presence (HARD RULE 1): never an OSC poll. A camera in the fleet but absent at L2
  // dropped.
  const std::vector<std::string> present = deps_.presence->present();
  std::vector<std::string> dropped;
  for (const auto &entry : fleet_) {
    if (!contains(present, entry.first)) {
      dropped.push_back(entry.first);
    }
  }
  return dropped;
}

void Coordinator::flush_telemetry() {
  // Drain the queued god's-view events in the idle gap (single-radio). Best-effort; the durable
  // ordinal-log backup is unaffected (it is the fail-safe, not this opportunistic uplink).
  if (deps_.telemetry != nullptr) {
    for (const auto &line : pending_) {
      deps_.telemetry->send(line);
    }
  }
  pending_.clear();
}

bool Coordinator::stop(const std::string &reason) {
  if (sm_.offer(Input::Stop) != Action::BeginStop) {
    return false; // STOP valid only from recording
  }
  // Fire BOTH stops first (avoids the stop-stagger artifact, CONTRACT §1.7), then finalize per cam.
  for (const auto &entry : fleet_) {
    if (entry.second != nullptr) {
      entry.second->stop();
    }
  }
  take_.stop_reason = reason;
  take_.stopped_unix = deps_.clock->unix_seconds_frac();
  for (const auto &entry : fleet_) {
    read_clip_filename(entry.first); // recovers the clip name + sets recording_suspect on absence
  }
  queue_event(pending_, "take_stop", take_, fleet_.size());
  sm_.on_stopped(); // stopping → idle
  return true;
}

void Coordinator::mark_archive() {
  // DESCARTAR = void+keep: a soft discard. The footage is KEPT on-card; ingest routes archive==1 to
  // the archive bucket. stop_reason stays WHY-it-ended; archive is the discard flag (§2.2).
  take_.archive = 1;
}

eunomia::Sidecar Coordinator::assemble_current_sidecar(const CameraInfo &cam) const {
  return assemble_sidecar(assignment_, take_, cam);
}

} // namespace eunomia::core
