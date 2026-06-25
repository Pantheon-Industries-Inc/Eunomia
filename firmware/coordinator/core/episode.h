// firmware/coordinator/core/ — episode identity + the durable fob ordinal.
//
//  * mint_uuid_v4   — the episode_id pairing key (CONTRACT §7 / C-9): a UUIDv4 written identically
//  to
//                     both arms, the ONLY join key. Pure given the injected Rng.
//  * make_display_id— the DERIVED human handle <YYYYMMDD>_<operator>_<station>_<NNNNNN> (warn,
//                     never-a-key, §2.2). Date is computed from the fob wallclock by pure integer
//                     civil-calendar math (no <ctime>, no platform call) so it is fully testable.
//  * DurableOrdinal — the fob `episode_ordinal` (the LABEL-join source, distinct from the
//  camera-side
//                     NAND `global_episode_seq`). Persisted to flash BEFORE the in-RAM counter
//                     advances (SPEC §1.8) so a crash/swap can never lose OR reuse a number.
#ifndef EUNOMIA_COORDINATOR_CORE_EPISODE_H
#define EUNOMIA_COORDINATOR_CORE_EPISODE_H

#include <cstdint>
#include <string>

#include "seams.h"

namespace eunomia::core {

// A fresh RFC-4122 version-4 UUID, lower-case, 8-4-4-4-12. The episode_id pairing key.
std::string mint_uuid_v4(Rng &rng);

// The derived display handle <YYYYMMDD>_<operator_id>_<station_id>_<NNNNNN> (ordinal zero-padded to
// 6). `unix_seconds` is the fob wallclock; the date is computed in UTC.
std::string make_display_id(std::int64_t unix_seconds, const std::string &operator_id,
                            const std::string &station_id, std::int64_t ordinal);

// UTC calendar date for an epoch-seconds value (pure integer math; exposed for testing/display).
void ymd_from_unix(std::int64_t unix_seconds, int &year, int &month, int &day);

// The durable, monotonic fob episode ordinal. Persist-before-advance: a number is never lost OR
// reused across a crash/battery swap (the fob backup half of the two-ordinal model, CONTRACT §3.6).
class DurableOrdinal {
public:
  DurableOrdinal(PersistentStore &store, std::string key);

  // The last issued ordinal (0 = none issued yet / fresh counter).
  std::int64_t current() const { return current_; }

  // Persist the NEXT value durably, THEN advance the in-RAM counter and return it. Returns 0 (the
  // unknown sentinel — discardd's bump_episode_seq contract) if the durable write failed: the
  // counter does NOT advance in RAM, so a flash failure never burns an ordinal.
  std::int64_t advance();

private:
  PersistentStore &store_;
  std::string key_;
  std::int64_t current_ = 0;
};

} // namespace eunomia::core

#endif // EUNOMIA_COORDINATOR_CORE_EPISODE_H
