// Invariant test for the world-aligned dyadic lattice. Checks the resolution ladder, and
// parent/child round-trips.
#include <array>
#include <cmath>
#include <cstddef>

#include "check.hpp"
#include "veyra/core/types.hpp"

namespace {

using veyra::core::CellId;
using veyra::core::cells_per_m;
using veyra::core::childrenOf;
using veyra::core::parentOf;
using veyra::core::resolution_m;

constexpr double kEps = 1e-9;

bool approxEq(double a, double b) { return std::fabs(a - b) < kEps; }

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

}  // namespace

int main() {
  checkResolutionLadder();
  checkParentChildRoundTrip();
  return 0;
}
