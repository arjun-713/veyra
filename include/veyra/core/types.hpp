#pragma once
#include <cstdint>
#include <cmath>
#include <functional>
#include <stdexcept>

namespace veyra::core {

inline void validate_level(int level) {
  if (level < 0 || level > 3) {
    throw std::invalid_argument("map level must be in [0,3]");
  }
}

// World-aligned dyadic cell id. resolution(l) = 0.05 * 2^l meters.
struct CellId {
  int level = 0;  // 0=L0/5cm .. 3=L3/40cm
  int32_t ix = 0;
  int32_t iy = 0;

  constexpr bool operator==(const CellId &) const = default;
  constexpr CellId parent() const {
    if (level >= 3) return *this;
    const auto floor_half = [](int32_t value) constexpr {
      return value >= 0 || value % 2 == 0 ? value / 2 : value / 2 - 1;
    };
    return {level + 1, floor_half(ix), floor_half(iy)};
  }
};

struct CellIdHash {
  std::size_t operator()(const CellId &id) const noexcept {
    std::size_t h = std::hash<int>{}(id.level);
    h ^= std::hash<std::int32_t>{}(id.ix) + 0x9e3779b9U + (h << 6U) + (h >> 2U);
    h ^= std::hash<std::int32_t>{}(id.iy) + 0x9e3779b9U + (h << 6U) + (h >> 2U);
    return h;
  }
};

inline double resolution_m(int level) {
  validate_level(level);
  return 0.05 * static_cast<double>(1ULL << static_cast<unsigned>(level));
}

}  // namespace veyra::core
