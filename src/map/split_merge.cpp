#include "veyra/map/split_merge.hpp"

#include <array>

#include "veyra/map/cell.hpp"

namespace veyra::map {

bool split(TileGrid& grid, core::CellId parent) {
  const Cell* found = grid.find(parent);
  if (found == nullptr) {
    return false;
  }
  const Cell src = *found;  // copied before the parent is erased

  grid.erase(parent);
  for (const core::CellId child : core::childrenOf(parent)) {
    grid.findOrCreate(child) = src;
  }
  return true;
}

}  // namespace veyra::map
