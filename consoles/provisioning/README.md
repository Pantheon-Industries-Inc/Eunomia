# `consoles/provisioning/`

**Filled in its own run.** Bench flash/assign UI; calls the `camera-image` core; captures the
provisioning facts (serial, MAC, AP/WiFi, IP scheme, kit/side, fob id, firmware versions, calibration
ref) against the unit (R-2); runs the per-kit ship-gate (isolation locked + identity set + firmware
match) before a kit can ship.
