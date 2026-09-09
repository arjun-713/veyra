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

// Cells per meter at `level` — the reciprocal of resolution_m, written as
// 20.0 scaled by a power of two so it stays exact in IEEE-754. Indexing is
// expressed as x * cells_per_m rather than x / resolution_m so that the L0
// index and every coarser index differ only by a power-of-two scaling, which
// rounds identically.
constexpr double cells_per_m(int level) { return 20.0 / (1 << level); }

constexpr bool operator==(CellId a, CellId b) {
  return a.level == b.level && a.ix == b.ix && a.iy == b.iy;
}

}  // namespace veyra::core
