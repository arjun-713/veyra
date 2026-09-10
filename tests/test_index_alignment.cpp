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

  // Floor division at the negative seam must agree with the dyadic parent
  // relationship: parent -1 covers children -2 and -1, never 0.
  for (const auto parent_x : {-2, -1, 0, 1}) {
    for (const auto parent_y : {-2, -1, 0, 1}) {
      const veyra::core::CellId parent{1, parent_x, parent_y};
      for (const auto dx : {0, 1}) {
        for (const auto dy : {0, 1}) {
          const veyra::core::CellId child{0, parent_x * 2 + dx,
                                          parent_y * 2 + dy};
          assert(child.parent() == parent);
        }
      }
    }
  }
  assert((veyra::core::CellId{0, -1, -1}.parent() ==
          veyra::core::CellId{1, -1, -1}));
  assert((veyra::core::CellId{0, -2, -2}.parent() ==
          veyra::core::CellId{1, -1, -1}));
  return 0;
}
