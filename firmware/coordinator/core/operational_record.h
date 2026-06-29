// firmware/coordinator/core/ — operational-record serialization (F9).
//
// Structured JSONL records emitted to the durable episode log alongside the F5 ordinal-join
// entries. Each record carries a "T" type discriminator: "O" = ordinal (F5, now explicit), "E" =
// episode lifecycle, "S" = session lifecycle, "A" = station/task assignment. The ingest pipeline
// parses these into S1's operational_event table. Old F5 entries without a "T" field are implicitly
// "O" (backward-compat). All serialize functions return a single JSONL line (no trailing newline —
// EpisodeLogStore::append adds it). Pure + off-target testable.
#ifndef EUNOMIA_COORDINATOR_CORE_OPERATIONAL_RECORD_H
#define EUNOMIA_COORDINATOR_CORE_OPERATIONAL_RECORD_H

#include <cstdint>
#include <string>

#include "sidecar_assembly.h"

namespace eunomia::core {

struct TakeContext; // forward (defined in sidecar_assembly.h)

std::string serialize_episode_started(const Assignment &a, const TakeContext &t);

std::string serialize_episode_stopped(const TakeContext &t, const std::string &kit_id);

std::string serialize_episode_discarded(const TakeContext &t, const std::string &kit_id);

std::string serialize_session_signin(const Assignment &a, const std::string &session_id,
                                     std::int64_t wallclock);

std::string serialize_station_assignment(const Assignment &a, std::int64_t wallclock,
                                         const std::string &session_id);

} // namespace eunomia::core

#endif // EUNOMIA_COORDINATOR_CORE_OPERATIONAL_RECORD_H
