#include "veyra/map/resolution_pass.hpp"

#include <cmath>
#include <vector>

namespace veyra::map {
namespace {

double rangeTo(const PassContext& ctx, core::CellId id) {
  const core::CellExtent e = core::extentOf(id);
  const double dx = 0.5 * (e.min_x + e.max_x) - ctx.vehicle_x;
  const double dy = 0.5 * (e.min_y + e.max_y) - ctx.vehicle_y;
  return std::sqrt(dx * dx + dy * dy);
}

int requestedLevel(policy::LodPolicy& pol, core::CellId id, double range_m) {
  policy::DecisionInput in;
  in.range_m = range_m;
  in.active_level = id.level;
  in.state_cell = id;
  return pol.decide(in).requested_level;
}

}  // namespace

PolicyStats applyPolicy(TileGrid& grid, policy::LodPolicy& pol, const PassContext& ctx) {
  PolicyStats stats;

  // Snapshot first: split and merge mutate the grid, so the walk cannot run
  // over live storage. One allocation per pass, not per cell.
  std::vector<core::CellId> leaves;
  grid.forEachActiveLeaf([&leaves](core::CellId id, const Cell&) { leaves.push_back(id); });

  std::size_t ops = 0;
  for (const core::CellId id : leaves) {
    // A sibling's merge may already have consumed this cell.
    if (grid.find(id) == nullptr) {
      continue;
    }
    ++stats.examined;

    const double range = rangeTo(ctx, id);
    const int want = requestedLevel(pol, id, range);
    if (want == id.level) {
      continue;
    }

    // Hysteresis, expressed through the policy rather than by duplicating its
    // thresholds: the same level must still be wanted a margin further into
    // the move. A cell sitting on a boundary therefore stays put.
    //
    // This evaluates the policy twice per candidate. For a stateless policy --
    // Uniform5, Uniform40, DistanceLod -- that is free of side effects. A
    // stateful one would see two frames per frame, so when UtilityLOD lands
    // the pass needs a dwell counter instead. Recorded rather than assumed.
    const double probe = (want < id.level) ? range + kHysteresisM : range - kHysteresisM;
    if (requestedLevel(pol, id, probe > 0.0 ? probe : 0.0) != want) {
      ++stats.held_by_hysteresis;
      continue;
    }

    // The safety floor, checked before the cap so that protection is never a
    // casualty of a busy frame.
    if (want > id.level && range < kNearFieldRadiusM) {
      ++stats.near_field_protected;
      continue;
    }

    if (ops >= kMaxOpsPerPass) {
      ++stats.deferred;
      continue;
    }

    const bool ok = (want < id.level) ? split(grid, id) : merge(grid, core::parentOf(id));
    ++ops;
    if (!ok) {
      ++stats.refused;
    } else if (want < id.level) {
      ++stats.splits;
    } else {
      ++stats.merges;
    }
  }
  return stats;
}

}  // namespace veyra::map
