// Invariant test for the world-aligned dyadic lattice. Checks the resolution ladder, parent/child
// round-trips, and the negative-index case where >> and / disagree.
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>

#include "check.hpp"
#include "veyra/core/types.hpp"

namespace {

using veyra::core::CellExtent;
using veyra::core::CellId;
using veyra::core::cells_per_m;
using veyra::core::childrenOf;
using veyra::core::parentOf;
using veyra::core::resolution_m;

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

}  // namespace

int main() {
  checkResolutionLadder();
  checkParentChildRoundTrip();
  checkNegativeIndices();
  return 0;
}
