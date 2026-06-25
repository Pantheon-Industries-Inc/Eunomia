// firmware/coordinator/ui/ — the CYD resistive touch (XPT2046) read + the debounce/hysteresis
// latch. Arduino/TFT-coupled, so the WHOLE module is behind PANTHEON_HAS_TFT (the headless
// env:esp32 build compiles this to nothing and still links — Victor's pattern). Adapted
// verbatim-in-spirit from the vendored main.cpp (xptRead/touchRaw/touchScreenX/Y + the
// kPressHi/kReleaseLo/kRelSamples latch). (Run F3; the UI half of SPEC §1.8 — the core spam-safety
// is the guarantee underneath.)
#ifndef EUNOMIA_COORDINATOR_UI_TOUCH_H
#define EUNOMIA_COORDINATOR_UI_TOUCH_H

#ifdef PANTHEON_HAS_TFT

#include <cstdint>

namespace eunomia::ui::touch {

// Init the XPT2046 on its own VSPI bus (separate from the TFT's HSPI). Call once from begin().
void begin();

// Poll the panel once per loop tick. Returns true EXACTLY ONCE per physical press — a debounced
// rising edge — with the calibrated screen coordinate in *sx/*sy. Carries Victor's hysteresis +
// release-latch (the "single tap registers as double" fix): fire only above kPressHi, and re-arm
// only after pressure stays below the LOWER kReleaseLo for kRelSamples consecutive samples. A
// mid-press pressure dip can no longer fake a finger-lift, so one press = one action. A stray
// re-tap can never inject a toggle — and even if the debounce were defeated, core's
// TriggerStateMachine never double-fires (the F1 guarantee this must not regress).
bool poll(std::uint32_t now_ms, int *sx, int *sy);

// True while the panel is under finger contact (pressure above the contact threshold), updated by
// the last poll(). Used to defer background radio windows so touch stays responsive.
bool contact();

} // namespace eunomia::ui::touch

#endif // PANTHEON_HAS_TFT

#endif // EUNOMIA_COORDINATOR_UI_TOUCH_H
