// Invariant test for observation intake and fusion: invariant 1 of
// docs/map-correctness.md -- every accepted XY observation belongs to exactly
// one active leaf, and every point offered is either accepted or rejected.
//
// Each group names the production bug it exists to catch.
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"
#include "veyra/map/fusion.hpp"
#include "veyra/map/observation.hpp"
#include "veyra/map/rolling_window.hpp"
#include "veyra/map/tile_grid.hpp"

namespace {

using veyra::map::FusionStats;
using veyra::map::integrate;
using veyra::map::Observation;
using veyra::map::TileGrid;

// Tolerances as locked in docs/map-correctness.md invariant 4.
constexpr double kMeanTol = 1e-9;
constexpr double kVarTol = 1e-5;

bool relClose(double a, double b, double tol) {
  const double scale = std::max({1.0, std::fabs(a), std::fabs(b)});
  return std::fabs(a - b) <= tol * scale;
}

Observation obs(double x, double y, float z) {
  Observation o;
  o.x = x;
  o.y = y;
  o.z = z;
  o.semantic_class = 1;
  o.semantic_confidence = 1.0F;
  return o;
}

// 1. Conservation: every point offered is accounted for exactly once, as
//    either accepted or rejected -- never both, never neither.
//    Catches: a counter incremented on both paths, or a path that silently
//    drops a point without counting it.
void checkConservation() {
  TileGrid grid;

  const FusionStats empty = integrate(grid, {}, 0);
  CHECK(empty.accepted + empty.rejected() == 0);

  const std::vector<Observation> batch = {obs(0.0, 0.0, 1.0F), obs(1.0, 1.0, 2.0F),
                                          obs(-1.0, -1.0, 3.0F)};
  const FusionStats s = integrate(grid, batch, 0);
  CHECK(s.accepted + s.rejected() == batch.size());
}

// 2. Unique ownership (invariant 1). A point belongs to exactly one cell:
//    two points inside the same 5 cm square make one cell holding both, and
//    two points in adjacent squares make two cells holding one each.
//    Catches: a point written to more than one cell, and an index that
//    collapses adjacent cells together.
void checkUniqueOwnership() {
  TileGrid same;
  const std::vector<Observation> together = {obs(0.01, 0.01, 1.0F), obs(0.04, 0.04, 3.0F)};
  const FusionStats a = integrate(same, together, 0);
  CHECK(a.accepted == 2);
  CHECK(same.statistics().occupied_cells == 1);
  const veyra::map::Cell* one = same.find(veyra::core::CellId{0, 0, 0});
  CHECK(one != nullptr);
  CHECK(one->count == 2);

  TileGrid apart;
  const std::vector<Observation> separate = {obs(0.01, 0.01, 1.0F), obs(0.06, 0.01, 2.0F)};
  const FusionStats b = integrate(apart, separate, 0);
  CHECK(b.accepted == 2);
  CHECK(apart.statistics().occupied_cells == 2);
  CHECK(apart.find(veyra::core::CellId{0, 0, 0})->count == 1);
  CHECK(apart.find(veyra::core::CellId{0, 1, 0})->count == 1);
}

// 3. Boundary determinism. A point exactly on a cell boundary lands in the
//    cell whose half-open extent [min, max) contains it, on both sides of the
//    origin. The corners are taken from extentOf so the test states the
//    convention rather than restating the implementation's arithmetic.
//    Catches: an index that rounds instead of flooring, and truncation toward
//    zero, which only misbehaves left of the origin.
void checkBoundaryDeterminism() {
  for (const std::int32_t ix : {-3, -1, 0, 1, 4}) {
    TileGrid grid;
    const veyra::core::CellId cell{0, ix, ix};
    const veyra::core::CellExtent e = veyra::core::extentOf(cell);

    // The lower corner belongs to this cell ...
    integrate(grid, std::vector<Observation>{obs(e.min_x, e.min_y, 1.0F)}, 0);
    CHECK(grid.find(cell) != nullptr);
    CHECK(grid.find(cell)->count == 1);

    // ... and the upper corner belongs to the next one.
    integrate(grid, std::vector<Observation>{obs(e.max_x, e.max_y, 1.0F)}, 0);
    const veyra::core::CellId next{0, static_cast<std::int32_t>(ix + 1),
                                   static_cast<std::int32_t>(ix + 1)};
    CHECK(grid.find(next) != nullptr);
    CHECK(grid.statistics().occupied_cells == 2);
  }
}

// 4. Statistics correctness. Heights folded through integrate produce the same
//    cell as folding them directly with updateCell.
//    Catches: fusion dropping a point, applying the update twice, or passing
//    the wrong value as z.
void checkStatisticsCorrectness() {
  const std::vector<float> heights = {1.0F, 2.0F, 3.0F, 4.0F};

  TileGrid grid;
  std::vector<Observation> batch;
  for (const float h : heights) {
    batch.push_back(obs(0.01, 0.01, h));
  }
  integrate(grid, batch, 0);

  veyra::map::Cell direct{};
  for (const float h : heights) {
    veyra::map::updateCell(direct, static_cast<double>(h));
  }

  const veyra::map::Cell* fused = grid.find(veyra::core::CellId{0, 0, 0});
  CHECK(fused != nullptr);
  CHECK(fused->count == direct.count);
  CHECK(fused->min_z == direct.min_z);
  CHECK(fused->max_z == direct.max_z);
  CHECK(relClose(fused->mean_z, direct.mean_z, kMeanTol));
  CHECK(relClose(veyra::map::varianceOf(*fused), veyra::map::varianceOf(direct), kVarTol));
}

// 5. Integrating into an existing cell updates it rather than replacing it,
//    and never creates a second cell for the same id.
//    Catches: a fusion path that resets the cell, and one that creates a new
//    cell per call instead of finding the existing one.
void checkIdempotentCreation() {
  TileGrid grid;
  const veyra::core::CellId id{0, 0, 0};

  const FusionStats first = integrate(grid, std::vector<Observation>{obs(0.01, 0.01, 1.0F)}, 0);
  CHECK(first.accepted == 1);
  const veyra::map::Cell* after_first = grid.find(id);
  CHECK(after_first != nullptr);
  CHECK(after_first->count == 1);

  const FusionStats second = integrate(grid, std::vector<Observation>{obs(0.02, 0.02, 5.0F)}, 1);
  CHECK(second.accepted == 1);
  CHECK(grid.statistics().occupied_cells == 1);
  CHECK(grid.statistics().tiles == 1);
  const veyra::map::Cell* after_second = grid.find(id);
  CHECK(after_second == after_first);  // same storage, not replaced
  CHECK(after_second->count == 2);
  CHECK(after_second->max_z == 5.0F);
}

// 6. A point beyond the map extent is rejected and counted, not an error and
//    not silently dropped. It creates no cell and no tile.
//    Catches: an unbounded index, which would let a stray coordinate allocate
//    a tile far from the map and blow the memory budget; and a rejection path
//    that forgets to count.
void checkOutOfRangeRejection() {
  TileGrid grid;
  const double far = veyra::map::kDefaultWindowRadiusM + 1.0;
  const std::vector<Observation> batch = {obs(0.01, 0.01, 1.0F), obs(far, 0.0, 1.0F),
                                          obs(0.0, -far, 1.0F), obs(-far, -far, 1.0F)};
  const FusionStats s = integrate(grid, batch, 0);

  CHECK(s.accepted == 1);
  CHECK(s.rejected_out_of_range == 3);
  CHECK(s.accepted + s.rejected() == batch.size());
  CHECK(grid.statistics().tiles == 1);
  CHECK(grid.statistics().occupied_cells == 1);

  // The window is a disc, not a box: just inside the radius is accepted, just
  // outside is not.
  TileGrid edge;
  const double r = veyra::map::kDefaultWindowRadiusM;
  const FusionStats lo = integrate(edge, std::vector<Observation>{obs(r - 0.5, 0.0, 1.0F)}, 0);
  CHECK(lo.accepted == 1);
  const FusionStats hi = integrate(edge, std::vector<Observation>{obs(r + 0.5, 0.0, 1.0F)}, 0);
  CHECK(hi.accepted == 0);
  CHECK(hi.rejected_out_of_range == 1);
}

// 7. Non-finite coordinates are rejected and counted separately from
//    out-of-range ones. A NaN reaching the index arithmetic is a silent
//    corruption, not a rejection, so the two are not the same event.
//    Catches: a missing finite check, and a range check placed before it --
//    every comparison against NaN is false, so a NaN would pass a naive
//    range test and reach the double-to-int32 conversion, which is undefined
//    behaviour.
void checkNonFiniteRejection() {
  const double nan_v = std::numeric_limits<double>::quiet_NaN();
  const double inf_v = std::numeric_limits<double>::infinity();

  TileGrid grid;
  const std::vector<Observation> batch = {
      obs(nan_v, 0.0, 1.0F),  obs(0.0, nan_v, 1.0F), obs(inf_v, 0.0, 1.0F),
      obs(0.0, -inf_v, 1.0F), obs(0.01, 0.01, 1.0F),
  };
  const FusionStats s = integrate(grid, batch, 0);

  CHECK(s.accepted == 1);
  CHECK(s.rejected_non_finite == 4);
  CHECK(s.rejected_out_of_range == 0);
  CHECK(s.accepted + s.rejected() == batch.size());
  CHECK(grid.statistics().occupied_cells == 1);
  CHECK(grid.statistics().tiles == 1);

  // A non-finite height is rejected too: it would poison the Welford mean of
  // every later point in that cell.
  TileGrid hz;
  const FusionStats z = integrate(
      hz, std::vector<Observation>{obs(0.01, 0.01, std::numeric_limits<float>::quiet_NaN())}, 0);
  CHECK(z.accepted == 0);
  CHECK(z.rejected_non_finite == 1);
  CHECK(hz.statistics().tiles == 0);
}

// 8. last_seen records the frame the cell was last observed in, and a later
//    frame updates it. cells_touched counts cells first seen in this frame,
//    cells_created counts cells that did not exist at all.
//    Catches: a constant stamped instead of the frame index, and a touched
//    count that cannot distinguish a new cell from a revisited one.
void checkLastSeenStamping() {
  TileGrid grid;
  const veyra::core::CellId id{0, 0, 0};

  const FusionStats f7 = integrate(grid, std::vector<Observation>{obs(0.01, 0.01, 1.0F)}, 7);
  CHECK(grid.find(id)->last_seen == 7);
  CHECK(f7.cells_created == 1);
  CHECK(f7.cells_touched == 1);

  const FusionStats f9 = integrate(grid, std::vector<Observation>{obs(0.02, 0.02, 2.0F)}, 9);
  CHECK(grid.find(id)->last_seen == 9);
  CHECK(f9.cells_created == 0);  // already existed
  CHECK(f9.cells_touched == 1);

  // Two points in the same cell in one frame touch one cell, not two.
  TileGrid pair;
  const FusionStats both =
      integrate(pair, std::vector<Observation>{obs(0.01, 0.01, 1.0F), obs(0.02, 0.02, 2.0F)}, 3);
  CHECK(both.accepted == 2);
  CHECK(both.cells_created == 1);
  CHECK(both.cells_touched == 1);
  CHECK(pair.find(id)->last_seen == 3);
}

Observation labelled(double x, double y, std::uint8_t cls, float conf) {
  Observation o = obs(x, y, 1.0F);
  o.semantic_class = cls;
  o.semantic_confidence = conf;
  return o;
}

// 9. Semantic accumulation. Cell::cls holds the dominant class by streaming
//    majority and Cell::confidence is a saturating agreement counter read as
//    confidence in that class. An observation carrying no confidence votes on
//    nothing but still contributes geometry.
//    Catches: a counter that wraps instead of clamping -- 256 agreeing
//    observations reporting confidence 0 would invert the meaning of the
//    field; and a takeover rule that lets a single disagreeing point flip an
//    established label.
void checkSemanticAccumulation() {
  // A new cell adopts the first labelled observation it sees.
  TileGrid fresh;
  integrate(fresh, std::vector<Observation>{labelled(0.01, 0.01, 4, 1.0F)}, 0);
  const veyra::core::CellId id{0, 0, 0};
  CHECK(fresh.find(id)->cls == 4);
  CHECK(fresh.find(id)->confidence == 1);

  // Agreement accumulates and then clamps. 300 > 255, so a wrapping counter
  // would land near zero instead.
  TileGrid agree;
  std::vector<Observation> many;
  for (int i = 0; i < 300; ++i) {
    many.push_back(labelled(0.01, 0.01, 4, 1.0F));
  }
  integrate(agree, many, 0);
  CHECK(agree.find(id)->cls == 4);
  CHECK(agree.find(id)->confidence == 255);
  CHECK(agree.find(id)->count == 300);

  // Disagreement erodes the counter before it flips the label: one dissenting
  // point cannot unseat a class, two can when the counter is at 1.
  TileGrid flip;
  integrate(flip, std::vector<Observation>{labelled(0.01, 0.01, 4, 1.0F)}, 0);
  integrate(flip, std::vector<Observation>{labelled(0.01, 0.01, 7, 1.0F)}, 0);
  CHECK(flip.find(id)->cls == 4);  // eroded, not unseated
  CHECK(flip.find(id)->confidence == 0);
  integrate(flip, std::vector<Observation>{labelled(0.01, 0.01, 7, 1.0F)}, 0);
  CHECK(flip.find(id)->cls == 7);  // counter was spent, the challenger takes over
  CHECK(flip.find(id)->confidence == 1);

  // An observation with no confidence carries no semantic evidence: it does
  // not vote, but its height still counts.
  TileGrid quiet;
  integrate(quiet, std::vector<Observation>{labelled(0.01, 0.01, 4, 1.0F)}, 0);
  integrate(quiet, std::vector<Observation>{labelled(0.01, 0.01, 9, 0.0F)}, 0);
  CHECK(quiet.find(id)->cls == 4);
  CHECK(quiet.find(id)->confidence == 1);
  CHECK(quiet.find(id)->count == 2);
}

// 10. A canonical 16-bit semantic id must not be silently narrowed by the
// legacy TileGrid's compact 8-bit class slot. Geometry remains accepted, but
// the unsupported semantic evidence is reported explicitly.
void checkSemanticLabelDoesNotNarrow() {
  TileGrid grid;
  Observation point = obs(0.01, 0.01, 2.0F);
  point.semantic_class = 300;
  point.semantic_confidence = 1.0F;
  const FusionStats stats = integrate(grid, std::vector<Observation>{point}, 0);

  CHECK(stats.accepted == 1);
  CHECK(stats.semantic_labels_unrepresentable == 1);
  const auto* cell = grid.find(veyra::core::CellId{0, 0, 0});
  CHECK(cell != nullptr);
  CHECK(cell->count == 1);
  CHECK(cell->confidence == 0);
}

// 11. Batch equivalence: integrating N points in one call leaves the grid in
//     the same state as integrating them one at a time, and the summed
//     statistics agree.
//     Catches: state carried between points within a batch -- a running
//     index, a cached tile pointer, or an accumulator that is not reset.
void checkBatchEquivalence() {
  std::vector<Observation> batch;
  for (int i = 0; i < 60; ++i) {
    const double x = -0.3 + 0.021 * static_cast<double>(i);
    const double y = 0.2 - 0.017 * static_cast<double>(i);
    batch.push_back(labelled(x, y, static_cast<std::uint8_t>(i % 3), 1.0F));
  }

  TileGrid at_once;
  const FusionStats bulk = integrate(at_once, batch, 5);

  TileGrid one_by_one;
  FusionStats summed;
  for (const Observation& o : batch) {
    const FusionStats s = integrate(one_by_one, std::vector<Observation>{o}, 5);
    summed.accepted += s.accepted;
    summed.rejected_out_of_range += s.rejected_out_of_range;
    summed.rejected_non_finite += s.rejected_non_finite;
    summed.cells_created += s.cells_created;
    summed.cells_touched += s.cells_touched;
  }

  CHECK(bulk.accepted == summed.accepted);
  CHECK(bulk.rejected() == summed.rejected());
  CHECK(bulk.cells_created == summed.cells_created);
  CHECK(bulk.cells_touched == summed.cells_touched);

  const veyra::map::GridStats ga = at_once.statistics();
  const veyra::map::GridStats gb = one_by_one.statistics();
  CHECK(ga.tiles == gb.tiles);
  CHECK(ga.occupied_cells == gb.occupied_cells);
  CHECK(ga.allocated_bytes == gb.allocated_bytes);

  // Every cell agrees, field by field, not just in aggregate.
  std::size_t compared = 0;
  at_once.forEachActiveLeaf([&](veyra::core::CellId id, const veyra::map::Cell& lhs) {
    const veyra::map::Cell* rhs = one_by_one.find(id);
    CHECK(rhs != nullptr);
    CHECK(lhs.count == rhs->count);
    CHECK(lhs.min_z == rhs->min_z);
    CHECK(lhs.max_z == rhs->max_z);
    CHECK(lhs.last_seen == rhs->last_seen);
    CHECK(lhs.cls == rhs->cls);
    CHECK(lhs.confidence == rhs->confidence);
    CHECK(relClose(lhs.mean_z, rhs->mean_z, kMeanTol));
    CHECK(relClose(veyra::map::varianceOf(lhs), veyra::map::varianceOf(*rhs), kVarTol));
    ++compared;
  });
  CHECK(compared == ga.occupied_cells);
  CHECK(compared > 1);
}

}  // namespace

int main() {
  checkConservation();
  checkUniqueOwnership();
  checkBoundaryDeterminism();
  checkStatisticsCorrectness();
  checkIdempotentCreation();
  checkOutOfRangeRejection();
  checkNonFiniteRejection();
  checkLastSeenStamping();
  checkSemanticAccumulation();
  checkSemanticLabelDoesNotNarrow();
  checkBatchEquivalence();
  return 0;
}
