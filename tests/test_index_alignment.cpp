// Invariant test for the world-aligned dyadic lattice. Checks the resolution
// ladder, parent/child round-trips, the negative-index case where >> and /
// disagree, four children exactly covering one parent, agreement between
// per-level indexing and shifting from L0, and [min, max) boundary ownership.
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <random>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"

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

int main() {
  checkResolutionLadder();
  checkParentChildRoundTrip();
  checkNegativeIndices();
  checkChildrenCoverParent();
  checkDirectVsShiftAgreement();
  checkBoundaryOwnership();
  checkCenterRoundTrip();
  checkTileLocalGlobal();
  return 0;
}
