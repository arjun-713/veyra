// Native regression suites. CTest runs each section in a fresh process.
#include <cstdio>
#include <string_view>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <random>
#include <vector>
#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"
#include "veyra/map/rolling_window.hpp"
#include "veyra/map/split_merge.hpp"
#include "veyra/map/tile_grid.hpp"
#include <algorithm>
#include <limits>
#include "veyra/map/fusion.hpp"
#include "veyra/map/observation.hpp"

namespace index_alignment {

// Invariant test for the world-aligned dyadic lattice. Checks the resolution
// ladder, parent/child round-trips, the negative-index case where >> and /
// disagree, four children exactly covering one parent, agreement between
// per-level indexing and shifting from L0, [min, max) boundary ownership,
// coordinate -> cell -> centre -> cell stability, and tile-local plus tile
// origin resolving to the same global cell.


namespace {

using veyra::core::CellExtent;
using veyra::core::cellFromTile;
using veyra::core::CellId;
using veyra::core::cells_per_m;
using veyra::core::childrenOf;
using veyra::core::extentOf;
using veyra::core::localIndex;
using veyra::core::parentOf;
using veyra::core::resolution_m;
using veyra::core::TileId;
using veyra::core::tileOf;
using veyra::core::worldToKey;

constexpr double kEps = 1e-9;

bool approxEq(double a, double b) { return std::fabs(a - b) < kEps; }

// True when two boxes overlap in at most their edges: one lies entirely on the
// low side of the other along at least one axis.
bool interiorsDisjoint(const CellExtent& a, const CellExtent& b) {
  return a.max_x - b.min_x < kEps || b.max_x - a.min_x < kEps || a.max_y - b.min_y < kEps ||
         b.max_y - a.min_y < kEps;
}

double areaOf(const CellExtent& e) { return (e.max_x - e.min_x) * (e.max_y - e.min_y); }

// 1. Resolution ladder: resolution_m(l) == 0.05 * 2^l, and each level is
//    exactly twice the one below it.
void checkResolutionLadder() {
  CHECK(approxEq(resolution_m(0), 0.05));
  CHECK(approxEq(resolution_m(1), 0.10));
  CHECK(approxEq(resolution_m(2), 0.20));
  CHECK(approxEq(resolution_m(3), 0.40));
  for (int l = 0; l < 3; ++l) {
    CHECK(approxEq(resolution_m(l + 1), 2.0 * resolution_m(l)));
  }
  // cells_per_m is the reciprocal the indexing actually uses.
  for (int l = 0; l <= 3; ++l) {
    CHECK(approxEq(resolution_m(l) * cells_per_m(l), 1.0));
  }
}

// 2. Every element of childrenOf(k) reports k as its parent, the four are
//    distinct, and the levels move by exactly one in each direction.
void checkParentChildRoundTrip() {
  static constexpr std::array<CellId, 9> kSeeds = {
      CellId{1, 0, 0},   CellId{1, 7, 3},   CellId{1, -7, 3},
      CellId{1, 7, -3},  CellId{1, -7, -3}, CellId{2, 12, -1},
      CellId{2, -12, 1}, CellId{3, -1, -1}, CellId{3, 1000, -1000}};

  for (const CellId k : kSeeds) {
    CHECK(parentOf(k).level == k.level + 1);

    const std::array<CellId, 4> kids = childrenOf(k);
    for (std::size_t i = 0; i < kids.size(); ++i) {
      CHECK(kids[i].level == k.level - 1);
      CHECK(parentOf(kids[i]) == k);
      for (std::size_t j = i + 1; j < kids.size(); ++j) {
        CHECK(kids[i] != kids[j]);
      }
    }
  }
}

// 3. Negative indices, the case the whole scheme turns on. parentOf must floor
//    toward negative infinity; truncating division would put ix=-3 under parent
//    -1 and leave three cells sharing parent 0.
void checkNegativeIndices() {
  CHECK(parentOf(CellId{0, -3, -3}) == (CellId{1, -2, -2}));
  CHECK(parentOf(CellId{0, -3, -3}) != (CellId{1, -1, -1}));

  static constexpr std::array<int32_t, 8> kIx = {-4, -3, -2, -1, 0, 1, 2, 3};
  static constexpr std::array<int32_t, 8> kParentIx = {-2, -2, -1, -1, 0, 0, 1, 1};
  for (std::size_t i = 0; i < kIx.size(); ++i) {
    CHECK(parentOf(CellId{0, kIx[i], kIx[i]}) == (CellId{1, kParentIx[i], kParentIx[i]}));
  }

  // The cells sharing a parent are the pairs {-4,-3}, {-2,-1}, {0,1}, {2,3};
  // cells on opposite sides of a parent edge must not share one.
  for (std::size_t i = 0; i + 1 < kIx.size(); i += 2) {
    CHECK(parentOf(CellId{0, kIx[i], 0}) == parentOf(CellId{0, kIx[i + 1], 0}));
    if (i + 2 < kIx.size()) {
      CHECK(parentOf(CellId{0, kIx[i + 1], 0}) != parentOf(CellId{0, kIx[i + 2], 0}));
    }
  }

  // The round trip of group 2 also holds with negative ids on both axes.
  for (const int32_t ix : kIx) {
    for (const int32_t iy : kIx) {
      const CellId k{1, ix, iy};
      for (const CellId child : childrenOf(k)) {
        CHECK(parentOf(child) == k);
      }
    }
  }
}

// 4. Four children exactly cover one parent: they stay inside it, their
//    interiors are disjoint, their edges meet at the parent's midlines, and
//    their areas sum to the parent's area. Together that is cover with no gap
//    and no overlap.
void checkChildrenCoverParent() {
  static constexpr std::array<CellId, 4> kParents = {CellId{1, 3, 5}, CellId{1, -3, -5},
                                                     CellId{2, -1, 2}, CellId{3, -7, -8}};

  for (const CellId parent : kParents) {
    const CellExtent pe = extentOf(parent);
    const std::array<CellId, 4> kids = childrenOf(parent);
    const double mid_x = 0.5 * (pe.min_x + pe.max_x);
    const double mid_y = 0.5 * (pe.min_y + pe.max_y);

    double area_sum = 0.0;
    for (std::size_t i = 0; i < kids.size(); ++i) {
      const CellExtent ke = extentOf(kids[i]);
      area_sum += areaOf(ke);
      // Contained in the parent.
      CHECK(ke.min_x >= pe.min_x - kEps);
      CHECK(ke.min_y >= pe.min_y - kEps);
      CHECK(ke.max_x <= pe.max_x + kEps);
      CHECK(ke.max_y <= pe.max_y + kEps);
      // Half the parent's side on each axis.
      CHECK(approxEq(ke.max_x - ke.min_x, 0.5 * (pe.max_x - pe.min_x)));
      CHECK(approxEq(ke.max_y - ke.min_y, 0.5 * (pe.max_y - pe.min_y)));
      // No overlap: interiors are pairwise disjoint.
      for (std::size_t j = i + 1; j < kids.size(); ++j) {
        CHECK(interiorsDisjoint(ke, extentOf(kids[j])));
      }
    }

    // No gap: the four children's outer edges are the parent's edges and their
    // inner edges meet on the parent's midlines.
    const CellExtent sw = extentOf(kids[0]);
    const CellExtent se = extentOf(kids[1]);
    const CellExtent nw = extentOf(kids[2]);
    const CellExtent ne = extentOf(kids[3]);
    CHECK(approxEq(sw.min_x, pe.min_x));
    CHECK(approxEq(sw.min_y, pe.min_y));
    CHECK(approxEq(ne.max_x, pe.max_x));
    CHECK(approxEq(ne.max_y, pe.max_y));
    CHECK(approxEq(sw.max_x, mid_x));
    CHECK(approxEq(se.min_x, mid_x));
    CHECK(approxEq(sw.max_y, mid_y));
    CHECK(approxEq(nw.min_y, mid_y));
    CHECK(approxEq(area_sum, areaOf(pe)));
  }
}

// 5. Indexing at level l directly agrees with indexing at L0 and shifting
//    right l times. This locks in the design decision to derive coarse indices
//    by shifting; a future rewrite that divides per level would break here.
//    Fixed values plus a fixed-seed PRNG, so the case set is reproducible.
void checkDirectVsShiftAgreement() {
  std::vector<double> xs;
  std::vector<double> ys;

  // Exact L0 cell corners either side of the origin, plus their midpoints.
  for (int32_t i = -12; i <= 12; ++i) {
    const CellExtent e = extentOf(CellId{0, i, i});
    xs.push_back(e.min_x);
    ys.push_back(e.min_y);
    xs.push_back(0.5 * (e.min_x + e.max_x));
    ys.push_back(0.5 * (e.min_y + e.max_y));
  }
  // Coarse-level corners, where several L0 cells share an edge.
  for (int32_t i = -6; i <= 6; ++i) {
    for (int l = 1; l <= 3; ++l) {
      const CellExtent e = extentOf(CellId{l, i, -i});
      xs.push_back(e.min_x);
      ys.push_back(e.min_y);
    }
  }
  xs.push_back(0.0);
  ys.push_back(-0.0);

  std::mt19937 rng(20260909u);  // fixed seed: the case set must be reproducible
  std::uniform_real_distribution<double> dist(-100.0, 100.0);
  for (int i = 0; i < 200; ++i) {
    xs.push_back(dist(rng));
    ys.push_back(dist(rng));
  }

  CHECK(xs.size() == ys.size());
  for (std::size_t i = 0; i < xs.size(); ++i) {
    const double x = xs[i];
    const double y = ys[i];
    const CellId k0 = worldToKey(x, y, 0);
    CHECK(k0.level == 0);

    CellId shifted = k0;
    for (int l = 1; l <= 3; ++l) {
      shifted =
          CellId{l, static_cast<int32_t>(shifted.ix >> 1), static_cast<int32_t>(shifted.iy >> 1)};
      CHECK(worldToKey(x, y, l) == shifted);
    }
  }
}

// 6. Boundary ownership. A cell owns [min, max) on each axis: a point on the
//    lower edge is inside, a point on the upper edge belongs to the next cell.
//    Checked either side of the origin, where floor's behaviour on negatives
//    makes the answer non-obvious.
void checkBoundaryOwnership() {
  for (int l = 0; l <= 3; ++l) {
    for (int32_t i = -8; i <= 8; ++i) {
      const CellId c{l, i, i};
      const CellExtent e = extentOf(c);
      const double quarter_x = 0.25 * (e.max_x - e.min_x);
      const double quarter_y = 0.25 * (e.max_y - e.min_y);

      // Lower edge inclusive, upper edge exclusive.
      CHECK(worldToKey(e.min_x, e.min_y, l) == c);
      CHECK(worldToKey(e.max_x, e.max_y, l) == (CellId{l, i + 1, i + 1}));
      // Interior stays put; a step below the lower edge falls to the neighbour.
      CHECK(worldToKey(e.min_x + quarter_x, e.min_y + quarter_y, l) == c);
      CHECK(worldToKey(e.min_x - quarter_x, e.min_y - quarter_y, l) == (CellId{l, i - 1, i - 1}));

      // Exactly one cell claims the lower edge: the previous cell's extent
      // ends at it and, being half-open, does not contain it.
      const CellExtent prev = extentOf(CellId{l, i - 1, i - 1});
      CHECK(approxEq(prev.max_x, e.min_x));
      CHECK(approxEq(prev.max_y, e.min_y));
      CHECK(!(prev.min_x <= e.min_x && e.min_x < prev.max_x));

      // The cell returned for a boundary point contains that point.
      const CellId hit = worldToKey(e.min_x, e.min_y, l);
      const CellExtent he = extentOf(hit);
      CHECK(he.min_x <= e.min_x && e.min_x < he.max_x);
      CHECK(he.min_y <= e.min_y && e.min_y < he.max_y);
    }
  }
}

// 7. A world coordinate, the cell it lands in, that cell's centre, and the
//    cell the centre indexes back to are all the same cell. Driven from both
//    ends: from arbitrary coordinates, and from a sweep of indices spanning
//    the origin.
void checkCenterRoundTrip() {
  std::mt19937 rng(20260910u);  // fixed seed: the case set must be reproducible
  std::uniform_real_distribution<double> dist(-100.0, 100.0);
  for (int n = 0; n < 200; ++n) {
    const double x = dist(rng);
    const double y = dist(rng);
    for (int l = 0; l <= 3; ++l) {
      const CellId k = worldToKey(x, y, l);
      const CellExtent e = extentOf(k);
      const double cx = 0.5 * (e.min_x + e.max_x);
      const double cy = 0.5 * (e.min_y + e.max_y);
      // The centre lies strictly inside the cell it came from ...
      CHECK(e.min_x < cx && cx < e.max_x);
      CHECK(e.min_y < cy && cy < e.max_y);
      // ... and indexes back to that same cell.
      CHECK(worldToKey(cx, cy, l) == k);
    }
  }

  // Same round trip from the index side, negative indices included.
  for (int l = 0; l <= 3; ++l) {
    for (int32_t i = -40; i <= 40; ++i) {
      const CellId c{l, i, static_cast<int32_t>(-i)};
      const CellExtent e = extentOf(c);
      const double cx = 0.5 * (e.min_x + e.max_x);
      const double cy = 0.5 * (e.min_y + e.max_y);
      CHECK(worldToKey(cx, cy, l) == c);
      // Both anchors of the cell agree: centre and lower corner.
      CHECK(worldToKey(e.min_x, e.min_y, l) == c);
    }
  }
}

// 8. Tile-local index plus tile origin resolves to the same global cell, on
//    both sides of a tile boundary and either side of the origin. Index
//    arithmetic only -- no tile storage exists yet.
void checkTileLocalGlobal() {
  for (int tile_log2 = 1; tile_log2 <= 5; ++tile_log2) {
    const auto span = static_cast<int32_t>(1 << tile_log2);
    for (int l = 0; l <= 3; ++l) {
      for (int32_t i = -3 * span; i <= 3 * span; ++i) {
        const CellId c{l, i, static_cast<int32_t>(-i - 1)};
        const TileId t = tileOf(c, tile_log2);
        const int32_t lx = localIndex(c.ix, tile_log2);
        const int32_t ly = localIndex(c.iy, tile_log2);

        // Local indices stay inside the tile, negative cells included.
        CHECK(lx >= 0 && lx < span);
        CHECK(ly >= 0 && ly < span);
        // Tile origin + local offset recovers the global cell exactly.
        CHECK(cellFromTile(t, lx, ly, tile_log2) == c);
        CHECK(t.level == c.level);

        // The neighbour one cell east resolves to the same global cell
        // whichever tile it is reached from, and the tile index steps exactly
        // once, at the span boundary.
        const CellId east{l, static_cast<int32_t>(c.ix + 1), c.iy};
        const TileId te = tileOf(east, tile_log2);
        CHECK(cellFromTile(te, localIndex(east.ix, tile_log2), localIndex(east.iy, tile_log2),
                           tile_log2) == east);
        if (lx == span - 1) {
          CHECK(te != t);
          CHECK(te.tx == t.tx + 1);
        } else {
          CHECK(te == t);
        }
      }
    }
  }
  // The trap, stated explicitly. Truncating division puts cell -1 in tile 0
  // with local index -1 -- outside its own tile, and colliding with cell 0.
  CHECK(tileOf(CellId{0, -1, -1}, 4) == (TileId{0, -1, -1}));
  CHECK(tileOf(CellId{0, -1, -1}, 4) != (TileId{0, 0, 0}));
  CHECK(localIndex(-1, 4) == 15);
  CHECK(cellFromTile(TileId{0, -1, -1}, 15, 15, 4) == (CellId{0, -1, -1}));
}

}  // namespace

int run() {
  checkResolutionLadder();
  checkParentChildRoundTrip();
  checkNegativeIndices();
  checkChildrenCoverParent();
  checkDirectVsShiftAgreement();
  checkBoundaryOwnership();
  checkCenterRoundTrip();
  checkTileLocalGlobal();
  return 0;
  return 0;
}

}  // namespace index_alignment

namespace parent_child_exclusivity {

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

int run() {
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
  return 0;
}

}  // namespace parent_child_exclusivity

namespace rolling_window {

// Invariant test for the rolling window: invariant 6 of
// docs/map-correctness.md -- evicting distant tiles never changes the identity
// of remaining in-window cells -- plus the bound the window exists to provide.
//
// Each group names the production bug it exists to catch.


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

int run() {
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
  return 0;
}

}  // namespace rolling_window

int main(int argc, char** argv) {
  if (argc == 2) {
    const std::string_view suite{argv[1]};
    if (suite == "index_alignment") return index_alignment::run();
    if (suite == "parent_child_exclusivity") return parent_child_exclusivity::run();
    if (suite == "rolling_window") return rolling_window::run();
  }
  std::fputs("Select a registered CTest suite.\n", stderr);
  return 2;
}
