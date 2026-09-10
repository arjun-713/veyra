// Invariant test for per-cell statistics: the Welford update, Chan's parallel
// merge, and the property that merging two cells equals accumulating their
// points into one. Covers invariant 4 of docs/map-correctness.md, statistics
// half only -- split/merge policy is a later PR.
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <random>
#include <vector>

#include "check.hpp"
#include "veyra/map/cell.hpp"

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

}  // namespace

int main() {
  checkSinglePoint();
  checkKnownSmallSet();
  checkMergeEqualsUnion();
  checkMergeCommutativeAssociative();
  checkEmptyOperands();
  checkFourChildMerge();
  checkNegativeAndMixedHeights();
  checkHighCount();
  return 0;
}
