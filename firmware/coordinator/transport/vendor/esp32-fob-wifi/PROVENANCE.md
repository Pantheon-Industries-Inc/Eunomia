# Vendored: Victor's X3 WiFi-OSC fob source (reference baseline for Run F2)

This directory holds an **unmodified** copy of Victor's proven WiFi-OSC fob firmware. It is the
**reviewable baseline the F2 adaptation diffs against** — it is NOT compiled by any PlatformIO env
(`build_src_filter` excludes `transport/vendor/`). Do not edit these files; they are reference.

## Source (re-vendored 2026-06-24 from the UPDATED fob source — supersedes a38f5a9)

- **Repo:** `github.com/Pantheon-Industries-Inc/x3-capture-kit`
- **Paths copied (flattened into this dir):**
  - `ble_bridge/esp32-fob-wifi/src/main.cpp`  → `main.cpp`
  - `ble_bridge/esp32-fob-wifi/platformio.ini` → `platformio.ini`
- **Repo state vendored:** HEAD `f96b97a4a78dc07028e88953364bb504f065fb9d`
  (`f96b97a` — "setup-app: proven end-to-end on fresh hardware + day's fixes; field handoff",
  2026-06-24 20:39:36 -0700).
- **Commit that last modified `main.cpp`:** `6365643` ("fix two REVISA/join bugs found on the kit_55
  bench", 2026-06-24 17:34) — the fob deltas landed across `79e61d8` + `6365643`; `f96b97a` is a
  setup-app commit that did not touch the fob source.
- **Firmware version string:** `3.8.3-fast-guard` (`#define FOB_FW_VERSION` at `main.cpp:187`) —
  unchanged from a38f5a9 (Victor bumps fixes under the same version string).
- **Vendored by:** Run F2 (gh-authenticated as `Mzcassim`); clone lives in the gitignored
  `.context/x3-capture-kit/` scratch dir (the whole clone is NOT committed).

## md5 of the copied files (verified equal to the originals at clone time)

| file            | md5                                | size                  |
|-----------------|------------------------------------|-----------------------|
| `main.cpp`      | `60f433227fefc145b12ddde21961d927` | 3269 lines            |
| `platformio.ini`| `87acc2e09a3f36fa81c5d0a4ddd6e4ab` | 136 lines             |

## Supersedes a38f5a9 — the delta is bounded (ground-truth diff-checked)

The first F2 vendoring took `a38f5a9` (2026-06-23, fw 3.8.3-fast-guard, md5 `df6468…`). Victor then
shipped his 2026-06-24 fixes to `main`, so F2 re-vendored from the current source. `a38f5a9` is a
linear **ancestor** of `f96b97a` (not divergent), and `git diff a38f5a9..f96b97a` over the two files
touches ONLY four bounded areas (diff-checked, no surprise sprawl):

1. **`apChannel`** — `{1,6,11}` → `{1,6,6}`. ch11 dropped: the ESP32 SoftAP reports up on ch11 but no
   client can associate (kit_56, 2026-06-24); the `kit_num % 3 == 2` slot now maps to ch6.
2. **`camCardCheckAll`** — `nOk == nTot` → `nOk >= kMinCams`. A battery-pulled cam lingers as a GHOST
   station in the AP table ~18h (`kApInactiveSec`) with a dead IP; the old all-must-pass check threw a
   false "REVISA SD" until power-cycle (kit_57). The lesson for our L2 presence: gate on *required cams
   present*, not *exactly N stations*.
3. **`lockToConnectedCams`** — now does a ONE-SHOT `/osc/info` per cam at lock time (serialized under
   `wifiLock`, both cams idle — depot action, NOT background OSC) to learn the real serial, fixing the
   empty-allowlist bug. This is what makes the depot-provisioned MAC→side binding (plan OQ-2 option B)
   viable.
4. **`platformio.ini`** — `upload_speed` 460800 → 115200 (a field-flashing reliability tweak; does not
   affect the Eunomia build, which never flashes in CI).

These ARE the three deltas plan OQ-9 flagged (plus the flashing tweak), now landed in Victor's source —
so OQ-9's re-derivation fallback is moot; F2 adapts the current `{1,6,6}` / `/osc/info`-at-lock /
required-cams-present behaviors directly. Read the CODE, not the docs: the fw version string is
unchanged across the fixes, so the version alone does not tell you which behavior you have — the commit
does.
