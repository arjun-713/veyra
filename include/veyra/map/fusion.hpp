#pragma once
#include <cstddef>
#include <cstdint>
#include <span>

#include "veyra/map/observation.hpp"
#include "veyra/map/tile_grid.hpp"

namespace veyra::map {

// Half-open map extent per axis, in metres: a point is inside when
// -kMapHalfExtentM <= v < +kMapHalfExtentM.
//
// PROPOSAL. Nothing in the repository defines a map extent; this is derived
// from the outermost band of configs/distance_lod.yaml (0-10, 10-30, 30-60,
// 60-100), and needs sign-off alongside Observation.
//
// It is a safety gate as well as a policy: worldToKey casts a double to
// int32_t, and converting an out-of-range or non-finite double to an integer
// is undefined behaviour. That is why the range check exists even though a
// stray point would "only" allocate a distant tile.
inline constexpr double kMapHalfExtentM = 100.0;

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
