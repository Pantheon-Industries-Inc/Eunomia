# `firmware/camera-image/` — the camera-image build tool

**Filled in a later run.** A reproducible **packaging** of a stock Insta360 binary + the on-camera
agent that holds capture mode and writes the per-clip sidecar. NOT firmware we author. Core + CLI
today, callable by the provisioning console later. **Checksum-verified** — the packaged binary is
verified against a recorded checksum before it can ship.

Run 0a provides the **checksum-gate stub** (`checksum_gate.py`) — a no-op that passes (no binary to
verify yet), wired into `make gates` / CI so the gate slot exists and flips to blocking when the
image lands.
