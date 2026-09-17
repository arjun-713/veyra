#pragma once
#include <cstddef>
#include <cstdint>
#include <span>

#include "veyra/map/observation.hpp"
#include "veyra/map/rolling_window.hpp"
#include "veyra/map/tile_grid.hpp"

namespace veyra::map {

struct FusionStats {
  std::size_t accepted = 0;
  std::size_t rejected_out_of_range = 0;
  std::size_t rejected_non_finite = 0;
  // The canonical Observation supports uint16 semantic ids while the legacy
  // compact TileGrid cell stores uint8. Such a point still contributes
  // geometry, but this counter prevents the label from being truncated.
  std::size_t semantic_labels_unrepresentable = 0;
  std::size_t cells_touched = 0;
  std::size_t cells_created = 0;

  std::size_t rejected() const { return rejected_out_of_range + rejected_non_finite; }
};

// Folds a batch of observations into the grid at level 0.
//
// A point is in range when its cell is inside the grid's window -- the same
// predicate recenter() evicts by, on the same argument type. There is no
// second range gate anchored to the odom origin; two range checks that can
// disagree is the bug this replaced.
FusionStats integrate(TileGrid& grid, std::span<const Observation> points,
                      std::uint32_t frame_index);

}  // namespace veyra::map
