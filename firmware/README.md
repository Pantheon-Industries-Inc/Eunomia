# `firmware/` — the kit (C++ / PlatformIO, ESP32)

**Single responsibility:** the embedded code that runs on the capture kit — the fob coordinator and
the camera-image packaging.

**Dependency rule:** depends only on `contracts/` (via the generated C++ header
`contracts/_generated/cpp/`). A console never imports firmware; firmware never imports a service.
`firmware/` is outside the Python import-linter — its boundary is the include structure + the
cross-language conformance gate.

**Adapt-not-rebuild:** change the board → new `transport/` (+ maybe `ui/`); change the camera → a new
`CaptureDevicePort` implementation. `core/` and the contracts are untouched.

## Layout

| Path | Responsibility |
|---|---|
| `coordinator/core/` | the trigger state machine, episode/ordinal logic, sidecar assembly, phantom-press guarantee, touch-ack UI state. **Pure, off-target testable, hardware-free.** Implements `CoordinatorPort`. |
| `coordinator/transport/` | WiFi-AP hosting + serialized OSC client + telnet client. The hardware-coupled, **swappable** layer (the SoftAP load-test hedge). |
| `coordinator/ui/` | the touchscreen screens. Swappable without touching `core/`. |
| `camera-image/` | reproducible **packaging** of a stock binary + the on-camera agent. Checksum-verified. Not firmware we author. |

The on-target build is `pio run -e esp32`; the **off-target host tests** are `pio test -e native`
(the one-machine rule — the core must be testable with no rig). See `coordinator/platformio.ini`.

> Run 0a is the build shell only: the codegen proof's off-target test, the two environments, and the
> per-submodule READMEs. No coordinator logic yet.
