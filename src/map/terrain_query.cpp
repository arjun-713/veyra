#include "veyra/map/terrain_query.hpp"

#include <cmath>
#include <limits>
#include <numbers>
#include <stdexcept>

#include "veyra/map/map.hpp"
#include "veyra/map/occupancy.hpp"

namespace veyra::map {

void VehicleProfile::validate() const {
  const bool finite = std::isfinite(clearance_envelope_m) && std::isfinite(vehicle_height_m) &&
                      std::isfinite(roughness_limit_m) && std::isfinite(step_limit_m) &&
                      std::isfinite(max_slope_rad);
  if (!finite) {
    throw std::invalid_argument("vehicle profile limits must be finite");
  }
  if (clearance_envelope_m <= 0.0 || vehicle_height_m <= 0.0) {
    throw std::invalid_argument("vehicle height and clearance envelope must be positive");
  }
  if (roughness_limit_m < 0.0 || step_limit_m < 0.0) {
    throw std::invalid_argument("roughness and step limits must not be negative");
  }
  if (max_slope_rad < 0.0 || max_slope_rad > std::numbers::pi / 2.0) {
    throw std::invalid_argument("max_slope_rad must be within [0, pi/2]");
  }
  if (vehicle_height_m > clearance_envelope_m) {
    // Returns between vehicle_height_m and clearance_envelope_m were filed as
    // overhead when the cell was built, so for this platform they are obstacles
    // that the map can no longer distinguish. Refuse rather than under-report.
    throw std::invalid_argument("vehicle is taller than the clearance envelope the map sorts at");
  }
  if (min_ground_returns == 0) {
    throw std::invalid_argument("min_ground_returns must be at least 1");
  }
}

namespace {

// The classification itself, with validation already done by the caller.
TerrainVerdict classify_validated(const CellStats& stats, const VehicleProfile& profile,
                                  std::uint64_t current_time) {
  TerrainVerdict verdict;
  verdict.occupancy = stats.occupancy();
  verdict.occupancy_probability = logodds::probability_of(stats.occupancy_logodds);
  verdict.has_obstacle = !stats.obstacle.empty();
  verdict.has_overhead = !stats.overhead.empty();

  // A cell sorted under a shorter envelope than this platform needs cannot
  // separate obstacles from overhead for this vehicle: returns filed as
  // overhead may be things this taller vehicle would strike.
  //
  // The flag is recorded here but deliberately does NOT short-circuit. The
  // ambiguity is one-directional -- misfiled overhead can only turn out to be
  // an obstacle, never the reverse -- so a mismatch can only make a cell
  // worse. A cell already refused on evidence stays refused, with its real
  // reason intact; only a cell that would otherwise read Drivable is
  // downgraded to Unknown, at the end of this function. Short-circuiting here
  // would throw away a definite NonDrivable and replace it with a vaguer
  // answer, which is not more conservative, just less useful.
  verdict.envelope_mismatch =
      stats.sorted_envelope_m > 0.0F &&
      profile.vehicle_height_m > static_cast<double>(stats.sorted_envelope_m);

  // Ground first. Everything below is expressed relative to the ground
  // surface, so without it there is nothing to measure against -- and a cell
  // that saw a roof but never the road is precisely the case a pooled mean
  // answers confidently and wrongly.
  if (stats.ground.empty()) {
    verdict.ground_state =
        (verdict.has_obstacle || verdict.has_overhead) ? GroundState::Occluded : GroundState::Unobserved;
    verdict.traversability = Traversability::Unknown;
    verdict.reason = TerrainReason::NoGroundEvidence;
    return verdict;
  }
  if (stats.ground.count < profile.min_ground_returns) {
    verdict.ground_state = GroundState::Occluded;
    verdict.traversability = Traversability::Unknown;
    verdict.reason = TerrainReason::InsufficientGround;
    verdict.ground_height_m = stats.ground.mean_z;
    return verdict;
  }

  verdict.ground_state = GroundState::Observed;
  verdict.ground_height_m = stats.ground.mean_z;
  verdict.ground_roughness_m = stats.ground.stddev_z();
  verdict.slope_available = stats.ground_gradient_count > 0;
  if (verdict.slope_available) {
    const double gx = stats.ground_gradient_x();
    const double gy = stats.ground_gradient_y();
    verdict.slope_rad = std::atan(std::hypot(gx, gy));
    const double normal_length = std::sqrt(gx * gx + gy * gy + 1.0);
    verdict.normal_x = -gx / normal_length;
    verdict.normal_y = -gy / normal_length;
    verdict.normal_z = 1.0 / normal_length;
  } else if (profile.require_slope_evidence) {
    verdict.traversability = Traversability::Unknown;
    verdict.reason = TerrainReason::InsufficientSlope;
    return verdict;
  }
  // No overhead return means open sky, which is infinite clearance, not zero.
  verdict.clearance_m = verdict.has_overhead
                            ? static_cast<double>(stats.overhead.min_z) - verdict.ground_height_m
                            : std::numeric_limits<double>::infinity();
  if (verdict.has_obstacle) {
    // The obstacle layer's min_z is the base of the thing standing here: the
    // lip of a kerb, the edge of a step. This is the number a pooled mean
    // cannot recover and the reason the layer stores it.
    verdict.obstacle_height_m = static_cast<double>(stats.obstacle.min_z) - verdict.ground_height_m;
  }

  // Positive evidence of absence outranks the stored obstacle geometry.
  //
  // A cell can hold obstacle returns from a pedestrian who has since walked
  // away. Those returns are not wrong -- something really was there -- so they
  // are not deleted. What settles it is that beams have since been observed
  // passing through the volume those returns claimed, driving the occupancy
  // accumulator to Free. Geometry says "an obstacle was here"; visibility says
  // "and it is not here now", and visibility is the more recent evidence.
  //
  // This is the one path that may clear an obstacle. Ageing cannot, because
  // not looking at a place tells you nothing about it.
  const bool cleared_by_visibility =
      verdict.has_obstacle && verdict.occupancy == OccupancyState::Free;

  // Staleness is checked before any drivable verdict is issued, and it can
  // only downgrade to Unknown. Evidence that has aged out means the vehicle
  // stopped looking, which is indistinguishable from occlusion; neither is
  // evidence that the obstacle left.
  if (verdict.has_obstacle && !cleared_by_visibility && current_time > stats.obstacle.last_seen &&
      current_time - stats.obstacle.last_seen > profile.staleness_horizon) {
    verdict.traversability = Traversability::Unknown;
    verdict.reason = TerrainReason::StaleEvidence;
    return verdict;
  }

  if (verdict.has_obstacle && !cleared_by_visibility &&
      verdict.obstacle_height_m > profile.step_limit_m) {
    verdict.traversability = Traversability::NonDrivable;
    verdict.reason = TerrainReason::ObstaclePresent;
    return verdict;
  }
  if (verdict.ground_roughness_m > profile.roughness_limit_m) {
    verdict.traversability = Traversability::NonDrivable;
    verdict.reason = TerrainReason::GroundTooRough;
    return verdict;
  }
  if (verdict.slope_available && verdict.slope_rad > profile.max_slope_rad) {
    verdict.traversability = Traversability::NonDrivable;
    verdict.reason = TerrainReason::GroundTooSteep;
    return verdict;
  }
  if (verdict.clearance_m < profile.vehicle_height_m) {
    verdict.traversability = Traversability::NonDrivable;
    verdict.reason = TerrainReason::InsufficientClearance;
    return verdict;
  }

  if (verdict.envelope_mismatch) {
    // Everything measurable says drivable, but this platform is taller than
    // the envelope the evidence was sorted under, so "no obstacle" is not a
    // claim this cell can make for this vehicle.
    verdict.traversability = Traversability::Unknown;
    verdict.reason = TerrainReason::InsufficientClearance;
    return verdict;
  }

  verdict.traversability = Traversability::Drivable;
  verdict.reason = cleared_by_visibility ? TerrainReason::ClearedByVisibility : TerrainReason::Ok;
  return verdict;
}

}  // namespace

TerrainVerdict classify(const CellStats& stats, const VehicleProfile& profile,
                        std::uint64_t current_time) {
  profile.validate();
  return classify_validated(stats, profile, current_time);
}

TerrainClassifier::TerrainClassifier(VehicleProfile profile) : profile_(profile) {
  profile_.validate();
}

TerrainVerdict TerrainClassifier::classify(const CellStats& stats,
                                           std::uint64_t current_time) const {
  return classify_validated(stats, profile_, current_time);
}

}  // namespace veyra::map
