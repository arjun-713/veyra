#include "veyra/map/fusion.hpp"

#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"

namespace veyra::map {

FusionStats integrate(TileGrid& grid, std::span<const Observation> points,
                      std::uint32_t frame_index) {
  (void)frame_index;
  FusionStats stats;
  for (const Observation& o : points) {
    const core::CellId id = core::worldToKey(o.x, o.y, 0);
    Cell& cell = grid.findOrCreate(id);
    updateCell(cell, static_cast<double>(o.z));
    ++stats.accepted;
  }
  return stats;
}

}  // namespace veyra::map
