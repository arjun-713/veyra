// Minimal invariant test: resolution(l) = 0.05 * 2^l, 4 children cover 1 parent.
#include <cassert>
#include <cmath>

#include "veyra/core/types.hpp"

int main() {
  using veyra::core::resolution_m;
  assert(std::fabs(resolution_m(0) - 0.05) < 1e-9);
  assert(std::fabs(resolution_m(1) - 0.10) < 1e-9);
  assert(std::fabs(resolution_m(2) - 0.20) < 1e-9);
  assert(std::fabs(resolution_m(3) - 0.40) < 1e-9);
  // Exact hierarchy: parent width == 2 * child width at every level.
  for (int l = 0; l < 3; ++l) {
    assert(std::fabs(resolution_m(l + 1) - 2.0 * resolution_m(l)) < 1e-9);
  }
  return 0;
}
