#include "coordinator.h"

#include <utility>

#include "operational_record.h"

namespace eunomia::core {

namespace {
constexpr char kOrdinalKey[] = "fob_episode_ordinal";
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
      ordinal_(*deps.store, kOrdinalKey) {}

void Coordinator::set_assignment(const Assignment &a) { assignment_ = a; }

void Coordinator::set_confirmer(const std::string &side, StartConfirmable *confirmer) {
  confirmers_[side] = confirmer;
}

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

void Coordinator::abort_fire(const std::vector<std::string> &cameras,
                             const std::vector<std::string> &present) {
  // Stop every cam we just fired — Victor's camStopAll("error") on a short start, so no one-sided
  // clip is left rolling. Best-effort + fire-and-forget; no ordinal/take side effects here.
  for (const auto &cam : cameras) {
    if (contains(present, cam)) {
      if (auto *dev = device(cam)) {
        dev->stop();
      }
    }
  }
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

  // 3) Build the take with the PROSPECTIVE ordinal (current + 1, NOT yet committed). start() pushes
  //    current_assignment.env projected from take() (OQ-1), so the take's episode_id / bimanual /
  //    ordinal MUST be populated BEFORE the fire — but the durable ordinal is advanced only AFTER
  //    the fire confirms (FIRE-THEN-COMMIT, mirroring Victor's camStartAll→logStart order). A
  //    failed fire therefore NEVER advances the ordinal: nothing to roll back, no skip/reuse, no
  //    orphaned durable-log line (SPEC §1.8 / the F5 durable-log coordination).
  if (pending_episode_id_.empty()) {
    mint_episode_id();
  }
  const std::int64_t prospective = ordinal_.current() + 1;
  take_ = TakeContext{};
  take_.episode_id = pending_episode_id_;
  take_.bimanual_episode_id = pending_bimanual_id_;
  take_.episode_ordinal = prospective;
  take_.started_unix = deps_.clock->unix_seconds_frac();
  take_.display_id = make_display_id(deps_.clock->unix_seconds(), assignment_.operator_id,
                                     assignment_.station_id, prospective);

  // 4) Fire the present cameras, serialized (the wifiLock serialization is transport's, F2), and
  //    CONFIRM each fire via the startCapture connect-ack (the StartConfirmable side-channel — the
  //    contract port's start() is void). A side with no registered confirmer falls back to the void
  //    start() and is counted as started (the F1 behaviour for adapters/tests that don't confirm).
  sm_.begin_firing(); // arming → starting (the ~3 s pipeline re-init window)
  std::size_t started = 0;
  for (const auto &cam : cameras) {
    if (!contains(present, cam)) {
      continue;
    }
    auto it = confirmers_.find(cam);
    if (it != confirmers_.end() && it->second != nullptr) {
      if (it->second->start_confirmed()) { // connect-ack (NOT a body read; HARD RULE 2)
        ++started;
      }
    } else if (auto *dev = device(cam)) {
      dev->start(); // startCapture directly — no per-take arm (HARD RULE 2); no ack channel
      ++started;
    }
  }

  // 5) Fire-confirm rollback: not enough cams actually started. Stop any that did (no one-sided
  // clip
  //    left rolling) and refuse the take with NO ordinal advance. recording_suspect stays the
  //    STOP-time backstop; this is the loud press-time primary.
  if (started < required_cameras_) {
    abort_fire(cameras, present);
    sm_.on_start_aborted();
    take_ = TakeContext{};
    last_outcome_ = GateOutcome::StartFailed;
    return false;
  }

  // 6) COMMIT. Durable-before-advance: persist the ordinal now that the fire is confirmed. A flash
  //    failure returns 0 (the unknown sentinel) and does NOT commit — roll back the fire too, never
  //    burn/reuse an ordinal (SPEC §1.8).
  const std::int64_t ord = ordinal_.advance();
  if (ord <= 0) {
    abort_fire(cameras, present);
    sm_.on_start_aborted();
    take_ = TakeContext{};
    last_outcome_ = GateOutcome::StartFailed;
    return false;
  }
  take_.episode_ordinal = ord; // == prospective under the single-threaded wifi-lock

  // The fob-side ordinal-join backup (the §1.7 fail-safe; lives on the fob, not the card) — now
  // DURABLE (F5). Written here, AFTER the fire confirmed (step 4/5) and the ordinal committed: an
  // F6 StartFailed rollback returns before this point, so a rolled-back ordinal never leaves a
  // durable line. Best-effort — a failed durable write must NOT abort the take (the card episode_id
  // is the primary join, OQ-1). Counter-first is preserved (advance() already persisted the NVS
  // counter); our lines carry the ABSOLUTE ordinal, so a missing line is a benign gap, not Victor's
  // positional cascade (so strict log-before-bump is unnecessary — F5 §4).
  if (deps_.episode_log != nullptr) {
    OrdinalLogEntry e;
    e.ordinal = ord;
    e.wallclock_unix = deps_.clock->unix_seconds();
    e.kit_id = assignment_.kit_id;
    e.fob_id = assignment_.fob_id;
    e.fob_session_id = assignment_.fob_session_id;
    e.episode_id = take_.episode_id;
    deps_.episode_log->append(serialize_ordinal_entry(e));
    deps_.episode_log->append(serialize_episode_started(assignment_, take_));
  }

  pending_episode_id_.clear();
  pending_bimanual_id_.clear();
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
  // No-op (F5): the god's-view event queue (pending_/queue_event) was a DEAD, unbounded-within-a-
  // shift growth path feeding a cut uplink (DisabledUplink, OQ-4) — deleted. The CoordinatorPort
  // method stays (removing it is a contract change, out of F5 scope); the real opportunistic-uplink
  // drain is F7's, over the (not-yet-built) idle/boot channel. The durable §1.7 backup is the
  // fail-safe, written in trigger() — not this path.
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
  if (deps_.episode_log != nullptr) {
    deps_.episode_log->append(serialize_episode_stopped(take_, assignment_.kit_id));
  }
  sm_.on_stopped(); // stopping → idle
  return true;
}

void Coordinator::mark_archive() {
  // DESCARTAR = void+keep: a soft discard. The footage is KEPT on-card; ingest routes archive==1 to
  // the archive bucket. stop_reason stays WHY-it-ended; archive is the discard flag (§2.2).
  take_.archive = 1;
  if (deps_.episode_log != nullptr) {
    deps_.episode_log->append(serialize_episode_discarded(take_, assignment_.kit_id));
  }
}

eunomia::Sidecar Coordinator::assemble_current_sidecar(const CameraInfo &cam) const {
  return assemble_sidecar(assignment_, take_, cam);
}

} // namespace eunomia::core
