#include "ordinal_log.h"

namespace eunomia::core {

namespace {
const OrdinalLogEntry kEmpty{};
} // namespace

OrdinalLog::OrdinalLog(std::size_t capacity) : buf_(capacity == 0 ? 1 : capacity) {}

void OrdinalLog::append(const OrdinalLogEntry &entry) {
  const std::size_t cap = buf_.size();
  if (size_ < cap) {
    buf_[(head_ + size_) % cap] = entry;
    ++size_;
  } else {
    // Full: overwrite the oldest and advance the head (self-bounding ring).
    buf_[head_] = entry;
    head_ = (head_ + 1) % cap;
  }
}

const OrdinalLogEntry &OrdinalLog::at(std::size_t i) const {
  if (i >= size_) {
    return kEmpty;
  }
  return buf_[(head_ + i) % buf_.size()];
}

} // namespace eunomia::core
