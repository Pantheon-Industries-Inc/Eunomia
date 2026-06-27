#include "screens.h"

#ifdef PANTHEON_HAS_TFT

#include <Arduino.h>
#include <SPI.h>
#include <TFT_eSPI.h>
#include <cstdio>

namespace eunomia::ui::screens {
namespace {

TFT_eSPI tft;
bool g_ready = false;

// ---- layout geometry (the single source of truth for render AND hit-test) ----
constexpr int TOG_Y0 = 68, TOG_Y1 = 150;  // big GRABAR/DETENER toggle
constexpr int ROW_Y0 = 158, ROW_Y1 = 233; // bottom row: full-width LLAMAR
constexpr int MID = (TOG_Y0 + TOG_Y1) / 2;
constexpr int PROMPT_Y = 44;   // text baseline-ish y for the prompt band
constexpr int PROMPT_VIS = 34; // approx chars visible across the band at 9pt
// 3x4 numeric keypad: cols x={8,114,220} (width 98, gap 8); rows y={86,124,162,200} (height 34).
constexpr int KP_X0 = 8, KP_DX = 106, KP_BW = 98;
constexpr int KP_Y0 = 86, KP_DY = 38, KP_BH = 34;
const char *const KP_LABEL[4][3] = {
    {"1", "2", "3"}, {"4", "5", "6"}, {"7", "8", "9"}, {"DEL", "0", "ENTRAR"}};

// Marquee state for the bilingual task prompt (cached so tick_prompt can redraw only the band).
String g_prompt;
int g_prompt_scroll = 0;
std::uint32_t g_prompt_scroll_ms = 0;

uint16_t c_green() { return tft.color565(0, 150, 70); }
uint16_t c_red() { return tft.color565(205, 35, 35); }
uint16_t c_call() { return tft.color565(245, 205, 0); } // yellow == LLAMAR

// Bilingual rolling prompt: "English | Espanol" (also " / "); English white, Spanish amber
// trailing. Long prompts MARQUEE (the loop advances g_prompt_scroll). Adapted from
// drawPromptBand().
void draw_prompt_band() {
  tft.fillRect(0, PROMPT_Y - 4, 320, (TOG_Y0 - 2) - (PROMPT_Y - 4), TFT_BLACK);
  if (!g_prompt.length()) {
    return;
  }
  tft.setTextDatum(TL_DATUM);
  tft.setFreeFont(&FreeSansBold9pt7b);
  const uint16_t C_EN = TFT_WHITE;
  const uint16_t C_ES = tft.color565(255, 190, 40); // amber = Spanish
  String en = g_prompt, es = "";
  int sep = g_prompt.indexOf('|');
  int seplen = 1;
  if (sep < 0) {
    sep = g_prompt.indexOf(" / ");
    seplen = 3;
  }
  if (sep >= 0) {
    en = g_prompt.substring(0, sep);
    en.trim();
    es = g_prompt.substring(sep + seplen);
    es.trim();
  }
  const String gap = "     ";
  String track = en;
  int esStart = -1, esEnd = -1;
  if (es.length()) {
    esStart = track.length() + gap.length();
    track += gap + es;
    esEnd = track.length();
  }
  bool scroll = (static_cast<int>(track.length()) > PROMPT_VIS);
  if (scroll) {
    track += gap; // wrap spacer so the loop reads cleanly
  }
  int n = track.length();
  int start = scroll ? (g_prompt_scroll % n) : 0;
  int len = scroll ? PROMPT_VIS : n;
  auto colorAt = [&](int idx) -> uint16_t {
    return (esStart >= 0 && idx >= esStart && idx < esEnd) ? C_ES : C_EN;
  };
  int x = 6, i = 0;
  while (i < len) {
    uint16_t c = colorAt((start + i) % n);
    String run;
    while (i < len) {
      int j = (start + i) % n;
      if (colorAt(j) != c) {
        break;
      }
      run += track[j];
      i++;
    }
    tft.setTextColor(c, TFT_BLACK);
    tft.drawString(run, x, PROMPT_Y);
    x += tft.textWidth(run);
  }
}

// Small padlock glyph on the LOCKED toggle (recording disabled until both cams connect).
void draw_lock_glyph(int cx, int cy, uint16_t fg, uint16_t bg) {
  tft.drawRoundRect(cx - 9, cy - 18, 18, 20, 9, fg);
  tft.drawRoundRect(cx - 8, cy - 18, 16, 20, 8, fg);
  tft.fillRoundRect(cx - 14, cy - 6, 28, 22, 4, fg);
  tft.fillCircle(cx, cy + 3, 3, bg);
  tft.fillRect(cx - 1, cy + 3, 3, 7, bg);
}

// Telephone handset on the LLAMAR button / CALL splash.
void draw_phone_icon(int cx, int cy, uint16_t color, uint16_t bg) {
  const float w = 5.0f;
  tft.fillSmoothCircle(cx + 4, cy + 10, 4, color, bg);
  tft.fillSmoothCircle(cx + 4, cy - 10, 4, color, bg);
  tft.drawWideLine(cx + 1, cy + 10, cx - 6, cy + 4, w, color, bg);
  tft.drawWideLine(cx - 6, cy + 4, cx - 6, cy - 4, w, color, bg);
  tft.drawWideLine(cx - 6, cy - 4, cx + 1, cy - 10, w, color, bg);
}

// Shared numeric-entry body (REGISTRO + sign-in + MESA). Adapted from renderNumEntry().
void render_num_entry(const char *title, const char *hint, const String &num, const char *err,
                      bool showBack) {
  const uint16_t C_GREEN = c_green();
  const uint16_t C_AMBER = tft.color565(155, 100, 20);
  const uint16_t C_KEY = tft.color565(55, 55, 65);
  const uint16_t C_BLUE = tft.color565(45, 95, 170);
  const uint16_t C_BOX = tft.color565(90, 90, 90);
  tft.fillScreen(TFT_BLACK);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setFreeFont(&FreeSansBold12pt7b);
  tft.drawString(title, 8, 6);
  if (showBack) {
    tft.fillRoundRect(212, 4, 104, 40, 6, C_BLUE); // big top-right ATRAS target
    tft.setTextColor(TFT_WHITE, C_BLUE);
    tft.setTextDatum(MC_DATUM);
    tft.setFreeFont(&FreeSansBold12pt7b);
    tft.drawString("ATRAS", 264, 24);
    tft.setTextDatum(TL_DATUM);
  }
  if (err != nullptr && err[0] != '\0') { // line 2: error (red) or hint (grey)
    tft.setTextColor(tft.color565(230, 70, 70), TFT_BLACK);
    String e = err;
    if (e.length() > 34) {
      e = e.substring(0, 32) + "..";
    }
    tft.drawString(e, 8, 38, 2);
  } else {
    tft.setTextColor(tft.color565(205, 205, 205), TFT_BLACK);
    tft.drawString(hint, 8, 38, 2);
  }
  tft.drawRoundRect(8, 52, 180, 32, 6, C_BOX); // number field (clears the ATRAS hit zone x>=196)
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setFreeFont(&FreeSansBold18pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.drawString(num.length() ? num : String("_"), 98, 68);
  tft.setTextDatum(MC_DATUM);
  for (int r = 0; r < 4; r++) {
    int y = KP_Y0 + r * KP_DY;
    for (int c = 0; c < 3; c++) {
      int x = KP_X0 + c * KP_DX;
      const char *lab = KP_LABEL[r][c];
      bool isDel = (r == 3 && c == 0), isEnter = (r == 3 && c == 2);
      uint16_t bg = isEnter ? C_GREEN : (isDel ? C_AMBER : C_KEY);
      tft.fillRoundRect(x, y, KP_BW, KP_BH, 6, bg);
      tft.setTextColor(TFT_WHITE, bg);
      if (isDel || isEnter) {
        tft.drawString(lab, x + KP_BW / 2, y + KP_BH / 2, 2);
      } else {
        tft.setFreeFont(&FreeSansBold18pt7b);
        tft.drawString(lab, x + KP_BW / 2, y + KP_BH / 2 - 2);
      }
    }
  }
  tft.setTextDatum(TL_DATUM);
}

} // namespace

void begin() {
  tft.init();
  tft.setRotation(1); // landscape 320x240
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.drawString("EUNOMIA FOB", 8, 6, 4);
  tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft.drawString("starting...", 8, 60, 4);
  g_ready = true;
}

bool ready() { return g_ready; }

void render_main(const MainView &v) {
  if (!g_ready) {
    return;
  }
  const uint16_t C_GREEN = c_green();
  const uint16_t C_RED = c_red();
  const uint16_t C_CALL = c_call();
  uint16_t camCol = (v.cam == CamLight::Go) ? C_GREEN : C_RED;
  g_prompt = (v.prompt != nullptr) ? String(v.prompt) : String("");
  tft.fillScreen(TFT_BLACK);
  // header: MESA (double-tap to re-pick the table) + the GO/NO-GO CAMS light
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setFreeFont(&FreeSansBold12pt7b);
  char hdr[28];
  std::snprintf(hdr, sizeof(hdr), "MESA %s", (v.station && v.station[0]) ? v.station : "--");
  tft.drawString(hdr, 6, 8);
  tft.setTextDatum(TR_DATUM);
  tft.setTextColor(camCol, TFT_BLACK);
  tft.setFreeFont(&FreeSansBold9pt7b);
  char cb[16];
  std::snprintf(cb, sizeof(cb), "CAMS %u/%u", static_cast<unsigned>(v.present),
                static_cast<unsigned>(v.required));
  tft.drawString(cb, 314, 6);
  // F7: clock indicator — loud-not-silent. HH:MM when synced, red "NO CLOCK" when not.
  tft.setTextDatum(TC_DATUM);
  if (v.time_set && v.clock_hhmm != nullptr) {
    tft.setTextColor(tft.color565(180, 180, 180), TFT_BLACK);
    tft.drawString(v.clock_hhmm, 160, 10, 2);
  } else {
    tft.setTextColor(C_RED, TFT_BLACK);
    tft.drawString("NO CLOCK", 160, 10, 2);
  }
  tft.setTextDatum(TR_DATUM);
  tft.setTextColor(tft.color565(205, 205, 205), TFT_BLACK);
  tft.drawString("toca 2x=cambiar mesa", 314, 26, 2);
  draw_prompt_band();
  // big GRABAR/DETENER/ESPERA toggle. The treatment is render_state's MainButton (FLAG-B): a
  // ui-owned DelayedButton in flight => Working (lockout); recording => DETENER; idle+cams =>
  // GRABAR; idle+no cams => locked ESPERA. The touch handler ignores a tap in any locked/working
  // state, so the operator physically cannot start a phantom/one-sided take or race a finalizing
  // one.
  bool locked = (v.button == MainButton::WaitingCams || v.button == MainButton::Working);
  bool rec = (v.button == MainButton::Recording);
  uint16_t bg = (rec || locked) ? C_RED : C_GREEN;
  tft.fillRoundRect(8, TOG_Y0, 304, TOG_Y1 - TOG_Y0, 10, bg);
  tft.setTextColor(TFT_WHITE, bg);
  tft.setTextDatum(MC_DATUM);
  if (locked) {
    const char *es = "Esperando 2 camaras";
    const char *en = "waiting for both cams";
    if (v.button == MainButton::Working) {
      es = "Trabajando...";
      en = "working, espera";
    }
    tft.setFreeFont(&FreeSansBold18pt7b);
    tft.drawString("ESPERA", 160, MID - 12);
    draw_lock_glyph(52, MID - 12, TFT_WHITE, bg);
    draw_lock_glyph(268, MID - 12, TFT_WHITE, bg);
    tft.setFreeFont(&FreeSansBold9pt7b);
    tft.drawString(es, 160, MID + 12);
    tft.drawString(en, 160, MID + 30, 2);
  } else {
    tft.setFreeFont(&FreeSansBold18pt7b);
    tft.drawString(rec ? "DETENER" : "GRABAR", 160, MID - 6);
    tft.setFreeFont(&FreeSansBold9pt7b);
    if (rec && v.present < v.required) {
      // Recording continues (the operator must be able to stop) but a cam fell off mid-take — say
      // so.
      tft.setTextColor(tft.color565(255, 220, 120), bg);
      tft.drawString("!  1/2 - una camara cayo", 160, MID + 24);
      tft.setTextColor(TFT_WHITE, bg);
    } else if (!rec && v.start_failed) {
      // F6 fire-confirm rollback: GRABAR is live (cams present), but the last START did NOT confirm
      // on both cams (or the durable commit failed) and was rolled back — NO take committed.
      // Loud-not-silent: tell the operator it FAILED (vs a mis-press) so they retry. Brief; flow
      // clears it after a couple seconds.
      tft.setTextColor(tft.color565(255, 220, 120), bg);
      tft.drawString("FALLO - reintenta / retry", 160, MID + 24);
      tft.setTextColor(TFT_WHITE, bg);
    } else {
      tft.drawString(rec ? "Stop recording" : "Start recording", 160, MID + 24);
    }
  }
  // bottom row: full-width LLAMAR (call lead). KEPT in F3 (FLAG-E): the splash + a local help-event
  // log; the dashboard "bell" POST is deferred to the god's-view uplink (SPEC §1.10).
  tft.fillRoundRect(8, ROW_Y0, 304, ROW_Y1 - ROW_Y0, 8, C_CALL);
  tft.setTextColor(TFT_BLACK, C_CALL);
  tft.setTextDatum(MC_DATUM);
  tft.setFreeFont(&FreeSansBold12pt7b);
  tft.drawString("LLAMAR", 160, ROW_Y0 + 24);
  tft.drawString("Call team lead", 160, ROW_Y0 + 52, 2);
  draw_phone_icon(64, ROW_Y0 + 30, TFT_BLACK, C_CALL);
  draw_phone_icon(256, ROW_Y0 + 30, TFT_BLACK, C_CALL);
  tft.setTextDatum(TL_DATUM);
}

void render_confirm(std::uint32_t take_n) {
  if (!g_ready) {
    return;
  }
  const uint16_t C_GREEN = c_green();
  const uint16_t C_RED = c_red();
  tft.fillScreen(TFT_BLACK);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setFreeFont(&FreeSansBold12pt7b);
  // Per-SESSION take number (resets on boot / table change) — NOT the lifetime NVS ordinal.
  char hdr[28];
  std::snprintf(hdr, sizeof(hdr), "TOMA #%u DETENIDA", static_cast<unsigned>(take_n));
  tft.drawString(hdr, 160, 22);
  tft.setTextColor(tft.color565(205, 205, 205), TFT_BLACK);
  tft.drawString("Take stopped - guardar o borrar?", 160, 48, 2);
  tft.fillRoundRect(8, 66, 304, 78, 10, C_GREEN); // GUARDAR (green, top) — the safe default
  tft.setTextColor(TFT_WHITE, C_GREEN);
  tft.setFreeFont(&FreeSansBold18pt7b);
  tft.drawString("GUARDAR", 160, 96);
  tft.setFreeFont(&FreeSansBold9pt7b);
  tft.drawString("Save take", 160, 126);
  tft.fillRoundRect(8, 152, 304, 80, 10, C_RED); // DESCARTAR (red, bottom)
  tft.setTextColor(TFT_WHITE, C_RED);
  tft.setFreeFont(&FreeSansBold18pt7b);
  tft.drawString("DESCARTAR", 160, 182);
  tft.setFreeFont(&FreeSansBold9pt7b);
  tft.drawString("Delete take", 160, 212);
  tft.setTextDatum(TL_DATUM);
}

void render_confirm_id(const char *name, const char *kit) {
  if (!g_ready) {
    return;
  }
  const uint16_t C_GREEN = c_green();
  const uint16_t C_RED = c_red();
  tft.fillScreen(TFT_BLACK);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setFreeFont(&FreeSansBold12pt7b);
  tft.drawString("CONFIRMA / Confirm", 160, 18);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setFreeFont(&FreeSansBold18pt7b);
  String nm = (name != nullptr) ? String(name) : String("");
  if (tft.textWidth(nm) > 300) {
    tft.setFreeFont(&FreeSansBold12pt7b);
  }
  tft.drawString(nm, 160, 64);
  tft.setTextColor(tft.color565(210, 210, 210), TFT_BLACK);
  char sub[40];
  std::snprintf(sub, sizeof(sub), "Kit %s  -  eres tu?", (kit != nullptr) ? kit : "");
  tft.drawString(sub, 160, 104, 2);
  tft.fillRoundRect(8, 138, 150, 94, 10, C_GREEN); // SI (green = yes, left)
  tft.setTextColor(TFT_WHITE, C_GREEN);
  tft.setFreeFont(&FreeSansBold18pt7b);
  tft.drawString("SI", 83, 172);
  tft.drawString("Soy yo", 83, 206, 2);
  tft.fillRoundRect(162, 138, 150, 94, 10, C_RED); // NO (red = no, right)
  tft.setTextColor(TFT_WHITE, C_RED);
  tft.setFreeFont(&FreeSansBold18pt7b);
  tft.drawString("NO", 237, 172);
  tft.drawString("Otro numero", 237, 206, 2);
  tft.setTextDatum(TL_DATUM);
}

void render_provision(const char *num, const char *err) {
  // REGISTRO is the root of setup: no ATRAS. Forward is ENTRAR -> sign-in.
  render_num_entry("REGISTRO", "Numero de kit / Kit number",
                   num != nullptr ? String(num) : String(), err, false);
}

void render_sign_in(const char *num, const char *err) {
  // Operator sign-in (OQ-1 A): type the operator number on the SAME keypad; ATRAS -> REGISTRO.
  render_num_entry("OPERADOR", "Tu numero / Your operator #",
                   num != nullptr ? String(num) : String(), err, true);
}

void render_mesa(const char *num, const char *err) {
  render_num_entry("ELIGE MESA", "Mesa / Table number", num != nullptr ? String(num) : String(),
                   err, true);
}

void render_confirm_task(const char *station, const char *task_name_str, const char *prompt_str) {
  if (!g_ready) {
    return;
  }
  const uint16_t C_GREEN = c_green();
  const uint16_t C_RED = c_red();
  tft.fillScreen(TFT_BLACK);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setFreeFont(&FreeSansBold12pt7b);
  char hdr[32];
  std::snprintf(hdr, sizeof(hdr), "MESA %s", (station != nullptr) ? station : "");
  tft.drawString(hdr, 160, 18);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setFreeFont(&FreeSansBold18pt7b);
  String tn = (task_name_str != nullptr) ? String(task_name_str) : String("");
  if (tft.textWidth(tn) > 300) {
    tft.setFreeFont(&FreeSansBold12pt7b);
  }
  tft.drawString(tn, 160, 56);
  tft.setTextColor(tft.color565(210, 210, 210), TFT_BLACK);
  String pr = (prompt_str != nullptr) ? String(prompt_str) : String("");
  if (pr.length() > 38) {
    pr = pr.substring(0, 36) + "..";
  }
  tft.drawString(pr, 160, 94, 2);
  tft.setTextColor(tft.color565(205, 205, 205), TFT_BLACK);
  tft.drawString("Es correcto? / Is this correct?", 160, 118, 2);
  tft.fillRoundRect(8, 138, 150, 94, 10, C_GREEN);
  tft.setTextColor(TFT_WHITE, C_GREEN);
  tft.setFreeFont(&FreeSansBold18pt7b);
  tft.drawString("SI", 83, 172);
  tft.drawString("Confirm", 83, 206, 2);
  tft.fillRoundRect(162, 138, 150, 94, 10, C_RED);
  tft.setTextColor(TFT_WHITE, C_RED);
  tft.setFreeFont(&FreeSansBold18pt7b);
  tft.drawString("NO", 237, 172);
  tft.drawString("Otra mesa", 237, 206, 2);
  tft.setTextDatum(TL_DATUM);
}

void tick_prompt(std::uint32_t now_ms) {
  if (!g_ready) {
    return;
  }
  if (static_cast<int>(g_prompt.length()) > PROMPT_VIS && now_ms - g_prompt_scroll_ms > 240) {
    g_prompt_scroll_ms = now_ms;
    g_prompt_scroll++;
    draw_prompt_band();
  }
}

namespace {
// Full-screen confirmation flash + ~1.1 s hold (the ack for the already-stopped take / the call).
// The blocking hold is safe (nothing is mid-record) and doubles as a release guard so lifting off
// can't bleed into a MAIN tap.
void splash(uint16_t bg, const char *big, const char *sub) {
  if (!g_ready) {
    return;
  }
  tft.fillScreen(bg);
  tft.setTextColor(TFT_WHITE, bg);
  tft.setTextDatum(MC_DATUM);
  tft.setFreeFont(&FreeSansBold18pt7b);
  tft.drawString(big, 160, 108);
  tft.setFreeFont(&FreeSansBold9pt7b);
  tft.drawString(sub, 160, 148);
  tft.setTextDatum(TL_DATUM);
  delay(1100);
}
} // namespace

void confirm_splash_save() { splash(c_green(), "GUARDADO", "Saved"); }
void confirm_splash_discard() { splash(c_red(), "DESCARTADO", "Archivado"); }
void confirm_splash_error(const char *sub) { splash(c_red(), "ERROR", sub); }

void call_splash() {
  if (!g_ready) {
    return;
  }
  const uint16_t C = c_call();
  tft.fillScreen(C);
  tft.setTextColor(TFT_BLACK, C);
  tft.setTextDatum(MC_DATUM);
  tft.setFreeFont(&FreeSansBold18pt7b);
  tft.drawString("LLAMANDO", 160, 110);
  tft.setFreeFont(&FreeSansBold9pt7b);
  tft.drawString("Llamando al lider", 160, 152);
  draw_phone_icon(40, 110, TFT_BLACK, C);
  draw_phone_icon(280, 110, TFT_BLACK, C);
  tft.setTextDatum(TL_DATUM);
  delay(1100);
}

// ---- hit-tests ----
MainHit hit_main(int sx, int sy) {
  (void)sx;
  if (sy < TOG_Y0) {
    return MainHit::Header;
  }
  if (sy <= TOG_Y1) {
    return MainHit::Toggle;
  }
  if (sy >= ROW_Y0) {
    return MainHit::Call;
  }
  return MainHit::None;
}

bool keypad_hit(int sx, int sy, int &row, int &col) {
  if (sy < KP_Y0) {
    return false; // header area, not a key
  }
  int r = (sy - KP_Y0) / KP_DY;
  if (r < 0) {
    r = 0;
  }
  if (r > 3) {
    r = 3;
  }
  int c = (sx - KP_X0) / KP_DX;
  if (c < 0) {
    c = 0;
  }
  if (c > 2) {
    c = 2;
  }
  row = r;
  col = c;
  return true;
}

const char *keypad_label(int row, int col) {
  if (row < 0 || row > 3 || col < 0 || col > 2) {
    return "";
  }
  return KP_LABEL[row][col];
}
bool keypad_is_del(int row, int col) { return row == 3 && col == 0; }
bool keypad_is_enter(int row, int col) { return row == 3 && col == 2; }

bool hit_back(int sx, int sy) {
  return sy < KP_Y0 && sx >= 196;
} // MESA/sign-in ATRAS top-right zone
bool confirm_is_save(int sy) { return sy < 148; }
bool confirm_id_in_band(int sy) { return sy >= 138; }
bool confirm_id_is_yes(int sx, int sy) {
  (void)sy;
  return sx < 160;
}

} // namespace eunomia::ui::screens

#endif // PANTHEON_HAS_TFT
