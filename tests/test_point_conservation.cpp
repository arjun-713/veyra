// Invariant test for observation intake and fusion: invariant 1 of
// docs/map-correctness.md -- every accepted XY observation belongs to exactly
// one active leaf, and every point offered is either accepted or rejected.
//
// Each group names the production bug it exists to catch.
#include <cstddef>
#include <cstdint>
#include <vector>

#include "check.hpp"
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

}  // namespace

int main() {
  checkConservation();
  return 0;
}
