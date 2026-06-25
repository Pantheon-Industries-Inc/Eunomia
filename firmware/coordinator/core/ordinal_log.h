// firmware/coordinator/core/ — the fob-side ordinal-join backup (CONTRACT §1.7).
//
// Independently of the on-card sidecars, the fob keeps a tiny append-at-START log —
// `episode_ordinal`
// + fob NTP wallclock + kit/fob/session/episode ids, a few bytes each. It is the fail-safe pairing
// when a sidecar write fails ENTIRELY: the Nth fob-START matches the Nth camera episode, and a
// count mismatch routes to needs-review rather than mislabeling. It MUST live on the fob, not the
// card (a backup sharing the card's failure mode is no backup), and it is a SELF-BOUNDING ring
// buffer — it keeps roughly the last ~2 days (≥2× the drain cadence), dropping the oldest, so an
// un-networked fob never grows without limit. This is NET-NEW vs discardd (which has only the
// camera-side NAND ordinal).
#ifndef EUNOMIA_COORDINATOR_CORE_ORDINAL_LOG_H
#define EUNOMIA_COORDINATOR_CORE_ORDINAL_LOG_H

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace eunomia::core {

// One append-at-START record. Keys ingest's order-join: de-dup on (kit_id, fob_session_id,
// ordinal).
struct OrdinalLogEntry {
  std::int64_t ordinal = 0;        // the fob episode_ordinal (label-join source)
  std::int64_t wallclock_unix = 0; // fob NTP wallclock at START (authoritative time)
  std::string kit_id;
  std::string fob_id;
  std::string fob_session_id; // random per fob boot — the fob-swap disambiguator
  std::string episode_id;     // the UUIDv4 pairing key
};

// A fixed-capacity ring buffer (the ~2-day self-bounding window). Append-only from the caller's
// view; drops the oldest entry once full.
class OrdinalLog {
public:
  explicit OrdinalLog(std::size_t capacity);

  void append(const OrdinalLogEntry &entry);

  std::size_t size() const { return size_; }
  std::size_t capacity() const { return buf_.size(); }

  // Entries oldest→newest (index 0 = oldest retained). Out-of-range returns a static empty entry.
  const OrdinalLogEntry &at(std::size_t i) const;

private:
  std::vector<OrdinalLogEntry> buf_;
  std::size_t head_ = 0; // index of the oldest entry
  std::size_t size_ = 0;
};

} // namespace eunomia::core

#endif // EUNOMIA_COORDINATOR_CORE_ORDINAL_LOG_H
