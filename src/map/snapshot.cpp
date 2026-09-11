#include "veyra/map/snapshot.hpp"

namespace veyra::map {

MapSnapshot snapshot(const TileGrid& grid, std::uint32_t frame_index) {
  MapSnapshot out;
  out.stats_ = grid.statistics();
  out.centre_x_ = grid.window().centre_x;
  out.centre_y_ = grid.window().centre_y;
  out.frame_ = frame_index;

  // One allocation, not a growth sequence: statistics() already knows how many
  // active leaves there are.
  out.cells_.reserve(out.stats_.occupied_cells);
  grid.forEachActiveLeaf(
      [&out](core::CellId id, const Cell& cell) { out.cells_.push_back(SnapshotCell{id, cell}); });
  return out;
}

}  // namespace veyra::map
