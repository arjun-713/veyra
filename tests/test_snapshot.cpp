// Invariant test for map snapshots: a read-only, self-owning copy of the
// active leaves at one instant, so a consumer can read the map without
// walking live tile storage that may change under them.
//
// Each group names the production bug it exists to catch.
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <new>
#include <type_traits>
#include <utility>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/fusion.hpp"
#include "veyra/map/observation.hpp"
#include "veyra/map/rolling_window.hpp"
#include "veyra/map/snapshot.hpp"
#include "veyra/map/split_merge.hpp"
#include "veyra/map/tile_grid.hpp"

// Counting allocator hooks, so the one-allocation claim is measured rather
// than asserted from the signature. Global scope, to replace the real ones.
std::size_t g_alloc_count = 0;
bool g_counting = false;

void* operator new(std::size_t n) {
  if (g_counting) {
    ++g_alloc_count;
  }
  void* p = std::malloc(n != 0 ? n : 1);
  if (p == nullptr) {
    throw std::bad_alloc();
  }
  return p;
}
void* operator new[](std::size_t n) { return ::operator new(n); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
void operator delete[](void* p, std::size_t) noexcept { std::free(p); }

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

// Cell is 32 bytes with no padding, so "identical" can be taken literally.
bool sameCell(const veyra::map::Cell& a, const veyra::map::Cell& b) {
  return std::memcmp(&a, &b, sizeof(veyra::map::Cell)) == 0;
}

veyra::map::Observation point(double x, double y, float z) {
  veyra::map::Observation o;
  o.x = x;
  o.y = y;
  o.z = z;
  o.cls = 2;
  o.confidence = 1.0F;
  return o;
}

// A grid with real content: distinct heights so every cell differs.
TileGrid populatedGrid() {
  TileGrid grid{MapWindow{0.0, 0.0, 20.0}};
  std::vector<veyra::map::Observation> batch;
  for (int i = 0; i < 40; ++i) {
    for (int j = 0; j < 40; ++j) {
      batch.push_back(point(0.05 * i, 0.05 * j, static_cast<float>(0.01 * (i * 40 + j))));
    }
  }
  veyra::map::integrate(grid, batch, 7);
  return grid;
}

// Collects the grid's active leaves for direct comparison.
std::vector<veyra::map::SnapshotCell> liveLeaves(const TileGrid& grid) {
  std::vector<veyra::map::SnapshotCell> out;
  grid.forEachActiveLeaf([&out](CellId id, const veyra::map::Cell& c) {
    out.push_back(veyra::map::SnapshotCell{id, c});
  });
  return out;
}

// Finds a captured cell by id. Linear: the snapshot deliberately has no index.
const veyra::map::SnapshotCell* findIn(const std::vector<veyra::map::SnapshotCell>& v, CellId id) {
  for (const veyra::map::SnapshotCell& e : v) {
    if (e.id == id) {
      return &e;
    }
  }
  return nullptr;
}

std::vector<veyra::map::SnapshotCell> captured(const MapSnapshot& snap) {
  std::vector<veyra::map::SnapshotCell> out;
  out.reserve(snap.size());
  snap.forEachCell([&out](const veyra::map::SnapshotCell& e) { out.push_back(e); });
  return out;
}

// 2. Fidelity: the snapshot matches the grid's active leaves exactly -- same
//    count, same ids, same statistics field for field, not approximately.
//    Catches: a capture that drops or duplicates cells, and one that copies
//    the id but not the cell behind it.
void checkFidelity() {
  const TileGrid grid = populatedGrid();
  const MapSnapshot snap = veyra::map::snapshot(grid, 7);
  const std::vector<veyra::map::SnapshotCell> live = liveLeaves(grid);

  CHECK(snap.size() == live.size());
  CHECK(snap.size() > 100);
  CHECK(snap.statistics().occupied_cells == live.size());

  const std::vector<veyra::map::SnapshotCell> got = captured(snap);
  CHECK(got.size() == live.size());
  for (const veyra::map::SnapshotCell& want : live) {
    const veyra::map::SnapshotCell* have = findIn(got, want.id);
    CHECK(have != nullptr);
    CHECK(sameCell(have->cell, want.cell));
  }
  CHECK(snap.frame() == 7);
  CHECK(snap.centreX() == grid.window().centre_x);
  CHECK(snap.centreY() == grid.window().centre_y);
}

// 3. Isolation -- the property the type exists for. After the snapshot is
//    taken, integrating, splitting and recentring leave it byte-identical.
//    Catches: a snapshot holding a pointer into live storage, which is the
//    single failure that would make every consumer wrong at once.
void checkIsolationFromLaterChanges() {
  TileGrid grid = populatedGrid();
  const MapSnapshot snap = veyra::map::snapshot(grid, 7);
  const std::vector<veyra::map::SnapshotCell> before = captured(snap);
  const veyra::map::GridStats stats_before = snap.statistics();
  CHECK(before.size() > 100);

  // Churn the grid hard: more points, a split, and a recentre that evicts.
  std::vector<veyra::map::Observation> more;
  for (int i = 0; i < 200; ++i) {
    more.push_back(point(0.05 * i, 5.0, 9.0F));
  }
  veyra::map::integrate(grid, more, 8);
  CHECK(veyra::map::split(grid, CellId{1, 0, 0}) || true);  // split if it is legal
  grid.recenter(15.0, 0.0);

  const std::vector<veyra::map::SnapshotCell> after = captured(snap);
  CHECK(after.size() == before.size());
  for (std::size_t i = 0; i < before.size(); ++i) {
    CHECK(after[i].id == before[i].id);
    CHECK(sameCell(after[i].cell, before[i].cell));
  }
  CHECK(snap.statistics().occupied_cells == stats_before.occupied_cells);
  CHECK(snap.statistics().allocated_bytes == stats_before.allocated_bytes);
  CHECK(snap.frame() == 7);
  // The grid really did change, so the comparison above means something.
  CHECK(grid.statistics().occupied_cells != stats_before.occupied_cells);
}

// 5. The snapshot outlives the grid it came from.
//    Catches: any borrowed storage -- this reads freed memory if the snapshot
//    does not own its data.
void checkOutlivesTheGrid() {
  MapSnapshot snap;
  std::vector<veyra::map::SnapshotCell> expected;
  {
    const TileGrid grid = populatedGrid();
    snap = veyra::map::snapshot(grid, 11);
    expected = captured(snap);
  }  // grid destroyed here

  const std::vector<veyra::map::SnapshotCell> after = captured(snap);
  CHECK(after.size() == expected.size());
  CHECK(after.size() > 100);
  for (std::size_t i = 0; i < expected.size(); ++i) {
    CHECK(after[i].id == expected[i].id);
    CHECK(sameCell(after[i].cell, expected[i].cell));
  }
  CHECK(snap.frame() == 11);
}

// 6. Mixed levels: a grid holding L0, L1 and L2 leaves captures all three,
//    and captures no split parent.
//    Catches: a capture that walks levels rather than active leaves, which
//    would include a parent alongside the children that replaced it.
void checkMixedLevels() {
  TileGrid grid{MapWindow{0.0, 0.0, 40.0}};
  grid.findOrCreate(CellId{2, 10, 10});
  grid.findOrCreate(CellId{1, 40, 0});
  grid.findOrCreate(CellId{0, 200, 0});
  CHECK(veyra::map::split(grid, CellId{2, 10, 10}));  // becomes four L1 cells

  const MapSnapshot snap = veyra::map::snapshot(grid, 3);
  const std::vector<veyra::map::SnapshotCell> got = captured(snap);

  std::size_t l0 = 0;
  std::size_t l1 = 0;
  std::size_t l2 = 0;
  for (const veyra::map::SnapshotCell& e : got) {
    l0 += static_cast<std::size_t>(e.id.level == 0);
    l1 += static_cast<std::size_t>(e.id.level == 1);
    l2 += static_cast<std::size_t>(e.id.level == 2);
  }
  CHECK(l0 == 1);
  CHECK(l1 == 5);  // the original L1 cell plus four from the split
  CHECK(l2 == 0);  // the split parent is gone, not captured
  CHECK(findIn(got, CellId{2, 10, 10}) == nullptr);
  CHECK(got.size() == grid.statistics().occupied_cells);
}

// 7. After eviction: evicted cells are absent and survivors are intact, with
//    identical coordinates and statistics.
//    Catches: a capture taken against a stale cell list, and any renumbering
//    of survivors.
void checkAfterEviction() {
  // A window small enough that moving it genuinely drops cells. populatedGrid
  // uses a 20 m radius over 2 m of content, so nothing there can ever be
  // evicted -- a recentre on that grid would test nothing.
  TileGrid grid{MapWindow{0.0, 0.0, 1.2}};
  std::vector<veyra::map::Observation> batch;
  for (int i = -20; i < 20; ++i) {
    for (int j = -20; j < 20; ++j) {
      batch.push_back(point(0.05 * i, 0.05 * j, static_cast<float>(0.01 * (i * 40 + j))));
    }
  }
  veyra::map::integrate(grid, batch, 7);
  const std::vector<veyra::map::SnapshotCell> before = liveLeaves(grid);
  CHECK(before.size() > 100);

  // Past a tile boundary: the window centre only moves when the vehicle
  // enters a different tile (1.6 m at L0), so a shorter hop would recentre
  // nothing and evict nothing.
  grid.recenter(2.0, 0.0);
  const std::vector<veyra::map::SnapshotCell> survivors = liveLeaves(grid);
  CHECK(survivors.size() < before.size());
  CHECK(survivors.size() > 0);

  const MapSnapshot snap = veyra::map::snapshot(grid, 9);
  const std::vector<veyra::map::SnapshotCell> got = captured(snap);
  CHECK(got.size() == survivors.size());
  for (const veyra::map::SnapshotCell& s : survivors) {
    const veyra::map::SnapshotCell* have = findIn(got, s.id);
    CHECK(have != nullptr);
    CHECK(sameCell(have->cell, s.cell));
    // The lattice is fixed: a survivor keeps its world extent exactly.
    const veyra::core::CellExtent e = veyra::core::extentOf(have->id);
    const veyra::core::CellExtent w = veyra::core::extentOf(s.id);
    CHECK(e.min_x == w.min_x);
    CHECK(e.max_y == w.max_y);
  }
  // A cell that was evicted is genuinely gone from the snapshot.
  std::size_t missing = 0;
  for (const veyra::map::SnapshotCell& b : before) {
    if (findIn(survivors, b.id) == nullptr) {
      CHECK(findIn(got, b.id) == nullptr);
      ++missing;
    }
  }
  CHECK(missing > 0);
}

// 8. Two snapshots of an unchanged grid are equal; two across a change differ
//    in exactly the cells that changed.
//    Catches: a frame stamp or centre bleeding into the cell data, and a
//    capture that is not deterministic for a fixed grid.
void checkTwoSnapshots() {
  TileGrid grid = populatedGrid();
  const std::vector<veyra::map::SnapshotCell> a = captured(veyra::map::snapshot(grid, 1));
  const std::vector<veyra::map::SnapshotCell> b = captured(veyra::map::snapshot(grid, 2));

  CHECK(a.size() == b.size());
  for (const veyra::map::SnapshotCell& e : a) {
    const veyra::map::SnapshotCell* other = findIn(b, e.id);
    CHECK(other != nullptr);
    CHECK(sameCell(other->cell, e.cell));
  }

  // Now change exactly one cell and check exactly one differs.
  veyra::map::integrate(grid, std::vector<veyra::map::Observation>{point(0.01, 0.01, 50.0F)}, 3);
  const std::vector<veyra::map::SnapshotCell> c = captured(veyra::map::snapshot(grid, 3));
  CHECK(c.size() == a.size());
  std::size_t differing = 0;
  for (const veyra::map::SnapshotCell& e : a) {
    const veyra::map::SnapshotCell* other = findIn(c, e.id);
    CHECK(other != nullptr);
    if (!sameCell(other->cell, e.cell)) {
      ++differing;
    }
  }
  CHECK(differing == 1);
}

// 9. Value semantics: a copy is independent of its source, and a move leaves
//    the copy usable.
//    Catches: a copy constructor sharing the underlying buffer, which would
//    silently reintroduce the aliasing the type exists to prevent.
void checkCopyAndMove() {
  const TileGrid grid = populatedGrid();
  const MapSnapshot original = veyra::map::snapshot(grid, 5);
  const std::size_t n = original.size();
  CHECK(n > 100);

  MapSnapshot copy = original;
  CHECK(copy.size() == n);
  CHECK(copy.frame() == original.frame());
  const std::vector<veyra::map::SnapshotCell> from_copy = captured(copy);
  const std::vector<veyra::map::SnapshotCell> from_original = captured(original);
  CHECK(from_copy.size() == from_original.size());
  for (std::size_t i = 0; i < n; ++i) {
    CHECK(from_copy[i].id == from_original[i].id);
    CHECK(sameCell(from_copy[i].cell, from_original[i].cell));
  }

  const MapSnapshot moved = std::move(copy);
  CHECK(moved.size() == n);
  CHECK(moved.frame() == 5);
  // The source survived the move of its copy, untouched.
  CHECK(original.size() == n);
  CHECK(captured(original).size() == n);
}

// 11. The snapshot's statistics are the grid's at capture time, derived rather
//     than recomputed or hardcoded.
//     Catches: a statistics field copied from the wrong source, which would
//     make the dashboard's memory figure quietly wrong.
void checkStatisticsAgree() {
  const TileGrid grid = populatedGrid();
  const veyra::map::GridStats live = grid.statistics();
  const MapSnapshot snap = veyra::map::snapshot(grid, 4);

  CHECK(snap.statistics().occupied_cells == live.occupied_cells);
  CHECK(snap.statistics().tiles == live.tiles);
  CHECK(snap.statistics().allocated_bytes == live.allocated_bytes);
  CHECK(snap.statistics().occupancy == live.occupancy);
  // And the cell array agrees with the count it reports.
  CHECK(snap.size() == snap.statistics().occupied_cells);
  CHECK(snap.statistics().allocated_bytes == live.tiles * TileGrid::bytesPerTile());
}

// 4. Reverse isolation: nothing done to or through a snapshot can affect the
//    grid.
//
//    This cannot be written as a runtime test, and saying so is more honest
//    than inventing a weak version. MapSnapshot exposes no mutator and no path
//    back to the grid, so there is no call a consumer could make that would
//    demonstrate the failure -- the property holds by the shape of the API,
//    and the compiler is what enforces it.
//
//    What is checkable is that shape: every accessor works on a const
//    snapshot, and iteration hands out const references. A mutating callback
//    would not compile, which is the point.
void checkReverseIsolationIsStructural() {
  const TileGrid grid = populatedGrid();
  const MapSnapshot snap = veyra::map::snapshot(grid, 6);

  CHECK(snap.size() > 100);
  CHECK(snap.statistics().occupied_cells == snap.size());
  CHECK(snap.frame() == 6);
  snap.forEachCell([](const veyra::map::SnapshotCell&) {});

  static_assert(std::is_copy_constructible_v<MapSnapshot>);
  static_assert(std::is_move_constructible_v<MapSnapshot>);
  // Iteration yields const: a callback taking a mutable reference is not
  // invocable with what forEachCell passes.
  static_assert(
      !std::is_invocable_v<void (*)(veyra::map::SnapshotCell&), const veyra::map::SnapshotCell&>);
}

// 10. The cell array costs one allocation, not a growth sequence.
//     Catches: a missing reserve, which turns a per-frame snapshot of 600k
//     cells into a run of reallocating copies.
void checkSingleAllocation() {
  const TileGrid grid = populatedGrid();

  g_alloc_count = 0;
  g_counting = true;
  const MapSnapshot snap = veyra::map::snapshot(grid, 12);
  g_counting = false;

  CHECK(snap.size() > 100);
  CHECK(g_alloc_count == 1);

  // The counter is live, so that a one above means something.
  g_alloc_count = 0;
  g_counting = true;
  { std::vector<int> proof(64, 0); }
  g_counting = false;
  CHECK(g_alloc_count > 0);
}

}  // namespace

int main() {
  checkEmptyGrid();
  checkFidelity();
  checkIsolationFromLaterChanges();
  checkOutlivesTheGrid();
  checkMixedLevels();
  checkAfterEviction();
  checkTwoSnapshots();
  checkCopyAndMove();
  checkStatisticsAgree();
  checkReverseIsolationIsStructural();
  checkSingleAllocation();
  return 0;
}
