#include "veyra/map/split_merge.hpp"

#include <array>

#include "veyra/map/cell.hpp"

namespace veyra::map {

bool split(TileGrid& grid, core::CellId parent) {
  // Level 0 is the floor. Without this an unguarded level - 1 would create
  // cells at level -1: a key that hashes and compares perfectly well but names
  // a resolution that does not exist.
  if (parent.level <= 0 || parent.level > kMaxLevel) {
    return false;
  }
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
