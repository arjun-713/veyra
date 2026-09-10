#pragma once
#include "veyra/core/types.hpp"
#include "veyra/map/tile_grid.hpp"

namespace veyra::map {

// Coarsest level the ladder defines: resolution_m(l) = 0.05 * 2^l, so
// 0 = 5 cm through 3 = 40 cm. Level 0 is the floor -- there is nothing finer
// to split into.
inline constexpr int kMaxLevel = 3;

// Splits an active cell into its four children one level finer. The parent is
// removed; the children become active. Returns false and changes nothing when
// the preconditions do not hold -- a refused split is a normal outcome, not an
// error, so this neither throws nor asserts on its input.
bool split(TileGrid& grid, core::CellId parent);

// Collapses a cell's four children back into it, one level coarser. The
// children are removed; the parent becomes active. Returns false and changes
// nothing when the preconditions do not hold.
bool merge(TileGrid& grid, core::CellId parent);

// The active leaf covering a world point, if any.
struct LeafHit {
  bool found = false;
  core::CellId id{};
};

// Finds the single active cell whose extent contains (x, y), searching finest
// level first. Invariant 1 says at most one exists; this returns it without
// exposing the grid's storage, so the search stays on the public API.
LeafHit activeLeafCovering(const TileGrid& grid, double x, double y);

}  // namespace veyra::map
