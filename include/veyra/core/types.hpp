#pragma once
#include <cstdint>

namespace veyra::core {

// World-aligned dyadic cell id. resolution(l) = 0.05 * 2^l meters.
struct CellId {
  int level = 0;  // 0=L0/5cm .. 3=L3/40cm
  int32_t ix = 0;
  int32_t iy = 0;
};

constexpr double resolution_m(int level) { return 0.05 * (1 << level); }

}  // namespace veyra::core
