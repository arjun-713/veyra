#include "veyra/map/fusion.hpp"

#include <cmath>

#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"

namespace veyra::map {

FusionStats integrate(TileGrid& grid, std::span<const Observation> points,
                      std::uint32_t frame_index) {
  FusionStats stats;
  for (const Observation& o : points) {
    // Finite first, always. Every comparison against NaN is false, so a NaN
    // would slip through the range test below and reach the double-to-int32
    // conversion in worldToKey, which is undefined behaviour.
    if (!std::isfinite(o.x) || !std::isfinite(o.y) || !std::isfinite(o.z)) {
      ++stats.rejected_non_finite;
      continue;
    }
    if (o.x < -kMapHalfExtentM || o.x >= kMapHalfExtentM || o.y < -kMapHalfExtentM ||
        o.y >= kMapHalfExtentM) {
      ++stats.rejected_out_of_range;
      continue;
    }
    const core::CellId id = core::worldToKey(o.x, o.y, 0);
    const bool created = grid.find(id) == nullptr;
    Cell& cell = grid.findOrCreate(id);
    // Read last_seen before stamping it: cells_touched counts cells first
    // seen in this frame, so a second point landing in the same cell in the
    // same frame must not count again.
    const bool first_this_frame = created || cell.last_seen != frame_index;

    updateCell(cell, static_cast<double>(o.z));
    cell.last_seen = frame_index;

    ++stats.accepted;
    stats.cells_created += static_cast<std::size_t>(created);
    stats.cells_touched += static_cast<std::size_t>(first_this_frame);
  }
  return stats;
}

}  // namespace veyra::map
