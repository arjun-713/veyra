#pragma once
#include <cstddef>
#include <cstdint>
#include <span>

#include "veyra/map/observation.hpp"
#include "veyra/map/tile_grid.hpp"

namespace veyra::map {

struct FusionStats {
  std::size_t accepted = 0;
  std::size_t rejected_out_of_range = 0;
  std::size_t rejected_non_finite = 0;
  std::size_t cells_touched = 0;
  std::size_t cells_created = 0;

  std::size_t rejected() const { return rejected_out_of_range + rejected_non_finite; }
};

// Folds a batch of observations into the grid at level 0.
FusionStats integrate(TileGrid& grid, std::span<const Observation> points,
                      std::uint32_t frame_index);

}  // namespace veyra::map
