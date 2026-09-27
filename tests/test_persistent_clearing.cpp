// Persistent-engine visibility clearing (P0.2 Step 1).
//
// Exercises PersistentEngineSession -- the stateful F/P/E path the viewer
// drives -- not DepthImage alone. Frame N occupies a cell; frame N+1 looks
// straight through it at a wall behind; the pass must step occupancy down.
// Occluded (wall) and never-observed (parked) controls must be untouched.
// Clearing is opt-in (default off); no time-decay, no age eviction.

#define main veyra_benchmark_program_main
#include "../src/runtime/engine.cpp"
#undef main
#include <cmath>
#include <optional>
#include <sstream>

#include "check.hpp"

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

void feed_points(PersistentEngineSession& session, const std::vector<std::string>& records) {
  for (const auto& record : records) session.ingest(record);
}

}  // namespace

int main() {
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
  std::vector<std::string> frame1;
  for (double z = 0.0; z <= 2.001; z += 0.02) frame1.push_back(point_record(kWallX, kWallY, z));
  session.ingest(frame_marker(2000, 1, frame1.size()));
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
}
