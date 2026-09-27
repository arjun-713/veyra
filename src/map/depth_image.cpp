#include "veyra/map/depth_image.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <limits>
#include <stdexcept>

#include "veyra/map/map.hpp"
#include "veyra/map/observation.hpp"

namespace veyra::map {
namespace {

constexpr double kTwoPi = 2.0 * std::numbers::pi;

// Azimuth wrapped into [0, 2pi). std::fmod alone leaves negatives negative,
// which would index off the front of the raster.
double wrap_azimuth(double radians) noexcept {
  double wrapped = std::fmod(radians, kTwoPi);
  if (wrapped < 0.0) wrapped += kTwoPi;
  return wrapped;
}

}  // namespace

Bearing bearing_of(double x, double y, double z, const SensorPose& pose) noexcept {
  const double dx = x - pose.x;
  const double dy = y - pose.y;
  const double dz = z - pose.z;
  const double horizontal = std::sqrt(dx * dx + dy * dy);
  Bearing bearing;
  bearing.range_m = std::sqrt(horizontal * horizontal + dz * dz);
  bearing.azimuth_rad = wrap_azimuth(std::atan2(dy, dx));
  // atan2 rather than asin(dz / range): at zero range asin divides by zero,
  // while atan2(0, 0) is defined and yields a harmless zero elevation.
  bearing.elevation_rad = std::atan2(dz, horizontal);
  return bearing;
}

DepthImage::DepthImage(std::size_t azimuth_bins, std::size_t elevation_bins,
                       double elevation_min_rad, double elevation_max_rad)
    : azimuth_bins_(azimuth_bins),
      elevation_bins_(elevation_bins),
      elevation_min_(elevation_min_rad),
      elevation_max_(elevation_max_rad) {
  if (azimuth_bins == 0 || elevation_bins == 0) {
    throw std::invalid_argument("depth image needs at least one bin per axis");
  }
  if (!std::isfinite(elevation_min_rad) || !std::isfinite(elevation_max_rad) ||
      !(elevation_max_rad > elevation_min_rad)) {
    throw std::invalid_argument("depth image elevation span must be finite and increasing");
  }
  nearest_range_.assign(azimuth_bins_ * elevation_bins_, -1.0F);
  measured_elevation_.assign(nearest_range_.size(), 0.0F);
  measured_azimuth_.assign(nearest_range_.size(), 0.0F);
}

void DepthImage::clear() {
  std::fill(nearest_range_.begin(), nearest_range_.end(), -1.0F);
  filled_ = 0;
  scan_timestamp_.reset();
}

std::size_t DepthImage::index_of(double azimuth_rad, double elevation_rad, bool& in_range) const {
  in_range = false;
  if (!std::isfinite(azimuth_rad) || !std::isfinite(elevation_rad)) return 0;
  if (elevation_rad < elevation_min_ || elevation_rad > elevation_max_) return 0;

  const double azimuth_step = kTwoPi / static_cast<double>(azimuth_bins_);
  const double elevation_step =
      (elevation_max_ - elevation_min_) / static_cast<double>(elevation_bins_);

  auto azimuth_index =
      static_cast<std::size_t>(wrap_azimuth(azimuth_rad) / azimuth_step);
  // A value landing exactly on the upper edge would index one past the end.
  azimuth_index = std::min(azimuth_index, azimuth_bins_ - 1);
  auto elevation_index =
      static_cast<std::size_t>((elevation_rad - elevation_min_) / elevation_step);
  elevation_index = std::min(elevation_index, elevation_bins_ - 1);

  in_range = true;
  return elevation_index * azimuth_bins_ + azimuth_index;
}

void DepthImage::insert(double x, double y, double z, const SensorPose& pose) {
  const Bearing bearing = bearing_of(x, y, z, pose);
  if (!std::isfinite(bearing.range_m) || bearing.range_m <= 0.0) return;
  bool in_range = false;
  const std::size_t index = index_of(bearing.azimuth_rad, bearing.elevation_rad, in_range);
  if (!in_range) return;

  float& slot = nearest_range_[index];
  const auto range = static_cast<float>(bearing.range_m);
  if (slot < 0.0F) {
    slot = range;
    measured_elevation_[index] = static_cast<float>(bearing.elevation_rad);
    measured_azimuth_[index] = static_cast<float>(bearing.azimuth_rad);
    ++filled_;
    return;
  }
  if (range < slot) {
    slot = range;
    measured_elevation_[index] = static_cast<float>(bearing.elevation_rad);
    measured_azimuth_[index] = static_cast<float>(bearing.azimuth_rad);
  }
}

void DepthImage::insert(const Observation& observation, const SensorPose& pose) {
  insert(observation.x, observation.y, observation.z, pose);
  scan_timestamp_ = std::max(scan_timestamp_.value_or(0), observation.timestamp);
}

double DepthImage::measured_elevation_at(double azimuth_rad, double elevation_rad) const {
  bool in_range = false;
  const auto index = index_of(azimuth_rad, elevation_rad, in_range);
  return in_range ? measured_elevation_[index] : elevation_rad;
}

double DepthImage::measured_azimuth_at(double azimuth_rad, double elevation_rad) const {
  bool in_range = false;
  const auto index = index_of(azimuth_rad, elevation_rad, in_range);
  return in_range ? measured_azimuth_[index] : azimuth_rad;
}

double DepthImage::elevation_of_row(std::size_t row) const noexcept {
  const double step = (elevation_max_ - elevation_min_) / static_cast<double>(elevation_bins_);
  return elevation_min_ + step * (static_cast<double>(row) + 0.5);
}

float DepthImage::range_at(double azimuth_rad, double elevation_rad) const {
  bool in_range = false;
  const std::size_t index = index_of(azimuth_rad, elevation_rad, in_range);
  if (!in_range) return -1.0F;
  return nearest_range_[index];
}

bool DepthImage::sees_past(double azimuth_rad, double elevation_rad, double range_m,
                           double margin_m) const {
  const float measured = range_at(azimuth_rad, elevation_rad);
  if (measured < 0.0F) return false;  // nothing measured: no evidence either way
  return static_cast<double>(measured) > range_m + margin_m;
}

ClearingOutcome test_cell_against_scan(const CellStats& stats, double centre_x, double centre_y,
                                       const DepthImage& image, const SensorPose& pose,
                                       double margin_m, double half_width_m) {
  if (stats.obstacle.empty()) return ClearingOutcome::NoObstacle;

  const double dx = centre_x - pose.x;
  const double dy = centre_y - pose.y;
  const double horizontal = std::sqrt(dx * dx + dy * dy);
  if (!(horizontal > 0.0)) return ClearingOutcome::NoEvidence;
  const double azimuth = wrap_azimuth(std::atan2(dy, dx));

  const double claim_low = static_cast<double>(stats.obstacle.min_z);
  const double claim_high = static_cast<double>(stats.obstacle.max_z);

  // The cell is a vertical column at a fixed horizontal distance. A beam
  // leaving the sensor at elevation phi crosses that column at height
  // pose.z + horizontal*tan(phi) and at slant range horizontal/cos(phi).
  //
  // Both quantities vary with phi, and that is the correction this function
  // exists to make. An earlier version compared every elevation against one
  // range taken from the column's nearest corner; because a raised sensor sees
  // the foot of a surface as FARTHER than its top, returns from the obstacle's
  // own base then read as lying beyond it and cleared the obstacle with its own
  // returns. The range a beam must exceed is the range at that beam's own
  // elevation, never a single number for the whole column.
  bool traversed = false;
  bool blocked = false;
  // A measured beam crossed the claimed extent. Rows that merely exist in the
  // raster do not count -- an unmeasured row tested nothing.
  bool measured_beam_crossed_claim = false;
  // Some measured beam on this bearing reached past the cell, at whatever
  // elevation. This is precisely what a projected 2D sweep looks at, and on
  // its own it is not grounds to clear anything.
  bool projection_would_clear = false;

  const std::size_t rows = image.elevation_bins();
  for (std::size_t row = 0; row < rows; ++row) {
    const double row_elevation = image.elevation_of_row(row);
    const float measured = image.range_at(azimuth, row_elevation);
    if (measured < 0.0F) continue;
    const double elevation = image.measured_elevation_at(azimuth, row_elevation);
    const double measured_azimuth = image.measured_azimuth_at(azimuth, row_elevation);
    // A return elsewhere in the angular bin does not prove this cell free.
    // Intersect the measured ray with the actual square footprint, and require
    // a return past its EXIT (not merely past the centre).
    double entry = 0.0;
    double exit = std::numeric_limits<double>::infinity();
    const auto intersect_axis = [&](double offset, double direction) {
      if (std::abs(direction) < 1e-12) return std::abs(offset) <= half_width_m + 1e-9;
      double a = (offset - half_width_m) / direction;
      double b = (offset + half_width_m) / direction;
      if (a > b) std::swap(a, b);
      entry = std::max(entry, a);
      exit = std::min(exit, b);
      return entry <= exit + 1e-9;
    };
    if (!intersect_axis(dx, std::cos(measured_azimuth)) ||
        !intersect_axis(dy, std::sin(measured_azimuth))) continue;
    const double cosine = std::cos(elevation);
    if (!(cosine > 1e-6)) continue;  // looking straight up or down: no column crossing

    const double crossing_range = exit / cosine;
    const bool reached_past = static_cast<double>(measured) > crossing_range + margin_m;
    if (reached_past) projection_would_clear = true;

    // Did this beam pass through the claimed extent, or over or under it?
    const double entry_height = pose.z + entry * std::tan(elevation);
    const double exit_height = pose.z + exit * std::tan(elevation);
    if (std::max(entry_height, exit_height) < claim_low ||
        std::min(entry_height, exit_height) > claim_high) continue;
    measured_beam_crossed_claim = true;

    if (reached_past) {
      traversed = true;
      continue;
    }
    blocked = true;
  }

  // Contradictory beams may hit different parts of the same aggregated cell.
  // Positive/occluding evidence wins; a single through-beam cannot clear it.
  if (blocked) return ClearingOutcome::Occluded;
  if (traversed) return ClearingOutcome::Cleared;
  // Beams reached past this cell, but every one of them passed over or under
  // the claimed extent without testing it. A projected 2D sweep would have
  // cleared the cell here and erased whatever stands in it.
  if (projection_would_clear && !measured_beam_crossed_claim) {
    return ClearingOutcome::SparedByElevation;
  }
  return ClearingOutcome::NoEvidence;
}

}  // namespace veyra::map
