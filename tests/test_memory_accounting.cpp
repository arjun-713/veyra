// Invariant test for tile storage: allocation is per tile and never per cell,
// byte accounting is derived rather than asserted, and the tile index is
// computed with >> and & so that cells left of the origin land in the right
// tile. Covers issue #6's storage half.
//
// Every group names the production bug it exists to catch.
#include <cstddef>
#include <cstdint>
#include <functional>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"
#include "veyra/map/tile_grid.hpp"

namespace {

using veyra::core::CellId;
using veyra::map::Cell;
using veyra::map::GridStats;
using veyra::map::kCellsPerTile;
using veyra::map::kTileSpan;
using veyra::map::TileGrid;

constexpr double kEps = 1e-9;

bool approxEq(double a, double b) { return (a > b ? a - b : b - a) < kEps; }

// 1. An empty grid holds nothing and costs nothing.
//    Catches: statistics() returning hardcoded numbers, and a grid that
//    pre-allocates tiles before anything is inserted.
void checkEmptyGrid() {
  // The tile shape is a settled design decision (issue #6), not an
  // implementation detail, so it is pinned with literals. Deriving these from
  // kTileSpan would make every expectation below move with the constant.
  CHECK(kTileSpan == 32);
  CHECK(kCellsPerTile == 1024);

  const TileGrid grid;
  const GridStats s = grid.statistics();
  CHECK(s.tiles == 0);
  CHECK(s.occupied_cells == 0);
  CHECK(s.allocated_bytes == 0);
  CHECK(approxEq(s.occupancy, 0.0));
}

// 2. One cell allocates exactly one tile, not one allocation per cell.
//    Catches: per-cell allocation, which is what tiling exists to avoid.
void checkOneCellOneTile() {
  TileGrid grid;
  grid.findOrCreate(CellId{0, 3, 4});
  const GridStats s = grid.statistics();
  CHECK(s.tiles == 1);
  CHECK(s.occupied_cells == 1);
  CHECK(s.allocated_bytes == TileGrid::bytesPerTile());
}

// 3. A full tile's worth of cells still allocates exactly one tile. This is
//    the entire point of the design.
//    Catches: findOrCreate allocating a fresh tile per call instead of
//    reusing; a tile_log2 smaller than 5, which would split these across
//    several tiles.
void checkFullTileIsOneTile() {
  TileGrid grid;
  for (int32_t iy = 0; iy < 32; ++iy) {
    for (int32_t ix = 0; ix < 32; ++ix) {
      grid.findOrCreate(CellId{0, ix, iy});
    }
  }
  const GridStats s = grid.statistics();
  CHECK(s.tiles == 1);
  CHECK(s.occupied_cells == 1024);
  CHECK(approxEq(s.occupancy, 1.0));
}

// 4. Cells beyond a tile's span go to separate tiles.
//    Catches: a tile index that ignores the high bits, collapsing the whole
//    plane into one tile.
void checkSeparateTileRegions() {
  TileGrid grid;
  grid.findOrCreate(CellId{0, 0, 0});
  grid.findOrCreate(CellId{0, 32, 0});
  grid.findOrCreate(CellId{0, 0, 32});
  const GridStats s = grid.statistics();
  CHECK(s.tiles == 3);
  CHECK(s.occupied_cells == 3);
}

// 5. Two cells with the same (tx, ty) but different levels are different
//    cells and must not share a tile.
//    Catches: a TileId hash or operator== that ignores level -- which would
//    silently overwrite an L0 cell with an L1 one.
void checkLevelsNeverShareATile() {
  TileGrid grid;
  Cell& a = grid.findOrCreate(CellId{0, 1, 1});
  Cell& b = grid.findOrCreate(CellId{1, 1, 1});
  a.count = 11;
  b.count = 22;

  const GridStats s = grid.statistics();
  CHECK(s.tiles == 2);
  CHECK(s.occupied_cells == 2);
  CHECK(grid.find(CellId{0, 1, 1})->count == 11);
  CHECK(grid.find(CellId{1, 1, 1})->count == 22);

  // The assertions above pass even with a level-blind hash, because
  // operator== still separates the keys -- the two tiles merely collide into
  // one bucket. So this pins hash quality directly. It proves the level
  // reaches the hash, not that lookup is correct; lookup is guarded above.
  using veyra::core::TileId;
  CHECK(std::hash<TileId>{}(TileId{0, 1, 1}) != std::hash<TileId>{}(TileId{1, 1, 1}));
}

// 6. Byte accounting is derived from sizeof, not written down.
//    Catches: a hardcoded byte count, which would rot the moment a field is
//    added to Cell or to the tile.
void checkByteAccountingIsDerived() {
  CHECK(TileGrid::bytesPerTile() >= kCellsPerTile * sizeof(Cell));

  TileGrid grid;
  for (int32_t i = 0; i < 5; ++i) {
    grid.findOrCreate(CellId{0, i * 32, 0});
  }
  const GridStats s = grid.statistics();
  CHECK(s.tiles == 5);
  CHECK(s.allocated_bytes == 5 * TileGrid::bytesPerTile());
}

// 7. Sparsity is measurable. One cell in a tile reports 1/1024 occupancy, so
//    the real cost of a sparse map is visible rather than hidden.
//    Catches: an occupancy figure computed from live cells alone, which would
//    always report 1.0 and make waste invisible.
void checkOccupancyWasteIsVisible() {
  TileGrid grid;
  grid.findOrCreate(CellId{0, 0, 0});
  const GridStats s = grid.statistics();
  CHECK(approxEq(s.occupancy, 1.0 / 1024.0));
  CHECK(s.allocated_bytes == TileGrid::bytesPerTile());
}

// 8. Negative coordinates. -1 >> 5 == -1 but -1 / 32 == 0, so a cell at
//    ix = -1 and one at ix = 31 belong to different tiles even though
//    truncating division puts them both in tile 0 -- where their intra-tile
//    indices would be -1 and 31, one of them out of bounds.
//    Catches: / instead of >> in the tile index, and % instead of & in the
//    slot index. This is the bug that only ever appears left of the origin.
void checkNegativeCoordinates() {
  TileGrid grid;
  Cell& left = grid.findOrCreate(CellId{0, -1, 0});
  Cell& right = grid.findOrCreate(CellId{0, 31, 0});
  Cell& further = grid.findOrCreate(CellId{0, -33, 0});
  left.count = 1;
  right.count = 2;
  further.count = 3;

  const GridStats s = grid.statistics();
  CHECK(s.tiles == 3);
  CHECK(s.occupied_cells == 3);
  CHECK(grid.find(CellId{0, -1, 0})->count == 1);
  CHECK(grid.find(CellId{0, 31, 0})->count == 2);
  CHECK(grid.find(CellId{0, -33, 0})->count == 3);

  // The ids come back out of iteration exactly as they went in, which pins
  // the slot -> CellId decomposition as well as the tile index.
  std::vector<CellId> seen;
  grid.forEachActiveLeaf([&seen](CellId id, const Cell&) { seen.push_back(id); });
  CHECK(seen.size() == 3);
  int found = 0;
  for (const CellId id : seen) {
    if (id == (CellId{0, -1, 0}) || id == (CellId{0, 31, 0}) || id == (CellId{0, -33, 0})) {
      ++found;
    }
  }
  CHECK(found == 3);
}

// 9. erase removes the cell, and a tile whose last cell goes is deallocated.
//    Catches: a tile that leaks after its contents are gone, and a live count
//    that is not decremented -- either of which makes the rolling window's
//    memory unbounded later.
void checkEraseDeallocatesEmptyTiles() {
  TileGrid grid;
  grid.findOrCreate(CellId{0, 0, 0});
  grid.findOrCreate(CellId{0, 1, 0});
  CHECK(grid.statistics().tiles == 1);
  CHECK(grid.statistics().occupied_cells == 2);

  CHECK(grid.erase(CellId{0, 0, 0}));
  CHECK(grid.find(CellId{0, 0, 0}) == nullptr);
  CHECK(grid.statistics().occupied_cells == 1);
  CHECK(grid.statistics().tiles == 1);  // one cell left, tile stays

  CHECK(grid.erase(CellId{0, 1, 0}));
  const GridStats s = grid.statistics();
  CHECK(s.tiles == 0);
  CHECK(s.occupied_cells == 0);
  CHECK(s.allocated_bytes == 0);

  // Erasing what is not there changes nothing and reports it.
  CHECK(!grid.erase(CellId{0, 0, 0}));
  CHECK(grid.statistics().tiles == 0);
}

// 10. find and findOrCreate address the same storage, and find never
//     allocates.
//     Catches: find reading a different slot than findOrCreate writes, and
//     find creating a tile as a side effect of lookup.
void checkRoundTrip() {
  TileGrid grid;
  Cell& created = grid.findOrCreate(CellId{0, 7, 9});
  created.count = 42;
  created.mean_z = 1.5;

  Cell* found = grid.find(CellId{0, 7, 9});
  CHECK(found != nullptr);
  CHECK(found == &created);
  CHECK(found->count == 42);
  CHECK(approxEq(found->mean_z, 1.5));

  // A second findOrCreate returns the same cell, it does not reset it.
  Cell& again = grid.findOrCreate(CellId{0, 7, 9});
  CHECK(&again == &created);
  CHECK(again.count == 42);
  CHECK(grid.statistics().occupied_cells == 1);

  // Absent cells read as null and cost nothing.
  CHECK(grid.find(CellId{0, 8, 9}) == nullptr);
  CHECK(grid.find(CellId{0, 1000, 1000}) == nullptr);
  CHECK(grid.statistics().tiles == 1);
  CHECK(grid.statistics().occupied_cells == 1);
}

}  // namespace

int main() {
  checkEmptyGrid();
  checkOneCellOneTile();
  checkFullTileIsOneTile();
  checkSeparateTileRegions();
  checkLevelsNeverShareATile();
  checkByteAccountingIsDerived();
  checkOccupancyWasteIsVisible();
  checkNegativeCoordinates();
  checkEraseDeallocatesEmptyTiles();
  checkRoundTrip();
  return 0;
}
