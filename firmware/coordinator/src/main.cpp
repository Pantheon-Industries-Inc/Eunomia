// Run 0a placeholder shell. No coordinator logic yet — the trigger state machine,
// transport (WiFi-AP/OSC/telnet), and touchscreen UI land in a later run. This exists
// only so the build environments have an entry point. Guarded out of unit-test builds
// (Unity provides main there).
#ifndef PIO_UNIT_TESTING
#if defined(ARDUINO)
void setup() {}
void loop() {}
#else
int main() { return 0; }
#endif
#endif
