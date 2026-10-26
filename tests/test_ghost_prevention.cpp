// Native regression suites. CTest runs each section in a fresh process.
#include <cstdio>
#include <string_view>
#define main veyra_benchmark_program_main
#include "../src/runtime/engine.cpp"
#undef main
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <numbers>
#include <sstream>
#include <string>
#include <vector>
#include "check.hpp"
#include "veyra/map/depth_image.hpp"
#include "veyra/map/map.hpp"
#include "veyra/map/occupancy.hpp"

namespace ghost_retention {

// Ghost-retention measurement with bounded visibility-evidence recovery
// (P0.2 strike rule).
//
// Contract under test: per-frame clearing arms before it decrements. The first
// kStrikesToDecrement (=2) contradictory frames only raise
// CellStats::consecutive_misses; log-odds and free_observations are untouched,
// so a single flicker frame cannot demote an Occupied cell. Past arming,
// exactly one kMiss applies per frame. Only accepted obstacle-layer evidence
// resets the streak; ground-only returns do not.
//
// Analytic schedule (all exact, all asserted below).
//
// Engine-ingested cells pin at exactly kHit (847): every ingested return adds
// one clamped hit and Map::update_at_level folds it in by count-weighted
// average, so N identical hits still read 847, not N*847. Saturation (3476)
// is reachable only through direct observe_occupied() calls and is covered at
// CellStats level in scenario G. The engine schedule from 847 is:
//   armed frames 1..2 (847, streak 1..2, still Occupied),
//   Unknown frame 3 (442), frames 4 (37) and 5 (-368),
//   Free frame 6 (arm + 4 applied, 847-4*405=-773).
// misses_to_clear_from_saturated()=10 and frames_to_clear_from_saturated()=12
// state the saturated-at-struct-level equivalents, asserted in scenario G.
//
// Metric: ghost_retention(K) = occupied mass in the departed footprint K
// frames after disappearance / mass before, plus ghost_free(K) = free mass /
// mass before (reported separately: retention measures flicker resistance,
// free-declaration measures genuine-disappearance release). Mass = occupied /
// free-leaf count in the footprint (0/1 on uniform5); thresholds are the
// production veyra::map::logodds::{kOccupied,kFree}Threshold.
//
// Driver mapping (private session methods exercised via ingest):
//   F record -> begin_frame, P record -> add_point,
//   E record -> end_frame -> clear_free_space -> snapshot.
// The test FAILS if the session stops invoking clearing (clearing has no
// value) or stops contradicting (armed+cleared == 0 on see-through frames).
//
// Scenarios (synthetic, deterministic, uniform5):
//   A (mover + sustained see-through): flicker frames arm without decrement;
//     exact per-frame log-odds past arming; Unknown-then-Free on frames 3/6.
//   B (parked, no contradiction): retention == 1.0, untouched.
//   C (occluded behind the wall): not falsely cleared, retention == 1.0.
//   D (thin single-hit cell): Unknown frame 3, Free frame 6 (arm+4).
//   E (reacquire after 2 applied misses): streak reset, exact clamp
//     arithmetic, one follow-up contradiction re-arms without decrement.
//   F (ground through the ghost): ground-only evidence neither resets the
//     streak nor spares the ghost; clearing still completes on schedule.
//   G (split/merge streak rules, direct Map): merge takes max, fresh children
//     start at 0, the retained prior carries the parent streak back on merge.
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
// down through armed, clamped log-odds.




namespace {

std::string identity_pose() { return "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"; }

// V2 text point: 19 fields (x y z intensity class conf ground drivable slope
// roughness hcomplex tconf step motion_prob motion_state velx vely obs_q raw).
// ground=0 with no height model (V2 text carries none) routes fail-safe to the
// obstacle layer. See ground_point_record for the ground-layer variant.
std::string point_record(double x, double y, double z) {
  std::ostringstream out;
  out << "P " << x << " " << y << " " << z << " 0.5 1 0.9 0 2 0 0 0.1 0.9 0 0.1 0 0 0 0.9 1";
  return out.str();
}

// Same envelope, ground=1: folds into the ground layer, never the obstacle
// layer, so it must neither reset a contradiction streak nor protect a ghost.
std::string ground_point_record(double x, double y, double z) {
  std::ostringstream out;
  out << "P " << x << " " << y << " " << z << " 0.5 1 0.9 1 2 0 0 0.1 0.9 0 0.1 0 0 0 0.9 1";
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

// Free-declaration mass, reported separately from retention: 1 when the leaf
// meets the production Free threshold, else 0.
std::uint64_t free_mass(const veyra::map::MapSnapshot& snapshot, double x, double y) {
  for (const auto& leaf : snapshot.leaves) {
    const double res = 0.05 * static_cast<double>(1 << leaf.id.level);
    const double min_x = static_cast<double>(leaf.id.ix) * res;
    const double min_y = static_cast<double>(leaf.id.iy) * res;
    if (x >= min_x && x < min_x + res && y >= min_y && y < min_y + res) {
      return leaf.stats.occupancy_logodds <= veyra::map::logodds::kFreeThreshold ? 1U : 0U;
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

veyra::map::Observation direct_ret(double x, double y, double z, double hag, std::uint8_t ground,
                                   std::uint64_t t = 1) {
  veyra::map::Observation o;
  o.x = x;
  o.y = y;
  o.z = z;
  o.height_above_ground = static_cast<float>(hag);
  o.ground = ground;
  o.timestamp = t;
  o.terrain_confidence = 0.9F;
  o.semantic_confidence = 0.9F;
  o.observation_quality = 0.9F;
  return o;
}

}  // namespace

int run() {
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
  constexpr int kArm = veyra::map::logodds::kStrikesToDecrement;
  CHECK(kArm == 2);

  // Contradiction frames: mover gone; dense wall sweep 0..2 m covers the
  // mover's claimed extent at the mover's own elevations (see-through).
  std::vector<std::string> see_through;
  for (double z = 0.0; z <= 2.001; z += 0.02)
    see_through.push_back(point_record(kWallX, kWallY, z));

  // ---- Scenario A/B/C: saturated mover + parked + occluded controls. ----
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
  CHECK(session.result().clearing->armed == 0);
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
  // Engine ingestion pins identical hits at exactly one kHit (count-weighted
  // averaging in CellStats::merge), so 9 stack points still read 847.
  CHECK(ped_before.logodds == veyra::map::logodds::kHit);
  CHECK(ped_before.logodds >= veyra::map::logodds::kOccupiedThreshold);
  CHECK(ped_before.streak == 0);
  CHECK(ped_before.free_obs == 0);

  // Six sustained contradictions: 2 arming + 4 applied. Analytic from 847:
  // Occupied through frame 2, Unknown 3..5, Free 6 (arm + 4).
  std::int16_t expect = veyra::map::logodds::kHit;
  int applied = 0;
  std::uint64_t mover_k2 = 0, mover_k3 = 0, mover_k6 = 0, free_k6 = 0;
  for (int f = 1; f <= 6; ++f) {
    run_frame(session, 1000 + static_cast<std::uint64_t>(f) * 1000, static_cast<std::uint64_t>(f),
              see_through);
    CHECK(session.result().clearing.has_value());
    CHECK(session.result().clearing->examined > 0);
    const CellView ped = find_cell(session.result().snapshot, kPedX, kPedY);
    CHECK(ped.found);
    if (f <= kArm) {
      // Flicker frames: armed, nothing else moves.
      CHECK(session.result().clearing->cleared == 0);
      CHECK(session.result().clearing->armed == 1);
      CHECK(ped.logodds == expect);
      CHECK(ped.free_obs == 0);
      CHECK(ped.streak == f);
      CHECK(ped.logodds >= veyra::map::logodds::kOccupiedThreshold);
    } else {
      // Sustained contradiction: exactly one kMiss per frame after arming.
      ++applied;
      expect = static_cast<std::int16_t>(expect + veyra::map::logodds::kMiss);
      CHECK(session.result().clearing->cleared == 1);
      CHECK(ped.logodds == expect);
      CHECK(ped.free_obs == static_cast<std::uint32_t>(applied));
      CHECK(ped.streak == kArm);
    }
    if (f == 2) {
      CHECK(ped.logodds >= veyra::map::logodds::kOccupiedThreshold);
      mover_k2 = occupied_mass(session.result().snapshot, kPedX, kPedY);
    }
    if (f == 3) {
      CHECK(ped.logodds < veyra::map::logodds::kOccupiedThreshold);
      CHECK(ped.logodds > veyra::map::logodds::kFreeThreshold);
      mover_k3 = occupied_mass(session.result().snapshot, kPedX, kPedY);
    }
    if (f == 6) {
      CHECK(ped.logodds <= veyra::map::logodds::kFreeThreshold);
      mover_k6 = occupied_mass(session.result().snapshot, kPedX, kPedY);
      free_k6 = free_mass(session.result().snapshot, kPedX, kPedY);
    }
  }
  CHECK(applied == 4);
  // Scenario A: retention holds through arming, drops exactly at frame 3, and
  // free-declares exactly at frame 6 (arm + 4 applied from a kHit cell).
  CHECK(mover_k2 == 1U);
  CHECK(mover_k3 == 0U);
  CHECK(mover_k6 == 0U);
  CHECK(free_k6 == 1U);
  const double retention_k2 = static_cast<double>(mover_k2) / static_cast<double>(mover_before);
  const double retention_k3 = static_cast<double>(mover_k3) / static_cast<double>(mover_before);
  const double retention_k6 = static_cast<double>(mover_k6) / static_cast<double>(mover_before);
  const double free_k6_ratio = static_cast<double>(free_k6) / static_cast<double>(mover_before);
  CHECK(retention_k2 == 1.0);
  CHECK(retention_k3 == 0.0);
  CHECK(retention_k6 == 0.0);
  CHECK(free_k6_ratio == 1.0);

  // Scenario B (parked, no contradiction): retention == 1.0 exactly, untouched.
  const CellView parked_after = find_cell(session.result().snapshot, kParkedX, kParkedY);
  CHECK(occupied_mass(session.result().snapshot, kParkedX, kParkedY) == parked_before);
  CHECK(parked_after.logodds == parked_before_view.logodds);
  CHECK(parked_after.free_obs == parked_before_view.free_obs);
  CHECK(parked_after.count == parked_before_view.count);
  CHECK(parked_after.streak == 0);
  // Scenario C (occluded behind the wall): not falsely cleared.
  const CellView occluded_after = find_cell(session.result().snapshot, kOccludedX, kOccludedY);
  CHECK(occupied_mass(session.result().snapshot, kOccludedX, kOccludedY) == occluded_before);
  CHECK(occluded_after.logodds == occluded_before_view.logodds);
  CHECK(occluded_after.free_obs == occluded_before_view.free_obs);
  CHECK(occluded_after.streak == 0);

  // ---- Scenario D: thin single-hit cell, Unknown frame 3, Free frame 6. ----
  // Two points, one cell: identical hits average to exactly one kHit, while a
  // non-degenerate extent [0.9, 1.1] keeps the claim contradictable. (A single
  // return claims a zero-thickness plane no raster row centre crosses -- that
  // geometry spares by elevation, which is correct but not this scenario.)
  PersistentEngineSession thin_session(options);
  std::vector<std::string> thin_frame0{point_record(kPedX, kPedY, 0.9),
                                       point_record(kPedX, kPedY, 1.1)};
  for (int i = 0; i < 5; ++i) thin_frame0.push_back(point_record(kWallX, kWallY, 1.0));
  run_frame(thin_session, 1000, 0, thin_frame0);
  const CellView thin_before = find_cell(thin_session.result().snapshot, kPedX, kPedY);
  CHECK(thin_before.found);
  CHECK(thin_before.logodds == veyra::map::logodds::kHit);  // exactly one hit
  CHECK(thin_before.streak == 0);
  const std::int16_t kThinExpect[7] = {
      0,                                         // unused index 0
      veyra::map::logodds::kHit,                 // f1 armed
      veyra::map::logodds::kHit,                 // f2 armed
      static_cast<std::int16_t>(847 - 405),      // f3 Unknown
      static_cast<std::int16_t>(847 - 2 * 405),  // f4 Unknown
      static_cast<std::int16_t>(847 - 3 * 405),  // f5 Unknown
      static_cast<std::int16_t>(847 - 4 * 405),  // f6 Free
  };
  for (int f = 1; f <= 6; ++f) {
    run_frame(thin_session, 1000 + static_cast<std::uint64_t>(f) * 1000,
              static_cast<std::uint64_t>(f), see_through);
    const CellView thin = find_cell(thin_session.result().snapshot, kPedX, kPedY);
    CHECK(thin.found);
    CHECK(thin.logodds == kThinExpect[f]);
    if (f <= kArm) {
      CHECK(thin.streak == f);
      CHECK(thin.free_obs == 0);
      CHECK(thin_session.result().clearing->cleared == 0);
      CHECK(thin_session.result().clearing->armed == 1);
    } else {
      CHECK(thin.streak == kArm);
      CHECK(thin.free_obs == static_cast<std::uint32_t>(f - kArm));
    }
  }
  const CellView thin_end = find_cell(thin_session.result().snapshot, kPedX, kPedY);
  CHECK(thin_end.logodds <= veyra::map::logodds::kFreeThreshold);  // arm+4 Free
  CHECK(free_mass(thin_session.result().snapshot, kPedX, kPedY) == 1U);
  CHECK(occupied_mass(thin_session.result().snapshot, kPedX, kPedY) == 0U);

  // ---- Scenario E: 2 applied misses, then reacquire. ----
  PersistentEngineSession reacquire_session(options);
  std::vector<std::string> reacquire_frame0;
  for (double z = 0.2; z <= 1.81; z += 0.2)
    reacquire_frame0.push_back(point_record(kPedX, kPedY, z));
  for (int i = 0; i < 5; ++i) reacquire_frame0.push_back(point_record(kWallX, kWallY, 1.0));
  run_frame(reacquire_session, 1000, 0, reacquire_frame0);
  const CellView re_before = find_cell(reacquire_session.result().snapshot, kPedX, kPedY);
  CHECK(re_before.logodds == veyra::map::logodds::kHit);
  for (int f = 1; f <= 4; ++f) {
    run_frame(reacquire_session, 1000 + static_cast<std::uint64_t>(f) * 1000,
              static_cast<std::uint64_t>(f), see_through);
  }
  const CellView re_missed = find_cell(reacquire_session.result().snapshot, kPedX, kPedY);
  CHECK(re_missed.found);
  CHECK(re_missed.streak == 2);
  CHECK(re_missed.free_obs == 2);
  CHECK(re_missed.logodds ==
        static_cast<std::int16_t>(veyra::map::logodds::kHit + 2 * veyra::map::logodds::kMiss));
  CHECK(re_missed.count == 9);
  // The object returns. The scan's obstacle returns apply ONE clamped kHit to
  // the pre-scan log-odds (37 + 847 = 884), floored at the Occupied threshold:
  // a surface measured in this scan reads Occupied in this scan. (Before, the
  // 9 hits were count-averaged in -- (37*9 + 847*9)/18 = 442 -- and the cell
  // stayed Unknown while being hit, which is the defect measured on
  // SemanticPOSS 00.) The streak resets at once.
  constexpr std::int16_t kReacquired =
      veyra::map::logodds::kHit + 2 * veyra::map::logodds::kMiss + veyra::map::logodds::kHit;
  run_frame(reacquire_session, 6000, 5, reacquire_frame0);
  const CellView re_back = find_cell(reacquire_session.result().snapshot, kPedX, kPedY);
  CHECK(re_back.found);
  CHECK(re_back.streak == 0);
  CHECK(re_back.logodds == kReacquired);
  CHECK(veyra::map::logodds::state_of(re_back.logodds) == veyra::map::OccupancyState::Occupied);
  CHECK(re_back.free_obs == 2);  // clearing skipped this frame (same-scan hit)
  CHECK(re_back.count == re_missed.count + 9);
  // One follow-up contradiction re-arms without decrementing.
  run_frame(reacquire_session, 7000, 6, see_through);
  const CellView re_flicker = find_cell(reacquire_session.result().snapshot, kPedX, kPedY);
  CHECK(re_flicker.found);
  CHECK(re_flicker.streak == 1);
  CHECK(re_flicker.logodds == kReacquired);
  CHECK(re_flicker.free_obs == 2);
  CHECK(reacquire_session.result().clearing->cleared == 0);
  CHECK(reacquire_session.result().clearing->armed == 1);

  // ---- Scenario F: ground observed through the ghost neither resets nor spares. ----
  PersistentEngineSession ground_session(options);
  run_frame(ground_session, 1000, 0, reacquire_frame0);
  run_frame(ground_session, 2000, 1, see_through);
  run_frame(ground_session, 3000, 2, see_through);
  const CellView g_armed = find_cell(ground_session.result().snapshot, kPedX, kPedY);
  CHECK(g_armed.streak == 2);
  CHECK(g_armed.logodds == veyra::map::logodds::kHit);
  // Frame 3 carries one ground return at the ghost plus the wall sweep: the
  // ground folds into the ground layer (count + 1) while the wall beams still
  // contradict the obstacle extent -- applied, streak untouched.
  std::vector<std::string> ground_frame{ground_point_record(kPedX, kPedY, 0.0)};
  ground_frame.insert(ground_frame.end(), see_through.begin(), see_through.end());
  run_frame(ground_session, 4000, 3, ground_frame);
  const CellView g_ground = find_cell(ground_session.result().snapshot, kPedX, kPedY);
  CHECK(g_ground.found);
  CHECK(g_ground.streak == 2);  // ground-only evidence did not reset
  CHECK(g_ground.logodds ==
        static_cast<std::int16_t>(veyra::map::logodds::kHit + veyra::map::logodds::kMiss));
  CHECK(g_ground.free_obs == 1);
  CHECK(g_ground.count == g_armed.count + 1);
  // Clearing still completes on the analytic schedule: applied #1 was the
  // ground frame, so Free still lands on contradictory frame 6 (arm + 4).
  for (int f = 4; f <= 6; ++f) {
    run_frame(ground_session, 1000 + static_cast<std::uint64_t>(f) * 1000,
              static_cast<std::uint64_t>(f), see_through);
  }
  const CellView g_end = find_cell(ground_session.result().snapshot, kPedX, kPedY);
  CHECK(g_end.found);
  CHECK(g_end.logodds <= veyra::map::logodds::kFreeThreshold);
  CHECK(g_end.free_obs == 4);
  CHECK(free_mass(ground_session.result().snapshot, kPedX, kPedY) == 1U);

  // ---- Scenario G: streak merge/split rules through the public Map API. ----
  CHECK([] {
    // Struct level: streaks merge as max, never summed.
    veyra::map::CellStats a;
    a.count = 3;
    a.consecutive_misses = 1;
    veyra::map::CellStats b;
    b.count = 5;
    b.consecutive_misses = 2;
    a.merge(b);
    if (a.consecutive_misses != 2) return false;
    veyra::map::CellStats c;
    c.count = 4;
    c.consecutive_misses = 0;
    veyra::map::CellStats d;
    d.count = 4;
    d.consecutive_misses = 2;
    d.merge(c);
    return d.consecutive_misses == 2;
  }());
  {
    // Map level: arm a level-1 parent, split it, merge it back.
    veyra::map::Map map{veyra::map::ResolutionPolicy::Uniform5};
    map.update_at_level(direct_ret(10.05, 0.05, 0.2, 0.2, 0), 1);
    map.update_at_level(direct_ret(10.05, 0.05, 1.2, 1.2, 0), 1);
    const veyra::map::SensorPose pose{0.0, 0.0, 0.0};
    veyra::map::DepthImage image{1440, 64, -25.0 * std::numbers::pi / 180.0,
                                 15.0 * std::numbers::pi / 180.0};
    // Same bearing as the cell centre (azimuth ~0.005): a sweep across the
    // claimed elevations guarantees a measured beam through the extent.
    for (double z = 1.0; z <= 1.81; z += 0.1) image.insert(20.1, 0.1, z, pose);
    const veyra::map::ClearingStats first = map.clear_free_space(image, pose);
    CHECK(first.armed == 1);
    CHECK(first.cleared == 0);
    const veyra::core::CellId parent{1, 100, 0};
    auto find_streak = [&map](veyra::core::CellId id) -> int {
      for (const auto& leaf : map.snapshot().leaves) {
        if (leaf.id == id) return leaf.stats.consecutive_misses;
      }
      return -1;
    };
    CHECK(find_streak(parent) == 1);
    map.split(parent);
    // Fresh children start at 0: refinement is not contradiction.
    CHECK(find_streak({0, 200, 0}) == 0);
    CHECK(find_streak({0, 201, 0}) == 0);
    CHECK(find_streak({0, 200, 1}) == 0);
    CHECK(find_streak({0, 201, 1}) == 0);
    // The retained prior carries the parent streak back on merge.
    map.merge_children(parent);
    CHECK(find_streak(parent) == 1);
  }
  {
    // Struct level: the saturated end of the schedule. Five direct hits
    // saturate (5*847 > clamp); the strike rule arms 2 frames first, so
    // end-to-end frames are 2 + applied. From 3476: Unknown at applied #7
    // (641), Free at applied #10 (-574) -- arm+10 -- and the helpers state
    // both the offset composition and the reacquire cost exactly.
    CHECK(veyra::map::logodds::frames_to_clear_from_saturated() ==
          2 + veyra::map::logodds::misses_to_clear_from_saturated());
    CHECK(veyra::map::logodds::misses_to_clear_from_saturated() == 10);
    veyra::map::CellStats saturated;
    for (int i = 0; i < 5; ++i) saturated.observe_occupied();
    CHECK(saturated.occupancy_logodds == veyra::map::logodds::kClampMax);
    for (int i = 0; i < 7; ++i) saturated.observe_free();
    CHECK(saturated.occupancy() == veyra::map::OccupancyState::Unknown);
    for (int i = 0; i < 3; ++i) saturated.observe_free();
    CHECK(saturated.occupancy() == veyra::map::OccupancyState::Free);
    CHECK(veyra::map::logodds::hits_to_recover_from_misses(0) == 0);
    CHECK(veyra::map::logodds::hits_to_recover_from_misses(2) == 0);
    CHECK(veyra::map::logodds::hits_to_recover_from_misses(7) == 1);
    CHECK(veyra::map::logodds::hits_to_recover_from_misses(9) == 2);
    CHECK(veyra::map::logodds::hits_to_recover_from_misses(10) == 2);
  }

  std::printf("ghost_retention k=2 value=%.3f mass=%llu base=%llu\n", retention_k2,
              static_cast<unsigned long long>(mover_k2),
              static_cast<unsigned long long>(mover_before));
  std::printf("ghost_retention k=3 value=%.3f mass=%llu base=%llu\n", retention_k3,
              static_cast<unsigned long long>(mover_k3),
              static_cast<unsigned long long>(mover_before));
  std::printf("ghost_retention k=6 value=%.3f mass=%llu base=%llu\n", retention_k6,
              static_cast<unsigned long long>(mover_k6),
              static_cast<unsigned long long>(mover_before));
  std::printf("ghost_free_declaration k=6 value=%.3f mass=%llu base=%llu\n", free_k6_ratio,
              static_cast<unsigned long long>(free_k6),
              static_cast<unsigned long long>(mover_before));
  std::printf("thin_retention k=2 value=1.000 (armed, no decrement)\n");
  std::printf("thin_free_declaration k=6 value=1.000 (arm+4 applied)\n");
  std::printf("parked_retention k=6 value=1.000 (no contradiction, untouched)\n");
  std::printf("occluded_retention k=6 value=1.000 (occluded, not falsely cleared)\n");
  std::printf("test_ghost_retention: all checks passed\n");
  return 0;
  return 0;
}

}  // namespace ghost_retention

namespace clearing_static_erosion {

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

int run() {
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
  return 0;
}

}  // namespace clearing_static_erosion

int main(int argc, char** argv) {
  if (argc == 2) {
    const std::string_view suite{argv[1]};
    if (suite == "ghost_retention") return ghost_retention::run();
    if (suite == "clearing_static_erosion") return clearing_static_erosion::run();
  }
  std::fputs("Select a registered CTest suite.\n", stderr);
  return 2;
}
