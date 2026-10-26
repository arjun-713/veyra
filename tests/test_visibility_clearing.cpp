// Native regression suites. CTest runs each section in a fresh process.
#include <cstdio>
#include <string_view>
#define main veyra_benchmark_program_main
#include "../src/runtime/engine.cpp"
#undef main
#include <cmath>
#include <cstdio>
#include <numbers>
#include <string>
#include "veyra/map/depth_image.hpp"
#include "veyra/map/map.hpp"
#include "veyra/map/terrain_query.hpp"
#include <optional>
#include <sstream>
#include "check.hpp"
#include <iostream>
#include <limits>
#include <vector>
#include "veyra/map/occupancy.hpp"

namespace depth_image_clearing {

// Depth-image visibility clearing (D-Map-inspired first-return approach).
//
// The decisive case is test_beam_over_a_kerb_does_not_erase_it. A projected 2D
// sweep clears every column it sees past, so a beam that flew over a 12 cm
// kerb to strike a wall behind it erases the kerb. Carrying elevation is the
// entire point of doing this in 2.5D.



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
  const auto outcome = veyra::map::test_cell_against_scan(cell, 10.0, 0.0, image, pose, 0.10);
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
  check(outcome != veyra::map::ClearingOutcome::Cleared, "an unscanned bearing never clears");
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

// A different elevation sees through part of a cell, but the SAME scan also
// directly observes an obstacle there. Negative evidence cannot erase that hit.
void test_current_scan_obstacle_is_not_self_cleared() {
  veyra::map::Map map{veyra::map::ResolutionPolicy::Uniform5};
  veyra::map::SensorPose pose{0.0, 0.0, 0.0};
  auto image = make_image();
  auto low = ret(10.025, 0.025, 0.2, 0.2, 0);
  auto high = ret(10.025, 0.025, 1.2, 1.2, 0);
  low.timestamp = high.timestamp = 42;
  map.update_at_level(low, 0);
  map.update_at_level(high, 0);
  image.insert(low, pose);
  image.insert(high, pose);
  image.insert(20.05, 0.05, 1.4, pose);
  const auto before = map.snapshot();
  const auto clearing = map.clear_free_space(image, pose);
  const auto after = map.snapshot();
  check(clearing.cleared == 0, "current obstacle hits dominate same-scan free evidence");
  check(
      after.leaves.front().stats.occupancy_logodds == before.leaves.front().stats.occupancy_logodds,
      "self-clearing must not reduce actual occupied support");
}

// The actual beam passes above the obstacle; the quantized row centre passes
// through it. A raster centre is not a measured ray and cannot license clearing.
void test_quantized_elevation_does_not_invent_a_crossing() {
  veyra::map::SensorPose pose{0.0, 0.0, 0.0};
  veyra::map::DepthImage image{1440, 1, 0.0, 0.1};
  image.insert(20.0, 0.0, 1.8, pose);
  auto cell = obstacle_cell(10.0, 0.0, 0.4, 0.6);
  check(veyra::map::test_cell_against_scan(cell, 10.0, 0.0, image, pose, 0.1) !=
            veyra::map::ClearingOutcome::Cleared,
        "a quantized row centre cannot manufacture free-space evidence");
}

void test_neighboring_beam_cannot_clear_a_cell_it_misses() {
  veyra::map::Map map{veyra::map::ResolutionPolicy::Uniform5};
  const veyra::map::SensorPose pose{0.0, 0.0, 0.0};
  auto image = make_image();
  map.update_at_level(ret(40.025, 0.025, 0.3, 0.3, 0), 0);
  map.update_at_level(ret(40.025, 0.025, 0.5, 0.5, 0), 0);
  // Same azimuth bin, but at x=40 the ray's y=0.10 misses [0, 0.05].
  image.insert(80.0, 0.20, 0.8, pose);
  const auto before = map.snapshot();
  map.clear_free_space(image, pose);
  check(map.snapshot().leaves.front().stats.occupancy_logodds ==
            before.leaves.front().stats.occupancy_logodds,
        "a neighboring measured ray must intersect the actual XY footprint");
}

void test_current_ground_does_not_protect_a_departed_obstacle() {
  veyra::map::Map map{veyra::map::ResolutionPolicy::Uniform5};
  const veyra::map::SensorPose pose{0.0, 0.0, 0.0};
  auto image = make_image();
  map.update_at_level(ret(10.025, 0.025, 0.2, 0.2, 0), 0);
  map.update_at_level(ret(10.025, 0.025, 1.2, 1.2, 0), 0);
  auto ground = ret(10.025, 0.025, 0.0, 0.0, 1);
  ground.timestamp = 2;
  map.update_at_level(ground, 0);
  image.insert(ground, pose);
  image.insert(20.05, 0.05, 1.4, pose);
  // Arming first: two contradictory passes raise the streak without moving
  // log-odds, and ground-only evidence must not reset it.
  check(map.clear_free_space(image, pose).armed == 1,
        "first contradiction arms rather than decrements");
  check(map.snapshot().leaves.front().stats.consecutive_misses == 1,
        "the streak is visible after one contradiction");
  check(map.clear_free_space(image, pose).armed == 1,
        "second contradiction completes arming, still no decrement");
  check(map.clear_free_space(image, pose).cleared == 1,
        "current ground must not protect historical obstacle evidence");
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
  check(after.reason == veyra::map::TerrainReason::ClearedByVisibility, "for the right reason");
  check(after.has_obstacle, "while the returns themselves are retained, not deleted");
}

}  // namespace

// Callers that omit the footprint (half_width_m defaults to 0) must keep the
// centre-column contract at every azimuth, not only along the x axis.
void test_default_footprint_clears_off_axis() {
  veyra::map::SensorPose pose{0.0, 0.0, 1.8};
  for (const double degrees : {30.0, 45.0, 73.0, 200.0}) {
    auto image = make_image();
    const double c = std::cos(degrees * std::numbers::pi / 180.0);
    const double s = std::sin(degrees * std::numbers::pi / 180.0);
    for (double z = 0.0; z <= 2.0; z += 0.02) image.insert(20.0 * c, 20.0 * s, z, pose);
    auto cell = obstacle_cell(10.0 * c, 10.0 * s, 0.2, 1.8);
    check(veyra::map::test_cell_against_scan(cell, 10.0 * c, 10.0 * s, image, pose, 0.10) ==
              veyra::map::ClearingOutcome::Cleared,
          "default footprint clears a departed obstacle off the x axis");
    check(veyra::map::test_cell_against_scan(cell, 10.0 * c, 10.0 * s, image, pose, 0.10, 0.025) ==
              veyra::map::ClearingOutcome::Cleared,
          "explicit footprint clears a departed obstacle off the x axis");
  }
}

int run() {
  test_default_footprint_clears_off_axis();
  test_departed_obstacle_is_cleared();
  test_beam_over_a_kerb_does_not_erase_it();
  test_surface_at_the_cell_is_occlusion_not_clearance();
  test_unscanned_bearing_gives_no_evidence();
  test_empty_obstacle_layer_is_a_no_op();
  test_bin_keeps_the_nearest_return();
  test_current_scan_obstacle_is_not_self_cleared();
  test_quantized_elevation_does_not_invent_a_crossing();
  test_neighboring_beam_cannot_clear_a_cell_it_misses();
  test_current_ground_does_not_protect_a_departed_obstacle();
  test_margin_prevents_self_clearing();
  test_clearing_drives_occupancy_and_traversability();

  if (failures == 0) {
    std::printf("test_depth_image_clearing: all checks passed\n");
    return 0;
  }
  std::printf("test_depth_image_clearing: %d check(s) failed\n", failures);
  return 1;
  return 0;
}

}  // namespace depth_image_clearing

namespace persistent_clearing {

// Persistent-engine visibility clearing (P0.2 Step 1).
//
// Exercises PersistentEngineSession -- the stateful F/P/E path the viewer
// drives -- not DepthImage alone. Frame N occupies a cell; frame N+1 looks
// straight through it at a wall behind; the pass must step occupancy down.
// Occluded (wall) and never-observed (parked) controls must be untouched.
// Clearing is opt-in (default off); no time-decay, no age eviction.




namespace {

std::string identity_pose() { return "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"; }

// V2 text point: 19 fields (x y z intensity class conf ground drivable slope
// roughness hcomplex tconf step motion_prob motion_state velx vely obs_q raw).
std::string point_record(double x, double y, double z) {
  std::ostringstream out;
  out << "P " << x << " " << y << " " << z << " 0.5 1 0.9 0 2 0 0 0.1 0.9 0 0.1 0 0 0 0.9 1";
  return out.str();
}

std::string frame_marker(std::uint64_t timestamp, std::uint64_t source_index, std::size_t count) {
  std::ostringstream out;
  out << "F " << timestamp << " " << timestamp << " " << source_index << " " << identity_pose()
      << " " << count;
  return out.str();
}

struct CellView {
  std::int16_t logodds = 0;
  std::uint32_t free_obs = 0;
  std::uint64_t count = 0;
  std::uint8_t streak = 0;
  bool found = false;
};

CellView find_cell(const veyra::map::MapSnapshot& snapshot, double x, double y) {
  CellView view;
  for (const auto& leaf : snapshot.leaves) {
    const double res = 0.05 * static_cast<double>(1 << leaf.id.level);
    const double min_x = static_cast<double>(leaf.id.ix) * res;
    const double min_y = static_cast<double>(leaf.id.iy) * res;
    if (x >= min_x && x < min_x + res && y >= min_y && y < min_y + res) {
      view.logodds = leaf.stats.occupancy_logodds;
      view.free_obs = leaf.stats.free_observations;
      view.count = leaf.stats.count;
      view.streak = leaf.stats.consecutive_misses;
      view.found = true;
      return view;
    }
  }
  return view;
}

void feed_points(PersistentEngineSession& session, const std::vector<std::string>& records) {
  for (const auto& record : records) session.ingest(record);
}

}  // namespace

int run() {
  constexpr double kPedX = 10.02;
  constexpr double kPedY = 0.02;
  constexpr double kParkedX = -10.02;
  constexpr double kParkedY = 0.02;
  constexpr double kWallX = 20.02;
  constexpr double kWallY = 0.02;

  // --- Enabled session: occupy then see through. ---
  Options options;
  options.policy = "uniform5";
  options.clearing_enabled = true;
  PersistentEngineSession session(options);

  // Frame 0: pedestrian (extent 0.2..1.8), parked car, wall surface.
  std::vector<std::string> frame0;
  for (double z = 0.2; z <= 1.81; z += 0.2) frame0.push_back(point_record(kPedX, kPedY, z));
  for (int i = 0; i < 5; ++i) frame0.push_back(point_record(kParkedX, kParkedY, 1.0));
  for (int i = 0; i < 5; ++i) frame0.push_back(point_record(kWallX, kWallY, 1.0));
  session.ingest(frame_marker(1000, 0, frame0.size()));
  feed_points(session, frame0);
  session.ingest("E");

  CHECK(session.result().clearing.has_value());
  CHECK(session.result().clearing->cleared == 0);
  const CellView ped_before = find_cell(session.result().snapshot, kPedX, kPedY);
  const CellView parked_before = find_cell(session.result().snapshot, kParkedX, kParkedY);
  const CellView wall_before = find_cell(session.result().snapshot, kWallX, kWallY);
  CHECK(ped_before.found);
  CHECK(parked_before.found);
  CHECK(wall_before.found);
  CHECK(ped_before.logodds >= veyra::map::logodds::kOccupiedThreshold);

  // Frame 1: pedestrian gone; dense wall sweep 0..2 m covers the claimed extent.
  // First contradiction only arms the streak: log-odds must not move.
  std::vector<std::string> frame1;
  for (double z = 0.0; z <= 2.001; z += 0.02) frame1.push_back(point_record(kWallX, kWallY, z));
  session.ingest(frame_marker(2000, 1, frame1.size()));
  feed_points(session, frame1);
  session.ingest("E");

  CHECK(session.result().clearing.has_value());
  CHECK(session.result().clearing->examined > 0);
  CHECK(session.result().clearing->cleared == 0);
  CHECK(session.result().clearing->armed > 0);
  const CellView ped_armed = find_cell(session.result().snapshot, kPedX, kPedY);
  CHECK(ped_armed.found);
  CHECK(ped_armed.logodds == ped_before.logodds);
  CHECK(ped_armed.free_obs == ped_before.free_obs);
  CHECK(ped_armed.streak == 1);

  // Frame 2: second contradiction completes arming; still no decrement.
  session.ingest(frame_marker(3000, 2, frame1.size()));
  feed_points(session, frame1);
  session.ingest("E");

  CHECK(session.result().clearing.has_value());
  CHECK(session.result().clearing->cleared == 0);
  CHECK(session.result().clearing->armed > 0);
  const CellView ped_armed2 = find_cell(session.result().snapshot, kPedX, kPedY);
  CHECK(ped_armed2.found);
  CHECK(ped_armed2.logodds == ped_before.logodds);
  CHECK(ped_armed2.free_obs == ped_before.free_obs);
  CHECK(ped_armed2.streak == 2);

  // Frame 3: sustained contradiction applies exactly one clamped miss.
  session.ingest(frame_marker(4000, 3, frame1.size()));
  feed_points(session, frame1);
  session.ingest("E");

  CHECK(session.result().clearing.has_value());
  CHECK(session.result().clearing->examined > 0);
  CHECK(session.result().clearing->cleared > 0);
  const CellView ped_after = find_cell(session.result().snapshot, kPedX, kPedY);
  const CellView parked_after = find_cell(session.result().snapshot, kParkedX, kParkedY);
  const CellView wall_after = find_cell(session.result().snapshot, kWallX, kWallY);
  CHECK(ped_after.found);
  CHECK(parked_after.found);
  CHECK(wall_after.found);
  // Contradicted cell steps toward free exactly once (clamped log-odds miss).
  CHECK(ped_after.logodds < ped_before.logodds);
  CHECK(ped_after.logodds == ped_before.logodds + veyra::map::logodds::kMiss);
  CHECK(ped_after.free_obs == ped_before.free_obs + 1);
  CHECK(ped_after.streak == 2);
  // Occluded control: the wall produced the beams; it is confirmed, never cleared.
  CHECK(wall_after.logodds >= wall_before.logodds);
  CHECK(wall_after.count > wall_before.count);
  // Parked/static control: no beam along its bearing, so untouched.
  CHECK(parked_after.logodds == parked_before.logodds);
  CHECK(parked_after.free_obs == parked_before.free_obs);
  CHECK(parked_after.count == parked_before.count);

  // --- Disabled session: same frames, no clearing (opt-in, default off). ---
  Options off;
  off.policy = "uniform5";
  CHECK(!off.clearing_enabled);
  PersistentEngineSession idle(off);
  idle.ingest(frame_marker(1000, 0, frame0.size()));
  feed_points(idle, frame0);
  idle.ingest("E");
  CHECK(!idle.result().clearing.has_value());
  const CellView ped_idle_before = find_cell(idle.result().snapshot, kPedX, kPedY);
  idle.ingest(frame_marker(2000, 1, frame1.size()));
  feed_points(idle, frame1);
  idle.ingest("E");
  CHECK(!idle.result().clearing.has_value());
  const CellView ped_idle_after = find_cell(idle.result().snapshot, kPedX, kPedY);
  CHECK(ped_idle_after.found);
  CHECK(ped_idle_after.logodds == ped_idle_before.logodds);
  CHECK(ped_idle_after.free_obs == ped_idle_before.free_obs);

  std::printf("test_persistent_clearing: all checks passed\n");
  return 0;
  return 0;
}

}  // namespace persistent_clearing

namespace batch_clearing {

// Batch-engine visibility-clearing guards (P0.2 Step 9).
//
// Drives production run() -- the stdin batch F/P/E path -- in-process via a
// redirected std::cin. Proves the batch path mirrors the persistent guards:
// rejected (out-of-window) points never populate the visibility raster, an
// invalid sensor pose skips clearing honestly, and an empty raster skips
// without touching the map. A see-through stream proves normal clearing still
// runs. Result.clearing reports the last frame only, so each case is its own
// stream ending with the frame under test.




namespace {

std::string identity_pose() { return "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"; }

// V2 text point: 19 fields (x y z intensity class conf ground drivable slope
// roughness hcomplex tconf step motion_prob motion_state velx vely obs_q raw).
std::string point_record(double x, double y, double z) {
  std::ostringstream out;
  out << "P " << x << " " << y << " " << z << " 0.5 1 0.9 0 2 0 0 0.1 0.9 0 0.1 0 0 0 0.9 1";
  return out.str();
}

std::string frame_marker(std::uint64_t timestamp, std::uint64_t source_index, std::size_t count) {
  std::ostringstream out;
  out << "F " << timestamp << " " << timestamp << " " << source_index << " " << identity_pose()
      << " " << count;
  return out.str();
}

struct CellView {
  std::int16_t logodds = 0;
  std::uint32_t free_obs = 0;
  std::uint64_t count = 0;
  bool found = false;
};

CellView find_cell(const veyra::map::MapSnapshot& snapshot, double x, double y) {
  CellView view;
  for (const auto& leaf : snapshot.leaves) {
    const double res = 0.05 * static_cast<double>(1 << leaf.id.level);
    const double min_x = static_cast<double>(leaf.id.ix) * res;
    const double min_y = static_cast<double>(leaf.id.iy) * res;
    if (x >= min_x && x < min_x + res && y >= min_y && y < min_y + res) {
      view.logodds = leaf.stats.occupancy_logodds;
      view.free_obs = leaf.stats.free_observations;
      view.count = leaf.stats.count;
      view.found = true;
      return view;
    }
  }
  return view;
}

// One production run() over a complete V2 text stream. run() reads std::cin,
// so the stream is swapped in for the call and restored after.
Result run_stream(const std::string& stream, const Options& options) {
  std::istringstream input(stream);
  auto* previous = std::cin.rdbuf(input.rdbuf());
  Result result;
  try {
    result = run(options);
  } catch (...) {
    std::cin.rdbuf(previous);
    throw;
  }
  std::cin.rdbuf(previous);
  return result;
}

std::string build_stream(const std::vector<std::vector<std::string>>& frames) {
  std::ostringstream out;
  out << "VEYRA_STREAM 2\nH batchtest\n";
  std::uint64_t timestamp = 1000;
  std::uint64_t source_index = 0;
  for (const auto& points : frames) {
    out << frame_marker(timestamp, source_index, points.size()) << "\n";
    for (const auto& point : points) out << point << "\n";
    out << "E\n";
    timestamp += 1000;
    ++source_index;
  }
  out << "D batchtest\n";
  return out.str();
}

Options clearing_options() {
  Options options;
  options.policy = "uniform5";
  options.clearing_enabled = true;
  return options;
}

}  // namespace

int run() {
  constexpr double kPedX = 10.02;
  constexpr double kPedY = 0.02;
  constexpr double kParkedX = -10.02;
  constexpr double kParkedY = 0.02;
  constexpr double kWallX = 20.02;
  constexpr double kWallY = 0.02;
  // Same bearing as the pedestrian but far outside the default 100 m window:
  // rejected by ingest_observation, so it must never reach the raster. Its
  // bearings coincide with the pedestrian's own bin, so a polluted raster
  // would clear the pedestrian.
  constexpr double kFarX = 500.02;
  constexpr double kFarY = 0.02;

  // Frame 0: pedestrian (extent 0.2..1.8), parked car, wall surface.
  std::vector<std::string> occupy;
  for (double z = 0.2; z <= 1.81; z += 0.2) occupy.push_back(point_record(kPedX, kPedY, z));
  for (int i = 0; i < 5; ++i) occupy.push_back(point_record(kParkedX, kParkedY, 1.0));
  for (int i = 0; i < 5; ++i) occupy.push_back(point_record(kWallX, kWallY, 1.0));

  // See-through: pedestrian gone; dense wall sweep 0..2 m covers the claimed
  // extent at the pedestrian's own elevations.
  std::vector<std::string> see_through;
  for (double z = 0.0; z <= 2.001; z += 0.02)
    see_through.push_back(point_record(kWallX, kWallY, z));

  // --- Normal clearing still runs on the batch path. ---
  // Result.clearing reports the last frame only. The first two contradictory
  // frames arm the streak (no decrement); the third applies the first miss.
  {
    const Result armed_once = run_stream(build_stream({occupy, see_through}), clearing_options());
    CHECK(armed_once.clearing.has_value());
    CHECK(armed_once.clearing->examined > 0);
    CHECK(armed_once.clearing->cleared == 0);
    CHECK(armed_once.clearing->armed > 0);
    const CellView flicker = find_cell(armed_once.snapshot, kPedX, kPedY);
    CHECK(flicker.found);
    CHECK(flicker.free_obs == 0);
    CHECK(flicker.logodds >= veyra::map::logodds::kOccupiedThreshold);

    const Result result = run_stream(build_stream({occupy, see_through, see_through, see_through}),
                                     clearing_options());
    CHECK(result.clearing.has_value());
    CHECK(result.clearing->examined > 0);
    CHECK(result.clearing->cleared > 0);
    const CellView ped = find_cell(result.snapshot, kPedX, kPedY);
    CHECK(ped.found);
    CHECK(ped.free_obs == 1);
    // Ingestion pins identical hits at one kHit, so the first applied miss
    // steps 847 -> 442 (Unknown, not Free): exactly one decrement past arming.
    CHECK(ped.logodds == veyra::map::logodds::kHit + veyra::map::logodds::kMiss);
    CHECK(ped.logodds < veyra::map::logodds::kOccupiedThreshold);
    CHECK(ped.logodds > veyra::map::logodds::kFreeThreshold);
  }

  // --- Rejected-only final frame: nothing accepted, so the raster stays empty
  // and clearing is skipped honestly (reset to nullopt, not stale stats). ---
  {
    std::vector<std::string> far_sweep;
    for (double z = 0.0; z <= 2.001; z += 0.02) far_sweep.push_back(point_record(kFarX, kFarY, z));
    const Result result = run_stream(build_stream({occupy, far_sweep}), clearing_options());
    CHECK(result.rejected_out_of_window == far_sweep.size());
    CHECK(result.input_points == occupy.size());
    CHECK(!result.clearing.has_value());
    const CellView ped = find_cell(result.snapshot, kPedX, kPedY);
    CHECK(ped.found);
    CHECK(ped.logodds >= veyra::map::logodds::kOccupiedThreshold);
    CHECK(ped.free_obs == 0);
  }

  // --- Empty final frame (zero-count): no evidence, no clearing, no leak. ---
  {
    const Result result =
        run_stream(build_stream({occupy, std::vector<std::string>{}}), clearing_options());
    CHECK(result.rejected_out_of_window == 0);
    CHECK(!result.clearing.has_value());
    const CellView ped = find_cell(result.snapshot, kPedX, kPedY);
    CHECK(ped.found);
    CHECK(ped.logodds >= veyra::map::logodds::kOccupiedThreshold);
    CHECK(ped.free_obs == 0);
  }

  // --- Invalid sensor pose (NaN height): accepted points still ingest, but
  // clearing is skipped honestly instead of running on a fabricated pose. ---
  {
    Options options = clearing_options();
    options.sensor_height_m = std::numeric_limits<double>::quiet_NaN();
    const Result result = run_stream(build_stream({occupy, see_through}), options);
    CHECK(!result.clearing.has_value());
    const CellView ped = find_cell(result.snapshot, kPedX, kPedY);
    CHECK(ped.found);
    CHECK(ped.logodds >= veyra::map::logodds::kOccupiedThreshold);
    CHECK(ped.free_obs == 0);
    // The contradictory wall returns still ingested; only clearing was gated.
    CHECK(result.input_points == occupy.size() + see_through.size());
  }

  std::printf("test_batch_clearing: all checks passed\n");
  return 0;
  return 0;
}

}  // namespace batch_clearing

int main(int argc, char** argv) {
  if (argc == 2) {
    const std::string_view suite{argv[1]};
    if (suite == "depth_image_clearing") return depth_image_clearing::run();
    if (suite == "persistent_clearing") return persistent_clearing::run();
    if (suite == "batch_clearing") return batch_clearing::run();
  }
  std::fputs("Select a registered CTest suite.\n", stderr);
  return 2;
}
