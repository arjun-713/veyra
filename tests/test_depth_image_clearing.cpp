// Depth-image visibility clearing (D-Map approach; see docs/prior-art.md).
//
// The decisive case is test_beam_over_a_kerb_does_not_erase_it. A projected 2D
// sweep clears every column it sees past, so a beam that flew over a 12 cm
// kerb to strike a wall behind it erases the kerb. Carrying elevation is the
// entire point of doing this in 2.5D.

#include <cmath>
#include <cstdio>
#include <numbers>
#include <string>

#include "veyra/map/depth_image.hpp"
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

constexpr double kPi = std::numbers::pi;

veyra::map::DepthImage make_image() {
  // 1440 x 64: a quarter-degree azimuth step and 64 elevation rows over
  // [-25, +15] degrees, close to a 64-beam spinning unit.
  return veyra::map::DepthImage{1440, 64, -25.0 * kPi / 180.0, 15.0 * kPi / 180.0};
}

veyra::map::Observation ret(double x, double y, double z, double hag, std::uint8_t ground) {
  veyra::map::Observation o;
  o.x = x;
  o.y = y;
  o.z = z;
  o.height_above_ground = static_cast<float>(hag);
  o.ground = ground;
  o.timestamp = 1;
  o.terrain_confidence = 0.9F;
  o.semantic_confidence = 0.9F;
  o.observation_quality = 0.9F;
  return o;
}

// An obstacle cell holding returns spanning [base, top] at (x, y).
veyra::map::CellStats obstacle_cell(double x, double y, double base, double top) {
  veyra::map::CellStats cell;
  for (int i = 0; i < 10; ++i) cell.add(ret(x, y, 0.0, 0.0, 1), 2.0);
  cell.add(ret(x, y, base, base, 0), 2.0);
  cell.add(ret(x, y, top, top, 0), 2.0);
  return cell;
}

// A pedestrian who has walked away. Beams now reach the wall behind, at the
// pedestrian's own torso height, so they pass through the claimed extent.
void test_departed_obstacle_is_cleared() {
  veyra::map::SensorPose pose{0.0, 0.0, 1.8};
  auto image = make_image();
  // The wall at 20 m, sampled across the elevations a torso would occupy.
  for (double z = 0.0; z <= 2.0; z += 0.02) image.insert(20.0, 0.0, z, pose);

  auto cell = obstacle_cell(10.0, 0.0, 0.2, 1.8);
  const auto outcome =
      veyra::map::test_cell_against_scan(cell, 10.0, 0.0, image, pose, 0.10);
  check(outcome == veyra::map::ClearingOutcome::Cleared,
        "a beam measured at 20 m contradicts an obstacle claimed at 10 m");
}

// The case a 2D projection gets wrong.
void test_beam_over_a_kerb_does_not_erase_it() {
  veyra::map::SensorPose pose{0.0, 0.0, 1.8};
  auto image = make_image();
  // A wall at 20 m, but only at heights well above the kerb. Every beam that
  // reached it passed OVER the kerb, never through it.
  for (double z = 1.0; z <= 2.5; z += 0.02) image.insert(20.0, 0.0, z, pose);

  // A 12 cm kerb at 10 m: its extent subtends elevations far below those beams.
  auto kerb = obstacle_cell(10.0, 0.0, 0.0, 0.12);
  const auto outcome = veyra::map::test_cell_against_scan(kerb, 10.0, 0.0, image, pose, 0.10);

  check(outcome != veyra::map::ClearingOutcome::Cleared,
        "a beam that flew over the kerb must not clear the kerb");
  check(outcome == veyra::map::ClearingOutcome::SparedByElevation,
        "and the reason is recorded as an elevation miss, not as absent evidence");

  // The 2D projection this corrects: ignoring elevation, the sensor plainly
  // saw past 10 m along this bearing, so a projected sweep would clear it.
  const double azimuth = 0.0;
  bool projected_would_clear = false;
  for (int row = 0; row < static_cast<int>(image.elevation_bins()); ++row) {
    const double elevation =
        -25.0 * kPi / 180.0 + (40.0 * kPi / 180.0) * (row + 0.5) / image.elevation_bins();
    if (image.sees_past(azimuth, elevation, 10.0, 0.10)) projected_would_clear = true;
  }
  check(projected_would_clear,
        "a 2D projection really would have cleared it -- this is the bug being fixed");
}

// Nothing behind the obstacle: the scan stops at it, so it says nothing about
// what is there and the claim stands.
void test_surface_at_the_cell_is_occlusion_not_clearance() {
  veyra::map::SensorPose pose{0.0, 0.0, 1.8};
  auto image = make_image();
  for (double z = 0.0; z <= 2.0; z += 0.02) image.insert(10.0, 0.0, z, pose);

  auto cell = obstacle_cell(10.0, 0.0, 0.2, 1.8);
  const auto outcome = veyra::map::test_cell_against_scan(cell, 10.0, 0.0, image, pose, 0.10);
  check(outcome == veyra::map::ClearingOutcome::Occluded,
        "a return at the obstacle confirms it rather than clearing it");
}

// A bearing the scan never sampled proves nothing in either direction.
void test_unscanned_bearing_gives_no_evidence() {
  veyra::map::SensorPose pose{0.0, 0.0, 1.8};
  auto image = make_image();
  for (double z = 0.0; z <= 2.0; z += 0.02) image.insert(20.0, 0.0, z, pose);

  // Behind the sensor, where nothing was inserted.
  auto cell = obstacle_cell(-10.0, 0.0, 0.2, 1.8);
  const auto outcome = veyra::map::test_cell_against_scan(cell, -10.0, 0.0, image, pose, 0.10);
  check(outcome != veyra::map::ClearingOutcome::Cleared,
        "an unscanned bearing never clears");
}

// A cell with no obstacle claim has nothing to contradict.
void test_empty_obstacle_layer_is_a_no_op() {
  veyra::map::SensorPose pose{0.0, 0.0, 1.8};
  auto image = make_image();
  image.insert(20.0, 0.0, 1.0, pose);

  veyra::map::CellStats road;
  for (int i = 0; i < 10; ++i) road.add(ret(10.0, 0.0, 0.0, 0.0, 1), 2.0);
  check(veyra::map::test_cell_against_scan(road, 10.0, 0.0, image, pose, 0.10) ==
            veyra::map::ClearingOutcome::NoObstacle,
        "open road has no obstacle claim to contradict");
}

// Nearest-return semantics: a bin must not let a far return clear a cell that
// a nearer return in the same bin proves is occluded.
void test_bin_keeps_the_nearest_return() {
  veyra::map::SensorPose pose{0.0, 0.0, 0.0};
  auto image = make_image();
  image.insert(30.0, 0.0, 0.0, pose);  // far
  image.insert(5.0, 0.0, 0.0, pose);   // near, same bearing

  const auto measured = image.range_at(0.0, 0.0);
  check(std::fabs(measured - 5.0) < 0.05,
        "the bin reports the nearest return, so free space stops at the first surface");
  check(!image.sees_past(0.0, 0.0, 10.0, 0.1),
        "and nothing beyond that first surface may be claimed free");
}

// The margin exists so a surface does not clear itself through range noise.
void test_margin_prevents_self_clearing() {
  veyra::map::SensorPose pose{0.0, 0.0, 0.0};
  auto image = make_image();
  image.insert(10.03, 0.0, 0.0, pose);  // 3 cm of range noise beyond the cell

  check(!image.sees_past(0.0, 0.0, 10.0, 0.10),
        "3 cm of noise does not count as seeing past a surface at 10 m");
  check(image.sees_past(0.0, 0.0, 9.0, 0.10), "but a genuine metre does");
}

// End to end through the occupancy accumulator: clearing drives a cell to
// Free, and classify() then reports the cell drivable for the right reason.
void test_clearing_drives_occupancy_and_traversability() {
  veyra::map::SensorPose pose{0.0, 0.0, 1.8};
  auto image = make_image();
  for (double z = 0.0; z <= 2.0; z += 0.02) image.insert(20.0, 0.0, z, pose);

  auto cell = obstacle_cell(10.0, 0.0, 0.2, 1.8);
  veyra::map::VehicleProfile profile;
  profile.step_limit_m = 0.10;
  check(veyra::map::classify(cell, profile, 1).traversability ==
            veyra::map::Traversability::NonDrivable,
        "the obstacle blocks before clearing");

  // One scan is not enough: clamped log-odds needs repeated contradiction, so
  // a single spurious frame cannot delete a wall.
  int frames = 0;
  while (cell.occupancy() != veyra::map::OccupancyState::Free && frames < 100) {
    if (veyra::map::test_cell_against_scan(cell, 10.0, 0.0, image, pose, 0.10) ==
        veyra::map::ClearingOutcome::Cleared) {
      cell.observe_free();
    }
    ++frames;
  }
  check(frames > 1, "clearing takes more than one frame -- no single-frame deletion");
  check(frames < 30, "but it is bounded and quick");

  const auto after = veyra::map::classify(cell, profile, 1);
  check(after.traversability == veyra::map::Traversability::Drivable,
        "a contradicted obstacle stops blocking");
  check(after.reason == veyra::map::TerrainReason::ClearedByVisibility,
        "for the right reason");
  check(after.has_obstacle, "while the returns themselves are retained, not deleted");
}

}  // namespace

int main() {
  test_departed_obstacle_is_cleared();
  test_beam_over_a_kerb_does_not_erase_it();
  test_surface_at_the_cell_is_occlusion_not_clearance();
  test_unscanned_bearing_gives_no_evidence();
  test_empty_obstacle_layer_is_a_no_op();
  test_bin_keeps_the_nearest_return();
  test_margin_prevents_self_clearing();
  test_clearing_drives_occupancy_and_traversability();

  if (failures == 0) {
    std::printf("test_depth_image_clearing: all checks passed\n");
    return 0;
  }
  std::printf("test_depth_image_clearing: %d check(s) failed\n", failures);
  return 1;
}
