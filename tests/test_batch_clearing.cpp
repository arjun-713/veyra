// Batch-engine visibility-clearing guards (P0.2 Step 9).
//
// Drives production run() -- the stdin batch F/P/E path -- in-process via a
// redirected std::cin. Proves the batch path mirrors the persistent guards:
// rejected (out-of-window) points never populate the visibility raster, an
// invalid sensor pose skips clearing honestly, and an empty raster skips
// without touching the map. A see-through stream proves normal clearing still
// runs. Result.clearing reports the last frame only, so each case is its own
// stream ending with the frame under test.

#define main veyra_benchmark_program_main
#include "../src/runtime/engine.cpp"
#undef main
#include <cmath>
#include <iostream>
#include <limits>
#include <sstream>
#include <string>
#include <vector>

#include "check.hpp"
#include "veyra/map/occupancy.hpp"

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

int main() {
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
}
