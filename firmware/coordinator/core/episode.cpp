#include "episode.h"

#include <cstdio>
#include <utility>

namespace eunomia::core {

namespace {
constexpr char kHex[] = "0123456789abcdef";
} // namespace

std::string mint_uuid_v4(Rng &rng) {
  std::uint8_t b[16];
  rng.fill(b, sizeof b);
  b[6] = static_cast<std::uint8_t>((b[6] & 0x0F) | 0x40); // version 4
  b[8] = static_cast<std::uint8_t>((b[8] & 0x3F) | 0x80); // variant 10xx
  std::string out;
  out.reserve(36);
  for (int i = 0; i < 16; ++i) {
    if (i == 4 || i == 6 || i == 8 || i == 10) {
      out.push_back('-');
    }
    out.push_back(kHex[b[i] >> 4]);
    out.push_back(kHex[b[i] & 0x0F]);
  }
  return out;
}

// Howard Hinnant's days→civil algorithm (proleptic Gregorian, pure integer, no <ctime>).
void ymd_from_unix(std::int64_t unix_seconds, int &year, int &month, int &day) {
  std::int64_t z = unix_seconds / 86400; // days since 1970-01-01 (floor for unix_seconds >= 0)
  if (unix_seconds < 0 && unix_seconds % 86400 != 0) {
    --z;
  }
  z += 719468;
  const std::int64_t era = (z >= 0 ? z : z - 146096) / 146097;
  const std::int64_t doe = z - era * 146097;                                      // [0, 146096]
  const std::int64_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365; // [0, 399]
  const std::int64_t y = yoe + era * 400;
  const std::int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
  const std::int64_t mp = (5 * doy + 2) / 153;                      // [0, 11]
  day = static_cast<int>(doy - (153 * mp + 2) / 5 + 1);             // [1, 31]
  month = static_cast<int>(mp < 10 ? mp + 3 : mp - 9);              // [1, 12]
  year = static_cast<int>(y + (month <= 2 ? 1 : 0));
}

std::string make_display_id(std::int64_t unix_seconds, const std::string &operator_id,
                            const std::string &station_id, std::int64_t ordinal) {
  int y = 0;
  int m = 0;
  int d = 0;
  ymd_from_unix(unix_seconds, y, m, d);
  char date[9];
  std::snprintf(date, sizeof date, "%04d%02d%02d", y, m, d);
  char ord[7];
  std::snprintf(ord, sizeof ord, "%06lld", static_cast<long long>(ordinal));
  std::string out;
  out.reserve(8 + 1 + operator_id.size() + 1 + station_id.size() + 1 + 6);
  out.append(date);
  out.push_back('_');
  out.append(operator_id);
  out.push_back('_');
  out.append(station_id);
  out.push_back('_');
  out.append(ord);
  return out;
}

DurableOrdinal::DurableOrdinal(PersistentStore &store, std::string key)
    : store_(store), key_(std::move(key)) {
  current_ = store_.read_i64(key_, 0);
  if (current_ < 0) {
    current_ = 0;
  }
}

std::int64_t DurableOrdinal::advance() {
  const std::int64_t next = current_ + 1;
  if (!store_.write_i64(key_, next)) {
    // Durable write failed: fail loud, do NOT advance in RAM (never reuse/lose an ordinal).
    return 0;
  }
  current_ = next;
  return current_;
}

} // namespace eunomia::core
