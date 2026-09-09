// Invariant test for the world-aligned dyadic lattice. Checks the resolution ladder.
#include <cmath>

#include "check.hpp"
#include "veyra/core/types.hpp"

namespace {

using veyra::core::cells_per_m;
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

}  // namespace

int main() {
  checkResolutionLadder();
  return 0;
}
