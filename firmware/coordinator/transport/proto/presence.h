// firmware/coordinator/transport/proto/ — L2 camera presence + the side↔IP registry (HARD RULE 1).
//
// Presence is tracked at L2 ONLY — the AP DHCP/station table (esp_netif_get_sta_list, Victor's
// `discoverCams`) — NEVER an OSC poll (the X3 cherokee crashes on background OSC). The station
// table yields MAC+IP, not serials (serials need OSC), so the depot-provisioned MAC→side allowlist
// (OQ-2, entry 0 = left, 1 = right) maps each connected MAC to a side. The CameraRegistry holds the
// dynamic side→IP binding the X3 device adapter fires against, and answers core's
// PresenceSource::present(). The hw layer (transport/hw/) supplies the raw station snapshot;
// everything here is pure + tested.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_PROTO_PRESENCE_H
#define EUNOMIA_COORDINATOR_TRANSPORT_PROTO_PRESENCE_H

#include <cstdint>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include "seams.h" // core's PresenceSource

namespace eunomia::transport {

// Staleness thresholds: a camera missing from the L2 snapshot for less than this is still
// considered present (absorbs momentary WiFi hiccups). The reconnect cycle is ~29s (camera-owned
// low-duty background scan); too-tight idle falsely strands a healthy cam offline for that long.
inline constexpr std::uint64_t kStalenessIdleMs = 3000;      // 3s — absorbs 4× the 700ms poll
inline constexpr std::uint64_t kStalenessRecordingMs = 6000; // 6s — drop-proof mid-take

// One AP station-table row. `ip` empty = associated but no DHCP lease yet (skip, as Victor does).
struct StationEntry {
  std::string mac; // lowercase colon form, e.g. "aa:bb:cc:dd:ee:ff"
  std::string ip;  // e.g. "192.168.42.2", or "" if no lease
};

// Maps a camera MAC → side handle ("left"/"right"). Built from the NVS allowlist (comma-joined,
// entry 0 = left, entry 1 = right — the depot pairs them in that order). MACs are matched
// case-insensitively. Empty allowlist = no mapping (every present cam is unbound → OQ-9: lockcams
// must populate the allowlist; until then presence yields no sides and GRABAR stays locked, which
// is the safe failure).
class MacSideMap {
public:
  MacSideMap() = default;
  static MacSideMap from_allowlist(const std::string &csv);
  std::string side_for(const std::string &mac) const; // "" if unmapped
  bool empty() const { return entries_.empty(); }
  std::size_t size() const { return entries_.size(); }

private:
  std::vector<std::pair<std::string, std::string>> entries_; // (lowercased mac, side)
};

// The dynamic side→IP binding, recomputed from each station snapshot. A side is "present" iff a
// mapped MAC has a DHCP lease (non-empty IP) in the latest snapshot.
//
// GHOST-STATION LESSON (Victor 2026-06-24, kit_57 battery swap): a battery-pulled cam lingers in
// the AP table ~18h (kApInactiveSec) as a ghost; an extra phantom STA (a stray Mac) can also
// appear. So presence is by SIDE, not station COUNT — an unmapped ghost is ignored entirely, and
// core's gate is "the REQUIRED cams (left AND right) are present", never "exactly N stations". A
// card-less or ghosted real cam is caught downstream by the STOP-time recording_suspect check (§2.2
// / F1 OQ-4), not by wedging the count. (Victor's matching fix moved camCardCheckAll from nOk==nTot
// to nOk>=kMinCams.)
class CameraRegistry {
public:
  void set_map(MacSideMap m) { map_ = std::move(m); }

  // Recompute side→{ip, present} from a fresh L2 snapshot. The overload accepting now_ms enables
  // the staleness window: a camera missing from the snapshot for less than staleness_ms is still
  // considered present. When now_ms == 0 (or the no-arg overload), staleness is disabled — a
  // missing camera is immediately absent (the pre-F7 behavior, preserved for tests + backward
  // compat).
  void update(const std::vector<StationEntry> &stations);
  void update(const std::vector<StationEntry> &stations, std::uint64_t now_ms);

  void set_staleness_ms(std::uint64_t ms) { staleness_ms_ = ms; }

  std::string ip_for(const std::string &side) const; // "" if not present
  bool is_present(const std::string &side) const;
  std::vector<std::string> present() const; // sides present, sorted for determinism

private:
  struct Slot {
    std::string ip;
    bool present = false;
    std::uint64_t last_seen_ms = 0;
  };
  MacSideMap map_;
  std::map<std::string, Slot> slots_; // side → slot
  std::uint64_t staleness_ms_ = 0;    // 0 = disabled (instant drop, pre-F7 behavior)
};

// core's PresenceSource backed by the registry (L2-only; no OSC, no socket).
class StationTablePresence : public eunomia::core::PresenceSource {
public:
  explicit StationTablePresence(CameraRegistry &reg) : reg_(reg) {}
  std::vector<std::string> present() override { return reg_.present(); }

private:
  CameraRegistry &reg_;
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_PROTO_PRESENCE_H
