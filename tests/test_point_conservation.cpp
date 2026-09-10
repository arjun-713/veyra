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
  o.cls = 1;
  o.confidence = 1.0F;
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
  const double far = veyra::map::kMapHalfExtentM + 1.0;
  const std::vector<Observation> batch = {obs(0.01, 0.01, 1.0F), obs(far, 0.0, 1.0F),
                                          obs(0.0, -far, 1.0F), obs(-far, -far, 1.0F)};
  const FusionStats s = integrate(grid, batch, 0);

  CHECK(s.accepted == 1);
  CHECK(s.rejected_out_of_range == 3);
  CHECK(s.accepted + s.rejected() == batch.size());
  CHECK(grid.statistics().tiles == 1);
  CHECK(grid.statistics().occupied_cells == 1);

  // The extent is half-open: the lower bound is inside, the upper bound is not.
  TileGrid edge;
  const FusionStats lo =
      integrate(edge,
                std::vector<Observation>{
                    obs(-veyra::map::kMapHalfExtentM, -veyra::map::kMapHalfExtentM, 1.0F)},
                0);
  CHECK(lo.accepted == 1);
  const FusionStats hi = integrate(
      edge,
      std::vector<Observation>{obs(veyra::map::kMapHalfExtentM, veyra::map::kMapHalfExtentM, 1.0F)},
      0);
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

}  // namespace

int main() {
  checkConservation();
  checkUniqueOwnership();
  checkBoundaryDeterminism();
  checkStatisticsCorrectness();
  checkIdempotentCreation();
  checkOutOfRangeRejection();
  checkNonFiniteRejection();
  return 0;
}
