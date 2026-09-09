#pragma once
#include <array>
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

constexpr bool operator!=(CellId a, CellId b) { return !(a == b); }

// Parent at level+1. Arithmetic right shift floors toward negative infinity;
// integer division truncates toward zero, which on the negative side groups
// the wrong cells together (-3 / 2 == -1 but -3 >> 1 == -2).
constexpr CellId parentOf(CellId c) {
  return CellId{c.level + 1, static_cast<int32_t>(c.ix >> 1), static_cast<int32_t>(c.iy >> 1)};
}

// The four cells at level-1 that tile `c`, ordered
// (x, y), (x+1, y), (x, y+1), (x+1, y+1).
constexpr std::array<CellId, 4> childrenOf(CellId c) {
  const int lvl = c.level - 1;
  const auto x0 = static_cast<int32_t>(c.ix * 2);
  const auto y0 = static_cast<int32_t>(c.iy * 2);
  const auto x1 = static_cast<int32_t>(x0 + 1);
  const auto y1 = static_cast<int32_t>(y0 + 1);
  return {CellId{lvl, x0, y0}, CellId{lvl, x1, y0}, CellId{lvl, x0, y1}, CellId{lvl, x1, y1}};
}

}  // namespace veyra::core
