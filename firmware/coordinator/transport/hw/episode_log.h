// firmware/coordinator/transport/hw/ — the LittleFS-backed durable episode log (the real fob).
//
// The on-target implementation of core's EpisodeLogStore (CONTRACT §1.7 ordinal-join backup). It is
// the SWAPPABLE durable medium behind the pure two-segment ping-pong logic in core/ — board/FS
// changes live here, never in core/ or the contract. Two LittleFS files ping-pong so the log stays
// bounded without a rewrite or a whole-file read (Victor's fragmentation lesson: never reserve the
// backlog). core/ owns the rotation logic (SegmentedEpisodeLog); this owns only the file I/O.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_HW_EPISODE_LOG_H
#define EUNOMIA_COORDINATOR_TRANSPORT_HW_EPISODE_LOG_H

#include <cstddef>
#include <string>

#include "ordinal_log.h" // core: EpisodeLogStore, LogSegment, SegmentedEpisodeLog

namespace eunomia::transport {

// Per-segment byte cap. Sized to the CYD deployment board's `min_spiffs` FS partition (0x20000 =
// 128 KB) — FLAG-I. Two segments ping-pong, so max storage = 2·64 KB = 128 KB, using the full
// partition (LittleFS metadata lives in-band, not a separate reservation). F9 bumped from 48→64 KB:
// operational records (episode started/stopped, session sign-in, station assignment) roughly double
// the daily log volume; at ~150 bytes/record × ~530 records/day ≈ ~80 KB/day, the old 96 KB budget
// gave only ~1.2 days. 128 KB restores the ~2-day retention window the ordinal-join backup needs.
// On env:esp32 (default partition, 1.5 MB FS) the same code has far more headroom. If the 128 KB
// partition proves too tight (LittleFS GC), fall back to 48 KB and accept the shorter window.
inline constexpr std::size_t kEpisodeLogSegmentBytes = 64 * 1024;

// One LittleFS file acting as a core::LogSegment. Append is FILE_APPEND + flush (durable per line);
// clear truncates to empty (FILE_WRITE). `size_` is cached (no per-status FS hit) and recomputed at
// begin(). Best-effort: an open/short-write failure logs and leaves size_ unchanged (the take still
// proceeds — the card episode_id is the primary join, OQ-1).
class LittleFsSegment : public eunomia::core::LogSegment {
public:
  explicit LittleFsSegment(const char *path) : path_(path) {}

  void begin(); // size_ = existing file size (after LittleFS.begin()); call once in setup

  void append(const std::string &line) override;
  void clear() override;
  std::size_t size() const override { return size_; }

private:
  const char *path_;
  std::size_t size_ = 0;
};

// The two-file durable episode log. Owns both segments + the pure ping-pong logic; presents the
// core::EpisodeLogStore seam the Coordinator writes to.
class LittleFsEpisodeLog : public eunomia::core::EpisodeLogStore {
public:
  LittleFsEpisodeLog() : impl_(seg_a_, seg_b_, kEpisodeLogSegmentBytes) {}

  void begin(); // mount-dependent: call AFTER LittleFS.begin()

  void append(const std::string &jsonl_line) override { impl_.append(jsonl_line); }
  std::size_t bytes() const override { return impl_.bytes(); }

private:
  LittleFsSegment seg_a_{"/ep0.jsonl"};
  LittleFsSegment seg_b_{"/ep1.jsonl"};
  eunomia::core::SegmentedEpisodeLog impl_;
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_HW_EPISODE_LOG_H
