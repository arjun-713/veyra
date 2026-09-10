// Invariant test for the resolution policy pass: the point of the project.
// Until this exists the map is a competent uniform grid; after it, resolution
// follows distance.
//
// The policy itself is veyra::policy::LodPolicy, which already carries the
// DistanceLOD bands. This file tests the bands' contract and the pass that
// applies them to the grid. Each group names the production bug it catches.
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/fusion.hpp"
#include "veyra/map/observation.hpp"
#include "veyra/map/resolution_pass.hpp"
#include "veyra/map/rolling_window.hpp"
#include "veyra/map/tile_grid.hpp"
#include "veyra/policy/policy.hpp"

namespace {

using veyra::core::CellId;
using veyra::map::MapWindow;
using veyra::map::PassContext;
using veyra::map::PolicyStats;
using veyra::map::TileGrid;
using veyra::policy::LodMode;
using veyra::policy::LodPolicy;
using veyra::policy::PolicyConfig;

LodPolicy distancePolicy() {
  return LodPolicy{PolicyConfig::defaults().with_mode(LodMode::DistanceLod)};
}

int levelAt(LodPolicy& pol, double range_m) {
  veyra::policy::DecisionInput in;
  in.range_m = range_m;
  in.active_level = 0;
  in.state_cell = CellId{0, 0, 0};
  return pol.decide(in).baseline_level;
}

void fillStrip(TileGrid& grid, std::int32_t ix_end) {
  for (std::int32_t iy = 0; iy < 8; ++iy) {
    for (std::int32_t ix = 0; ix < ix_end; ++ix) {
      grid.findOrCreate(CellId{0, ix, iy});
    }
  }
}

// Runs the pass until it stops doing work, or gives up. Returns the number of
// passes; the caller asserts it converged.
std::size_t runToConvergence(TileGrid& grid, LodPolicy& pol, const PassContext& ctx,
                             std::size_t max_passes) {
  for (std::size_t i = 1; i <= max_passes; ++i) {
    const PolicyStats s = veyra::map::applyPolicy(grid, pol, ctx);
    if (s.splits == 0 && s.merges == 0) {
      return i;
    }
  }
  return max_passes + 1;
}

// 1. The distance bands, and their half-open boundaries. Exactly 10.0 m is in
//    the second band, not the first, matching [min, max) everywhere else in
//    this codebase.
//    Catches: a boundary comparison flipped to <=, which would silently move
//    a whole band's worth of cells by one level.
void checkDistanceBands() {
  LodPolicy pol = distancePolicy();
  CHECK(levelAt(pol, 0.0) == 0);
  CHECK(levelAt(pol, 9.999) == 0);
  CHECK(levelAt(pol, 10.0) == 1);  // half-open: the boundary belongs upward
  CHECK(levelAt(pol, 29.999) == 1);
  CHECK(levelAt(pol, 30.0) == 2);
  CHECK(levelAt(pol, 59.999) == 2);
  CHECK(levelAt(pol, 60.0) == 3);
  CHECK(levelAt(pol, 99.0) == 3);
}

// 2. The thresholds in code match configs/distance_lod.yaml, which reads
//    ranges_m: [[0, 10], [10, 30], [30, 60], [60, 100]].
//    The YAML is documentation -- parsing it would be a new dependency, which
//    AGENTS.md gates. This assertion is what stops the two diverging silently.
//    Catches: a threshold edited in one place only.
void checkThresholdsMatchTheConfigFile() {
  const PolicyConfig cfg = PolicyConfig::defaults();
  CHECK(cfg.distance_boundaries_m[0] == 10.0);
  CHECK(cfg.distance_boundaries_m[1] == 30.0);
  CHECK(cfg.distance_boundaries_m[2] == 60.0);
  CHECK(cfg.max_range_m == 100.0);
}

// 3. A policy asking for something the grid will not do leaves the map
//    unchanged, and the refusal is counted rather than swallowed.
//    Catches: a pass that honours a request split or merge declined, which
//    would break invariant 2 while reporting success.
void checkRefusalsAreCountedNotSwallowed() {
  TileGrid grid{MapWindow{0.0, 0.0, 80.0}};
  // A lone cell 40 m out: Uniform40 wants it coarser, but merge needs all four
  // siblings and there is only one, so the grid must refuse.
  grid.findOrCreate(CellId{0, 800, 0});
  const veyra::map::GridStats before = grid.statistics();

  LodPolicy hostile{PolicyConfig::defaults().with_mode(LodMode::Uniform40)};
  const PolicyStats s = veyra::map::applyPolicy(grid, hostile, PassContext{0.0, 0.0});

  CHECK(s.refused > 0);
  CHECK(s.merges == 0);
  const veyra::map::GridStats after = grid.statistics();
  CHECK(after.occupied_cells == before.occupied_cells);
  CHECK(grid.find(CellId{0, 800, 0}) != nullptr);
}

// 4. The point of the project: a uniform level-0 strip becomes fine near the
//    vehicle and coarse far away.
//    Catches: a pass that does nothing, and one that coarsens uniformly --
//    either of which leaves a map that is not adaptive.
void checkLevelDistributionBecomesAdaptive() {
  TileGrid grid{MapWindow{0.0, 0.0, 120.0}};
  fillStrip(grid, 1600);  // 0 .. 80 m of level-0 cells, 8 rows
  const std::size_t uniform_cells = grid.statistics().occupied_cells;
  CHECK(uniform_cells == 8U * 1600U);

  LodPolicy pol = distancePolicy();
  const std::size_t passes = runToConvergence(grid, pol, PassContext{0.0, 0.2}, 400);
  CHECK(passes <= 400);

  std::array<std::size_t, 4> per_level{};
  grid.forEachActiveLeaf([&per_level](CellId id, const veyra::map::Cell&) {
    CHECK(id.level >= 0 && id.level <= 3);
    ++per_level[static_cast<std::size_t>(id.level)];
  });

  // Every band is represented, and the map shrank.
  CHECK(per_level[0] > 0);
  CHECK(per_level[1] > 0);
  CHECK(per_level[2] > 0);
  CHECK(per_level[3] > 0);
  CHECK(grid.statistics().occupied_cells < uniform_cells);

  // Resolution actually follows distance: near is finest, far is coarsest.
  const veyra::map::LeafHit near_hit = veyra::map::activeLeafCovering(grid, 2.0, 0.2);
  CHECK(near_hit.found);
  CHECK(near_hit.id.level == 0);
  const veyra::map::LeafHit far_hit = veyra::map::activeLeafCovering(grid, 70.0, 0.2);
  CHECK(far_hit.found);
  CHECK(far_hit.id.level == 3);
}

// 5. Hysteresis. A vehicle oscillating across a band boundary must not split
//    and merge the same cells on alternate frames.
//    Catches: a zero margin, which turns a stationary boundary into
//    allocation churn on the hot path -- AGENTS.md forbids it.
void checkHysteresisPreventsThrash() {
  TileGrid grid{MapWindow{0.0, 0.0, 60.0}};
  fillStrip(grid, 400);  // 0 .. 20 m, spanning the 10 m boundary

  LodPolicy pol = distancePolicy();
  CHECK(runToConvergence(grid, pol, PassContext{0.0, 0.2}, 400) <= 400);

  // Now jitter the vehicle either side of the boundary, indefinitely.
  //
  // The property is that the work *stops*, not that it never starts. A margin
  // rule makes oscillation converge: the first jitter can still move cells
  // that were sitting inside the margin, and once moved they stay moved,
  // because coming back would have to clear the margin in the other
  // direction. Measured here: 16 merges on the second frame, then nothing,
  // for as long as the jitter continues.
  //
  // Making even that first adjustment free would need a per-cell dwell
  // counter, which is state the pass deliberately does not keep.
  std::size_t settling = 0;
  std::size_t after_settling = 0;
  std::size_t held = 0;
  for (int frame = 0; frame < 20; ++frame) {
    const double dx = (frame % 2 == 0) ? 0.4 : -0.4;
    const PolicyStats s = veyra::map::applyPolicy(grid, pol, PassContext{dx, 0.2});
    const std::size_t ops = s.splits + s.merges;
    if (frame < 2) {
      settling += ops;
    } else {
      after_settling += ops;
    }
    held += s.held_by_hysteresis;
  }
  // Settled, and stays settled however long the vehicle keeps jittering.
  CHECK(after_settling == 0);
  // The margin is genuinely engaging rather than the map simply having
  // nothing left to do -- cells are being held back on every frame.
  CHECK(held > 0);
  CHECK(settling < 64);
}

// 6. The per-frame cap bounds the work, and the backlog is reported rather
//    than dropped.
//    Catches: a cap that is ignored, which turns a map-wide reshuffle into a
//    latency spike; and one that silently discards the remainder.
void checkPerFrameCapIsRespected() {
  TileGrid grid{MapWindow{0.0, 0.0, 120.0}};
  fillStrip(grid, 1600);

  LodPolicy pol = distancePolicy();
  const PolicyStats s = veyra::map::applyPolicy(grid, pol, PassContext{0.0, 0.2});

  CHECK(s.splits + s.merges <= veyra::map::kMaxOpsPerPass);
  CHECK(s.deferred > 0);  // far more work than one pass may do
  CHECK(s.examined > s.splits + s.merges);
}

// 7. Idempotence. Once converged, a pass with no motion does nothing.
//    Catches: a pass that keeps toggling cells, which would burn the operation
//    budget every frame while making no progress.
void checkIdempotentWhenConverged() {
  TileGrid grid{MapWindow{0.0, 0.0, 120.0}};
  fillStrip(grid, 800);

  LodPolicy pol = distancePolicy();
  CHECK(runToConvergence(grid, pol, PassContext{0.0, 0.2}, 400) <= 400);

  const veyra::map::GridStats before = grid.statistics();
  const PolicyStats again = veyra::map::applyPolicy(grid, pol, PassContext{0.0, 0.2});
  CHECK(again.splits == 0);
  CHECK(again.merges == 0);
  const veyra::map::GridStats after = grid.statistics();
  CHECK(after.occupied_cells == before.occupied_cells);
  CHECK(after.tiles == before.tiles);
}

// Invariant 2, checked directly: no active cell may sit beneath another
// active cell. Returns the number of violations so the caller can report it.
std::size_t countAncestorViolations(const TileGrid& grid) {
  std::size_t bad = 0;
  grid.forEachActiveLeaf([&grid, &bad](CellId id, const veyra::map::Cell&) {
    CellId up = id;
    while (up.level < veyra::map::kMaxLevel) {
      up = veyra::core::parentOf(up);
      if (grid.find(up) != nullptr) {
        ++bad;
        return;
      }
    }
  });
  return bad;
}

veyra::map::Observation point(double x, double y) {
  veyra::map::Observation o;
  o.x = x;
  o.y = y;
  o.z = 0.1F;
  o.cls = 1;
  o.confidence = 1.0F;
  return o;
}

// 17. The whole loop over a simulated drive: integrate, recentre, apply the
//     policy, repeatedly. Memory stays bounded, and the exclusivity invariant
//     holds at every single step.
//     Catches: any interaction between fusion, the window and the pass that
//     is invisible when each is tested alone.
void checkFullLoopOverADrive() {
  constexpr double kR = 25.0;
  TileGrid grid{MapWindow{0.0, 0.0, kR}};
  LodPolicy pol = distancePolicy();

  std::size_t max_cells = 0;
  std::size_t max_bytes = 0;
  std::size_t worst_violation = 0;

  for (int step = 0; step <= 120; ++step) {
    const double vx = static_cast<double>(step);
    grid.recenter(vx, 0.0);

    // A swath, not a single row. A one-cell-tall line can never be merged --
    // merge needs all four siblings -- so a line-shaped drive would coarsen
    // nothing and this test would pass without exercising the interaction it
    // exists to cover.
    std::vector<veyra::map::Observation> batch;
    // One point per 5 cm cell. At coarser spacing the swath is a comb with no
    // 2x2 sibling blocks, merge refuses every request, and this test passes
    // while coarsening nothing at all.
    for (int k = -400; k <= 400; ++k) {
      for (int r = 0; r < 8; ++r) {
        batch.push_back(point(vx + 0.05 * static_cast<double>(k), 0.05 * static_cast<double>(r)));
      }
    }
    veyra::map::integrate(grid, batch, static_cast<std::uint32_t>(step));
    veyra::map::applyPolicy(grid, pol, PassContext{vx, 0.0});

    const veyra::map::GridStats gs = grid.statistics();
    max_cells = std::max(max_cells, gs.occupied_cells);
    max_bytes = std::max(max_bytes, gs.allocated_bytes);
    worst_violation = std::max(worst_violation, countAncestorViolations(grid));
  }

  // Invariant 2 holds at every step of a 200 m drive.
  CHECK(worst_violation == 0);

  // ... and the detector above can actually fire, so that zero means
  // something. A cell placed directly beneath an active parent is exactly the
  // violation being ruled out.
  {
    TileGrid probe{MapWindow{0.0, 0.0, 50.0}};
    probe.findOrCreate(CellId{1, 5, 5});
    probe.findOrCreate(CellId{0, 10, 10});  // a child of the cell above
    CHECK(countAncestorViolations(probe) > 0);
  }

  // The drive really did coarsen -- otherwise the interaction above is untested.
  std::array<std::size_t, 4> per_level{};
  grid.forEachActiveLeaf([&per_level](CellId id, const veyra::map::Cell&) {
    ++per_level[static_cast<std::size_t>(id.level)];
  });
  CHECK(per_level[1] + per_level[2] + per_level[3] > 0);

  // Bounded: a disc of radius 25 m holds at most pi * 25^2 / 0.05^2 cells even
  // if every one of them were at level 0.
  CHECK(max_cells <= 785399U);
  CHECK(grid.statistics().occupied_cells > 0);
  CHECK(max_bytes > 0);

  // Still mapping 120 m from where it started.
  const veyra::map::LeafHit hit = veyra::map::activeLeafCovering(grid, 120.0, 0.1);
  CHECK(hit.found);
}

}  // namespace

int main() {
  checkDistanceBands();
  checkThresholdsMatchTheConfigFile();
  checkRefusalsAreCountedNotSwallowed();
  checkLevelDistributionBecomesAdaptive();
  checkHysteresisPreventsThrash();
  checkPerFrameCapIsRespected();
  checkIdempotentWhenConverged();
  checkFullLoopOverADrive();
  return 0;
}
