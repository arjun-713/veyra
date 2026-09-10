#include "veyra/map/tile_grid.hpp"

namespace veyra::map {

Cell* TileGrid::find(core::CellId id) {
  const auto it = tiles_.find(tileOf(id));
  if (it == tiles_.end()) {
    return nullptr;
  }
  const std::size_t slot = slotOf(id);
  if (!it->second.test(slot)) {
    return nullptr;
  }
  return &it->second.cells[slot];
}

const Cell* TileGrid::find(core::CellId id) const {
  const auto it = tiles_.find(tileOf(id));
  if (it == tiles_.end()) {
    return nullptr;
  }
  const std::size_t slot = slotOf(id);
  if (!it->second.test(slot)) {
    return nullptr;
  }
  return &it->second.cells[slot];
}

// The only allocating path in this file, and it allocates a whole tile or
// nothing at all -- never one allocation per cell.
Cell& TileGrid::findOrCreate(core::CellId id) {
  Tile& tile = tiles_[tileOf(id)];
  const std::size_t slot = slotOf(id);
  if (!tile.test(slot)) {
    tile.set(slot);
    ++tile.live;
  }
  return tile.cells[slot];
}

// A tile whose last cell is erased is released. The alternative -- retaining
// empty tiles -- would leave the rolling window's memory unbounded later.
bool TileGrid::erase(core::CellId id) {
  const auto it = tiles_.find(tileOf(id));
  if (it == tiles_.end()) {
    return false;
  }
  const std::size_t slot = slotOf(id);
  if (!it->second.test(slot)) {
    return false;
  }
  it->second.clear(slot);
  --it->second.live;
  it->second.cells[slot] = Cell{};
  if (it->second.live == 0) {
    tiles_.erase(it);
  }
  return true;
}

GridStats TileGrid::statistics() const {
  GridStats s;
  s.tiles = tiles_.size();
  for (const auto& entry : tiles_) {
    s.occupied_cells += entry.second.live;
  }
  // Derived from sizeof, never written down: counts tile payload only, not
  // the hash map's own bookkeeping.
  s.allocated_bytes = s.tiles * sizeof(Tile);
  if (s.tiles != 0) {
    s.occupancy =
        static_cast<double>(s.occupied_cells) / static_cast<double>(s.tiles * kCellsPerTile);
  }
  return s;
}

}  // namespace veyra::map
