#pragma once
#include <cstddef>

#include "veyra/map/split_merge.hpp"
#include "veyra/map/tile_grid.hpp"
#include "veyra/policy/policy.hpp"

namespace veyra::map {

// Safety floor. Cells within this radius of the vehicle are never coarsened,
// whatever any policy asks.
//
// Enforced here as a refusal rather than left to each policy to respect: a
// future UtilityLOD, or a resource governor shedding memory under pressure,
// must be *unable* to coarsen the near field. AGENTS.md states the rule; this
// is where it becomes true.
//
// Mirrors ResourceGovernorConfig::near_field_radius_m in veyra::policy, which
// is the governor's own view of the same 10 m.
inline constexpr double kNearFieldRadiusM = 10.0;

// Cap on split and merge operations per pass, so a map-wide reshuffle cannot
// become a latency spike. Work beyond the cap is deferred and counted, never
// dropped silently -- PolicyStats::deferred makes the backlog visible.
inline constexpr std::size_t kMaxOpsPerPass = 256;

// A cell must be at least this far past a band boundary before the pass acts.
// Without it a cell sitting on a boundary splits and merges on alternate
// frames, which is allocation churn on the hot path.
inline constexpr double kHysteresisM = 1.0;

struct PassContext {
  double vehicle_x = 0.0;
  double vehicle_y = 0.0;
};

struct PolicyStats {
  std::size_t examined = 0;
  std::size_t splits = 0;
  std::size_t merges = 0;
  std::size_t refused = 0;               // split/merge declined on a precondition
  std::size_t deferred = 0;              // wanted work, but the cap was reached
  std::size_t held_by_hysteresis = 0;    // inside the margin, deliberately idle
  std::size_t near_field_protected = 0;  // coarsening refused by the safety floor
};

// Walks the active leaves once and moves them toward the level the policy
// asks for, one ladder step per cell per pass.
//
// The policy proposes and the grid disposes: nothing here lets a policy reach
// the grid, and a refusal from split or merge is a normal outcome that is
// counted, not an error.
PolicyStats applyPolicy(TileGrid& grid, policy::LodPolicy& pol, const PassContext& ctx);

}  // namespace veyra::map
