#include "touch.h"

#ifdef PANTHEON_HAS_TFT

#include <Arduino.h>
#include <SPI.h>

namespace eunomia::ui::touch {
namespace {

// CYD resistive touch (XPT2046) on its OWN SPI bus, separate from the TFT (HSPI pins 12-15). Read
// it directly over VSPI — no library to version-mismatch. IRQ (GPIO36) goes LOW while touched.
// These pins are hardcoded here (in Victor's main.cpp, not his platformio.ini) — the TFT pins are
// build flags.
constexpr int kTClk = 25, kTMiso = 39, kTMosi = 32, kTCs = 33, kTIrq = 36;
SPIClass touch_spi(VSPI);

// Pressure-based detection (does NOT rely on PENIRQ, which on this CYD variant filtered out every
// tap). Z1 + (4095 - Z2) is the pressure; a real press makes it large. Threshold tuned from the
// [touchdbg] serial logs (vendored, 2026-06-17).
constexpr int kTouchZThresh = 1000;

// Debounce: FIRE only above kPressHi; re-arm only after pressure stays below the LOWER kReleaseLo
// for kRelSamples consecutive samples (a genuine lift). The hysteresis gap + the multi-sample
// release latch are what defeat the "single tap = double" noise bug on this panel.
constexpr int kPressHi = 220;
constexpr int kReleaseLo = 90;
constexpr int kRelSamples = 3;

bool g_contact = false;

std::uint16_t xpt_read(std::uint8_t cmd) {
  touch_spi.beginTransaction(SPISettings(2000000, MSBFIRST, SPI_MODE0));
  digitalWrite(kTCs, LOW);
  touch_spi.transfer(cmd);
  std::uint16_t hi = touch_spi.transfer(0x00);
  std::uint16_t lo = touch_spi.transfer(0x00);
  digitalWrite(kTCs, HIGH);
  touch_spi.endTransaction();
  return ((hi << 8) | lo) >> 3; // 12-bit sample
}

// Reads the XPT2046 Z1/Z2 pressure channels + averaged raw X/Y. Returns true above the contact
// threshold.
bool touch_raw(std::uint16_t &rx, std::uint16_t &ry, std::uint16_t &rz) {
  std::uint16_t z1 = xpt_read(0xB0);
  std::uint16_t z2 = xpt_read(0xC0);
  int z = static_cast<int>(z1) + (4095 - static_cast<int>(z2)); // higher = harder press
  if (z < 0) {
    z = 0;
  }
  rz = static_cast<std::uint16_t>(z);
  std::uint32_t sx = 0, sy = 0;
  for (int i = 0; i < 4; i++) {
    sx += xpt_read(0xD0);
    sy += xpt_read(0x90);
  }
  rx = static_cast<std::uint16_t>(sx / 4);
  ry = static_cast<std::uint16_t>(sy / 4);
  return z > kTouchZThresh;
}

// Calibrated raw->screen mapping (vendored 2026-06-17, corner taps). Axes are SWAPPED on this CYD:
// screen horizontal = raw Y channel, screen vertical = raw X channel; both non-inverted.
int screen_x(std::uint16_t ry) {
  long v = (static_cast<long>(ry) - 465) * 320 / 3075;
  return v < 0 ? 0 : (v > 319 ? 319 : static_cast<int>(v));
}
int screen_y(std::uint16_t rx) {
  long v = (static_cast<long>(rx) - 620) * 240 / 2660;
  return v < 0 ? 0 : (v > 239 ? 239 : static_cast<int>(v));
}

} // namespace

void begin() {
  pinMode(kTCs, OUTPUT);
  digitalWrite(kTCs, HIGH);
  pinMode(kTIrq, INPUT);
  touch_spi.begin(kTClk, kTMiso, kTMosi, kTCs);
}

bool poll(std::uint32_t now_ms, int *sx, int *sy) {
  static bool s_down = false;      // a press is in progress / not yet released
  static int s_rel_count = 0;      // consecutive below-release-threshold samples
  static std::uint32_t s_last = 0; // last fire time (the >200 ms inter-fire guard)
  std::uint16_t rx, ry, rz;
  touch_raw(rx, ry, rz);
  g_contact = (rz > kPressHi);
  // Re-arm ONLY on a debounced release (low threshold held for several samples).
  if (rz < kReleaseLo) {
    if (++s_rel_count >= kRelSamples) {
      s_down = false;
    }
  } else {
    s_rel_count = 0;
  }
  // RISING edge above the high threshold -> exactly one action per press.
  if (rz > kPressHi && !s_down && now_ms - s_last > 200) {
    s_down = true;
    s_last = now_ms;
    if (sx != nullptr) {
      *sx = screen_x(ry);
    }
    if (sy != nullptr) {
      *sy = screen_y(rx);
    }
    return true;
  }
  return false;
}

bool contact() { return g_contact; }

} // namespace eunomia::ui::touch

#endif // PANTHEON_HAS_TFT
