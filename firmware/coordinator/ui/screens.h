// firmware/coordinator/ui/ — the CYD screen renderers + glyphs + hit-test geometry.
// Arduino/TFT_eSPI- coupled, so the WHOLE module is behind PANTHEON_HAS_TFT (the headless env:esp32
// build compiles it to nothing). Adapted verbatim-in-spirit from the vendored main.cpp SCREEN_*
// renderers, drawPromptBand, the glyphs, confirmSplash/callSplash — RE-POINTED at render_state
// tokens (no g_anyRec/startGate/ g_connCount locals). This module DRAWS what flow/render_state
// decide; it owns no capture logic. Geometry (layout constants + the hit-tests) lives ONLY here so
// render and touch dispatch always agree. (Run F3; SPEC §1.8.)
#ifndef EUNOMIA_COORDINATOR_UI_SCREENS_H
#define EUNOMIA_COORDINATOR_UI_SCREENS_H

#ifdef PANTHEON_HAS_TFT

#include <cstddef>
#include <cstdint>

#include "render_state.h" // MainButton / CamLight

namespace eunomia::ui::screens {

// What the MAIN screen renders this frame (assembled by flow from core + the ui-owned counter).
struct MainView {
  MainButton button;   // the GRABAR/DETENER/ESPERA treatment (render_state)
  CamLight cam;        // the GO/NO-GO header light
  std::size_t present; // for the "CAMS n/2" readout
  std::size_t required;
  const char *station; // header "MESA <station>"
  const char *prompt;  // the bilingual task prompt (marquees if long)
};

// Where a tap landed on MAIN (Victor's y-band routing).
enum class MainHit : std::uint8_t { None, Header, Toggle, Call };

void begin(); // tft.init + rotation + backlight; sets ready()
bool ready();

// Renderers. Drawn only on change (flow drives the redraw); the prompt band marquees via
// tick_prompt.
void render_main(const MainView &v);
void render_confirm(std::uint32_t take_n);
void render_confirm_id(const char *name, const char *kit);
void render_provision(const char *num, const char *err); // REGISTRO (kit number)
void render_sign_in(const char *num, const char *err);   // operator sign-in (operator number)
void render_mesa(const char *num, const char *err);      // table number

// Advance + redraw ONLY the prompt marquee band (no full redraw / no flicker). Call each loop on
// MAIN.
void tick_prompt(std::uint32_t now_ms);

// Blocking confirmation flashes (the ack for the already-stopped take / the call). ~1.1 s hold.
void confirm_splash_save();    // green GUARDADO
void confirm_splash_discard(); // red DESCARTADO
void confirm_splash_error(const char *sub);
void call_splash(); // yellow LLAMANDO (LLAMAR feedback)

// ---- hit-tests (geometry lives here; flow routes by these) ----
MainHit hit_main(int sx, int sy);
bool keypad_hit(int sx, int sy, int &row, int &col); // edge-tolerant 3x4 keypad
const char *keypad_label(int row, int col);          // "1".."9","0","DEL","ENTRAR"
bool keypad_is_del(int row, int col);
bool keypad_is_enter(int row, int col);
bool hit_back(int sx, int sy);          // the MESA ATRAS top-right zone
bool confirm_is_save(int sy);           // CONFIRM: top half = GUARDAR, bottom = DESCARTAR
bool confirm_id_in_band(int sy);        // CONFIRM_ID: only react in the button band
bool confirm_id_is_yes(int sx, int sy); // CONFIRM_ID: left = SI, right = NO

} // namespace eunomia::ui::screens

#endif // PANTHEON_HAS_TFT

#endif // EUNOMIA_COORDINATOR_UI_SCREENS_H
