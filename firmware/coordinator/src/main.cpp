// Coordinator firmware entry point.
//
// Run F2: on the ESP32 (env:esp32 / env:cyd) this delegates to the headless transport app, which
// wires the pure core/ to the real WiFi/OSC/telnet/NVS via the transport/ seams. The whole thing is
// guarded out of the host unit-test build (Unity provides main there), and the Arduino include only
// happens under ARDUINO so the native (non-test) build stays a trivial main().
#ifndef PIO_UNIT_TESTING
#if defined(ARDUINO)
#include "app.h" // transport/hw (on the esp32/cyd include path)
void setup() { eunomia::transport::app_setup(); }
void loop() { eunomia::transport::app_loop(); }
#else
int main() { return 0; }
#endif
#endif
