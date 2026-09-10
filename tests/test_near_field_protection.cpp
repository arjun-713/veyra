// Invariant test for the safety floor: cells within kNearFieldRadiusM of the
// vehicle are never coarsened, whatever any policy asks.
//
// This is a refusal enforced by the pass, not a rule DistanceLOD happens to
// obey -- a future UtilityLOD or a resource governor under memory pressure
// must be unable to coarsen the near field. The tests therefore drive it with
// a deliberately hostile policy rather than the distance one.
//
// Each group names the production bug it catches.
#include <cstddef>
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/resolution_pass.hpp"
#include "veyra/map/rolling_window.hpp"
#include "veyra/map/tile_grid.hpp"
#include "veyra/policy/policy.hpp"

namespace {

using veyra::core::CellId;
using veyra::map::MapWindow;
using veyra::map::PassContext;
using veyra::map::TileGrid;

// Uniform40 asks for level 3 everywhere, so it tries to coarsen every cell in
// the map including the near field. That is exactly the request the floor
// exists to refuse.
veyra::policy::LodPolicy hostilePolicy() {
  return veyra::policy::LodPolicy{
      veyra::policy::PolicyConfig::defaults().with_mode(veyra::policy::LodMode::Uniform40)};
}

// 15. A hostile policy cannot coarsen a cell inside the near-field radius.
//     Catches: near-field protection missing entirely, and protection applied
//     as a policy preference rather than a refusal -- a policy that ignores it
//     would then win.
void checkHostilePolicyCannotCoarsenNearField() {
  TileGrid grid{MapWindow{0.0, 0.0, 60.0}};
  // A near cell, well inside 10 m, and a far cell well outside it.
  const CellId near_cell{0, 20, 0};  // 1.0 m out
  const CellId far_cell{0, 800, 0};  // 40 m out
  grid.findOrCreate(near_cell);
  grid.findOrCreate(far_cell);

  veyra::policy::LodPolicy pol = hostilePolicy();
  const veyra::map::PolicyStats s = veyra::map::applyPolicy(grid, pol, PassContext{0.0, 0.0});

  CHECK(s.near_field_protected > 0);
  // The near cell is still there, still at level 0.
  CHECK(grid.find(near_cell) != nullptr);
  const veyra::map::LeafHit hit = veyra::map::activeLeafCovering(grid, 1.0, 0.0);
  CHECK(hit.found);
  CHECK(hit.id.level == 0);
}

}  // namespace

int main() {
  checkHostilePolicyCannotCoarsenNearField();
  return 0;
}
