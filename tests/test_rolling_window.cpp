// Invariant test for the rolling window: invariant 6 of
// docs/map-correctness.md -- evicting distant tiles never changes the identity
// of remaining in-window cells -- plus the bound the window exists to provide.
//
// Each group names the production bug it exists to catch.
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"
#include "veyra/map/fusion.hpp"
#include "veyra/map/observation.hpp"
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

  // The boundary is inclusive: a cell whose centre lies exactly on the radius
  // stays inside. Built so both sides of the comparison are bit-identical
  // rather than merely close -- the window is centred on the cell's own row
  // and its radius is that cell's own distance, so no rounding separates them.
  const veyra::core::CellId on_edge{0, 9, 0};
  const veyra::core::CellExtent ee = veyra::core::extentOf(on_edge);
  const double ecx = 0.5 * (ee.min_x + ee.max_x);
  const double ecy = 0.5 * (ee.min_y + ee.max_y);
  const MapWindow exact{0.0, ecy, ecx};
  CHECK(veyra::map::inWindow(exact, on_edge));
  // ... and the next cell out is not, so this is a partition, not a constant.
  CHECK(!veyra::map::inWindow(exact, veyra::core::CellId{0, 10, 0}));
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

veyra::map::Observation obs(double x, double y) {
  veyra::map::Observation o;
  o.x = x;
  o.y = y;
  o.z = 1.0F;
  o.semantic_class = 1;
  o.semantic_confidence = 1.0F;
  return o;
}

// 8. integrate consults the window, not a fixed box around the odom origin.
//    After a recentre a point that used to be in range is rejected and one
//    that used to be out of range is accepted.
//    Catches: the bug this PR exists to remove -- a range test anchored to the
//    world origin, which silently rejects everything once the vehicle drives
//    past it while statistics still look healthy.
void checkIntegrateHonoursWindow() {
  TileGrid grid{MapWindow{0.0, 0.0, 1.0}};
  const veyra::map::Observation near_origin = obs(0.1, 0.0);
  const veyra::map::Observation far_out = obs(3.0, 0.0);

  const veyra::map::FusionStats before =
      veyra::map::integrate(grid, std::vector<veyra::map::Observation>{near_origin, far_out}, 0);
  CHECK(before.accepted == 1);
  CHECK(before.rejected_out_of_range == 1);
  CHECK(grid.find(veyra::core::worldToKey(0.1, 0.0, 0)) != nullptr);
  CHECK(grid.find(veyra::core::worldToKey(3.0, 0.0, 0)) == nullptr);

  grid.recenter(3.0, 0.0);

  const veyra::map::FusionStats after =
      veyra::map::integrate(grid, std::vector<veyra::map::Observation>{near_origin, far_out}, 1);
  CHECK(after.accepted == 1);
  CHECK(after.rejected_out_of_range == 1);
  // The roles have swapped, which is only possible if both sides share a
  // predicate anchored to the window.
  CHECK(grid.find(veyra::core::worldToKey(3.0, 0.0, 0)) != nullptr);
  CHECK(grid.find(veyra::core::worldToKey(0.1, 0.0, 0)) == nullptr);
}

// 9. The claim the project sells: drive far enough and memory stays bounded.
//    Recentre and integrate across 300 m -- three times the old fixed box --
//    and assert the cell and byte counts plateau instead of growing.
//    Catches: the origin-anchored range bug, which this test fails in two
//    ways at once -- the map stops updating past 100 m, and if it did not,
//    nothing would ever be evicted.
void checkLongDriveStaysBounded() {
  constexpr double kR = 2.0;
  TileGrid grid{MapWindow{0.0, 0.0, kR}};

  std::size_t max_cells = 0;
  std::size_t max_bytes = 0;
  std::size_t max_tiles = 0;
  std::size_t cells_at_50 = 0;
  for (int step = 0; step <= 300; ++step) {
    const double vx = static_cast<double>(step);
    grid.recenter(vx, 0.0);

    std::vector<veyra::map::Observation> batch;
    for (int k = -20; k <= 20; ++k) {
      batch.push_back(obs(vx + 0.05 * static_cast<double>(k), 0.05 * static_cast<double>(k)));
    }
    veyra::map::integrate(grid, batch, static_cast<std::uint32_t>(step));

    const GridStats s = grid.statistics();
    max_cells = std::max(max_cells, s.occupied_cells);
    max_bytes = std::max(max_bytes, s.allocated_bytes);
    max_tiles = std::max(max_tiles, s.tiles);
    if (step == 50) {
      cells_at_50 = s.occupied_cells;
    }
  }

  // Analytic ceiling: a disc of radius 2 m at 5 cm holds pi * 2^2 / 0.05^2 =
  // 5027 cells. Anything at or below that is bounded by the window, not by
  // luck.
  CHECK(max_cells <= 5027);
  // Bytes are bounded by the same disc. A 4 m diameter spans at most
  // ceil(4 / 1.6) + 1 = 4 tiles per axis, so 16 tiles, and the byte count must
  // agree with the tile count rather than being tracked separately.
  CHECK(max_tiles <= 16);
  CHECK(max_bytes == max_tiles * TileGrid::bytesPerTile());

  const GridStats end = grid.statistics();
  CHECK(end.occupied_cells > 0);
  // Plateau, not growth: 300 m in looks like 50 m in.
  CHECK(end.occupied_cells <= cells_at_50 + cells_at_50 / 5);
  CHECK(cells_at_50 > 0);
  // Still updating 300 m out -- the property the origin-anchored box destroyed.
  CHECK(grid.find(veyra::core::worldToKey(300.0, 0.0, 0)) != nullptr);
}

// 10. Thrash. Two hundred recentres that never leave the current tile move
//     nothing, evict nothing and allocate nothing; the next one that crosses
//     a tile boundary does move.
//     Catches: recentring on raw position, which would evict and re-create
//     boundary cells on every frame -- allocation on the hot path, which
//     AGENTS.md forbids.
void checkThrashIsSuppressed() {
  TileGrid grid{MapWindow{0.0, 0.0, 1.0}};
  fillBlock(grid, 40);
  const GridStats base = grid.statistics();
  CHECK(base.occupied_cells > 0);

  for (int i = 0; i < 200; ++i) {
    const double d = 0.007 * static_cast<double>(i);  // 0 .. 1.393, one tile wide
    const veyra::map::EvictionStats e = grid.recenter(d, d);
    CHECK(!e.centre_moved);
    CHECK(e.cells_evicted == 0);
    CHECK(e.tiles_released == 0);
  }
  const GridStats after = grid.statistics();
  CHECK(after.tiles == base.tiles);
  CHECK(after.occupied_cells == base.occupied_cells);
  CHECK(after.allocated_bytes == base.allocated_bytes);
  CHECK(grid.window().centre_x == 0.0);  // never moved

  // Crossing out of the tile does move it.
  const veyra::map::EvictionStats crossed = grid.recenter(2.0, 0.0);
  CHECK(crossed.centre_moved);
  CHECK(crossed.cells_evicted > 0);
  CHECK(grid.window().centre_x == 2.0);
}

// 11. The rejection ordering survives the range-check rewrite. Finite first,
//     then representability, then the window.
//     Catches: the finite check drifting after the range test -- every
//     comparison against NaN is false, so a NaN would slip through and reach
//     worldToKey's double-to-int32 conversion, which is undefined behaviour.
void checkNonFiniteStillRejected() {
  const double nan_v = std::numeric_limits<double>::quiet_NaN();
  const double inf_v = std::numeric_limits<double>::infinity();

  TileGrid grid{MapWindow{0.0, 0.0, 2.0}};
  const std::vector<veyra::map::Observation> batch = {obs(nan_v, 0.0), obs(0.0, inf_v),
                                                      obs(1.0e300, 0.0), obs(0.1, 0.0)};
  const veyra::map::FusionStats s = veyra::map::integrate(grid, batch, 0);

  CHECK(s.accepted == 1);
  CHECK(s.rejected_non_finite == 2);
  CHECK(s.rejected_out_of_range == 1);  // 1e300 is finite but not indexable
  CHECK(s.accepted + s.rejected() == batch.size());
  CHECK(grid.statistics().occupied_cells == 1);

  // recenter refuses a non-finite centre rather than corrupting the window.
  const veyra::map::EvictionStats e = grid.recenter(nan_v, 0.0);
  CHECK(!e.centre_moved);
  CHECK(grid.window().centre_x == 0.0);
  const veyra::map::EvictionStats huge = grid.recenter(1.0e300, 0.0);
  CHECK(!huge.centre_moved);
  CHECK(grid.window().centre_x == 0.0);
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
  checkIntegrateHonoursWindow();
  checkLongDriveStaysBounded();
  checkThrashIsSuppressed();
  checkNonFiniteStillRejected();
  return 0;
}
