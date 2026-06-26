// firmware/coordinator/core/ — the low-heap watchdog floor (pure, off-target-testable).
//
// Victor's #1 production failure was heap FRAGMENTATION: an unbounded /episodes.jsonl chewed the
// heap until an OSC/WiFi malloc for a contiguous buffer failed mid-START → cams:0 / kick while WiFi
// stayed up, surviving a power-cycle. We add the watchdog BY CONSTRUCTION (he added it reactively).
//
// The predictor is the LARGEST CONTIGUOUS FREE BLOCK, not total free — total free can look healthy
// while the largest block is too small for the next malloc. transport/hw reads the real ESP heap
// (ESP.getMaxAllocHeap()) and enforces the floor at the pre-START chokepoint (refuse + signal the
// operator — better than the silent wedge; STOP is never gated). The DECISION lives here as a pure
// function so the refuse-path is unit-testable without a rig (the one-machine rule).
#ifndef EUNOMIA_COORDINATOR_CORE_HEAP_HEALTH_H
#define EUNOMIA_COORDINATOR_CORE_HEAP_HEALTH_H

#include <cstddef>

namespace eunomia::core {

// Floors on the largest contiguous free block. BENCH-TUNE on the take-volume soak: conservative
// placeholders, well below Victor's observed ~214 KB flat free. kHeapFloorBytes refuses a START;
// kHeapWarnBytes only logs (so degradation is visible before it bites).
inline constexpr std::size_t kHeapFloorBytes = 32 * 1024;
inline constexpr std::size_t kHeapWarnBytes = 64 * 1024;

// True when the largest contiguous free block is at/above the refuse-START floor.
inline bool heap_ok(std::size_t largest_free_block) {
  return largest_free_block >= kHeapFloorBytes;
}

} // namespace eunomia::core

#endif // EUNOMIA_COORDINATOR_CORE_HEAP_HEALTH_H
