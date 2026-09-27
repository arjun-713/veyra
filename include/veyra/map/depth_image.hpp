#pragma once
#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

#include "veyra/map/sensor_model.hpp"

namespace veyra::map {

struct Observation;
struct CellStats;

// A spherical depth raster of one scan, used to decide what the sensor saw
// through rather than what it saw.
//
// This replaces the per-point ray traversal the dynamic-update design
// originally specified. Tracing a ray per return costs O(cells along the ray)
// for each of ~120k returns per frame, which forced decimation, work caps and
// a deferred backlog. Rasterising the scan once and asking each cell "was
// anything measured beyond you along your own bearing?" is O(1) per cell after
// an O(points) build, and needs none of that machinery. The approach is
// D-Map's (HKU MaRS); see docs/prior-art.md.
//
// Each bin stores the range of the NEAREST return that fell in it. Nearest,
// not farthest or mean: free space may only be claimed up to the first surface
// along a bearing, because everything past it is occluded and unobserved. Any
// other choice would clear cells hidden behind the first return, which is the
// defect this whole design exists to avoid.
class DepthImage {
 public:
  // `azimuth_bins` spans the full circle; `elevation_bins` spans
  // [elevation_min_rad, elevation_max_rad]. Bin sizes should be at or slightly
  // above the sensor's angular resolution: finer leaves unfilled bins between
  // beams, which read as "nothing measured here" and suppress clearing.
  DepthImage(std::size_t azimuth_bins, std::size_t elevation_bins, double elevation_min_rad,
             double elevation_max_rad);

  // Folds one world-frame return into the raster.
  void insert(double x, double y, double z, const SensorPose& pose);
  void insert(const Observation& observation, const SensorPose& pose);

  void clear();

  [[nodiscard]] std::size_t azimuth_bins() const noexcept { return azimuth_bins_; }
  [[nodiscard]] std::size_t elevation_bins() const noexcept { return elevation_bins_; }
  [[nodiscard]] std::size_t filled_bins() const noexcept { return filled_; }

  // Range of the nearest return along this bearing, or a negative value when
  // the scan measured nothing there.
  //
  // Nothing measured is not the same as nothing present: a bearing with no
  // return saw no surface AND proves no free space, so callers must treat a
  // negative result as "no evidence" and leave the cell alone.
  [[nodiscard]] float range_at(double azimuth_rad, double elevation_rad) const;

  // Centre elevation of one raster row, so callers can sweep the rows the
  // image actually has instead of inventing their own sampling and aliasing
  // against it.
  [[nodiscard]] double elevation_of_row(std::size_t row) const noexcept;
  // Actual elevation of the nearest measured return, not the raster centre.
  [[nodiscard]] double measured_elevation_at(double azimuth_rad, double elevation_rad) const;
  [[nodiscard]] double measured_azimuth_at(double azimuth_rad, double elevation_rad) const;
  [[nodiscard]] std::optional<std::uint64_t> scan_timestamp() const noexcept {
    return scan_timestamp_;
  }

  // Was a surface measured strictly beyond `range_m` along this bearing?
  //
  // True means a beam travelled past that distance here, so anything nearer
  // along this bearing was empty at scan time. `margin_m` keeps a return from
  // clearing the very surface it came from: without it, range noise on a wall
  // would have the wall clearing itself.
  [[nodiscard]] bool sees_past(double azimuth_rad, double elevation_rad, double range_m,
                               double margin_m) const;

 private:
  [[nodiscard]] std::size_t index_of(double azimuth_rad, double elevation_rad,
                                     bool& in_range) const;

  std::size_t azimuth_bins_;
  std::size_t elevation_bins_;
  double elevation_min_;
  double elevation_max_;
  std::size_t filled_ = 0;
  // Negative means empty. float is ample: this is a range in metres used for a
  // comparison with a centimetre-scale margin, never accumulated.
  std::vector<float> nearest_range_;
  std::vector<float> measured_elevation_;
  std::vector<float> measured_azimuth_;
  std::optional<std::uint64_t> scan_timestamp_;
};

// Spherical coordinates of a world point relative to the sensor.
struct Bearing {
  double azimuth_rad = 0.0;
  double elevation_rad = 0.0;
  double range_m = 0.0;
};

[[nodiscard]] Bearing bearing_of(double x, double y, double z, const SensorPose& pose) noexcept;

struct ClearingStats {
  std::size_t examined = 0;
  // Obstacle evidence contradicted: a beam was measured passing through the
  // claimed vertical extent.
  std::size_t cleared = 0;
  // The scan measured a surface at or before this cell, so it says nothing
  // about what lies behind. Left alone.
  std::size_t occluded = 0;
  // No return along this bearing at all. Also says nothing.
  std::size_t no_evidence = 0;
  // A beam passed above or below the claimed extent without traversing it.
  // This is the 2.5D correction: in a projected 2D sweep these would have been
  // cleared, and the kerb they flew over would have been erased.
  std::size_t spared_by_elevation = 0;
};

// Result of testing one cell's obstacle evidence against one scan.
enum class ClearingOutcome : std::uint8_t {
  NoObstacle = 0,       // nothing claimed here to contradict
  NoEvidence = 1,       // no return along this bearing
  Occluded = 2,         // a surface was measured at or before this cell
  SparedByElevation = 3,// beams passed, but not through the claimed extent
  Cleared = 4,          // a beam traversed the claimed extent: contradicted
};

// Tests whether a scan contradicts the obstacle evidence in one cell.
//
// The cell's obstacle layer claims a surface occupying [min_z, max_z] at
// (centre_x, centre_y), with a square footprint of half_width_m when supplied.
// Measured angles, not quantized raster centres, test that physical footprint.
// Those two heights give two bearings from the sensor,
// and the claim is contradicted only when the scan measured something BEYOND
// the cell along a bearing that actually passes through the claimed extent.
//
// This is the whole 2.5D correction. A projected 2D sweep asks only "did a
// beam go past this column?", which is true whenever the sensor saw anything
// behind a 12 cm kerb -- and so erases the kerb. Carrying elevation means a
// beam that flew over the kerb is recorded as having flown over it.
//
// Pure: reads the cell, writes nothing. The caller applies the outcome.
[[nodiscard]] ClearingOutcome test_cell_against_scan(const CellStats& stats, double centre_x,
                                                     double centre_y, const DepthImage& image,
                                                     const SensorPose& pose, double margin_m,
                                                     double half_width_m = 0.0);

}  // namespace veyra::map
