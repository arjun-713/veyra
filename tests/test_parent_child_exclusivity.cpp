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

// 2. Splitting a cell that is not active refuses and changes nothing.
//    Catches: a split that fabricates children out of an absent parent, which
//    would put four cells where the map has no evidence at all.
void checkSplitRefusesInactiveCell() {
  TileGrid grid;
  seed(grid, CellId{2, 0, 0}, 4, 1.0);
  const veyra::map::GridStats before = grid.statistics();

  CHECK(!veyra::map::split(grid, CellId{2, 99, 99}));

  const veyra::map::GridStats after = grid.statistics();
  CHECK(after.occupied_cells == before.occupied_cells);
  CHECK(after.tiles == before.tiles);
  CHECK(after.allocated_bytes == before.allocated_bytes);
  for (const CellId k : veyra::core::childrenOf(CellId{2, 99, 99})) {
    CHECK(grid.find(k) == nullptr);
  }
}

// 3. Level 0 is the floor. There is nothing finer than 5 cm, so a split there
//    must refuse rather than create cells at level -1.
//    Catches: an unguarded level - 1, which would produce a negative level --
//    a key that hashes and compares fine but names a resolution that does not
//    exist, corrupting every later lookup at that square.
void checkSplitRefusesAtLevelZero() {
  TileGrid grid;
  const CellId leaf{0, 4, 4};
  seed(grid, leaf, 3, 2.0);

  CHECK(!veyra::map::split(grid, leaf));

  CHECK(grid.find(leaf) != nullptr);
  CHECK(grid.statistics().occupied_cells == 1);
  CHECK(grid.find(CellId{-1, 8, 8}) == nullptr);
}

// 4. Invariant 3 across a real split: the four resulting cells exactly tile
//    the parent's world extent -- no gap, no overlap -- on both sides of the
//    origin.
//    Catches: a split that emits the wrong four ids, which would leave a strip
//    of the parent's square uncovered or double-covered.
void checkChildrenCoverParentExtent() {
  const std::array<CellId, 4> parents = {CellId{2, 3, 5}, CellId{2, -3, -5}, CellId{1, -1, 0},
                                         CellId{3, -7, 2}};
  for (const CellId parent : parents) {
    TileGrid grid;
    seed(grid, parent, 4, 1.0);
    const veyra::core::CellExtent pe = veyra::core::extentOf(parent);
    CHECK(veyra::map::split(grid, parent));

    double area = 0.0;
    std::vector<veyra::core::CellExtent> es;
    grid.forEachActiveLeaf([&](CellId id, const Cell&) {
      const veyra::core::CellExtent e = veyra::core::extentOf(id);
      es.push_back(e);
      area += (e.max_x - e.min_x) * (e.max_y - e.min_y);
      // Every child lies inside the parent.
      CHECK(e.min_x >= pe.min_x - 1e-9);
      CHECK(e.min_y >= pe.min_y - 1e-9);
      CHECK(e.max_x <= pe.max_x + 1e-9);
      CHECK(e.max_y <= pe.max_y + 1e-9);
    });
    CHECK(es.size() == 4);

    // No overlap: interiors are pairwise disjoint along at least one axis.
    for (std::size_t i = 0; i < es.size(); ++i) {
      for (std::size_t j = i + 1; j < es.size(); ++j) {
        const bool disjoint = es[i].max_x - es[j].min_x < 1e-9 ||
                              es[j].max_x - es[i].min_x < 1e-9 ||
                              es[i].max_y - es[j].min_y < 1e-9 || es[j].max_y - es[i].min_y < 1e-9;
        CHECK(disjoint);
      }
    }
    // No gap: the four areas sum to the parent's.
    const double parent_area = (pe.max_x - pe.min_x) * (pe.max_y - pe.min_y);
    CHECK(area > parent_area - 1e-9);
    CHECK(area < parent_area + 1e-9);
  }
}

}  // namespace

int main() {
  checkSplitReplacesParentWithFourChildren();
  checkSplitRefusesInactiveCell();
  checkSplitRefusesAtLevelZero();
  checkChildrenCoverParentExtent();
  return 0;
}
