# `contracts/interfaces/` — the hardware seams

**Filled in Run 0b.** The hardware swap-points as explicit interface definitions, so a board/camera
swap is a new implementation of the same port and nothing upstream changes:

- **CoordinatorPort** — mint the episode id, trigger both cameras serialized, read back the clip
  filename, write the sidecar, detect a camera drop, flush telemetry. (The fob does NOT arm per take.)
- **CaptureDevicePort** — start, stop, read-back-filename, get-state, set-profile, write-sidecar.

Firmware implements a port; this is *why* a hardware swap is cheap. Authoritative description:
`docs/MODULE_MAP.md` (`contracts/interfaces/`) + `docs/CONTRACT.md`.
