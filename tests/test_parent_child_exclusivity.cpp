// Invariant test for the split/merge mechanism: invariant 2 of
// docs/map-correctness.md -- a parent and any descendant are never both
// active -- together with invariant 3 (four children exactly cover one
// parent) and invariant 1 re-tested across levels.
//
// This is the first test in the repository where cells exist above level 0.
// Every earlier test ran entirely at L0, which is why a level-blind bug could
// hide.
//
// Each group names the production bug it exists to catch.
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"
#include "veyra/map/split_merge.hpp"
#include "veyra/map/tile_grid.hpp"

namespace {

using veyra::core::CellId;
using veyra::map::Cell;
using veyra::map::TileGrid;

// Seed a cell with real folded points, so its statistics are those of an
// actual observation rather than hand-set fields.
Cell& seed(TileGrid& grid, CellId id, int points, double base_z) {
  Cell& c = grid.findOrCreate(id);
  for (int i = 0; i < points; ++i) {
    veyra::map::updateCell(c, base_z + 0.01 * static_cast<double>(i));
  }
  return c;
}

// 1. Splitting an active cell removes it and leaves exactly its four children
//    active, one level finer.
//    Catches: a split that leaves the parent behind -- the direct violation of
//    invariant 2 -- and one that produces the wrong number of children.
void checkSplitReplacesParentWithFourChildren() {
  TileGrid grid;
  const CellId parent{2, 3, 5};
  seed(grid, parent, 8, 1.0);
  CHECK(grid.statistics().occupied_cells == 1);

  CHECK(veyra::map::split(grid, parent));

  CHECK(grid.find(parent) == nullptr);
  CHECK(grid.statistics().occupied_cells == 4);
  const std::array<CellId, 4> kids = veyra::core::childrenOf(parent);
  for (const CellId k : kids) {
    CHECK(k.level == parent.level - 1);
    CHECK(grid.find(k) != nullptr);
    CHECK(veyra::core::parentOf(k) == parent);
  }
}

}  // namespace

int main() {
  checkSplitReplacesParentWithFourChildren();
  return 0;
}
