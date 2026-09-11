#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>

#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"
#include "veyra/map/tile_grid.hpp"

namespace veyra::map {

// One active leaf, as captured. Flat pair rather than a copy of the tile
// structure: a consumer wants to read cells, not navigate storage, and the
// tile layout stays private exactly as it does on the live grid.
struct SnapshotCell {
  core::CellId id{};
  Cell cell{};
};

// A read-only copy of the map's active leaves at one instant.
//
// Owns its data outright -- a plain copy, not copy-on-write. CoW is wrong for
// this workload: a frame integrates ~120k points across a wide area and then
// runs a policy pass, so most tiles near the vehicle are written every frame
// and would be cloned anyway, as scattered small allocations on the hot path.
// It would also tie tile lifetime to eager eviction, putting an asterisk back
// on a memory claim that currently has none. If a measurement later shows the
// copy too slow, CoW is the right fix then, benchmarked against this.
//
// Holds no pointer or reference into the grid, so it stays valid after the
// grid recentres, evicts, or is destroyed outright.
//
// Iteration only, no find(CellId): a lookup index would cost a hash build on
// every snapshot for a use case nobody has asked for. The dashboard walks
// everything; the benchmark aggregates.
//
// There is deliberately no mutating API. Every accessor is const and hands
// back const data, so a consumer can neither change a snapshot nor reach the
// grid through one.
class MapSnapshot {
 public:
  MapSnapshot() = default;

  [[nodiscard]] std::size_t size() const { return cells_.size(); }
  [[nodiscard]] const GridStats& statistics() const { return stats_; }
  [[nodiscard]] double centreX() const { return centre_x_; }
  [[nodiscard]] double centreY() const { return centre_y_; }
  [[nodiscard]] std::uint32_t frame() const { return frame_; }

  // Visits every captured cell. The callback receives a const reference, so
  // iteration cannot be used as a back door to modify the snapshot.
  template <class Fn>
  void forEachCell(Fn fn) const {
    for (const SnapshotCell& entry : cells_) {
      fn(entry);
    }
  }

 private:
  friend MapSnapshot snapshot(const TileGrid& grid, std::uint32_t frame_index);

  std::vector<SnapshotCell> cells_;
  GridStats stats_{};
  double centre_x_ = 0.0;
  double centre_y_ = 0.0;
  std::uint32_t frame_ = 0;
};

// Captures the grid's active leaves.
//
// The window centre is read from the grid, which already knows it. The frame
// stamp is not: nothing in the map tracks frames, so the caller supplies it --
// the same reason recenter() is separate from integrate(). The map does not
// run its own loop and does not decide when to publish.
MapSnapshot snapshot(const TileGrid& grid, std::uint32_t frame_index);

}  // namespace veyra::map
