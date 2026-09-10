// Invariant test for map snapshots: a read-only, self-owning copy of the
// active leaves at one instant, so a consumer can read the map without
// walking live tile storage that may change under them.
//
// Each group names the production bug it exists to catch.
#include <cstddef>
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/rolling_window.hpp"
#include "veyra/map/snapshot.hpp"
#include "veyra/map/tile_grid.hpp"

namespace {

using veyra::core::CellId;
using veyra::map::MapSnapshot;
using veyra::map::MapWindow;
using veyra::map::TileGrid;

// 1. An empty grid snapshots to an empty snapshot: no cells, zero statistics,
//    and iteration that visits nothing.
//    Catches: a snapshot that fabricates entries, and iteration bounds taken
//    from capacity rather than size.
void checkEmptyGrid() {
  const TileGrid grid;
  const MapSnapshot snap = veyra::map::snapshot(grid, 0);

  CHECK(snap.size() == 0);
  CHECK(snap.statistics().occupied_cells == 0);
  CHECK(snap.statistics().tiles == 0);
  CHECK(snap.statistics().allocated_bytes == 0);

  std::size_t visited = 0;
  snap.forEachCell([&visited](const veyra::map::SnapshotCell&) { ++visited; });
  CHECK(visited == 0);
}

}  // namespace

int main() {
  checkEmptyGrid();
  return 0;
}
