// Native regression suites. CTest runs each section in a fresh process.
#include <cstdio>
#include <string_view>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <random>
#include <vector>
#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"
#include "veyra/map/fusion.hpp"
#include "veyra/map/observation.hpp"
#include "veyra/map/split_merge.hpp"
#include "veyra/map/tile_grid.hpp"
#include <algorithm>
#include <limits>
#include "veyra/map/rolling_window.hpp"

namespace split_merge {

// Invariant test for per-cell statistics: the Welford update, Chan's parallel
// merge, and the property that merging two cells equals accumulating their
// points into one. Covers invariant 4 of docs/map-correctness.md, statistics
// half only -- split/merge policy is a later PR.


namespace {

using veyra::map::Cell;
using veyra::map::mergeCells;
using veyra::map::updateCell;
using veyra::map::varianceOf;

// Tolerances from docs/map-correctness.md invariant 4. The mean is strict
// because it is a double; the variance is looser because m2 is a float.
// count and min_z / max_z are compared with == and need no constant.
constexpr double kMeanTol = 1e-9;
constexpr double kVarTol = 1e-5;

// Relative comparison, falling back to absolute near zero so that a tiny
// expected value does not make the tolerance vanish.
bool relClose(double a, double b, double tol) {
  const double scale = std::max({1.0, std::fabs(a), std::fabs(b)});
  return std::fabs(a - b) <= tol * scale;
}

Cell cellFrom(const std::vector<double>& zs) {
  Cell c{};
  for (const double z : zs) {
    updateCell(c, z);
  }
  return c;
}

// The four rules of invariant 4, applied together.
void checkStatsEqual(const Cell& got, const Cell& want) {
  CHECK(got.count == want.count);
  CHECK(got.min_z == want.min_z);
  CHECK(got.max_z == want.max_z);
  CHECK(relClose(got.mean_z, want.mean_z, kMeanTol));
  CHECK(relClose(varianceOf(got), varianceOf(want), kVarTol));
}

std::vector<double> deterministicPoints(std::size_t n, double centre, double spread) {
  std::mt19937 rng(20260910u);  // fixed seed: the point set must be reproducible
  std::uniform_real_distribution<double> dist(centre - spread, centre + spread);
  std::vector<double> zs;
  zs.reserve(n);
  for (std::size_t i = 0; i < n; ++i) {
    zs.push_back(dist(rng));
  }
  return zs;
}

// 1. A cell holding one point: the mean is that point, there is no spread, and
//    the bounds are the point itself.
void checkSinglePoint() {
  Cell c{};
  updateCell(c, 4.25);
  CHECK(c.count == 1);
  CHECK(relClose(c.mean_z, 4.25, kMeanTol));
  CHECK(c.m2 == 0.0F);
  CHECK(varianceOf(c) == 0.0);
  CHECK(c.min_z == 4.25F);
  CHECK(c.max_z == 4.25F);
  // An empty cell has no spread either, and must not divide by zero.
  const Cell empty{};
  CHECK(varianceOf(empty) == 0.0);
}

// 2. A hand-computed set, so the test is anchored to arithmetic rather than to
//    itself. z = {1, 2, 3, 4}: mean 2.5, sum of squared deviations 5.0,
//    population variance 1.25. Every value here is exact in binary.
void checkKnownSmallSet() {
  const Cell c = cellFrom({1.0, 2.0, 3.0, 4.0});
  CHECK(c.count == 4);
  CHECK(relClose(c.mean_z, 2.5, kMeanTol));
  CHECK(relClose(static_cast<double>(c.m2), 5.0, kVarTol));
  CHECK(relClose(varianceOf(c), 1.25, kVarTol));
  CHECK(c.min_z == 1.0F);
  CHECK(c.max_z == 4.0F);
}

// 3. The central property: merging two cells equals accumulating the union of
//    their points into one cell. Several splits of the same set, including a
//    lopsided 1-vs-999.
void checkMergeEqualsUnion() {
  const std::vector<double> zs = deterministicPoints(1000, 12.0, 3.0);
  const Cell whole = cellFrom(zs);

  for (const std::size_t split : {std::size_t{1}, std::size_t{2}, std::size_t{17}, std::size_t{500},
                                  std::size_t{998}, std::size_t{999}}) {
    const std::vector<double> left(zs.begin(), zs.begin() + static_cast<std::ptrdiff_t>(split));
    const std::vector<double> right(zs.begin() + static_cast<std::ptrdiff_t>(split), zs.end());
    const Cell merged = mergeCells(cellFrom(left), cellFrom(right));
    CHECK(merged.count == 1000);
    checkStatsEqual(merged, whole);
  }
}

// 4. Merge is commutative and associative over the statistics, so the order in
//    which a subtree is folded up cannot change the result.
void checkMergeCommutativeAssociative() {
  const Cell a = cellFrom(deterministicPoints(37, 5.0, 2.0));
  const Cell b = cellFrom({1.5, 2.5, 3.5, 4.5, 5.5});
  const Cell c = cellFrom({-2.0, 0.0, 2.0});

  checkStatsEqual(mergeCells(a, b), mergeCells(b, a));
  checkStatsEqual(mergeCells(b, c), mergeCells(c, b));
  checkStatsEqual(mergeCells(a, mergeCells(b, c)), mergeCells(mergeCells(a, b), c));
}

// 5. Empty operands are the identity, and two empties stay empty.
void checkEmptyOperands() {
  const Cell empty{};
  const Cell a = cellFrom({3.0, 6.0, 9.0});

  checkStatsEqual(mergeCells(a, empty), a);
  checkStatsEqual(mergeCells(empty, a), a);

  const Cell both = mergeCells(empty, empty);
  CHECK(both.count == 0);
  CHECK(varianceOf(both) == 0.0);
}

// 6. Four children merged into one parent -- the case the grid actually
//    performs, and invariant 3's counterpart on the statistics side.
void checkFourChildMerge() {
  const std::vector<double> zs = deterministicPoints(400, 20.0, 1.5);
  const Cell whole = cellFrom(zs);

  std::vector<Cell> quarters;
  for (std::size_t q = 0; q < 4; ++q) {
    const std::vector<double> part(zs.begin() + static_cast<std::ptrdiff_t>(q * 100),
                                   zs.begin() + static_cast<std::ptrdiff_t>((q + 1) * 100));
    quarters.push_back(cellFrom(part));
  }

  const Cell merged =
      mergeCells(mergeCells(quarters[0], quarters[1]), mergeCells(quarters[2], quarters[3]));
  CHECK(merged.count == 400);
  checkStatsEqual(merged, whole);
}

// 7. Heights entirely below zero, and heights straddling zero. Confirms that
//    min_z / max_z are seeded from the first point rather than left at 0,
//    which would silently include a height the cell never saw.
void checkNegativeAndMixedHeights() {
  const Cell below = cellFrom({-7.0, -5.0, -3.0, -1.0});
  CHECK(below.max_z == -1.0F);
  CHECK(below.min_z == -7.0F);
  CHECK(relClose(below.mean_z, -4.0, kMeanTol));
  CHECK(below.max_z < 0.0F);  // 0 must not leak in as a bound

  const Cell straddling = cellFrom({-2.5, -0.5, 0.5, 2.5});
  CHECK(straddling.min_z == -2.5F);
  CHECK(straddling.max_z == 2.5F);
  CHECK(relClose(straddling.mean_z, 0.0, kMeanTol));

  // The property survives a merge of two one-sided cells.
  const Cell rejoined = mergeCells(cellFrom({-2.5, -0.5}), cellFrom({0.5, 2.5}));
  checkStatsEqual(rejoined, straddling);
}

// 8. High count. This is the property mean_z was made a double for: in float
//    the ulp at 30 m is ~1.9e-6, so once count is large the increment
//    delta / count lands near it and updates are silently swallowed, leaving a
//    plausible-looking wrong mean with no error raised. Both sets below have
//    an analytically exact mean, and a float mean_z fails both -- measured
//    error 2.3e-4 and 4.6e-7 against a 3e-8 tolerance.
void checkHighCount() {
  // 90k points at 30.0 then 10k at 31.0: the mean is exactly 30.1.
  Cell step{};
  for (int i = 0; i < 90000; ++i) {
    updateCell(step, 30.0);
  }
  for (int i = 0; i < 10000; ++i) {
    updateCell(step, 31.0);
  }
  CHECK(step.count == 100000);
  CHECK(relClose(step.mean_z, 30.1, kMeanTol));
  CHECK(step.min_z == 30.0F);
  CHECK(step.max_z == 31.0F);

  // The swallowed-update case in its purest form: a single outlier arriving
  // last, when the increment delta / count is at its smallest.
  Cell late{};
  for (int i = 0; i < 99999; ++i) {
    updateCell(late, 30.0);
  }
  updateCell(late, 31.0);
  CHECK(late.count == 100000);
  CHECK(relClose(late.mean_z, 30.0 + 1.0 / 100000.0, kMeanTol));
  CHECK(late.max_z == 31.0F);
}

// --- split/merge statistics: invariant 4 across a level change ------------

veyra::map::Cell& seedGrid(veyra::map::TileGrid& grid, veyra::core::CellId id, int points) {
  veyra::map::Cell& c = grid.findOrCreate(id);
  for (int i = 0; i < points; ++i) {
    updateCell(c, 3.0 + 0.05 * static_cast<double>(i));
  }
  return c;
}

// 5. Splitting distributes evidence rather than multiplying it: each child
//    takes roughly a quarter of the count, keeps the parent's mean and
//    extremes, and carries a reduced confidence to mark it as an estimate.
//    Catches: m2 or count copied undivided, which would let four children each
//    claim the parent's full observation weight -- inventing evidence that was
//    never gathered.
void checkSplitDistributesStatistics() {
  veyra::map::TileGrid grid;
  const veyra::core::CellId parent{2, 1, 1};
  Cell& p = seedGrid(grid, parent, 8);
  p.confidence = 8;
  const Cell before = p;

  CHECK(veyra::map::split(grid, parent));

  std::uint32_t total = 0;
  std::uint32_t conf_total = 0;
  double m2_total = 0.0;
  std::size_t kids = 0;
  grid.forEachActiveLeaf([&](veyra::core::CellId, const Cell& c) {
    ++kids;
    total += c.count;
    conf_total += c.confidence;
    m2_total += static_cast<double>(c.m2);
    CHECK(c.count == 2);  // 8 / 4, no remainder
    // The parent's mean is the best available estimate for every part of its
    // square, and its extremes genuinely bound the children's.
    CHECK(c.mean_z == before.mean_z);
    CHECK(c.min_z == before.min_z);
    CHECK(c.max_z == before.max_z);
    // Each child keeps the parent's variance: m2 scales with count.
    CHECK(relClose(varianceOf(c), varianceOf(before), kVarTol));
    // Provenance: a split child holds an estimate, not a measurement.
    CHECK(c.confidence < before.confidence);
  });
  CHECK(kids == 4);
  CHECK(total == before.count);
  CHECK(conf_total == before.confidence);
  CHECK(relClose(m2_total, static_cast<double>(before.m2), kVarTol));
}

// 6. The integer remainder is distributed, not dropped. n / 4 loses up to
//    three counts; at n = 101 that is a silent conservation failure that
//    n = 100 would never reveal.
//    Catches: count divided by four with the remainder discarded.
void checkRemainderIsDistributed() {
  for (const int n : {1, 2, 3, 5, 7, 101}) {
    veyra::map::TileGrid grid;
    const veyra::core::CellId parent{2, 0, 0};
    seedGrid(grid, parent, n);
    const std::uint32_t before = grid.find(parent)->count;
    CHECK(before == static_cast<std::uint32_t>(n));

    CHECK(veyra::map::split(grid, parent));

    std::uint32_t total = 0;
    std::size_t kids = 0;
    grid.forEachActiveLeaf([&](veyra::core::CellId, const Cell& c) {
      total += c.count;
      ++kids;
    });
    CHECK(kids == 4);
    CHECK(total == before);
  }
}

// 7. Invariant 4 across a level change: merge(split(x)) reproduces x. The
//    equal-mean construction makes Chan's correction term vanish, so this
//    should hold exactly on count and to within the locked tolerances on mean
//    and variance.
//    Catches: evidence lost or invented in either direction -- the failure
//    that silently corrupts every number the benchmark later reports.
void checkSplitMergeRoundTrip() {
  for (const int n : {1, 2, 3, 4, 5, 7, 8, 101}) {
    veyra::map::TileGrid grid;
    const veyra::core::CellId parent{2, 2, -3};
    Cell& p = seedGrid(grid, parent, n);
    p.confidence = static_cast<std::uint8_t>(n % 256);
    const Cell before = p;

    CHECK(veyra::map::split(grid, parent));
    CHECK(grid.statistics().occupied_cells == 4);
    CHECK(veyra::map::merge(grid, parent));

    const Cell* after = grid.find(parent);
    CHECK(after != nullptr);
    CHECK(grid.statistics().occupied_cells == 1);

    CHECK(after->count == before.count);  // exact, not within a tolerance
    CHECK(after->min_z == before.min_z);  // exact
    CHECK(after->max_z == before.max_z);  // exact
    CHECK(after->confidence == before.confidence);
    CHECK(relClose(after->mean_z, before.mean_z, kMeanTol));
    CHECK(relClose(varianceOf(*after), varianceOf(before), kVarTol));
  }
}

// 12. A split child is an estimate until a real observation reaches it. After
//     integrating, that child's count grows and its confidence rises, while
//     its siblings are untouched.
//     Chosen behaviour: the count grows and confidence recovers -- there is no
//     separate flag to clear, because provenance is carried as the reduced
//     confidence itself.
//     Catches: an observation landing in the wrong child, and a split that
//     leaves children unreachable to fusion.
void checkSplitThenIntegrate() {
  veyra::map::TileGrid grid;
  const veyra::core::CellId parent{1, 2, 2};  // splits into level-0 children
  Cell& p = seedGrid(grid, parent, 12);
  p.confidence = 12;
  CHECK(veyra::map::split(grid, parent));

  const std::array<veyra::core::CellId, 4> kids = veyra::core::childrenOf(parent);
  const veyra::core::CellId target = kids[2];
  const Cell before = *grid.find(target);
  CHECK(before.count == 3);

  // Aim at the middle of that child so the point cannot land on a boundary.
  const veyra::core::CellExtent e = veyra::core::extentOf(target);
  veyra::map::Observation o;
  o.x = 0.5 * (e.min_x + e.max_x);
  o.y = 0.5 * (e.min_y + e.max_y);
  o.z = 9.0F;
  o.semantic_class = before.cls;
  o.semantic_confidence = 1.0F;
  const veyra::map::FusionStats fs =
      veyra::map::integrate(grid, std::vector<veyra::map::Observation>{o}, 77);
  CHECK(fs.accepted == 1);
  CHECK(fs.cells_created == 0);  // the child already existed

  const Cell* after = grid.find(target);
  CHECK(after != nullptr);
  CHECK(after->count == before.count + 1);
  CHECK(after->confidence > before.confidence);  // evidence recovered
  CHECK(after->last_seen == 77);
  CHECK(after->max_z == 9.0F);

  // Siblings untouched, and no fifth cell created.
  CHECK(grid.statistics().occupied_cells == 4);
  for (std::size_t i = 0; i < 4; ++i) {
    if (kids[i] == target) {
      continue;
    }
    CHECK(grid.find(kids[i])->count == 3);
    CHECK(grid.find(kids[i])->last_seen != 77);
  }
}

}  // namespace

int run() {
  checkSinglePoint();
  checkKnownSmallSet();
  checkMergeEqualsUnion();
  checkMergeCommutativeAssociative();
  checkEmptyOperands();
  checkFourChildMerge();
  checkNegativeAndMixedHeights();
  checkHighCount();
  checkSplitDistributesStatistics();
  checkRemainderIsDistributed();
  checkSplitMergeRoundTrip();
  checkSplitThenIntegrate();
  return 0;
  return 0;
}

}  // namespace split_merge

namespace point_conservation {

// Invariant test for observation intake and fusion: invariant 1 of
// docs/map-correctness.md -- every accepted XY observation belongs to exactly
// one active leaf, and every point offered is either accepted or rejected.
//
// Each group names the production bug it exists to catch.


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

int run() {
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
  return 0;
}

}  // namespace point_conservation

int main(int argc, char** argv) {
  if (argc == 2) {
    const std::string_view suite{argv[1]};
    if (suite == "split_merge") return split_merge::run();
    if (suite == "point_conservation") return point_conservation::run();
  }
  std::fputs("Select a registered CTest suite.\n", stderr);
  return 2;
}
