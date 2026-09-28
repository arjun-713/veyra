// Static-surface erosion by visibility clearing (regressions from the
// SemanticPOSS 00 paired replay of #68).
//
// With clearing on, parked cars and static structure lost Occupied cells, and
// 1172 of 15251 obstacle cells hit by the CURRENT scan read non-Occupied. Each
// test below pins one of the measured root causes:
//
//  1. a cell hit this scan was not re-confirmed (count-averaged log-odds);
//  2. the "consecutive" contradiction streak survived non-contradicting frames;
//  3. only the cell-centre azimuth bin was examined, so blocking beams in the
//     other bins the footprint spans were ignored;
//  4. no range-dependent tolerance: beams ending within range noise of the
//     surface behind a cell, or grazing a claim edge, counted as pass-through;
//  5. the raster was hard-coded for a uniform 64-row sensor; a 40-beam
//     non-uniform Pandora folded beams together and discarded evidence.
//
// Movers must still clear: see test_departed_mover_still_clears here and
// tests/test_ghost_retention.cpp.

#define main veyra_benchmark_program_main
#include "../src/runtime/engine.cpp"
#undef main

#include <cmath>
#include <cstdio>
#include <numbers>
#include <string>
#include <vector>

namespace {

namespace vm = veyra::map;

int failures = 0;

void check(bool condition, const char* what) {
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", what);
    ++failures;
  }
}

constexpr double kDeg = std::numbers::pi / 180.0;
const vm::SensorPose kPose{0.0, 0.0, 1.8};

vm::DepthImage uniform64() { return vm::DepthImage{1440, 64, -25.0 * kDeg, 15.0 * kDeg}; }

// Hesai Pandora (Pandar40) beam elevations, estimated from SemanticPOSS 00
// sensor-frame returns: 1 deg spacing at the edges, ~0.33 deg in the middle.
const std::vector<double> kPandora40Deg{
    -15.57, -14.65, -13.71, -12.75, -11.79, -10.83, -9.85, -8.87, -7.87, -6.89,
    -5.89,  -5.55,  -5.21,  -4.87,  -4.55,  -4.21,  -3.87, -3.53, -3.19, -2.85,
    -2.51,  -2.19,  -1.85,  -1.51,  -1.17,  -0.83,  -0.49, -0.15, 0.19,  0.53,
    0.87,   1.21,   1.53,   1.89,   2.21,   3.23,   4.25,  5.25,  6.25,  7.27};

vm::DepthImage pandora40() {
  std::vector<double> beams;
  for (const double d : kPandora40Deg) beams.push_back(d * kDeg);
  return vm::DepthImage::for_beams(1440, beams);
}

vm::Observation obstacle_return(double x, double y, double z, std::uint64_t timestamp) {
  vm::Observation o;
  o.x = x;
  o.y = y;
  o.z = z;
  o.height_above_ground = static_cast<float>(z);
  o.ground = 0;
  o.timestamp = timestamp;
  o.terrain_confidence = 0.9F;
  o.semantic_confidence = 0.9F;
  o.observation_quality = 0.9F;
  return o;
}

// A world point at (range_h horizontal, azimuth, elevation) from kPose.
void insert_beam(vm::DepthImage& image, double horizontal, double azimuth_deg,
                 double elevation_deg, std::uint64_t timestamp) {
  const double x = horizontal * std::cos(azimuth_deg * kDeg);
  const double y = horizontal * std::sin(azimuth_deg * kDeg);
  const double z = kPose.z + horizontal * std::tan(elevation_deg * kDeg);
  image.insert(obstacle_return(x, y, z, timestamp), kPose);
}

// The obstacle cell under test: 5 cm cell x in [10.00, 10.05], y in [0, 0.05].
constexpr double kCellX = 10.02;
constexpr double kCellY = 0.02;

// A scan that sees straight through the cell to a wall at 20 m, at every
// torso height (the departed-pedestrian geometry of test_ghost_retention).
vm::DepthImage see_through(std::uint64_t timestamp) {
  auto image = uniform64();
  for (double z = 0.0; z <= 2.0; z += 0.02) {
    image.insert(obstacle_return(20.0 * kCellX / 10.0, 20.0 * kCellY / 10.0, z, timestamp), kPose);
  }
  return image;
}

// A scan whose beams end AT the cell's surface (occluding/supporting) without
// being ingested into it, e.g. returns that fell in the neighbouring cell.
vm::DepthImage blocked_at_surface(std::uint64_t timestamp) {
  auto image = uniform64();
  for (double z = 0.0; z <= 2.0; z += 0.02) {
    image.insert(obstacle_return(kCellX + 0.01, kCellY, z, timestamp), kPose);
  }
  return image;
}

vm::Map occupied_cell_map() {
  vm::Map map(vm::ResolutionPolicy::Uniform5);
  for (double z = 0.2; z <= 1.81; z += 0.2) map.update(obstacle_return(kCellX, kCellY, z, 1));
  return map;
}

const vm::CellStats* cell_of(const vm::MapSnapshot& snapshot) {
  const auto ix = static_cast<std::int64_t>(std::floor(kCellX / 0.05));
  const auto iy = static_cast<std::int64_t>(std::floor(kCellY / 0.05));
  for (const auto& leaf : snapshot.leaves) {
    if (leaf.id.level == 0 && leaf.id.ix == ix && leaf.id.iy == iy) {
      return &leaf.stats;
    }
  }
  return nullptr;
}

// Root cause 1. Drive a static cell Free with sustained see-through frames,
// then hit it in a new scan: that scan's returns must make it Occupied, and a
// see-through raster of the same scan must not take it back.
void test_cell_hit_in_current_scan_is_never_non_occupied() {
  auto map = occupied_cell_map();
  std::uint64_t t = 1;
  for (int frame = 0; frame < 12; ++frame) (void)map.clear_free_space(see_through(++t), kPose);
  {
    const auto snapshot = map.snapshot();
    const auto* stats = cell_of(snapshot);
    check(stats != nullptr && stats->occupancy() == vm::OccupancyState::Free,
          "precondition: sustained see-through clears the cell");
  }
  ++t;
  map.update(obstacle_return(kCellX, kCellY, 1.0, t));
  {
    const auto snapshot = map.snapshot();
    const auto* stats = cell_of(snapshot);
    check(stats != nullptr && stats->occupancy() == vm::OccupancyState::Occupied,
          "an obstacle return in this scan makes the cell Occupied in this scan");
  }
  (void)map.clear_free_space(see_through(t), kPose);
  const auto snapshot = map.snapshot();
  const auto* stats = cell_of(snapshot);
  check(stats != nullptr && stats->occupancy() == vm::OccupancyState::Occupied,
        "and clearing in the same scan does not free a cell that scan hit");
}

// Root cause 1, accumulation. A static surface re-observed every scan builds
// evidence (one clamped kHit per scan) instead of pinning at exactly kHit, so
// one applied miss no longer demotes it.
void test_repeated_scans_accumulate_evidence() {
  vm::Map map(vm::ResolutionPolicy::Uniform5);
  for (std::uint64_t t = 1; t <= 5; ++t) {
    for (double z = 0.2; z <= 1.81; z += 0.2) map.update(obstacle_return(kCellX, kCellY, z, t));
  }
  const auto snapshot = map.snapshot();
  const auto* stats = cell_of(snapshot);
  check(stats != nullptr && stats->occupancy_logodds == vm::logodds::kClampMax,
        "five scans of a static surface saturate at the clamp (4 x kHit > clamp)");
  // Same-scan returns add nothing beyond the first: one scan is one hit.
  vm::Map single(vm::ResolutionPolicy::Uniform5);
  for (int i = 0; i < 20; ++i) single.update(obstacle_return(kCellX, kCellY, 1.0, 7));
  const auto one = single.snapshot();
  const auto* one_stats = cell_of(one);
  check(one_stats != nullptr && one_stats->occupancy_logodds == vm::logodds::kHit,
        "twenty returns of one scan are one kHit, not twenty");
}

// Root cause 2. A static surface flickers: every other frame a beam passes
// through, but the frames between test the claim and are NOT contradictory.
// The streak counts CONSECUTIVE contradictions, so it never arms.
void test_intermittent_contradiction_with_non_contradicting_frames_is_not_cleared() {
  auto map = occupied_cell_map();
  std::uint64_t t = 1;
  for (int round = 0; round < 10; ++round) {
    (void)map.clear_free_space(see_through(++t), kPose);
    (void)map.clear_free_space(blocked_at_surface(++t), kPose);
  }
  const auto snapshot = map.snapshot();
  const auto* stats = cell_of(snapshot);
  check(stats != nullptr, "cell still resident");
  if (stats == nullptr) return;
  check(stats->free_observations == 0, "alternating flicker never applies a miss");
  check(stats->occupancy_logodds == vm::logodds::kHit, "log-odds untouched");
  check(stats->occupancy() == vm::OccupancyState::Occupied, "still Occupied");
}

// Root cause 3. A 20 cm cell at 15 m spans three quarter-degree azimuth bins.
// A through-beam in the centre bin and a beam ending on the surface in the
// next bin: blocked-wins must see the second beam.
void test_blocking_beam_in_another_bin_of_the_footprint_wins() {
  vm::CellStats cell;
  // Footprint x in [15.0, 15.2], y in [0, 0.2]; claim [0.2, 1.8].
  cell.add(obstacle_return(15.1, 0.1, 0.2, 1), 2.0);
  cell.add(obstacle_return(15.1, 0.1, 1.8, 1), 2.0);
  auto image = uniform64();
  insert_beam(image, 30.0, 0.38, -3.19, 2);  // centre bin, through the claim to 30 m
  insert_beam(image, 15.1, 0.60, -2.51, 2);  // next bin, ends on the surface
  check(vm::test_cell_against_scan(cell, 15.1, 0.1, image, kPose, 0.10, 0.1) ==
            vm::ClearingOutcome::Occluded,
        "a beam stopped by the surface anywhere in the footprint blocks clearing");
}

// Root cause 4a. At 30 m, sigma(r) = 2 cm + 0.0017 r = 7.1 cm. A beam that
// ends 15 cm past the exit (the surface just behind this edge cell) is within
// range noise of it and is not a pass-through; one ending metres past still is.
void test_range_noise_is_not_pass_through() {
  const vm::MapConfig config;
  const vm::ClearingTolerance tolerance{&config.clearing_noise, config.clearing_range_sigmas,
                                        config.clearing_height_sigmas};
  vm::CellStats cell;  // 5 cm cell x in [30.00, 30.05], y in [0, 0.05]
  cell.add(obstacle_return(30.02, 0.02, 0.2, 1), 2.0);
  cell.add(obstacle_return(30.02, 0.02, 1.8, 1), 2.0);
  const double azimuth = std::atan2(0.025, 30.025) / kDeg;
  auto near_surface = uniform64();
  insert_beam(near_surface, 30.05 + 0.15, azimuth, -1.51, 2);
  check(vm::test_cell_against_scan(cell, 30.025, 0.025, near_surface, kPose, 0.10, 0.025) ==
            vm::ClearingOutcome::Cleared,
        "precondition: the bare 10 cm margin calls this a pass-through");
  check(vm::test_cell_against_scan(cell, 30.025, 0.025, near_surface, kPose, 0.10, 0.025,
                                   tolerance) != vm::ClearingOutcome::Cleared,
        "a return within 3 sigma(r) of the exit does not contradict the cell");
  auto far_wall = uniform64();
  insert_beam(far_wall, 32.0, azimuth, -1.51, 2);
  check(vm::test_cell_against_scan(cell, 30.025, 0.025, far_wall, kPose, 0.10, 0.025,
                                   tolerance) == vm::ClearingOutcome::Cleared,
        "a return 2 m past the cell still contradicts it");
}

// Root cause 4b. A beam crossing a parked car's claim 2 cm below its roof at
// 10 m (sigma = 3.7 cm) grazes the edge within its own beam spread.
void test_grazing_the_claim_edge_is_not_pass_through() {
  const vm::MapConfig config;
  const vm::ClearingTolerance tolerance{&config.clearing_noise, config.clearing_range_sigmas,
                                        config.clearing_height_sigmas};
  vm::CellStats cell;
  cell.add(obstacle_return(kCellX, kCellY, 0.3, 1), 2.0);
  cell.add(obstacle_return(kCellX, kCellY, 1.5, 1), 2.0);
  const double azimuth = std::atan2(0.025, 10.025) / kDeg;
  // Crosses x = 10.0..10.05 at heights ~1.48: elevation atan((1.48 - 1.8) / 10.025).
  const double elevation = std::atan((1.48 - 1.8) / 10.025) / kDeg;
  auto graze = uniform64();
  insert_beam(graze, 25.0, azimuth, elevation, 2);
  check(vm::test_cell_against_scan(cell, 10.025, 0.025, graze, kPose, 0.10, 0.025) ==
            vm::ClearingOutcome::Cleared,
        "precondition: the bare test clears on an edge graze");
  check(vm::test_cell_against_scan(cell, 10.025, 0.025, graze, kPose, 0.10, 0.025, tolerance) !=
            vm::ClearingOutcome::Cleared,
        "a graze within sigma(r) of the claim edge does not clear it");
  // A single-return (zero-span) claim is still clearable through its middle.
  vm::CellStats thin;
  thin.add(obstacle_return(kCellX, kCellY, 1.0, 1), 2.0);
  const double through_mid = std::atan((1.0 - 1.8) / 10.025) / kDeg;
  auto mid = uniform64();
  insert_beam(mid, 25.0, azimuth, through_mid, 2);
  check(vm::test_cell_against_scan(thin, 10.025, 0.025, mid, kPose, 0.10, 0.025, tolerance) ==
            vm::ClearingOutcome::Cleared,
        "a zero-thickness claim remains clearable by a beam through it");
}

// Root cause 5. The Pandora's 40 non-uniform beams each get their own row.
void test_forty_beam_raster_keeps_every_beam() {
  auto beams = pandora40();
  auto grid = uniform64();
  check(beams.elevation_bins() == 40, "one raster row per beam");
  for (std::size_t row = 0; row < kPandora40Deg.size(); ++row) {
    auto alone = pandora40();
    insert_beam(alone, 20.0, 10.0, kPandora40Deg[row], 1);
    check(alone.range_at(10.0 * kDeg, alone.elevation_of_row(row)) > 0.0F,
          "beam i lands in row i (edges halfway between neighbouring beams)");
  }
  for (const double elevation : kPandora40Deg) {
    insert_beam(beams, 20.0, 10.0, elevation, 1);
    insert_beam(grid, 20.0, 10.0, elevation, 1);
  }
  check(beams.filled_bins() == 40, "all 40 beams on one bearing are retained");
  check(grid.filled_bins() < 40,
        "precondition: the uniform 64-row grid folds the dense 0.33 deg beams together");
}

// Root cause 5, consequence. In the 64-row grid the -1.17 and -0.83 deg beams
// share a row; nearest wins, so a nearer beam that misses the footprint
// laterally discards the farther one that ended on the surface. The matched
// raster keeps both, and the surface blocks clearing.
void test_forty_beam_raster_preserves_blocking_evidence() {
  vm::CellStats cell;  // 5 cm cell x in [10.00, 10.05], y in [0.05, 0.10]
  cell.add(obstacle_return(10.025, 0.075, 0.2, 1), 2.0);
  cell.add(obstacle_return(10.025, 0.075, 1.8, 1), 2.0);
  const auto fill = [](vm::DepthImage& image) {
    insert_beam(image, 5.0, 0.26, -1.17, 2);    // nearer, outside the footprint
    insert_beam(image, 10.03, 0.40, -0.83, 2);  // ends on the surface
    insert_beam(image, 20.0, 0.40, -5.21, 2);   // through the claim to 20 m
  };
  auto grid = uniform64();
  auto beams = pandora40();
  fill(grid);
  fill(beams);
  check(vm::test_cell_against_scan(cell, 10.025, 0.075, grid, kPose, 0.10, 0.025) ==
            vm::ClearingOutcome::Cleared,
        "precondition: the folded row lost the blocking beam");
  check(vm::test_cell_against_scan(cell, 10.025, 0.075, beams, kPose, 0.10, 0.025) ==
            vm::ClearingOutcome::Occluded,
        "the beam-matched raster keeps it, and blocked wins");
}

// The engine accepts the sensor's beam table and builds the matched raster.
void test_engine_builds_raster_from_beam_table() {
  std::string table;
  for (const double d : kPandora40Deg) table += (table.empty() ? "" : ",") + std::to_string(d);
  std::vector<std::string> args{"veyra", "--policy", "distance_lod", "--scan-beam-elevations",
                                table, "--scan-azimuth-bins", "1800"};
  std::vector<char*> argv;
  for (auto& arg : args) argv.push_back(arg.data());
  const auto options = parse_options(static_cast<int>(argv.size()), argv.data());
  const auto image = make_scan_image(options);
  check(image.elevation_bins() == 40 && image.azimuth_bins() == 1800,
        "--scan-beam-elevations/--scan-azimuth-bins shape the raster");
  Options defaults;
  defaults.policy = "distance_lod";
  const auto fallback = make_scan_image(defaults);
  check(fallback.elevation_bins() == 64 && fallback.azimuth_bins() == 1440,
        "the default raster is unchanged");
}

// Movers still clear under the default tolerance (bounded, arm + applied).
void test_departed_mover_still_clears() {
  auto map = occupied_cell_map();
  std::uint64_t t = 1;
  for (int frame = 0; frame < 6; ++frame) (void)map.clear_free_space(see_through(++t), kPose);
  const auto snapshot = map.snapshot();
  const auto* stats = cell_of(snapshot);
  check(stats != nullptr && stats->occupancy() == vm::OccupancyState::Free,
        "a one-scan ghost seen through for 6 frames is Free (2 arm + 4 applied)");
}

}  // namespace

int main() {
  test_cell_hit_in_current_scan_is_never_non_occupied();
  test_repeated_scans_accumulate_evidence();
  test_intermittent_contradiction_with_non_contradicting_frames_is_not_cleared();
  test_blocking_beam_in_another_bin_of_the_footprint_wins();
  test_range_noise_is_not_pass_through();
  test_grazing_the_claim_edge_is_not_pass_through();
  test_forty_beam_raster_keeps_every_beam();
  test_forty_beam_raster_preserves_blocking_evidence();
  test_engine_builds_raster_from_beam_table();
  test_departed_mover_still_clears();
  if (failures != 0) {
    std::fprintf(stderr, "%d failure(s)\n", failures);
    return 1;
  }
  std::puts("clearing static erosion: all checks passed");
  return 0;
}
