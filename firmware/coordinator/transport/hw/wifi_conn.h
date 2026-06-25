// firmware/coordinator/transport/hw/ — the Arduino bindings for the transport seams (on-target
// only).
//
// hw/ is the impure half of transport: it implements the proto/ seams (Conn/Delayer) + core's seams
// (Clock/Rng/PersistentStore/PresenceSource/TelemetrySink) against the REAL ESP32/WiFi/NVS, and
// wires the headless app. It is compiled ONLY by env:esp32 / env:cyd (Arduino framework); the
// native test never sees it. core/ stays pure; seams.h + the proto seams are the boundary.
#ifndef EUNOMIA_COORDINATOR_TRANSPORT_HW_WIFI_CONN_H
#define EUNOMIA_COORDINATOR_TRANSPORT_HW_WIFI_CONN_H

#include <Arduino.h>
#include <WiFiClient.h>

#include "conn.h"

namespace eunomia::transport {

// proto::Conn over a real WiFiClient (one fresh client per request, as Victor's
// oscSendNoWait/telnet).
class WifiConn : public Conn {
public:
  bool connect(const std::string &host, std::uint16_t port, std::uint32_t timeout_ms) override {
    return client_.connect(host.c_str(), port, static_cast<int32_t>(timeout_ms)) == 1;
  }
  bool connected() override { return client_.connected(); }
  int available() override { return client_.available(); }
  int read() override { return client_.read(); }
  std::size_t write(const std::uint8_t *data, std::size_t n) override {
    return client_.write(data, n);
  }
  void flush() override { client_.flush(); }
  void stop() override { client_.stop(); }

private:
  WiFiClient client_;
};

// proto::Delayer over Arduino delay() — the real OSC grace (~120 ms) + settle gap (~150 ms).
class ArduinoDelayer : public Delayer {
public:
  void delay_ms(std::uint32_t ms) override { delay(ms); }
};

} // namespace eunomia::transport

#endif // EUNOMIA_COORDINATOR_TRANSPORT_HW_WIFI_CONN_H
