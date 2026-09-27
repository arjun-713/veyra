// Ghost-retention measurement (P0.2 Step 3, bounded).
//
// Metric: ghost_retention(K) = occupied mass in the departed footprint K
// frames after disappearance / mass before. Mass = occupied-leaf count in the
// footprint (0/1 on uniform5); occupied = production threshold
// veyra::map::logodds::kOccupiedThreshold. K=0/1/2 driven through the live
// PersistentEngineSession F/P/E path.
//
// Driver mapping (private session methods exercised via ingest):
//   F record -> begin_frame, P record -> add_point,
//   E record -> end_frame -> clear_free_space -> snapshot.
// The test FAILS if the session stops invoking clearing (clearing has no
// value) or stops contradicting (cleared == 0 on see-through frames).
//
// Scenarios (synthetic, deterministic, uniform5):
//   A (mover + contradictory see-through): retention drops after K>=1.
//   B (parked, no contradiction): retention == 1.0.
//   C (occluded behind the wall): not falsely cleared, retention == 1.0.
//
// Real data: BLOCKED, never fabricated.
//   - KITTI-08 (SemanticKITTI seq08): absent locally. Velodyne scans,
//     calib.txt and times.txt require KITTI benchmark login; only labels +
//     poses are public. No scan replay possible without inventing beams.
//   - SemanticPOSS (present under SemanticPOSS_dataset/dataset/sequences,
//     e.g. 00/velodyne + poses.txt): publishes no timestamps, so no velocity
//     or K-ordering can be derived and the temporal/evaluator path reports
//     explicit UNKNOWN rather than scoring (see
//     perception/temporal/evaluator.py: "ghosts never score", UNKNOWN on
//     missing time). A map-level ghost_retention over real frames would need
//     the same invented time, so it stays BLOCKED too.
// Tracker-evaluator complement: perception/temporal/evaluator.py scores only
// freshly observed tracks (missed_frames == 0); ghosts never score. This test
// measures the map side: how fast contradicted occupied mass actually steps
// down through clamped log-odds.

#define main veyra_benchmark_program_main
#include "../src/runtime/engine.cpp"
#undef main
#include <cmath>
#include <cstdint>
#include <cstdio>
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

// Production occupied mass in a single-cell footprint: 1 when the resident
// leaf meets the production Occupied threshold, else 0.
std::uint64_t occupied_mass(const veyra::map::MapSnapshot& snapshot, double x, double y) {
  for (const auto& leaf : snapshot.leaves) {
    const double res = 0.05 * static_cast<double>(1 << leaf.id.level);
    const double min_x = static_cast<double>(leaf.id.ix) * res;
    const double min_y = static_cast<double>(leaf.id.iy) * res;
    if (x >= min_x && x < min_x + res && y >= min_y && y < min_y + res) {
      return leaf.stats.occupancy_logodds >= veyra::map::logodds::kOccupiedThreshold ? 1U : 0U;
    }
  }
  return 0U;
}

void feed_points(PersistentEngineSession& session, const std::vector<std::string>& records) {
  for (const auto& record : records) session.ingest(record);
}

void run_frame(PersistentEngineSession& session, std::uint64_t timestamp,
               std::uint64_t source_index, const std::vector<std::string>& points) {
  // F -> begin_frame, P -> add_point, E -> end_frame -> clear_free_space -> snapshot.
  session.ingest(frame_marker(timestamp, source_index, points.size()));
  feed_points(session, points);
  session.ingest("E");
}

}  // namespace

int main() {
  constexpr double kPedX = 10.02;
  constexpr double kPedY = 0.02;
  constexpr double kParkedX = -10.02;
  constexpr double kParkedY = 0.02;
  constexpr double kWallX = 20.02;
  constexpr double kWallY = 0.02;
  // Exactly on the wall's sightline from the sensor (0,0,1.8): sensor +
  // 1.25 * (wall - sensor), so both share one depth bin and the nearer wall
  // return wins it. Any other far placement risks landing in an adjacent
  // elevation bin whose beam would see past the wall and clear it in frame 0.
  constexpr double kOccludedX = 25.025;
  constexpr double kOccludedY = 0.025;
  constexpr double kOccludedZ = 0.8;

  Options options;
  options.policy = "uniform5";
  options.clearing_enabled = true;
  PersistentEngineSession session(options);

  // Frame 0: mover stack (extent 0.2..1.8), parked car, wall surface, and an
  // occupied cell behind the wall (same bearing, farther range -> occluded).
  std::vector<std::string> frame0;
  for (double z = 0.2; z <= 1.81; z += 0.2) frame0.push_back(point_record(kPedX, kPedY, z));
  for (int i = 0; i < 5; ++i) frame0.push_back(point_record(kParkedX, kParkedY, 1.0));
  for (int i = 0; i < 5; ++i) frame0.push_back(point_record(kWallX, kWallY, 1.0));
  for (int i = 0; i < 5; ++i) frame0.push_back(point_record(kOccludedX, kOccludedY, kOccludedZ));
  run_frame(session, 1000, 0, frame0);

  // Session must invoke clearing on every frame (opt-in path, not skipped).
  CHECK(session.result().clearing.has_value());
  CHECK(session.result().clearing->cleared == 0);
  const std::uint64_t mover_before = occupied_mass(session.result().snapshot, kPedX, kPedY);
  const std::uint64_t parked_before = occupied_mass(session.result().snapshot, kParkedX, kParkedY);
  const std::uint64_t occluded_before =
      occupied_mass(session.result().snapshot, kOccludedX, kOccludedY);
  CHECK(mover_before == 1U);
  CHECK(parked_before == 1U);
  CHECK(occluded_before == 1U);
  const CellView ped_before = find_cell(session.result().snapshot, kPedX, kPedY);
  const CellView parked_before_view = find_cell(session.result().snapshot, kParkedX, kParkedY);
  const CellView occluded_before_view =
      find_cell(session.result().snapshot, kOccludedX, kOccludedY);
  CHECK(ped_before.found);
  CHECK(ped_before.logodds >= veyra::map::logodds::kOccupiedThreshold);

  // Contradiction frames: mover gone; dense wall sweep 0..2 m covers the
  // mover's claimed extent at the mover's own elevations (see-through).
  std::vector<std::string> see_through;
  for (double z = 0.0; z <= 2.001; z += 0.02)
    see_through.push_back(point_record(kWallX, kWallY, z));

  run_frame(session, 2000, 1, see_through);
  CHECK(session.result().clearing.has_value());
  CHECK(session.result().clearing->examined > 0);
  CHECK(session.result().clearing->cleared > 0);
  const std::uint64_t mover_k1 = occupied_mass(session.result().snapshot, kPedX, kPedY);
  const std::uint64_t parked_k1 = occupied_mass(session.result().snapshot, kParkedX, kParkedY);
  const std::uint64_t occluded_k1 =
      occupied_mass(session.result().snapshot, kOccludedX, kOccludedY);
  const CellView ped_k1 = find_cell(session.result().snapshot, kPedX, kPedY);
  const CellView parked_k1_view = find_cell(session.result().snapshot, kParkedX, kParkedY);
  const CellView occluded_k1_view = find_cell(session.result().snapshot, kOccludedX, kOccludedY);
  // Exactly one clamped log-odds miss: proves end_frame ran clearing.
  CHECK(ped_k1.found);
  CHECK(ped_k1.logodds == ped_before.logodds + veyra::map::logodds::kMiss);
  CHECK(ped_k1.free_obs == ped_before.free_obs + 1);

  run_frame(session, 3000, 2, see_through);
  CHECK(session.result().clearing.has_value());
  CHECK(session.result().clearing->examined > 0);
  CHECK(session.result().clearing->cleared > 0);
  const std::uint64_t mover_k2 = occupied_mass(session.result().snapshot, kPedX, kPedY);
  const std::uint64_t parked_k2 = occupied_mass(session.result().snapshot, kParkedX, kParkedY);
  const std::uint64_t occluded_k2 =
      occupied_mass(session.result().snapshot, kOccludedX, kOccludedY);
  const CellView ped_k2 = find_cell(session.result().snapshot, kPedX, kPedY);
  const CellView parked_k2_view = find_cell(session.result().snapshot, kParkedX, kParkedY);
  const CellView occluded_k2_view = find_cell(session.result().snapshot, kOccludedX, kOccludedY);
  CHECK(ped_k2.found);
  CHECK(ped_k2.logodds == ped_k1.logodds + veyra::map::logodds::kMiss);
  CHECK(ped_k2.free_obs == ped_k1.free_obs + 1);

  const double retention_k0 = 1.0;
  const double retention_k1 = static_cast<double>(mover_k1) / static_cast<double>(mover_before);
  const double retention_k2 = static_cast<double>(mover_k2) / static_cast<double>(mover_before);
  const double parked_k1_ret = static_cast<double>(parked_k1) / static_cast<double>(parked_before);
  const double parked_k2_ret = static_cast<double>(parked_k2) / static_cast<double>(parked_before);
  const double occluded_k1_ret =
      static_cast<double>(occluded_k1) / static_cast<double>(occluded_before);
  const double occluded_k2_ret =
      static_cast<double>(occluded_k2) / static_cast<double>(occluded_before);

  // Scenario A (mover + contradiction): retention drops and never recovers.
  CHECK(retention_k1 < 1.0);
  CHECK(retention_k2 <= retention_k1);
  CHECK(mover_k1 == 0U);
  CHECK(mover_k2 == 0U);
  // Scenario B (parked, no contradiction): retention ~= 1.0 exactly.
  CHECK(parked_k1_ret == 1.0);
  CHECK(parked_k2_ret == 1.0);
  CHECK(parked_k1_view.logodds == parked_before_view.logodds);
  CHECK(parked_k2_view.logodds == parked_before_view.logodds);
  CHECK(parked_k1_view.free_obs == parked_before_view.free_obs);
  CHECK(parked_k2_view.free_obs == parked_before_view.free_obs);
  CHECK(parked_k1_view.count == parked_before_view.count);
  CHECK(parked_k2_view.count == parked_before_view.count);
  // Scenario C (occluded behind the wall): not falsely cleared.
  CHECK(occluded_k1_ret == 1.0);
  CHECK(occluded_k2_ret == 1.0);
  CHECK(occluded_k1_view.logodds == occluded_before_view.logodds);
  CHECK(occluded_k2_view.logodds == occluded_before_view.logodds);
  CHECK(occluded_k1_view.free_obs == occluded_before_view.free_obs);
  CHECK(occluded_k2_view.free_obs == occluded_before_view.free_obs);

  std::printf("ghost_retention k=0 value=%.3f mass=%llu base=%llu\n", retention_k0,
              static_cast<unsigned long long>(mover_before),
              static_cast<unsigned long long>(mover_before));
  std::printf("ghost_retention k=1 value=%.3f mass=%llu base=%llu\n", retention_k1,
              static_cast<unsigned long long>(mover_k1),
              static_cast<unsigned long long>(mover_before));
  std::printf("ghost_retention k=2 value=%.3f mass=%llu base=%llu\n", retention_k2,
              static_cast<unsigned long long>(mover_k2),
              static_cast<unsigned long long>(mover_before));
  std::printf("parked_retention k=1 value=%.3f mass=%llu base=%llu\n", parked_k1_ret,
              static_cast<unsigned long long>(parked_k1),
              static_cast<unsigned long long>(parked_before));
  std::printf("parked_retention k=2 value=%.3f mass=%llu base=%llu\n", parked_k2_ret,
              static_cast<unsigned long long>(parked_k2),
              static_cast<unsigned long long>(parked_before));
  std::printf("occluded_retention k=1 value=%.3f mass=%llu base=%llu\n", occluded_k1_ret,
              static_cast<unsigned long long>(occluded_k1),
              static_cast<unsigned long long>(occluded_before));
  std::printf("occluded_retention k=2 value=%.3f mass=%llu base=%llu\n", occluded_k2_ret,
              static_cast<unsigned long long>(occluded_k2),
              static_cast<unsigned long long>(occluded_before));
  std::printf("test_ghost_retention: all checks passed\n");
  return 0;
}
