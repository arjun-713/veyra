// Invariant test for observation intake and fusion: invariant 1 of
// docs/map-correctness.md -- every accepted XY observation belongs to exactly
// one active leaf, and every point offered is either accepted or rejected.
//
// Each group names the production bug it exists to catch.
#include <cstddef>
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"
#include "veyra/map/fusion.hpp"
#include "veyra/map/observation.hpp"
#include "veyra/map/tile_grid.hpp"

namespace {

using veyra::map::FusionStats;
using veyra::map::integrate;
using veyra::map::Observation;
using veyra::map::TileGrid;

Observation obs(double x, double y, float z) {
  Observation o;
  o.x = x;
  o.y = y;
  o.z = z;
  o.cls = 1;
  o.confidence = 1.0F;
  return o;
}

// 1. Conservation: every point offered is accounted for exactly once, as
//    either accepted or rejected -- never both, never neither.
//    Catches: a counter incremented on both paths, or a path that silently
//    drops a point without counting it.
void checkConservation() {
  TileGrid grid;

  const FusionStats empty = integrate(grid, {}, 0);
  CHECK(empty.accepted + empty.rejected() == 0);

  const std::vector<Observation> batch = {obs(0.0, 0.0, 1.0F), obs(1.0, 1.0, 2.0F),
                                          obs(-1.0, -1.0, 3.0F)};
  const FusionStats s = integrate(grid, batch, 0);
  CHECK(s.accepted + s.rejected() == batch.size());
}

// 2. Unique ownership (invariant 1). A point belongs to exactly one cell:
//    two points inside the same 5 cm square make one cell holding both, and
//    two points in adjacent squares make two cells holding one each.
//    Catches: a point written to more than one cell, and an index that
//    collapses adjacent cells together.
void checkUniqueOwnership() {
  TileGrid same;
  const std::vector<Observation> together = {obs(0.01, 0.01, 1.0F), obs(0.04, 0.04, 3.0F)};
  const FusionStats a = integrate(same, together, 0);
  CHECK(a.accepted == 2);
  CHECK(same.statistics().occupied_cells == 1);
  const veyra::map::Cell* one = same.find(veyra::core::CellId{0, 0, 0});
  CHECK(one != nullptr);
  CHECK(one->count == 2);

  TileGrid apart;
  const std::vector<Observation> separate = {obs(0.01, 0.01, 1.0F), obs(0.06, 0.01, 2.0F)};
  const FusionStats b = integrate(apart, separate, 0);
  CHECK(b.accepted == 2);
  CHECK(apart.statistics().occupied_cells == 2);
  CHECK(apart.find(veyra::core::CellId{0, 0, 0})->count == 1);
  CHECK(apart.find(veyra::core::CellId{0, 1, 0})->count == 1);
}

}  // namespace

int main() {
  checkConservation();
  checkUniqueOwnership();
  return 0;
}
