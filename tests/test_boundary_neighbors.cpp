// Invariant test for mixed-resolution neighbour queries. docs/architecture.md
// requires neighbours to understand resolution: a coarse cell bordering finer
// ground has several active neighbours along that edge, and each of those has
// one neighbour several times its size.
//
// This is invariant A seen sideways -- every stretch of edge is covered by
// exactly one active leaf. Each group names the production bug it catches.
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <new>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/neighbors.hpp"
#include "veyra/map/rolling_window.hpp"
#include "veyra/map/split_merge.hpp"
#include "veyra/map/tile_grid.hpp"

// Global allocation counter, so "does not allocate" is measured rather than
// asserted. Must live at global scope to replace the real operators.
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

// A grid of level-1 cells with one of them split into four level-0 children,
// so every mixed-resolution case below has real ground to stand on.
TileGrid mixedGrid() {
  TileGrid grid{MapWindow{0.0, 0.0, 5.0}};
  for (std::int32_t iy = -2; iy <= 2; ++iy) {
    for (std::int32_t ix = -2; ix <= 2; ++ix) {
      grid.findOrCreate(CellId{1, ix, iy});
    }
  }
  CHECK(veyra::map::split(grid, CellId{1, 1, 0}));  // -> L0 (2,0) (3,0) (2,1) (3,1)
  return grid;
}

// 2. A coarse cell bordering subdivided ground reports every finer leaf on
//    that edge, not one of them and not the parent.
//    Catches: a walk-down that returns the first leaf it finds, and one that
//    reports the subdivided region as if it were still a single cell.
void checkCoarseAgainstFiner() {
  const TileGrid grid = mixedGrid();

  std::size_t gaps = 0;
  const std::vector<CellId> n = neighborsOf(grid, CellId{1, 0, 0}, &gaps);
  CHECK(gaps == 0);
  // Three same-level edges plus two finer leaves on the eastern edge.
  CHECK(n.size() == 5);

  int finer = 0;
  for (const CellId c : n) {
    if (c.level == 0) {
      ++finer;
      CHECK(c == (CellId{0, 2, 0}) || c == (CellId{0, 2, 1}));
      CHECK(grid.find(c) != nullptr);
    }
  }
  CHECK(finer == 2);
  // The split parent must never be reported: it is no longer active.
  for (const CellId c : n) {
    CHECK(!(c == (CellId{1, 1, 0})));
  }
}

// 3. A fine cell bordering coarser ground reports the one larger cell.
//    Catches: a walk-up that stops before finding the active ancestor, and one
//    that reports a non-active intermediate level.
void checkFineAgainstCoarser() {
  const TileGrid grid = mixedGrid();

  std::size_t gaps = 0;
  const std::vector<CellId> n = neighborsOf(grid, CellId{0, 2, 0}, &gaps);
  CHECK(gaps == 0);

  int coarser = 0;
  for (const CellId c : n) {
    if (c.level == 1) {
      ++coarser;
      CHECK(grid.find(c) != nullptr);
    }
  }
  CHECK(coarser >= 1);
  // Its western neighbour is the L1 cell it was split away from.
  bool saw_west = false;
  for (const CellId c : n) {
    saw_west = saw_west || c == (CellId{1, 0, 0});
  }
  CHECK(saw_west);
}

// 4. Symmetry: if A lists B then B lists A, across every mixed-resolution
//    pairing in the grid. This single property catches most neighbour bugs,
//    so it is checked exhaustively rather than sampled.
//    Catches: an edge-to-child mapping that is wrong in one direction, which
//    a one-sided test would miss entirely.
void checkSymmetry() {
  const TileGrid grid = mixedGrid();

  std::vector<CellId> all;
  grid.forEachActiveLeaf([&all](CellId id, const veyra::map::Cell&) { all.push_back(id); });
  CHECK(all.size() > 8);

  std::size_t checked = 0;
  for (const CellId a : all) {
    const std::vector<CellId> na = neighborsOf(grid, a);
    for (const CellId b : na) {
      const std::vector<CellId> nb = neighborsOf(grid, b);
      bool mutual = false;
      for (const CellId back : nb) {
        mutual = mutual || back == a;
      }
      CHECK(mutual);
      ++checked;
    }
  }
  CHECK(checked > 20);
}

// 5. Negative coordinates. The >> versus / hazard reaches the neighbour path
//    through parentOf on the walk up.
//    Catches: truncation toward zero, which only misbehaves left of the
//    origin and would pair a cell with an ancestor that does not contain it.
void checkNegativeCoordinates() {
  TileGrid grid{MapWindow{0.0, 0.0, 5.0}};
  for (std::int32_t iy = -4; iy <= 1; ++iy) {
    for (std::int32_t ix = -4; ix <= 1; ++ix) {
      grid.findOrCreate(CellId{1, ix, iy});
    }
  }
  CHECK(veyra::map::split(grid, CellId{1, -2, -2}));  // -> L0 (-4,-4) (-3,-4) (-4,-3) (-3,-3)

  std::size_t gaps = 0;
  const std::vector<CellId> n = neighborsOf(grid, CellId{1, -3, -2}, &gaps);
  CHECK(gaps == 0);
  int finer = 0;
  for (const CellId c : n) {
    if (c.level == 0) {
      ++finer;
      CHECK(c == (CellId{0, -4, -4}) || c == (CellId{0, -4, -3}));
    }
  }
  CHECK(finer == 2);

  // And the reverse direction, where parentOf must floor rather than truncate.
  const std::vector<CellId> back = neighborsOf(grid, CellId{0, -4, -4});
  bool saw = false;
  for (const CellId c : back) {
    saw = saw || c == (CellId{1, -3, -2});
  }
  CHECK(saw);
}

// 6. The neighbour path allocates nothing. Measured with a counting global
//    operator new, not asserted from the signature.
//    Catches: a future refactor that returns a std::vector, which would put a
//    heap allocation on a per-cell hot path -- AGENTS.md forbids hidden
//    allocations there.
void checkNeighborPathDoesNotAllocate() {
  const TileGrid grid = mixedGrid();  // built before counting starts

  std::size_t seen = 0;
  g_alloc_count = 0;
  g_counting = true;
  const std::size_t gaps =
      veyra::map::forEachNeighbor(grid, CellId{1, 0, 0}, [&seen](CellId) { ++seen; });
  g_counting = false;

  CHECK(gaps == 0);
  CHECK(seen == 5);  // the same mixed-resolution case as group 2
  CHECK(g_alloc_count == 0);

  // The counter itself works, so a zero above means something.
  g_alloc_count = 0;
  g_counting = true;
  { std::vector<CellId> proof(8, CellId{0, 0, 0}); }
  g_counting = false;
  CHECK(g_alloc_count > 0);
}

}  // namespace

int main() {
  checkUniformGridHasFourNeighbors();
  checkCoarseAgainstFiner();
  checkFineAgainstCoarser();
  checkSymmetry();
  checkNegativeCoordinates();
  checkNeighborPathDoesNotAllocate();
  return 0;
}
