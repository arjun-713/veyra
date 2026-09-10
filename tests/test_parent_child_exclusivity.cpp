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
#include "veyra/map/rolling_window.hpp"
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

// 8. Merging refuses unless all four children are active. Three children do
//    not cover the parent's square, so collapsing them would claim coverage
//    of ground the map has no cell for.
//    Catches: a merge that accepts a partial set and silently invents the
//    missing quarter.
void checkMergeRefusesPartialChildren() {
  TileGrid grid;
  const CellId parent{2, 5, 5};
  seed(grid, parent, 8, 1.0);
  CHECK(veyra::map::split(grid, parent));

  const std::array<CellId, 4> kids = veyra::core::childrenOf(parent);
  CHECK(grid.erase(kids[3]));
  CHECK(grid.statistics().occupied_cells == 3);

  CHECK(!veyra::map::merge(grid, parent));

  // Nothing moved: still three children, still no parent.
  CHECK(grid.statistics().occupied_cells == 3);
  CHECK(grid.find(parent) == nullptr);
  for (std::size_t i = 0; i < 3; ++i) {
    CHECK(grid.find(kids[i]) != nullptr);
  }
}

// 9. Merging refuses while a descendant two levels down is active. Collapsing
//    to the parent would leave that grandchild underneath an active ancestor
//    -- invariant 2 violated, and the same square owned twice.
//    Catches: a merge that only looks one level down.
void checkMergeRefusesActiveGrandchild() {
  TileGrid grid;
  const CellId parent{2, 0, 0};
  seed(grid, parent, 8, 1.0);
  CHECK(veyra::map::split(grid, parent));

  const CellId child0 = veyra::core::childrenOf(parent)[0];
  const CellId grandchild = veyra::core::childrenOf(child0)[0];
  seed(grid, grandchild, 2, 1.0);
  CHECK(grid.find(child0) != nullptr);
  CHECK(grid.find(grandchild) != nullptr);
  const veyra::map::GridStats before = grid.statistics();

  CHECK(!veyra::map::merge(grid, parent));

  CHECK(grid.find(parent) == nullptr);
  CHECK(grid.statistics().occupied_cells == before.occupied_cells);
  CHECK(grid.find(grandchild) != nullptr);
}

// True when any ancestor of `id` is also active. Invariant 2 says this can
//    never happen.
bool anyAncestorActive(const TileGrid& grid, CellId id) {
  CellId up = id;
  while (up.level < veyra::map::kMaxLevel) {
    up = veyra::core::parentOf(up);
    if (grid.find(up) != nullptr) {
      return true;
    }
  }
  return false;
}

// 10. Invariant 2 under a scripted sequence of splits and merges, not just a
//     single operation. After every step, no active cell has an active
//     ancestor.
//     Catches: an operation that leaves a stale cell behind at the wrong
//     level -- which a single split-then-check would not reveal.
void checkExclusivityUnderSequences() {
  TileGrid grid;
  const CellId root{3, 1, -2};
  seed(grid, root, 40, 5.0);

  const auto assertExclusive = [&grid]() {
    std::size_t seen = 0;
    grid.forEachActiveLeaf([&](CellId id, const Cell&) {
      CHECK(!anyAncestorActive(grid, id));
      ++seen;
    });
    CHECK(seen == grid.statistics().occupied_cells);
  };

  assertExclusive();
  CHECK(veyra::map::split(grid, root));  // L3 -> four L2
  assertExclusive();

  const std::array<CellId, 4> l2 = veyra::core::childrenOf(root);
  CHECK(veyra::map::split(grid, l2[0]));  // one L2 -> four L1
  assertExclusive();
  CHECK(veyra::map::split(grid, veyra::core::childrenOf(l2[0])[3]));  // one L1 -> four L0
  assertExclusive();

  // Collapse back up in the reverse order.
  CHECK(veyra::map::merge(grid, veyra::core::childrenOf(l2[0])[3]));
  assertExclusive();
  CHECK(veyra::map::merge(grid, l2[0]));
  assertExclusive();
  CHECK(veyra::map::merge(grid, root));
  assertExclusive();

  CHECK(grid.statistics().occupied_cells == 1);
  CHECK(grid.find(root) != nullptr);
}

// 11. Invariant 1 across levels, tested for the first time with more than one
//     level present. Every point falls in exactly one active leaf when the map
//     holds a mix of L0, L1 and L2 cells.
//     Catches: the level-blind class of bug -- a key that ignores level would
//     make two cells at different resolutions collide or both claim a point.
void checkOwnershipAcrossMixedLevels() {
  TileGrid grid;
  const CellId root{2, 0, 0};
  seed(grid, root, 32, 4.0);
  CHECK(veyra::map::split(grid, root));  // four L1
  const CellId l1 = veyra::core::childrenOf(root)[0];
  CHECK(veyra::map::split(grid, l1));            // one L1 -> four L0
  CHECK(grid.statistics().occupied_cells == 7);  // 3 x L1 + 4 x L0

  const veyra::core::CellExtent re = veyra::core::extentOf(root);
  std::size_t probed = 0;
  for (int i = 1; i < 20; ++i) {
    for (int j = 1; j < 20; ++j) {
      const double x = re.min_x + (re.max_x - re.min_x) * (static_cast<double>(i) / 20.0);
      const double y = re.min_y + (re.max_y - re.min_y) * (static_cast<double>(j) / 20.0);

      // Count every active cell whose half-open extent contains the point.
      std::size_t owners = 0;
      grid.forEachActiveLeaf([&](CellId id, const Cell&) {
        const veyra::core::CellExtent e = veyra::core::extentOf(id);
        if (e.min_x <= x && x < e.max_x && e.min_y <= y && y < e.max_y) {
          ++owners;
        }
      });
      CHECK(owners == 1);

      // And the grid's own lookup agrees with that single owner.
      const veyra::map::LeafHit hit = veyra::map::activeLeafCovering(grid, x, y);
      CHECK(hit.found);
      const veyra::core::CellExtent he = veyra::core::extentOf(hit.id);
      CHECK(he.min_x <= x && x < he.max_x);
      CHECK(he.min_y <= y && y < he.max_y);
      ++probed;
    }
  }
  CHECK(probed == 19 * 19);

  // A point outside the square is owned by nobody.
  CHECK(!veyra::map::activeLeafCovering(grid, re.min_x - 1.0, re.min_y - 1.0).found);
}

// 13. Eviction and split compose: when a split cell's children fall outside
//     the window they are all evicted, leaving no orphan behind.
//     Catches: children that outlive their region because eviction only knew
//     about the level the parent used to be at.
void checkEvictionRemovesSplitChildren() {
  TileGrid grid{veyra::map::MapWindow{0.0, 0.0, 1.0}};
  const CellId parent{2, 1, 1};
  seed(grid, parent, 8, 1.0);
  CHECK(veyra::map::split(grid, parent));
  CHECK(grid.statistics().occupied_cells == 4);

  const veyra::map::EvictionStats e = grid.recenter(40.0, 40.0);
  CHECK(e.centre_moved);
  CHECK(e.cells_evicted == 4);

  CHECK(grid.statistics().occupied_cells == 0);
  CHECK(grid.statistics().tiles == 0);
  CHECK(grid.find(parent) == nullptr);
  for (const CellId k : veyra::core::childrenOf(parent)) {
    CHECK(grid.find(k) == nullptr);
  }
}

// 14. Levels never share a tile, so a split moves its cells into a different
//     tile and releases the one the parent occupied.
//     Catches: a tile key that ignores level -- the bug PR B's mutation check
//     found and which nothing could exercise until cells existed above L0.
void checkSplitMovesCellsToADifferentTile() {
  TileGrid grid;
  const CellId parent{2, 0, 0};
  seed(grid, parent, 8, 1.0);
  const veyra::map::GridStats before = grid.statistics();
  CHECK(before.tiles == 1);
  CHECK(before.occupied_cells == 1);

  CHECK(veyra::map::split(grid, parent));
  const veyra::map::GridStats after = grid.statistics();
  CHECK(after.occupied_cells == 4);
  CHECK(after.tiles == 1);  // the level-2 tile released, a level-1 tile taken
  CHECK(after.allocated_bytes == after.tiles * TileGrid::bytesPerTile());

  // Re-creating a cell at the old level takes a second tile, because a tile
  // belongs to exactly one level even at the same (tx, ty).
  seed(grid, parent, 2, 1.0);
  CHECK(grid.statistics().tiles == 2);
  CHECK(grid.statistics().allocated_bytes == 2 * TileGrid::bytesPerTile());
}

}  // namespace

int main() {
  checkSplitReplacesParentWithFourChildren();
  checkSplitRefusesInactiveCell();
  checkSplitRefusesAtLevelZero();
  checkChildrenCoverParentExtent();
  checkMergeRefusesPartialChildren();
  checkMergeRefusesActiveGrandchild();
  checkExclusivityUnderSequences();
  checkOwnershipAcrossMixedLevels();
  checkEvictionRemovesSplitChildren();
  checkSplitMovesCellsToADifferentTile();
  return 0;
}
