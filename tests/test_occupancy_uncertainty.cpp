// Bayesian occupancy and range-aware ingestion.
//
// These two mechanisms are standard in mature mapping systems and were absent
// from Veyra: log-odds occupancy with clamping (OctoMap, UFOMap, ROG-Map) and
// a sensor noise model with Mahalanobis outlier rejection (ETH/ANYbotics
// elevation_mapping). See docs/prior-art.md.

#include <cmath>
#include <cstdio>
#include <string>

#include "veyra/map/map.hpp"
#include "veyra/map/occupancy.hpp"
#include "veyra/map/sensor_model.hpp"
#include "veyra/map/terrain_query.hpp"

namespace {

int failures = 0;

void check(bool condition, const std::string& what) {
  if (!condition) {
    std::printf("FAIL: %s\n", what.c_str());
    ++failures;
  }
}

veyra::map::Observation ret(double x, double z, double hag, std::uint8_t ground,
                            std::uint64_t t = 1) {
  veyra::map::Observation o;
  o.x = x;
  o.y = 0.0;
  o.z = z;
  o.height_above_ground = static_cast<float>(hag);
  o.ground = ground;
  o.timestamp = t;
  o.terrain_confidence = 0.9F;
  o.semantic_confidence = 0.8F;
  o.observation_quality = 0.9F;
  return o;
}

// The property clamping exists to provide: however long a cell has been
// observed as occupied, it can be contradicted in a bounded number of
// observations. Without clamping this number grows without limit and a parked
// car that drives away persists for minutes.
void test_clamping_bounds_time_to_change_mind() {
  veyra::map::CellStats brief;
  for (int i = 0; i < 5; ++i) brief.observe_occupied();
  veyra::map::CellStats long_observed;
  for (int i = 0; i < 100000; ++i) long_observed.observe_occupied();

  check(brief.occupancy() == veyra::map::OccupancyState::Occupied, "5 hits occupy a cell");
  check(long_observed.occupancy_logodds == veyra::map::logodds::kClampMax,
        "100k hits saturate at the clamp rather than accumulating");
  check(brief.occupancy_logodds == long_observed.occupancy_logodds,
        "a cell observed 100k times is no harder to contradict than one observed 5 times");

  int misses = 0;
  while (long_observed.occupancy() != veyra::map::OccupancyState::Free && misses < 1000) {
    long_observed.observe_free();
    ++misses;
  }
  check(long_observed.occupancy() == veyra::map::OccupancyState::Free,
        "a saturated cell does clear");
  check(misses == veyra::map::logodds::misses_to_clear_from_saturated(),
        "and in exactly the bounded number of observations the header advertises");
  check(misses < 20, "which is a small number -- 100k hits did not buy 100k of inertia");
}

// Unknown is a real state with a wide band, not a coin flip between free and
// occupied. A cell with one hit and one miss must not read as either.
void test_unknown_is_a_real_state() {
  veyra::map::CellStats fresh;
  check(fresh.occupancy() == veyra::map::OccupancyState::Unknown, "a new cell is unknown");

  veyra::map::CellStats mixed;
  mixed.observe_occupied();
  mixed.observe_free();
  check(mixed.occupancy() == veyra::map::OccupancyState::Unknown,
        "one hit and one miss is unknown, not a decision");
}

// Ageing must never produce Free. Only observe_free() may, and only a beam
// through the volume calls it.
void test_only_visibility_produces_free() {
  veyra::map::CellStats cell;
  for (int i = 0; i < 20; ++i) cell.add(ret(1.0, 0.0, 0.0, 1), 2.0);
  for (int i = 0; i < 20; ++i) cell.add(ret(1.0, 0.5, 0.5, 0), 2.0);

  // add() without the sensor overload records geometry but asserts no
  // occupancy, so the cell is Unknown, not Free.
  check(cell.occupancy() != veyra::map::OccupancyState::Free,
        "accumulating returns never makes a cell free");

  veyra::map::VehicleProfile profile;
  profile.staleness_horizon = 10;
  const auto aged = veyra::map::classify(cell, profile, 10000);
  check(aged.traversability == veyra::map::Traversability::Unknown,
        "ageing gives unknown");
  check(aged.traversability != veyra::map::Traversability::Drivable,
        "ageing never gives drivable");
}

// The walk-stop-walk case from docs/layered-map-design.md 3.4, now executable
// rather than a prose claim.
void test_pedestrian_clears_without_eroding_the_kerb() {
  // A cell the pedestrian stood in: ground plus torso-height returns.
  veyra::map::CellStats person_cell;
  for (int i = 0; i < 10; ++i) person_cell.add(ret(1.0, 0.0, 0.0, 1, 10), 2.0);
  for (int i = 0; i < 10; ++i) person_cell.add(ret(1.0, 1.1, 1.1, 0, 10), 2.0);
  for (int i = 0; i < 10; ++i) person_cell.observe_occupied();

  // A kerb cell behind them: occluded while they stood there, so it receives
  // no returns and no beams at all.
  veyra::map::CellStats kerb_cell;
  for (int i = 0; i < 10; ++i) kerb_cell.add(ret(2.0, 0.0, 0.0, 1, 10), 2.0);
  for (int i = 0; i < 4; ++i) kerb_cell.add(ret(2.0, 0.14, 0.14, 0, 10), 2.0);
  for (int i = 0; i < 4; ++i) kerb_cell.observe_occupied();

  veyra::map::VehicleProfile profile;
  profile.step_limit_m = 0.10;
  profile.staleness_horizon = 50;

  // While the person stands there, both cells block.
  check(veyra::map::classify(person_cell, profile, 20).traversability ==
            veyra::map::Traversability::NonDrivable,
        "the standing pedestrian blocks");
  check(veyra::map::classify(kerb_cell, profile, 20).traversability ==
            veyra::map::Traversability::NonDrivable,
        "the kerb blocks");

  // The person walks on. Beams now pass through the volume they occupied.
  for (int i = 0; i < 10; ++i) person_cell.observe_free();
  // The kerb becomes visible again and is re-confirmed by returns.
  for (int i = 0; i < 4; ++i) kerb_cell.add(ret(2.0, 0.14, 0.14, 0, 200), 2.0);
  for (int i = 0; i < 4; ++i) kerb_cell.observe_occupied();

  const auto cleared = veyra::map::classify(person_cell, profile, 200);
  check(cleared.traversability == veyra::map::Traversability::Drivable,
        "the departed pedestrian's cell clears");
  check(cleared.reason == veyra::map::TerrainReason::ClearedByVisibility,
        "and clears for the right reason -- visibility, not a timer");
  check(cleared.has_obstacle,
        "while the obstacle returns themselves are retained, not deleted");

  const auto kerb = veyra::map::classify(kerb_cell, profile, 200);
  check(kerb.traversability == veyra::map::Traversability::NonDrivable,
        "the kerb behind them was never eroded");
  check(kerb.reason == veyra::map::TerrainReason::ObstaclePresent, "and still blocks on geometry");
}

// A single spurious return must not permanently shift a cell's surface.
void test_outlier_is_rejected_and_counted() {
  veyra::map::SensorNoiseModel noise;
  veyra::map::SensorPose pose;  // sensor at the origin
  veyra::map::CellStats cell;

  for (int i = 0; i < 20; ++i) {
    check(cell.add(ret(5.0, 0.0, 0.0, 1), 2.0, noise, pose), "clean returns are accepted");
  }
  const double before = cell.ground.mean_z;

  // A wild return 4 m above a surface observed 20 times at 5 m range.
  const bool accepted = cell.add(ret(5.0, 4.0, 0.0, 1), 2.0, noise, pose);
  check(!accepted, "a 4 m outlier at 5 m range is rejected");
  check(cell.rejected_outliers == 1, "and counted, not silently dropped");
  check(cell.ground.mean_z == before, "the surface estimate is untouched");
  check(cell.ground.count == 20, "and it does not enter the statistics");
}

// The gate must widen with range, or it would reject the distant returns the
// noise model exists to accommodate.
void test_gate_widens_with_range() {
  veyra::map::SensorNoiseModel noise;
  veyra::map::SensorPose pose;

  // Same 12 cm disagreement, observed at 5 m and at 80 m.
  auto build = [&](double x) {
    veyra::map::CellStats c;
    for (int i = 0; i < 20; ++i) c.add(ret(x, 0.0, 0.0, 1), 2.0, noise, pose);
    return c;
  };
  veyra::map::CellStats near = build(5.0);
  veyra::map::CellStats far = build(80.0);

  const bool near_accepted = near.add(ret(5.0, 0.12, 0.0, 1), 2.0, noise, pose);
  const bool far_accepted = far.add(ret(80.0, 0.12, 0.0, 1), 2.0, noise, pose);

  check(!near_accepted, "12 cm of disagreement at 5 m exceeds what the sensor can explain");
  check(far_accepted, "the same 12 cm at 80 m is within beam-divergence error and is accepted");
  check(noise.stddev_at(80.0) > noise.stddev_at(5.0), "modelled noise grows with range");
}

// Gating must not begin before there is something to gate against, or the
// first spurious return would lock the cell and reject the true surface.
void test_gate_does_not_engage_on_an_empty_layer() {
  veyra::map::SensorNoiseModel noise;
  veyra::map::SensorPose pose;
  veyra::map::CellStats cell;

  check(cell.add(ret(5.0, 3.0, 0.0, 1), 2.0, noise, pose), "the first return is always accepted");
  for (int i = 0; i < 4; ++i) {
    check(cell.add(ret(5.0, 0.0, 0.0, 1), 2.0, noise, pose),
          "and so are the next few, before the gate engages");
  }
  check(cell.rejected_outliers == 0, "no rejections while the layer is still establishing itself");
}

// Coarsening must not make a cell harder to contradict than its children were.
void test_merge_averages_occupancy_rather_than_summing() {
  veyra::map::CellStats a;
  veyra::map::CellStats b;
  for (int i = 0; i < 50; ++i) {
    a.add(ret(1.0, 0.0, 0.0, 1), 2.0);
    b.add(ret(1.0, 0.0, 0.0, 1), 2.0);
    a.observe_occupied();
    b.observe_occupied();
  }
  check(a.occupancy_logodds == veyra::map::logodds::kClampMax, "both children saturated");

  a.merge(b);
  check(a.occupancy_logodds <= veyra::map::logodds::kClampMax,
        "the merged parent stays inside the clamp");
  check(a.occupancy() == veyra::map::OccupancyState::Occupied, "and is still occupied");

  int misses = 0;
  while (a.occupancy() != veyra::map::OccupancyState::Free && misses < 1000) {
    a.observe_free();
    ++misses;
  }
  check(misses == veyra::map::logodds::misses_to_clear_from_saturated(),
        "a coarsened cell clears as fast as a fine one -- coarsening buys no inertia");
}

void test_memory_cost_of_occupancy() {
  // 8 bytes bought the entire occupancy and outlier-accounting system:
  // int16 log-odds, uint16 rejections, uint32 free observations.
  check(sizeof(veyra::map::CellStats) == 168, "CellStats is 168 B");
  check(sizeof(veyra::map::Leaf) == 184, "Leaf is 184 B");
}

}  // namespace

int main() {
  test_clamping_bounds_time_to_change_mind();
  test_unknown_is_a_real_state();
  test_only_visibility_produces_free();
  test_pedestrian_clears_without_eroding_the_kerb();
  test_outlier_is_rejected_and_counted();
  test_gate_widens_with_range();
  test_gate_does_not_engage_on_an_empty_layer();
  test_merge_averages_occupancy_rather_than_summing();
  test_memory_cost_of_occupancy();

  if (failures == 0) {
    std::printf("test_occupancy_uncertainty: all checks passed\n");
    return 0;
  }
  std::printf("test_occupancy_uncertainty: %d check(s) failed\n", failures);
  return 1;
}
