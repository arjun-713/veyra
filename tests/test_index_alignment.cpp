// Minimal invariant test: resolution(l) = 0.05 * 2^l.
#include <cmath>

#include "check.hpp"
#include "veyra/core/types.hpp"

namespace {

using veyra::core::resolution_m;

constexpr double kEps = 1e-9;

bool approxEq(double a, double b) { return std::fabs(a - b) < kEps; }

}  // namespace

int main() {
  CHECK(approxEq(resolution_m(0), 0.05));
  CHECK(approxEq(resolution_m(1), 0.10));
  CHECK(approxEq(resolution_m(2), 0.20));
  CHECK(approxEq(resolution_m(3), 0.40));
  // Exact hierarchy: parent width == 2 * child width at every level.
  for (int l = 0; l < 3; ++l) {
    CHECK(approxEq(resolution_m(l + 1), 2.0 * resolution_m(l)));
  }
  return 0;
}
