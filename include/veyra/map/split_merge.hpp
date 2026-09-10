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

}  // namespace veyra::map
