#pragma once
#include <array>
#include <cmath>
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

// Axis-aligned world extent of a cell, in meters. A cell owns [min, max) on
// each axis: the lower edge belongs to this cell, the upper edge to the next.
struct CellExtent {
  double min_x = 0.0;
  double min_y = 0.0;
  double max_x = 0.0;
  double max_y = 0.0;
};

// Corners are divided by cells_per_m rather than multiplied by resolution_m so
// that they invert worldToKey exactly; the two forms are not bit-identical
// because 0.05 is not representable in binary.
constexpr CellExtent extentOf(CellId c) {
  const double n = cells_per_m(c.level);
  return CellExtent{c.ix / n, c.iy / n, (c.ix + 1) / n, (c.iy + 1) / n};
}

// XY -> cell id on the lattice, which is world-aligned and fixed in `odom`.
// Indexed once at L0 and shifted right to reach coarser levels, so a cell and
// its ancestors agree by construction instead of by per-level rounding.
inline CellId worldToKey(double x, double y, int level) {
  const auto ix0 = static_cast<int32_t>(std::floor(x * cells_per_m(0)));
  const auto iy0 = static_cast<int32_t>(std::floor(y * cells_per_m(0)));
  return CellId{level, static_cast<int32_t>(ix0 >> level), static_cast<int32_t>(iy0 >> level)};
}

// A tile is a square block of 2^tile_log2 cells at one level, world-aligned
// like the cells themselves. These helpers are index arithmetic only; no tile
// storage exists yet.
struct TileId {
  int level = 0;
  int32_t tx = 0;
  int32_t ty = 0;
};

constexpr bool operator==(TileId a, TileId b) {
  return a.level == b.level && a.tx == b.tx && a.ty == b.ty;
}

constexpr bool operator!=(TileId a, TileId b) { return !(a == b); }

// Tile containing `c`. Right shift for the same reason parentOf uses it:
// truncating division would put cells left of the origin in the wrong tile.
constexpr TileId tileOf(CellId c, int tile_log2) {
  return TileId{c.level, static_cast<int32_t>(c.ix >> tile_log2),
                static_cast<int32_t>(c.iy >> tile_log2)};
}

// Index of `i` within its tile, always in [0, 2^tile_log2). Masking, not %:
// % is sign-preserving, so -1 % 16 == -1 would place a cell outside its tile.
constexpr int32_t localIndex(int32_t i, int tile_log2) {
  return static_cast<int32_t>(i & ((int32_t{1} << tile_log2) - 1));
}

}  // namespace veyra::core
