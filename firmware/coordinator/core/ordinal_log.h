// firmware/coordinator/core/ — the fob-side ordinal-join backup (CONTRACT §1.7), now DURABLE.
//
// Independently of the on-card sidecars, the fob keeps a tiny append-at-START log —
// `episode_ordinal` + fob NTP wallclock + kit/fob/session/episode ids, a few bytes each. It is the
// fail-safe pairing when a sidecar write fails ENTIRELY: the Nth fob-START matches the Nth camera
// episode, and a count mismatch routes to needs-review rather than mislabeling. It MUST live on the
// fob, not the card (a backup sharing the card's failure mode is no backup). This is the fob half
// of the two-ordinal redundancy (CONTRACT §3.6) and is NET-NEW vs discardd (camera-side NAND only).
//
// F5: the log is now DURABLE-to-flash (a battery swap, 4-5×/day, no longer wipes the fob half) and
// BOUNDED — Victor's heap-death lesson: an unbounded /episodes.jsonl fragments the heap until OSC
// mallocs fail. We bound it WITHOUT a rewrite/whole-file read: a two-segment ping-pong (see
// SegmentedEpisodeLog). The DURABLE STORAGE is a transport seam (LittleFS on-target, a string fake
// off-target) so core/ stays hardware-free; the ordinal-counter (episode.h DurableOrdinal, NVS) is
// a DISTINCT structure and keeps its counter-first "never reuse" invariant unchanged.
#ifndef EUNOMIA_COORDINATOR_CORE_ORDINAL_LOG_H
#define EUNOMIA_COORDINATOR_CORE_ORDINAL_LOG_H

#include <cstddef>
#include <cstdint>
#include <string>

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

// The compact JSONL line written to the durable log. Schema (fob-internal, NOT a contract type —
// consumed by ingest's order-join): {"o":ordinal,"t":wallclock_unix,"k":kit_id,"f":fob_id,
// "s":fob_session_id,"e":episode_id}. Compact keys keep more of the ~2-day window in the small
// LittleFS partition (FLAG-I). Pure + testable.
std::string serialize_ordinal_entry(const OrdinalLogEntry &e);

// The durable sink core/ writes one line per committed START to. Implemented in transport/hw over
// LittleFS (the real fob) and by a string fake off-target — core/ never touches the filesystem.
class EpisodeLogStore {
public:
  virtual ~EpisodeLogStore() = default;
  // Append one already-serialized line (best-effort; a failed write must NOT abort the take — the
  // card episode_id is the primary join, OQ-1). Implementations bound themselves.
  virtual void append(const std::string &jsonl_line) = 0;
  // Total bytes currently retained on the durable medium (the `log_bytes` health metric).
  virtual std::size_t bytes() const = 0;
};

// One bounded storage segment: a file on LittleFS on-target, a std::string off-target. `append`
// writes the line PLUS a trailing newline; `clear` truncates it to empty; `size` is the byte count.
class LogSegment {
public:
  virtual ~LogSegment() = default;
  virtual void append(const std::string &line) = 0; // writes line + '\n'
  virtual void clear() = 0;                         // truncate to empty
  virtual std::size_t size() const = 0;
};

// A bounded durable log built from TWO ping-pong segments — bounded WITHOUT a rewrite or a
// whole-file read (the fragmentation-safe alternative to single-file rotation on a tiny FS). Always
// retains ≥ one full segment; max storage = 2·seg_bytes. When the active segment would overflow, it
// switches to the other (older) segment and clears it — an O(1), crash-safe truncate (no temp
// file). On recovery the active segment is the SMALLER one (it grows from empty after each switch).
// This is pure logic over the LogSegment seam, so the rotation is unit-tested off-target.
class SegmentedEpisodeLog : public EpisodeLogStore {
public:
  SegmentedEpisodeLog(LogSegment &a, LogSegment &b, std::size_t seg_bytes);

  // Pick the active segment after a (re)boot: the smaller of the two (recovery, see header note).
  void begin();

  void append(const std::string &jsonl_line) override;
  std::size_t bytes() const override;

private:
  LogSegment *seg_[2];
  std::size_t seg_bytes_;
  int active_ = 0;
};

} // namespace eunomia::core

#endif // EUNOMIA_COORDINATOR_CORE_ORDINAL_LOG_H
