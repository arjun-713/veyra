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
}
