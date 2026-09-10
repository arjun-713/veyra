#pragma once
#include <cstddef>
#include <cstdint>
#include <limits>

#include "veyra/core/types.hpp"

namespace veyra::map {

// Radius of the window that follows the vehicle, in metres.
//
// PROPOSAL, same provenance as the constant it replaces: derived from the
// outermost band of configs/distance_lod.yaml (0-10, 10-30, 30-60, 60-100).
//
// Worth stating plainly: at 5 cm a 100 m radius is pi * 100^2 * 400 = 12.6
// million cells, about 402 MB of Cell alone. Uniform5 over a full window is
// not viable, which is what DistanceLOD exists to fix. Tests here use radii
// of a few metres for that reason.
inline constexpr double kDefaultWindowRadiusM = 100.0;

// Largest |coordinate| whose L0 index still fits in an int32_t. This is not a
// policy bound -- it is a representability guard. worldToKey converts a double
// to int32_t, and converting a value outside the integer's range is undefined
// behaviour, so a finite but absurd coordinate must be turned away before it
// reaches the conversion.
inline constexpr double kMaxIndexableM =
    static_cast<double>(std::numeric_limits<std::int32_t>::max()) / 20.0;

// The window is a disc centred on the vehicle rather than a square.
//
// Circular because the resolution policy is already radial -- DistanceLOD
// bands are 0-10, 10-30, 30-60, 60-100 m from the vehicle -- so a square
// window would hold corner cells that no band covers. It is also 4/pi = 1.27x
// less area than the enclosing square for the same reach.
//
// The centre is snapped to tile granularity by TileGrid::recenter; it is not
// the raw vehicle position. See that function for why.
struct MapWindow {
  double centre_x = 0.0;
  double centre_y = 0.0;
  double radius_m = kDefaultWindowRadiusM;
};

struct EvictionStats {
  std::size_t cells_evicted = 0;
  std::size_t tiles_released = 0;
  bool centre_moved = false;
};

// THE shared predicate. Both acceptance in integrate() and eviction in
// recenter() go through this one function, on the same argument type -- a
// CellId, not a raw point. Sharing the function is not enough on its own: if
// one caller tested the observation's position and the other the cell's
// centre, they could still disagree at the boundary. Taking a CellId makes
// that impossible by construction.
//
// A cell is inside when its centre is within the radius, inclusive.
constexpr bool inWindow(const MapWindow& w, core::CellId id) {
  const core::CellExtent e = core::extentOf(id);
  const double dx = 0.5 * (e.min_x + e.max_x) - w.centre_x;
  const double dy = 0.5 * (e.min_y + e.max_y) - w.centre_y;
  return dx * dx + dy * dy <= w.radius_m * w.radius_m;
}

}  // namespace veyra::map
