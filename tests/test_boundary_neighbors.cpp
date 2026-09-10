// Invariant test for mixed-resolution neighbour queries. docs/architecture.md
// requires neighbours to understand resolution: a coarse cell bordering finer
// ground has several active neighbours along that edge, and each of those has
// one neighbour several times its size.
//
// This is invariant A seen sideways -- every stretch of edge is covered by
// exactly one active leaf. Each group names the production bug it catches.
#include <cstddef>
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/neighbors.hpp"
#include "veyra/map/rolling_window.hpp"
#include "veyra/map/tile_grid.hpp"

namespace {

using veyra::core::CellId;
using veyra::map::MapWindow;
using veyra::map::TileGrid;

std::vector<CellId> neighborsOf(const TileGrid& grid, CellId id, std::size_t* uncovered = nullptr) {
  std::vector<CellId> out;
  const std::size_t gaps =
      veyra::map::forEachNeighbor(grid, id, [&out](CellId n) { out.push_back(n); });
  if (uncovered != nullptr) {
    *uncovered = gaps;
  }
  return out;
}

// 1. On a uniform grid every interior cell has exactly four neighbours, one
//    per edge, all at its own level.
//    Catches: an edge dropped from the scan, and a same-level lookup that
//    misses an active cell.
void checkUniformGridHasFourNeighbors() {
  TileGrid grid{MapWindow{0.0, 0.0, 5.0}};
  for (std::int32_t iy = -4; iy <= 4; ++iy) {
    for (std::int32_t ix = -4; ix <= 4; ++ix) {
      grid.findOrCreate(CellId{0, ix, iy});
    }
  }

  std::size_t gaps = 0;
  const std::vector<CellId> n = neighborsOf(grid, CellId{0, 0, 0}, &gaps);
  CHECK(n.size() == 4);
  CHECK(gaps == 0);
  for (const CellId c : n) {
    CHECK(c.level == 0);
    CHECK(grid.find(c) != nullptr);
  }

  // The four are the cardinal neighbours, each exactly once.
  int east = 0;
  int west = 0;
  int north = 0;
  int south = 0;
  for (const CellId c : n) {
    east += static_cast<int>(c == (CellId{0, 1, 0}));
    west += static_cast<int>(c == (CellId{0, -1, 0}));
    north += static_cast<int>(c == (CellId{0, 0, 1}));
    south += static_cast<int>(c == (CellId{0, 0, -1}));
  }
  CHECK(east == 1);
  CHECK(west == 1);
  CHECK(north == 1);
  CHECK(south == 1);
}

}  // namespace

int main() {
  checkUniformGridHasFourNeighbors();
  return 0;
}
