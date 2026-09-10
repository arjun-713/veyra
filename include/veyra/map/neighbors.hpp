#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

#include "veyra/core/types.hpp"
#include "veyra/map/split_merge.hpp"
#include "veyra/map/tile_grid.hpp"

namespace veyra::map {
namespace detail {

// The four edges, as unit steps in cell indices at the cell's own level.
inline constexpr std::array<std::array<std::int32_t, 2>, 4> kEdgeSteps = {
    {{{1, 0}}, {{-1, 0}}, {{0, 1}}, {{0, -1}}}};

// Which two of childrenOf's four children touch the shared edge, given the
// direction we crossed to reach the neighbour. childrenOf is ordered
// (x, y), (x+1, y), (x, y+1), (x+1, y+1), so for a neighbour to the east the
// touching children are its western column -- indices 0 and 2.
inline constexpr std::array<std::array<std::size_t, 2>, 4> kTouchingChildren = {
    {{{0, 2}}, {{1, 3}}, {{0, 1}}, {{2, 3}}}};

// Collects every active leaf inside `region` that touches the shared edge.
// Returns the number found. The recursion is bounded by the ladder: at most
// kMaxLevel steps, so this cannot run away.
template <class Fn>
std::size_t collectFinerLeaves(const TileGrid& grid, core::CellId region, std::size_t edge, Fn fn) {
  if (region.level <= 0) {
    return 0;  // nothing finer exists below level 0
  }
  std::size_t found = 0;
  const std::array<core::CellId, 4> kids = childrenOf(region);
  for (const std::size_t which : kTouchingChildren[edge]) {
    const core::CellId child = kids[which];
    if (grid.find(child) != nullptr) {
      fn(child);
      ++found;
    } else {
      found += collectFinerLeaves(grid, child, edge, fn);
    }
  }
  return found;
}

}  // namespace detail

// Calls `fn(CellId)` once for every active leaf sharing an edge with `id`, and
// returns the number of edges left uncovered.
//
// Three cases per edge, checked in order; exactly one succeeds when the map is
// correct:
//   1. same level  -- the neighbour id at this level is active
//   2. coarser     -- walk up; the first active ancestor is the neighbour
//   3. finer       -- walk down; collect every active leaf touching the edge
//
// A non-zero return means some stretch of edge is covered by no active leaf,
// which is a hole in the map rather than a boundary condition -- except at the
// edge of the mapped region, where having no neighbour is normal.
//
// Callback form rather than a returned container: this is a query on the hot
// path and must not allocate. Nothing here heap-allocates.
//
// This is a query, never a constraint. It does not rebalance the grid;
// docs/architecture.md forbids an unrestricted global 2:1 cascade.
template <class Fn>
std::size_t forEachNeighbor(const TileGrid& grid, core::CellId id, Fn fn) {
  std::size_t uncovered = 0;
  for (std::size_t edge = 0; edge < detail::kEdgeSteps.size(); ++edge) {
    const core::CellId same{id.level,
                            static_cast<std::int32_t>(id.ix + detail::kEdgeSteps[edge][0]),
                            static_cast<std::int32_t>(id.iy + detail::kEdgeSteps[edge][1])};

    // 1. same level
    if (grid.find(same) != nullptr) {
      fn(same);
      continue;
    }

    // 2. coarser -- the first active ancestor covers this edge
    bool done = false;
    core::CellId up = same;
    while (up.level < kMaxLevel) {
      up = core::parentOf(up);
      if (grid.find(up) != nullptr) {
        fn(up);
        done = true;
        break;
      }
    }
    if (done) {
      continue;
    }

    // 3. finer -- the region is subdivided; collect every leaf on the edge
    if (detail::collectFinerLeaves(grid, same, edge, fn) == 0) {
      ++uncovered;
    }
  }
  return uncovered;
}

}  // namespace veyra::map
