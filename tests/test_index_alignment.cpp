// Invariant test for the world-aligned dyadic lattice. Checks the resolution ladder, parent/child
// round-trips, the negative-index case where >> and / disagree, four children exactly covering one
// parent, and agreement between per-level indexing and shifting from L0.
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
using veyra::core::CellId;
using veyra::core::cells_per_m;
using veyra::core::childrenOf;
using veyra::core::extentOf;
using veyra::core::parentOf;
using veyra::core::resolution_m;
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

}  // namespace

int main() {
  checkResolutionLadder();
  checkParentChildRoundTrip();
  checkNegativeIndices();
  checkChildrenCoverParent();
  checkDirectVsShiftAgreement();
  return 0;
}
