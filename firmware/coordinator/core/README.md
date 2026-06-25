# `firmware/coordinator/core/` — the trigger logic (pure, off-target testable)

The hardware-free heart of the fob coordinator, landed in **Run F1**. It implements the generated
`CoordinatorPort` (CONTRACT §1.6) and is tested with **no rig** via `pio test -e native` (the
one-machine rule).

## Dependency rule

`core/` depends ONLY on `contracts/_generated/cpp/` (the contract types) + its own injected seams
(`seams.h`). It contains **no platform calls** — the real OSC/telnet/SoftAP/NVS/RNG/clock live in
`transport/` (Run F2); the native tests drive fakes. A board/camera swap replaces `transport/`/`ui/`,
never `core/` (adapt-not-rebuild). Written to **ESP32 constraints** (no C++ exceptions, no RTTI,
heap-aware) — enforced by the `env:esp32` cross-build (`-fno-exceptions -fno-rtti`).

## What lives here

| File | Responsibility |
|---|---|
| `seams.h` | The injected interfaces: `Clock` (NTP wallclock), `Rng` (UUIDv4 bytes), `PersistentStore` (NVS), `PresenceSource` (L2 station table), `TelemetrySink` (opportunistic uplink). |
| `trigger_state_machine.{h,cpp}` | idle→arming→starting→recording→stopping. **Spam-safety:** START acted on ONLY from idle; STOP only from recording; further inputs dropped (SPEC §1.8 core layer). |
| `episode.{h,cpp}` | `mint_uuid_v4` (the episode_id pairing key, §7), `make_display_id` (the derived handle, pure calendar math), `DurableOrdinal` (the fob `episode_ordinal`, **persisted to flash BEFORE the counter advances** — never lose/reuse a number). |
| `ordinal_log.{h,cpp}` | The fob-side ordinal-join backup (CONTRACT §1.7): an append-at-START, self-bounding ring buffer (the ~2-day window). Net-new vs discardd. |
| `sidecar_assembly.{h,cpp}` | Assemble `eunomia-sidecar/v1` from the coordinator-owned fields (the contract surface) + the `current_assignment.env`/`current_stop.env` projections discardd consumes (OQ-2 option C). |
| `button_feedback.{h,cpp}` | `DelayedButton` — the instant-ack/working/lockout STATE for ALL delayed buttons (logic, not pixels; SPEC §1.8). `ui/` (F2) renders it. |
| `coordinator.{h,cpp}` | The `CoordinatorPort` implementation: ties the above to the seams + the `CaptureDevicePort` fleet. The phantom-press gate (`sent==2`) lives here. |

## The two guarantees (proven off-target — see `test/test_core/`)

1. **Spam-safety** — a START is valid only from `idle`; a burst of taps mid-sequence fires exactly once.
2. **Phantom-press gate** — a START commits only when BOTH cameras are present at L2 (`sent==2`);
   `0` present = phantom (dropped), `1` = one-sided (GRABAR locked). Presence is **L2-only** (the
   `PresenceSource`), never an OSC poll (HARD RULE 1).

## Boundary to Victor's stack

`core/` is **authored**, not adapted. THE TWO HARD RULES are enforced in `transport/` (F2, adapted
from Victor's `esp32-fob-wifi` source); `core/` is built to not violate them. The on-card sidecar
stays discardd's job — `write_sidecar` on this stack = push the env projections; discardd materializes
the `pantheon-x3-sidecar/v2` JSON (untouched in F1; reconciled to v1 at ingest, joined by `episode_id`).
