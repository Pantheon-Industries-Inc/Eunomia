#include "episode_log.h"

#include <Arduino.h>
#include <LittleFS.h>

namespace eunomia::transport {

void LittleFsSegment::begin() {
  File f = LittleFS.open(path_, FILE_READ);
  size_ = f ? static_cast<std::size_t>(f.size()) : 0;
  if (f) {
    f.close();
  }
}

void LittleFsSegment::append(const std::string &line) {
  File f = LittleFS.open(path_, FILE_APPEND);
  if (!f) {
    Serial.printf("[eplog] append open failed: %s\n", path_);
    return; // best-effort — the card episode_id is the primary join (OQ-1)
  }
  std::size_t wrote = f.print(line.c_str());
  wrote += f.print('\n');
  f.flush();
  f.close();
  if (wrote < line.size() + 1) {
    Serial.println("[eplog] SHORT WRITE (fs full?)");
    return; // do not count a partial write
  }
  size_ += line.size() + 1;
}

void LittleFsSegment::clear() {
  File f = LittleFS.open(path_, FILE_WRITE); // FILE_WRITE truncates to empty
  if (f) {
    f.close();
  }
  size_ = 0;
}

void LittleFsEpisodeLog::begin() {
  seg_a_.begin();
  seg_b_.begin();
  impl_.begin(); // pick the active segment from the recovered sizes (survives a battery swap)
}

} // namespace eunomia::transport
