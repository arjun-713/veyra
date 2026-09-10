#pragma once
#include "veyra/core/types.hpp"
#include "veyra/map/tile_grid.hpp"

namespace veyra::map {

// Splits an active cell into its four children one level finer. The parent is
// removed; the children become active. Returns false and changes nothing when
// the preconditions do not hold -- a refused split is a normal outcome, not an
// error, so this neither throws nor asserts on its input.
bool split(TileGrid& grid, core::CellId parent);

}  // namespace veyra::map
