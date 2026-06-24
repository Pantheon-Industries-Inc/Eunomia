# `firmware/coordinator/ui/` — the touchscreen (swappable)

**Filled in a later run.** The display/touchscreen screens, swappable without touching `core/`:
full-screen color state, take counter, action toast, haptic/audio tick on a registered press. The CYD
(ESP32-2432S028R, 2.8" 320×240, resistive touch — which can miss presses, hence the instant
acknowledgement handled in `core/`).
