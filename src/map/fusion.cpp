#include "veyra/map/fusion.hpp"

namespace veyra::map {

FusionStats integrate(TileGrid& grid, std::span<const Observation> points,
                      std::uint32_t frame_index) {
  (void)grid;
  (void)frame_index;
  FusionStats stats;
  stats.accepted = points.size();
  return stats;
}

}  // namespace veyra::map
