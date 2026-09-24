// Layered 2.5D map: ground / obstacle / overhead separation.
//
// The cases below are the ones docs/layered-map-design.md claims to fix. Each
// one fails against a pooled elevation mean, which is the point.

#include <cmath>
#include <cstdio>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#include "veyra/map/map.hpp"
#include "veyra/map/terrain_query.hpp"

namespace {

int failures = 0;

void check(bool condition, const std::string& what) {
  if (!condition) {
    std::printf("FAIL: %s\n", what.c_str());
    ++failures;
  }
}

void check_close(double actual, double expected, double tolerance, const std::string& what) {
  if (!(std::fabs(actual - expected) <= tolerance)) {
    std::printf("FAIL: %s (got %.9f, want %.9f +/- %g)\n", what.c_str(), actual, expected,
                tolerance);
    ++failures;
  }
}

veyra::map::Observation ret(double z, double hag, std::uint8_t ground, std::uint64_t t = 1) {
  veyra::map::Observation o;
  o.x = 1.0;
  o.y = 1.0;
  o.z = z;
  o.height_above_ground = static_cast<float>(hag);
  o.ground = ground;
  o.timestamp = t;
  o.terrain_confidence = 0.9F;
  o.semantic_confidence = 0.8F;
  o.observation_quality = 0.9F;
  return o;
}

// Road at 0.0 m with a van roof at 2.4 m above it. A pooled mean reports
// ~1.2 m: a surface the sensor never observed and the vehicle cannot use.
void test_road_under_vehicle_roof() {
  veyra::map::CellStats cell;
  for (int i = 0; i < 20; ++i) cell.add(ret(0.0, 0.0, 1), 2.0);
  for (int i = 0; i < 20; ++i) cell.add(ret(2.4, 2.4, 0), 2.0);

  check_close(cell.mean_z(), 1.2, 1e-9, "pooled mean is the fiction we are replacing");
  check_close(cell.ground.mean_z, 0.0, 1e-9, "ground layer recovers the road surface");
  check_close(cell.overhead.mean_z, 2.4, 1e-9, "overhead layer holds the roof");
  check(cell.obstacle.empty(), "nothing stands on the road");

  veyra::map::VehicleProfile profile;
  const auto verdict = veyra::map::classify(cell, profile, 1);
  check(verdict.ground_state == veyra::map::GroundState::Observed, "road was observed");
  check(verdict.traversability == veyra::map::Traversability::Drivable,
        "road under a 2.4 m roof is drivable for a 1.8 m vehicle");
  check_close(verdict.ground_height_m, 0.0, 1e-9, "reported ground height is the road");
  check_close(verdict.clearance_m, 2.4, 1e-6, "clearance is measured to the roof");
}

// Same geometry, but the thing at 2.4 m reaches the ground: a wall, not a
// bridge. The pooled statistics are identical to the case above; only the
// layers tell them apart.
void test_obstacle_standing_on_road() {
  veyra::map::CellStats cell;
  for (int i = 0; i < 20; ++i) cell.add(ret(0.0, 0.0, 1), 2.0);
  for (int i = 0; i < 20; ++i) cell.add(ret(0.9, 0.9, 0), 2.0);

  check(!cell.obstacle.empty(), "obstacle layer holds the wall");
  check_close(static_cast<double>(cell.obstacle.min_z), 0.9, 1e-6, "obstacle base recorded");

  const auto verdict = veyra::map::classify(cell, veyra::map::VehicleProfile{}, 1);
  check(verdict.traversability == veyra::map::Traversability::NonDrivable,
        "a 0.9 m obstacle on the road is not drivable");
  check(verdict.reason == veyra::map::TerrainReason::ObstaclePresent, "refused for the right reason");
}

// The safety case the whole design exists for: a cell that saw a roof but
// never the road beneath it. A pooled map answers 2.4 m with confidence.
void test_occluded_ground_is_unknown_not_free() {
  veyra::map::CellStats cell;
  for (int i = 0; i < 20; ++i) cell.add(ret(2.4, 2.4, 0), 2.0);

  const auto verdict = veyra::map::classify(cell, veyra::map::VehicleProfile{}, 1);
  check(verdict.ground_state == veyra::map::GroundState::Occluded, "ground was never observed");
  check(verdict.traversability == veyra::map::Traversability::Unknown,
        "occluded ground is unknown, never drivable");
  check(verdict.reason == veyra::map::TerrainReason::NoGroundEvidence, "reason is the missing floor");
}

// A 12 cm kerb inside a 40 cm cell barely moves a pooled mean. The obstacle
// layer's min_z records it exactly.
void test_small_kerb_survives_in_layer() {
  veyra::map::CellStats cell;
  for (int i = 0; i < 60; ++i) cell.add(ret(0.0, 0.0, 1), 2.0);
  for (int i = 0; i < 4; ++i) cell.add(ret(0.12, 0.12, 0), 2.0);

  check(cell.mean_z() < 0.01, "pooled mean barely registers the kerb");
  check_close(static_cast<double>(cell.obstacle.min_z), 0.12, 1e-6, "kerb height preserved exactly");

  veyra::map::VehicleProfile profile;
  profile.step_limit_m = 0.10;
  const auto verdict = veyra::map::classify(cell, profile, 1);
  check(verdict.traversability == veyra::map::Traversability::NonDrivable,
        "a 12 cm kerb exceeds a 10 cm step limit");
}

// Overhead too low to pass under.
void test_low_bridge_blocks() {
  veyra::map::CellStats cell;
  for (int i = 0; i < 20; ++i) cell.add(ret(0.0, 0.0, 1), 2.5);
  for (int i = 0; i < 20; ++i) cell.add(ret(1.5, 1.5, 0), 2.5);  // below the 2.5 m envelope
  // 1.5 m return sits inside the envelope, so it is an obstacle, not overhead.
  check(!cell.obstacle.empty(), "a 1.5 m return under a 2.5 m envelope is an obstacle");

  veyra::map::CellStats bridge;
  for (int i = 0; i < 20; ++i) bridge.add(ret(0.0, 0.0, 1), 1.0);
  for (int i = 0; i < 20; ++i) bridge.add(ret(1.6, 1.6, 0), 1.0);  // above a 1.0 m envelope
  check(!bridge.overhead.empty(), "a 1.6 m return over a 1.0 m envelope is overhead");

  veyra::map::VehicleProfile profile;
  profile.clearance_envelope_m = 1.0;
  profile.vehicle_height_m = 1.0;
  const auto passes = veyra::map::classify(bridge, profile, 1);
  check(passes.traversability == veyra::map::Traversability::Drivable,
        "1.6 m clearance clears a 1.0 m vehicle");
  check_close(passes.clearance_m, 1.6, 1e-6, "clearance measured to the bridge soffit");

  // The same cell, a taller vehicle: now the bridge blocks. Nothing about the
  // stored evidence changed -- only the platform reading it -- which is why
  // the limits live in the profile and not in the cell.
  veyra::map::CellStats low;
  for (int i = 0; i < 20; ++i) low.add(ret(0.0, 0.0, 1), 1.0);
  for (int i = 0; i < 20; ++i) low.add(ret(1.6, 1.6, 0), 1.0);
  veyra::map::VehicleProfile tall_enough_to_hit;
  tall_enough_to_hit.clearance_envelope_m = 1.8;
  tall_enough_to_hit.vehicle_height_m = 1.8;
  const auto blocked = veyra::map::classify(low, tall_enough_to_hit, 1);
  check(blocked.traversability == veyra::map::Traversability::NonDrivable,
        "1.6 m clearance blocks a 1.8 m vehicle");
  check(blocked.reason == veyra::map::TerrainReason::InsufficientClearance,
        "refused on clearance, not on an obstacle");
}

// Depressions are hazards and must not be clamped away.
void test_depression_widens_ground_roughness() {
  veyra::map::CellStats cell;
  for (int i = 0; i < 20; ++i) cell.add(ret(0.0, 0.0, 1), 2.0);
  for (int i = 0; i < 20; ++i) cell.add(ret(-0.4, -0.4, 0), 2.0);

  check(cell.ground.count == 40, "sub-ground returns join the ground layer");
  check_close(static_cast<double>(cell.ground.min_z), -0.4, 1e-6, "pothole depth retained");
  const auto verdict = veyra::map::classify(cell, veyra::map::VehicleProfile{}, 1);
  check(verdict.traversability == veyra::map::Traversability::NonDrivable,
        "a 40 cm pothole is not drivable");
  check(verdict.reason == veyra::map::TerrainReason::GroundTooRough, "refused as roughness");
}

// Invariant 4, restated over the layers: Chan-merging the three layers must
// reproduce the pooled accumulator to the tolerances in
// docs/map-correctness.md. This is the claim that layering costs no
// accounting fidelity, held to the numbers rather than asserted in prose.
void test_pooled_reconstruction_matches_invariant_4() {
  veyra::map::CellStats cell;
  std::uint64_t t = 1;
  double ground_sum = 0.0;
  double obstacle_sum = 0.0;
  double overhead_sum = 0.0;
  for (int i = 0; i < 97; ++i) {
    const double z = 0.01 * i;
    ground_sum += z;
    cell.add(ret(z, 0.0, 1, t++), 2.0);
  }
  for (int i = 0; i < 53; ++i) {
    const double z = 0.7 + 0.01 * i;
    obstacle_sum += z;
    cell.add(ret(z, z, 0, t++), 2.0);
  }
  for (int i = 0; i < 31; ++i) {
    const double z = 3.0 + 0.02 * i;
    overhead_sum += z;
    cell.add(ret(z, z, 0, t++), 2.0);
  }
  const double ground_mean = ground_sum / 97.0;
  const double obstacle_mean = obstacle_sum / 53.0;
  const double overhead_mean = overhead_sum / 31.0;

  const auto pooled = cell.pooled_from_layers();
  check(pooled.count == cell.count, "count exact");
  check(cell.mean_z() == pooled.mean_z, "the pooled accessors are the reconstruction");
  check(cell.ground.count + cell.obstacle.count + cell.overhead.count == cell.count,
        "layers are exhaustive and disjoint");
  // Independent reference: the pooled mean the old stored accumulator would
  // have produced, recomputed here from first principles over the same data.
  const double reference_mean =
      (97.0 * ground_mean + 53.0 * obstacle_mean + 31.0 * overhead_mean) / 181.0;
  check_close(cell.mean_z(), reference_mean, std::fabs(reference_mean) * 1e-9 + 1e-12,
              "reconstructed mean matches a first-principles pooled mean, rel 1e-9");
  // min/max reconstruct to float precision, not to double. The layers store
  // these two as float, matching veyra::map::Cell, while the pooled fields on
  // CellStats are double. That is a deliberate asymmetry and it costs nothing:
  // the pooled fields are untouched by this change and remain the authoritative
  // record that invariant 4's exact-equality rule is stated over. Making the
  // layers double would widen HeightLayer from 32 to 40 bytes -- +24 per cell
  // -- to buy exactness in a cross-check rather than in the invariant itself.
  const double float_eps = 1e-6;
  check_close(cell.min_z(), 0.0, float_eps, "pooled min is the lowest ground return");
  check_close(cell.max_z(), 3.0 + 0.02 * 30.0, float_eps, "pooled max is the highest overhead");

  check_close(pooled.variance_z(), cell.m2_z() / static_cast<double>(cell.count),
              std::fabs(cell.m2_z() / static_cast<double>(cell.count)) * 1e-5,
              "variance agrees through the accessor, rel 1e-5");
}

// Merging two cells must merge layer-wise, or coarsening rebuilds the defect.
void test_merge_is_layer_wise() {
  veyra::map::CellStats a;
  for (int i = 0; i < 10; ++i) a.add(ret(0.0, 0.0, 1), 2.0);
  veyra::map::CellStats b;
  for (int i = 0; i < 10; ++i) b.add(ret(2.4, 2.4, 0), 2.0);

  a.merge(b);
  check(a.ground.count == 10, "ground survives the merge");
  check(a.overhead.count == 10, "overhead survives the merge");
  check_close(a.ground.mean_z, 0.0, 1e-9, "merged cell still knows the road height");

  const auto verdict = veyra::map::classify(a, veyra::map::VehicleProfile{}, 1);
  check(verdict.traversability == veyra::map::Traversability::Drivable,
        "a coarsened cell still reports drivable road under a roof");
}

// Absence of evidence ages to unknown, never to free.
void test_stale_obstacle_becomes_unknown_not_free() {
  veyra::map::CellStats cell;
  for (int i = 0; i < 20; ++i) cell.add(ret(0.0, 0.0, 1, 10), 2.0);
  for (int i = 0; i < 20; ++i) cell.add(ret(0.5, 0.5, 0, 10), 2.0);

  veyra::map::VehicleProfile profile;
  profile.staleness_horizon = 60;
  const auto fresh = veyra::map::classify(cell, profile, 30);
  check(fresh.traversability == veyra::map::Traversability::NonDrivable,
        "fresh obstacle evidence blocks");

  const auto stale = veyra::map::classify(cell, profile, 200);
  check(stale.traversability == veyra::map::Traversability::Unknown,
        "aged-out obstacle evidence is unknown");
  check(stale.reason == veyra::map::TerrainReason::StaleEvidence, "reason names staleness");
  check(stale.traversability != veyra::map::Traversability::Drivable,
        "a timeout must never produce free space");
}

// A missing ground model must not silently vanish.
void test_unmodelled_returns_are_counted_and_fail_safe() {
  veyra::map::CellStats cell;
  for (int i = 0; i < 5; ++i) cell.add(ret(0.0, 0.0, 1), 2.0);
  auto bad = ret(1.0, 0.0, 0);
  bad.height_above_ground = std::numeric_limits<float>::quiet_NaN();
  cell.add(bad, 2.0);

  check(cell.unmodelled_returns == 1, "degraded ground stage is visible, not silent");
  check(cell.obstacle.count == 1, "unmodelled return fails safe into the obstacle layer");
  check(cell.count == 6, "it still counts toward point conservation");
}

// Two envelopes cannot be reconciled without raw points, which the map does
// not keep. Refuse rather than answer wrongly.
// A producer that has not been updated to supply height_above_ground must be
// visible in telemetry, not silently absorbed. The V2 wire format does not
// carry the field yet, so this is the live runtime's current behaviour.
void test_unset_height_above_ground_is_loud() {
  veyra::map::Observation unset;  // as the runtime constructs it today
  unset.x = 1.0;
  unset.y = 1.0;
  unset.z = 1.0;
  unset.ground = 0;
  unset.timestamp = 1;

  veyra::map::CellStats cell;
  cell.add(unset, 2.0);
  check(cell.unmodelled_returns == 1, "an unset height is counted, not assumed to be zero");
  check(cell.overhead.empty(), "and never silently promoted to overhead");
  check(cell.obstacle.count == 1, "it fails safe into the obstacle layer");
}

void test_envelope_mismatch_refuses() {
  veyra::map::CellStats cell;
  cell.add(ret(0.0, 0.0, 1), 2.0);
  bool threw = false;
  try {
    cell.add(ret(0.0, 0.0, 1), 3.0);
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  check(threw, "re-sorting a cell under a different envelope is refused");

  veyra::map::VehicleProfile tall;
  tall.clearance_envelope_m = 4.0;
  tall.vehicle_height_m = 3.0;
  const auto verdict = veyra::map::classify(cell, tall, 1);
  check(verdict.envelope_mismatch, "a vehicle taller than the sorted envelope is flagged");
  check(verdict.traversability == veyra::map::Traversability::Unknown,
        "and gets unknown, not a guess");
}

// Evidence must still change its mind after a cell has accumulated returns.
//
// This is the guard on a reverted optimisation. Quantising the eight evidence
// floats to one byte each saved 24 bytes per cell and was implemented in full
// before this test was written. It froze them: because the fields are running
// averages, the per-update change (v - x)/n falls below one quantum after a
// few hundred returns, and every later update rounds straight back. Twenty
// thousand observations of 0.20 against a stored 0.73 moved it by exactly
// zero.
//
// Anyone tempted to shrink these fields again should run this test first.
void test_quantised_evidence_does_not_drift() {
  veyra::map::CellStats steady;
  for (int i = 0; i < 20000; ++i) {
    auto o = ret(0.0, 0.0, 1);
    o.terrain_confidence = 0.73F;
    o.observation_quality = 0.61F;
    steady.add(o, 2.0);
  }
  check_close(steady.terrain_confidence(), 0.73, 1e-3,
              "a constant input is held accurately after 20k updates");
  check_close(steady.observation_quality(), 0.61, 1e-3,
              "and so is a second field with a different value");

  // A step change must still be tracked: quantisation must not freeze a cell.
  for (int i = 0; i < 20000; ++i) {
    auto o = ret(0.0, 0.0, 1);
    o.terrain_confidence = 0.20F;
    steady.add(o, 2.0);
  }
  check(steady.terrain_confidence() < 0.50F,
        "and a sustained change in the input still moves the stored average");
  check_close(steady.terrain_confidence(), 0.465, 1e-3,
              "to the true running mean of the whole history");
}

// The cost of the layers, asserted rather than estimated.
//
// CellStats was 168 B and Leaf 184 B before retaining two ground-plane
// derivatives plus their observation count. They now measure 176 B and
// 192 B respectively; Observation grows 80 -> 88 B. Quantising the evidence
// floats was reverted -- see test_quantised_evidence_does_not_drift.
//
// Pinned here because an estimate is not a measurement: the first draft of
// docs/layered-map-design.md guessed +60 B by hand and was wrong by most of a
// factor of two, and this guard has already caught one silent drift.
void test_memory_cost_is_what_we_claim() {
  check(sizeof(veyra::map::HeightLayer) == 32, "HeightLayer stays 32 B, zero padding");
  check(sizeof(veyra::map::CellStats) == 176, "CellStats is 176 B with retained ground direction");
  check(sizeof(veyra::map::Leaf) == 192, "Leaf is 192 B with retained ground direction");
  check(sizeof(veyra::map::Observation) == 88, "Observation is 88 B with ground gradients");
}

void test_profile_slope_uses_ground_gradient_evidence() {
  veyra::map::CellStats cell;
  for (int i = 0; i < 5; ++i) {
    auto observation = ret(0.0, 0.0, 1);
    observation.ground_gradient_x = 0.5F;
    observation.ground_gradient_y = 0.0F;
    cell.add(observation, 2.0);
  }

  veyra::map::VehicleProfile wheeled;
  wheeled.max_slope_rad = 0.30;
  const auto wheeled_result = veyra::map::classify(cell, wheeled, 1);
  check(wheeled_result.traversability == veyra::map::Traversability::NonDrivable,
        "slope over the wheeled profile limit is refused");
  check_close(wheeled_result.slope_rad, std::atan(0.5), 1e-6,
              "slope is reconstructed from retained ground gradient");
  const double normal_length = std::sqrt(wheeled_result.normal_x * wheeled_result.normal_x +
                                         wheeled_result.normal_y * wheeled_result.normal_y +
                                         wheeled_result.normal_z * wheeled_result.normal_z);
  check_close(normal_length, 1.0, 1e-6, "derived surface normal is normalized");
  check_close(wheeled_result.normal_x, -0.5 / std::sqrt(1.25), 1e-6,
              "normal x follows the negative world-frame ground gradient");
  check_close(wheeled_result.normal_y, 0.0, 1e-6, "normal y follows the world-frame gradient");
  check_close(wheeled_result.normal_z, 1.0 / std::sqrt(1.25), 1e-6,
              "normal z is positive for an upward-facing ground surface");

  veyra::map::VehicleProfile legged;
  legged.max_slope_rad = 0.70;
  const auto legged_result = veyra::map::classify(cell, legged, 1);
  check(legged_result.traversability == veyra::map::Traversability::Drivable,
        "the same physical evidence is evaluated against the second profile");

  veyra::map::CellStats no_direction;
  for (int i = 0; i < 5; ++i) {
    no_direction.add(ret(0.0, 0.0, 1), 2.0);
  }
  const auto unknown_direction = veyra::map::classify(no_direction, legged, 1);
  check(!unknown_direction.slope_available,
        "missing gradient remains unavailable rather than being reported as a flat normal");
}

}  // namespace

int main() {
  test_road_under_vehicle_roof();
  test_obstacle_standing_on_road();
  test_occluded_ground_is_unknown_not_free();
  test_small_kerb_survives_in_layer();
  test_low_bridge_blocks();
  test_depression_widens_ground_roughness();
  test_pooled_reconstruction_matches_invariant_4();
  test_merge_is_layer_wise();
  test_stale_obstacle_becomes_unknown_not_free();
  test_unmodelled_returns_are_counted_and_fail_safe();
  test_envelope_mismatch_refuses();
  test_unset_height_above_ground_is_loud();
  test_quantised_evidence_does_not_drift();
  test_memory_cost_is_what_we_claim();
  test_profile_slope_uses_ground_gradient_evidence();

  if (failures == 0) {
    std::printf("test_layered_terrain: all checks passed\n");
    return 0;
  }
  std::printf("test_layered_terrain: %d check(s) failed\n", failures);
  return 1;
}
