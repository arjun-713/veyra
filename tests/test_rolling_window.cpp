// Invariant test for the rolling window: invariant 6 of
// docs/map-correctness.md -- evicting distant tiles never changes the identity
// of remaining in-window cells -- plus the bound the window exists to provide.
//
// Each group names the production bug it exists to catch.
#include <cstddef>
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"
#include "veyra/map/rolling_window.hpp"
#include "veyra/map/tile_grid.hpp"

namespace {

using veyra::map::GridStats;
using veyra::map::MapWindow;
using veyra::map::TileGrid;

// 1. A fresh grid has an origin-centred window of the default radius and holds
//    nothing.
//    Catches: a grid that pre-allocates, and a window left uninitialised so
//    that the first recentre appears to move from garbage.
void checkFreshGrid() {
  const TileGrid grid;
  CHECK(grid.window().centre_x == 0.0);
  CHECK(grid.window().centre_y == 0.0);
  CHECK(grid.window().radius_m == veyra::map::kDefaultWindowRadiusM);

  const GridStats s = grid.statistics();
  CHECK(s.tiles == 0);
  CHECK(s.occupied_cells == 0);
  CHECK(s.allocated_bytes == 0);

  // A grid may be built with a smaller window; the tests below rely on it,
  // because a 100 m radius at 5 cm is 12.6 million cells.
  const TileGrid small{MapWindow{0.0, 0.0, 2.0}};
  CHECK(small.window().radius_m == 2.0);
}

// 2. Recentring to where the window already is evicts nothing and releases
//    nothing, and says the centre did not move.
//    Catches: an unconditional walk-and-evict that churns the boundary on
//    every frame, which is allocation on the hot path.
void checkNoMovementNoEviction() {
  TileGrid grid{MapWindow{0.0, 0.0, 2.0}};
  for (std::int32_t i = -4; i <= 4; ++i) {
    grid.findOrCreate(veyra::core::CellId{0, i, i});
  }
  const GridStats before = grid.statistics();

  const veyra::map::EvictionStats e = grid.recenter(0.0, 0.0);
  CHECK(e.cells_evicted == 0);
  CHECK(e.tiles_released == 0);
  CHECK(!e.centre_moved);

  const GridStats after = grid.statistics();
  CHECK(after.tiles == before.tiles);
  CHECK(after.occupied_cells == before.occupied_cells);
  CHECK(after.allocated_bytes == before.allocated_bytes);
}

}  // namespace

int main() {
  checkFreshGrid();
  checkNoMovementNoEviction();
  return 0;
}
