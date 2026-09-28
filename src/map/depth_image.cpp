#include "veyra/map/depth_image.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <iterator>
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

DepthImage::DepthImage(std::size_t azimuth_bins, std::vector<double> row_edges_rad)
    : azimuth_bins_(azimuth_bins),
      elevation_bins_(row_edges_rad.size() < 2 ? 0 : row_edges_rad.size() - 1),
      elevation_min_(row_edges_rad.empty() ? 0.0 : row_edges_rad.front()),
      elevation_max_(row_edges_rad.empty() ? 0.0 : row_edges_rad.back()),
      row_edges_(std::move(row_edges_rad)) {
  if (azimuth_bins_ == 0 || elevation_bins_ == 0) {
    throw std::invalid_argument("depth image needs at least one bin per axis");
  }
  for (std::size_t i = 0; i < row_edges_.size(); ++i) {
    if (!std::isfinite(row_edges_[i]) || (i > 0 && !(row_edges_[i] > row_edges_[i - 1]))) {
      throw std::invalid_argument("depth image row edges must be finite and strictly increasing");
    }
  }
  nearest_range_.assign(azimuth_bins_ * elevation_bins_, -1.0F);
  measured_elevation_.assign(nearest_range_.size(), 0.0F);
  measured_azimuth_.assign(nearest_range_.size(), 0.0F);
}

DepthImage DepthImage::for_beams(std::size_t azimuth_bins,
                                 std::vector<double> beam_elevations_rad) {
  std::sort(beam_elevations_rad.begin(), beam_elevations_rad.end());
  if (beam_elevations_rad.size() < 2) {
    throw std::invalid_argument("a beam table needs at least two beams");
  }
  for (std::size_t i = 0; i < beam_elevations_rad.size(); ++i) {
    if (!std::isfinite(beam_elevations_rad[i]) ||
        (i > 0 && !(beam_elevations_rad[i] > beam_elevations_rad[i - 1]))) {
      throw std::invalid_argument("beam elevations must be finite and distinct");
    }
  }
  const std::size_t n = beam_elevations_rad.size();
  std::vector<double> edges;
  edges.reserve(n + 1);
  edges.push_back(beam_elevations_rad[0] -
                  0.5 * (beam_elevations_rad[1] - beam_elevations_rad[0]));
  for (std::size_t i = 1; i < n; ++i) {
    edges.push_back(0.5 * (beam_elevations_rad[i - 1] + beam_elevations_rad[i]));
  }
  edges.push_back(beam_elevations_rad[n - 1] +
                  0.5 * (beam_elevations_rad[n - 1] - beam_elevations_rad[n - 2]));
  return DepthImage(azimuth_bins, std::move(edges));
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
  std::size_t elevation_index = 0;
  if (row_edges_.empty()) {
    elevation_index = static_cast<std::size_t>((elevation_rad - elevation_min_) / elevation_step);
  } else {
    const auto upper = std::upper_bound(row_edges_.begin(), row_edges_.end(), elevation_rad);
    elevation_index = static_cast<std::size_t>(std::max<std::ptrdiff_t>(
        0, std::distance(row_edges_.begin(), upper) - 1));
  }
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

std::size_t DepthImage::row_of(double elevation_rad) const noexcept {
  if (!(elevation_rad > elevation_min_)) return 0;
  if (!(elevation_rad < elevation_max_)) return elevation_bins_ - 1;
  std::size_t row = 0;
  if (row_edges_.empty()) {
    const double step = (elevation_max_ - elevation_min_) / static_cast<double>(elevation_bins_);
    row = static_cast<std::size_t>((elevation_rad - elevation_min_) / step);
  } else {
    const auto upper = std::upper_bound(row_edges_.begin(), row_edges_.end(), elevation_rad);
    row = static_cast<std::size_t>(
        std::max<std::ptrdiff_t>(0, std::distance(row_edges_.begin(), upper) - 1));
  }
  return std::min(row, elevation_bins_ - 1);
}

double DepthImage::elevation_of_row(std::size_t row) const noexcept {
  if (!row_edges_.empty()) {
    const std::size_t r = std::min(row, elevation_bins_ - 1);
    return 0.5 * (row_edges_[r] + row_edges_[r + 1]);
  }
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
                                       double margin_m, double half_width_m,
                                       const ClearingTolerance& tolerance) {
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
  int traversed = 0;
  bool blocked = false;
  // A measured beam crossed the claimed extent. Rows that merely exist in the
  // raster do not count -- an unmeasured row tested nothing.
  bool measured_beam_crossed_claim = false;
  // Some measured beam on this bearing reached past the cell, at whatever
  // elevation. This is precisely what a projected 2D sweep looks at, and on
  // its own it is not grounds to clear anything.
  bool projection_would_clear = false;

  // Every azimuth bin the footprint spans, not only the centre's: a 20 cm
  // cell at 15 m covers three quarter-degree bins, and beams in the outer bins
  // that cross the footprint are evidence (blocking evidence especially) that
  // a centre-only test silently ignored.
  const double azimuth_step = 2.0 * std::numbers::pi / static_cast<double>(image.azimuth_bins());
  double half_span = 0.0;
  if (half_width_m > 0.0) {
    for (const double cx : {dx - half_width_m, dx + half_width_m}) {
      for (const double cy : {dy - half_width_m, dy + half_width_m}) {
        double delta = std::atan2(cy, cx) - azimuth;
        delta = std::remainder(delta, 2.0 * std::numbers::pi);
        half_span = std::max(half_span, std::abs(delta));
      }
    }
  }
  const auto side_bins = static_cast<int>(std::min<double>(
      std::ceil(half_span / azimuth_step), static_cast<double>(image.azimuth_bins() / 4)));

  const std::size_t rows = image.elevation_bins();
  // One measured beam, sampled at (sample_azimuth, row).
  const auto examine = [&](double sample_azimuth, std::size_t row) {
    const double row_elevation = image.elevation_of_row(row);
    const float measured = image.range_at(sample_azimuth, row_elevation);
    if (measured < 0.0F) return;
    const double elevation = image.measured_elevation_at(sample_azimuth, row_elevation);
    const double measured_azimuth = image.measured_azimuth_at(sample_azimuth, row_elevation);
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
    if (half_width_m > 0.0) {
      if (!intersect_axis(dx, std::cos(measured_azimuth)) ||
          !intersect_axis(dy, std::sin(measured_azimuth)))
        return;
    } else {
      // No footprint supplied: a zero-width square only intersects a ray that
      // passes exactly through the centre, which a float-stored measured
      // azimuth almost never does off-axis. Fall back to the centre-column
      // contract (crossing at the centre's horizontal distance) instead of
      // silently reporting NoEvidence for every off-axis cell.
      entry = horizontal;
      exit = horizontal;
    }
    const double cosine = std::cos(elevation);
    if (!(cosine > 1e-6)) return;  // looking straight up or down: no column crossing

    const double crossing_range = exit / cosine;
    const double sigma =
        tolerance.noise == nullptr ? 0.0 : tolerance.noise->stddev_at(crossing_range);
    const double range_margin = std::max(margin_m, tolerance.range_sigmas * sigma);
    const double height_margin = tolerance.height_sigmas * sigma;
    const bool reached_past = static_cast<double>(measured) > crossing_range + range_margin;
    if (reached_past) projection_would_clear = true;

    // Did this beam pass through the claimed extent, or over or under it?
    const double entry_height = pose.z + entry * std::tan(elevation);
    const double exit_height = pose.z + exit * std::tan(elevation);
    const double beam_low = std::min(entry_height, exit_height);
    const double beam_high = std::max(entry_height, exit_height);
    if (beam_high < claim_low || beam_low > claim_high) return;

    if (!reached_past) {
      // Ends at or before the cell within its own noise: occluding or
      // supporting evidence, tested against the full claimed extent.
      measured_beam_crossed_claim = true;
      blocked = true;
      return;
    }
    // A through-beam must pass the claim's interior; one that only grazes an
    // edge within its own vertical uncertainty has not shown the column
    // empty. The interior never vanishes: a claim thinner than 2*margin
    // (a single return has zero span) keeps its mid-height, so thin ghosts
    // still clear, just only by beams through their middle.
    const double claim_mid = 0.5 * (claim_low + claim_high);
    const double interior_low = std::min(claim_low + height_margin, claim_mid);
    const double interior_high = std::max(claim_high - height_margin, claim_mid);
    if (beam_high < interior_low || beam_low > interior_high) return;
    measured_beam_crossed_claim = true;
    ++traversed;
  };

  // Only rows whose band can reach the claimed heights somewhere across the
  // footprint can block or traverse it. The band is a superset: for a beam at
  // elevation e the column height at horizontal distance d is z + d*tan(e),
  // so tan(e) must lie in [(low - z)/d, (high - z)/d] for some d in
  // [near, far]. Skipping the rest is exact and keeps the footprint sweep
  // affordable (every cell x bins x all rows was a 2.6x map-update cost).
  const double reach = half_width_m * std::numbers::sqrt2;
  std::size_t first_row = 0;
  std::size_t last_row = rows - 1;
  if (horizontal > reach + 1e-6) {
    const double near = horizontal - reach;
    const double far = horizontal + reach;
    const double low = claim_low - pose.z;
    const double high = claim_high - pose.z;
    const double tan_min = low < 0.0 ? low / near : low / far;
    const double tan_max = high > 0.0 ? high / near : high / far;
    first_row = image.row_of(std::atan(tan_min));
    last_row = image.row_of(std::atan(tan_max));
    // Measured elevations sit anywhere inside a row's band; one guard row
    // each side absorbs a band edge landing exactly on the bound.
    first_row = first_row == 0 ? 0 : first_row - 1;
    last_row = std::min(last_row + 1, rows - 1);
  }
  // Blocked wins, so the first occluding beam settles the outcome.
  for (int bin = -side_bins; bin <= side_bins && !blocked; ++bin) {
    const double sample_azimuth = azimuth + static_cast<double>(bin) * azimuth_step;
    for (std::size_t row = first_row; row <= last_row && !blocked; ++row) {
      examine(sample_azimuth, row);
    }
  }
  // Rows outside the band can only show a beam flying over or under the
  // claim; they decide SparedByElevation versus NoEvidence, never clearing.
  if (!blocked && traversed == 0 && !measured_beam_crossed_claim) {
    for (int bin = -side_bins; bin <= side_bins && !projection_would_clear; ++bin) {
      const double sample_azimuth = azimuth + static_cast<double>(bin) * azimuth_step;
      for (std::size_t row = 0; row < rows && !projection_would_clear; ++row) {
        if (row >= first_row && row <= last_row) continue;
        examine(sample_azimuth, row);
      }
    }
  }

  // Contradictory beams may hit different parts of the same aggregated cell.
  // Positive/occluding evidence wins; a single through-beam cannot clear it.
  if (blocked) return ClearingOutcome::Occluded;
  if (traversed > 0) return ClearingOutcome::Cleared;
  // Beams reached past this cell, but every one of them passed over or under
  // the claimed extent without testing it. A projected 2D sweep would have
  // cleared the cell here and erased whatever stands in it.
  if (projection_would_clear && !measured_beam_crossed_claim) {
    return ClearingOutcome::SparedByElevation;
  }
  return ClearingOutcome::NoEvidence;
}

}  // namespace veyra::map
