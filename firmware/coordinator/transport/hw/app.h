// firmware/coordinator/transport/hw/ — the headless app glue (on-target only).
//
// Constructs the Coordinator with the real seams + the X3 fleet, runs the core-0 discovery worker +
// the core-1 input loop (BOOT button + serial), and serializes the OSC/telnet burst under wifiLock
// (THE TWO HARD RULES live here at the radio level). This is the entry the Arduino src/main.cpp
// calls under `#if defined(ARDUINO)`; ui/ (F3) renders on top of the same coordinator without
// changing it.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_HW_APP_H
#define EUNOMIA_COORDINATOR_TRANSPORT_HW_APP_H

namespace eunomia::transport {

void app_setup();
void app_loop();

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_HW_APP_H
