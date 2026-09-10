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

// Fill a square block of cells, wider than any window used below.
void fillBlock(TileGrid& grid, std::int32_t half) {
  for (std::int32_t iy = -half; iy <= half; ++iy) {
    for (std::int32_t ix = -half; ix <= half; ++ix) {
      grid.findOrCreate(veyra::core::CellId{0, ix, iy});
    }
  }
}

// 3. THE invariant. After recenter returns, not one active cell lies outside
//    the window. Walked exhaustively, not sampled.
//    Catches: a recentre that moves the centre but skips the walk, an
//    eviction that stops early, and any off-by-one at the boundary.
void checkNoCellOutsideWindow() {
  TileGrid grid{MapWindow{0.0, 0.0, 1.5}};
  fillBlock(grid, 60);  // 121 x 121 cells = 6.05 m across
  const std::size_t before = grid.statistics().occupied_cells;
  CHECK(before == 121U * 121U);

  const veyra::map::EvictionStats e = grid.recenter(3.0, 0.0);
  CHECK(e.centre_moved);
  CHECK(e.cells_evicted > 0);

  std::size_t seen = 0;
  grid.forEachActiveLeaf([&](veyra::core::CellId id, const veyra::map::Cell&) {
    CHECK(veyra::map::inWindow(grid.window(), id));
    ++seen;
  });
  CHECK(seen > 0);
  CHECK(seen == grid.statistics().occupied_cells);
  CHECK(seen == before - e.cells_evicted);
}

// 4. Invariant 6: a cell that survives a recentre is untouched. Same id, same
//    world extent, same statistics, bit for bit. The lattice is fixed in odom
//    -- only the view moves.
//    Catches: any renumbering or re-keying of surviving cells, and statistics
//    reset or drifting during the walk.
void checkCoordinatePreservation() {
  TileGrid grid{MapWindow{0.0, 0.0, 1.5}};
  for (std::int32_t iy = -60; iy <= 60; ++iy) {
    for (std::int32_t ix = -60; ix <= 60; ++ix) {
      veyra::map::Cell& c = grid.findOrCreate(veyra::core::CellId{0, ix, iy});
      veyra::map::updateCell(c, 0.01 * static_cast<double>(ix) + 0.001 * static_cast<double>(iy));
      c.last_seen = static_cast<std::uint32_t>(ix * 1000 + iy);
      c.cls = static_cast<std::uint8_t>((ix + iy) & 0xFF);
    }
  }

  std::vector<veyra::core::CellId> ids;
  std::vector<veyra::map::Cell> cells;
  std::vector<veyra::core::CellExtent> extents;
  grid.forEachActiveLeaf([&](veyra::core::CellId id, const veyra::map::Cell& c) {
    ids.push_back(id);
    cells.push_back(c);
    extents.push_back(veyra::core::extentOf(id));
  });

  grid.recenter(2.0, 0.0);

  std::size_t survivors = 0;
  for (std::size_t i = 0; i < ids.size(); ++i) {
    const veyra::map::Cell* now = grid.find(ids[i]);
    if (now == nullptr) {
      continue;  // evicted, which group 3 already constrains
    }
    ++survivors;
    const veyra::core::CellExtent e = veyra::core::extentOf(ids[i]);
    CHECK(e.min_x == extents[i].min_x);
    CHECK(e.min_y == extents[i].min_y);
    CHECK(e.max_x == extents[i].max_x);
    CHECK(e.max_y == extents[i].max_y);
    CHECK(now->count == cells[i].count);
    CHECK(now->mean_z == cells[i].mean_z);
    CHECK(now->m2 == cells[i].m2);
    CHECK(now->min_z == cells[i].min_z);
    CHECK(now->max_z == cells[i].max_z);
    CHECK(now->last_seen == cells[i].last_seen);
    CHECK(now->cls == cells[i].cls);
  }
  CHECK(survivors > 0);
  CHECK(survivors == grid.statistics().occupied_cells);
}

// 5. The eviction count is exactly the number of cells whose centre leaves the
//    disc, derived here by hand rather than from the predicate under test.
//    Catches: an off-by-one at the boundary and a count that reports work it
//    did not do. Radius 1.237 m is deliberately not a multiple of the cell
//    size, so no cell centre sits within rounding distance of the edge.
void checkEvictionCountIsExact() {
  constexpr double kR = 1.237;
  constexpr double kNewCx = 2.0;
  TileGrid grid{MapWindow{0.0, 0.0, kR}};
  fillBlock(grid, 60);
  const std::size_t before = grid.statistics().occupied_cells;

  std::size_t expected_survivors = 0;
  for (std::int32_t iy = -60; iy <= 60; ++iy) {
    for (std::int32_t ix = -60; ix <= 60; ++ix) {
      const double cx = (static_cast<double>(ix) + 0.5) / 20.0;
      const double cy = (static_cast<double>(iy) + 0.5) / 20.0;
      const double dx = cx - kNewCx;
      if (dx * dx + cy * cy <= kR * kR) {
        ++expected_survivors;
      }
    }
  }

  const veyra::map::EvictionStats e = grid.recenter(kNewCx, 0.0);
  CHECK(e.centre_moved);
  CHECK(grid.statistics().occupied_cells == expected_survivors);
  CHECK(e.cells_evicted == before - expected_survivors);
}

// 6. Tiles emptied by eviction are released, and the byte count follows.
//    Catches: cells cleared but tiles retained -- counts right, memory wrong,
//    which is the failure mode that makes a bounded map unbounded.
void checkTilesAreReleased() {
  TileGrid grid{MapWindow{0.0, 0.0, 1.5}};
  fillBlock(grid, 60);
  const GridStats before = grid.statistics();
  CHECK(before.tiles > 1);

  const veyra::map::EvictionStats e = grid.recenter(3.0, 0.0);
  const GridStats after = grid.statistics();

  CHECK(e.tiles_released > 0);
  CHECK(after.tiles == before.tiles - e.tiles_released);
  CHECK(after.allocated_bytes == after.tiles * TileGrid::bytesPerTile());
  CHECK(after.allocated_bytes < before.allocated_bytes);
}

// 7. Recentring toward negative coordinates evicts the far side, not the near
//    one. The >> versus / hazard lives here as much as anywhere.
//    Catches: a tile index that truncates toward zero, which only misbehaves
//    left of the origin.
void checkNegativeMotion() {
  TileGrid grid{MapWindow{0.0, 0.0, 1.0}};
  fillBlock(grid, 80);
  grid.recenter(-3.0, 0.0);

  // A cell well to the negative side survives; its mirror does not.
  CHECK(grid.find(veyra::core::CellId{0, -60, 0}) != nullptr);
  CHECK(grid.find(veyra::core::CellId{0, 60, 0}) == nullptr);
  CHECK(grid.find(veyra::core::CellId{0, 0, 0}) == nullptr);

  std::size_t seen = 0;
  grid.forEachActiveLeaf([&](veyra::core::CellId id, const veyra::map::Cell&) {
    CHECK(id.ix < 0);
    CHECK(veyra::map::inWindow(grid.window(), id));
    ++seen;
  });
  CHECK(seen > 0);
}

}  // namespace

int main() {
  checkFreshGrid();
  checkNoMovementNoEviction();
  checkNoCellOutsideWindow();
  checkCoordinatePreservation();
  checkEvictionCountIsExact();
  checkTilesAreReleased();
  checkNegativeMotion();
  return 0;
}
