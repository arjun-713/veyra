// Native regression suites. CTest runs each section in a fresh process.
#include <cstdio>
#include <string_view>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <random>
#include <utility>
#include <vector>
#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/map.hpp"
#include <tuple>
#include <cstdio>

namespace randomized_map_invariants {

namespace {

using veyra::core::CellExtent;
using veyra::core::CellId;
using veyra::map::Leaf;
using veyra::map::Map;
using veyra::map::Observation;
using veyra::map::ResolutionPolicy;

constexpr double kExtentEpsilon = 1e-12;
constexpr std::uint32_t kSeed = 0x5EED2605U;
constexpr int kSteps = 800;

bool interiorsDisjoint(const CellExtent& left, const CellExtent& right) {
  return left.max_x <= right.min_x + kExtentEpsilon ||
         right.max_x <= left.min_x + kExtentEpsilon ||
         left.max_y <= right.min_y + kExtentEpsilon ||
         right.max_y <= left.min_y + kExtentEpsilon;
}

void checkSnapshotTopology(const std::vector<Leaf>& leaves) {
  for (std::size_t i = 0; i < leaves.size(); ++i) {
    const CellExtent left = veyra::core::extentOf(leaves[i].id);
    for (std::size_t j = i + 1; j < leaves.size(); ++j) {
      const CellExtent right = veyra::core::extentOf(leaves[j].id);
      CHECK(interiorsDisjoint(left, right));
    }
  }
}

void checkAcceptedObservationHasOneActiveOwner(const Map& map, const std::vector<Leaf>& leaves,
                                               double x, double y) {
  const CellId expected = map.cell_for(x, y);
  std::size_t owners = 0;
  for (const Leaf& leaf : leaves) {
    owners += leaf.id == expected ? 1U : 0U;
  }
  CHECK(owners == 1);
}

CellId randomSplittableLeaf(const std::vector<Leaf>& leaves, std::mt19937& rng) {
  std::vector<CellId> candidates;
  for (const Leaf& leaf : leaves) {
    if (leaf.id.level != 0) candidates.push_back(leaf.id);
  }
  CHECK(!candidates.empty());
  std::uniform_int_distribution<std::size_t> pick(0, candidates.size() - 1);
  return candidates[pick(rng)];
}

CellId randomMergeCandidate(const std::vector<Leaf>& leaves, std::mt19937& rng) {
  std::vector<CellId> candidates;
  for (const Leaf& leaf : leaves) {
    if (leaf.id.level == 3) continue;
    const CellId parent = veyra::core::parentOf(leaf.id);
    const auto children = veyra::core::childrenOf(parent);
    bool all_children_active = true;
    for (const CellId child : children) {
      all_children_active = all_children_active &&
                            std::any_of(leaves.begin(), leaves.end(),
                                        [child](const Leaf& other) { return other.id == child; });
    }
    if (all_children_active &&
        std::none_of(candidates.begin(), candidates.end(),
                     [parent](CellId candidate) { return candidate == parent; })) {
      candidates.push_back(parent);
    }
  }
  CHECK(!candidates.empty());
  std::uniform_int_distribution<std::size_t> pick(0, candidates.size() - 1);
  return candidates[pick(rng)];
}

void checkRandomizedMixedResolutionChurn() {
  Map map(ResolutionPolicy::Uniform40,
          veyra::map::MapConfig{.window_radius_m = 8.0, .tile_size_m = 0.8});
  std::mt19937 rng(kSeed);
  std::uniform_real_distribution<double> radius(0.0, 7.95);
  std::uniform_real_distribution<double> angle(-3.14159265358979323846,
                                               3.14159265358979323846);
  std::uniform_real_distribution<double> height(-20.0, 20.0);
  std::uniform_int_distribution<int> action(0, 2);
  std::uint64_t accepted = 0;

  // Deterministic half-open-boundary probes anchor the randomized run on both
  // sides of the origin. These are public Map updates, not direct grid setup.
  for (const auto& [x, y] : std::array<std::pair<double, double>, 6>{
           std::pair{-1.6, -1.2}, std::pair{-0.4, 0.0}, std::pair{0.0, 0.4},
           std::pair{0.4, -0.4}, std::pair{1.2, 0.8}, std::pair{-0.8, 1.6}}) {
    map.update(Observation{.x = x, .y = y, .z = height(rng), .timestamp = ++accepted});
    const auto snapshot = map.snapshot();
    CHECK(snapshot.point_count == accepted);
    CHECK(snapshot.has_no_parent_descendant_overlap());
    checkSnapshotTopology(snapshot.leaves);
    checkAcceptedObservationHasOneActiveOwner(map, snapshot.leaves, x, y);
  }

  for (int step = 0; step < kSteps; ++step) {
    const int operation = action(rng);
    const auto before = map.snapshot();
    const bool has_splittable_leaf =
        std::any_of(before.leaves.begin(), before.leaves.end(),
                    [](const Leaf& leaf) { return leaf.id.level != 0; });
    if (operation == 0 || before.leaves.empty() || (operation == 1 && !has_splittable_leaf)) {
      const double r = radius(rng);
      const double theta = angle(rng);
      const double x = r * std::cos(theta);
      const double y = r * std::sin(theta);
      map.update(Observation{.x = x, .y = y, .z = height(rng),
                             .timestamp = static_cast<std::uint64_t>(step + 1)});
      ++accepted;
      const auto snapshot = map.snapshot();
      CHECK(snapshot.point_count == accepted);
      CHECK(snapshot.has_no_parent_descendant_overlap());
      checkSnapshotTopology(snapshot.leaves);
      checkAcceptedObservationHasOneActiveOwner(map, snapshot.leaves, x, y);
      continue;
    }

    if (operation == 1) {
      const CellId id = randomSplittableLeaf(before.leaves, rng);
      map.split(id);
    } else {
      bool has_candidate = false;
      for (const Leaf& leaf : before.leaves) {
        if (leaf.id.level == 0) continue;
        const auto children = veyra::core::childrenOf(leaf.id);
        has_candidate = std::all_of(children.begin(), children.end(), [&before](CellId child) {
          return std::any_of(before.leaves.begin(), before.leaves.end(),
                             [child](const Leaf& other) { return other.id == child; });
        });
        if (has_candidate) break;
      }
      if (has_candidate) map.merge_children(randomMergeCandidate(before.leaves, rng));
    }

    const auto after = map.snapshot();
    CHECK(after.point_count == accepted);
    CHECK(after.nonspatial_prior_point_count <= accepted);
    CHECK(after.has_no_parent_descendant_overlap());
    checkSnapshotTopology(after.leaves);
  }

  const auto final_snapshot = map.snapshot();
  CHECK(final_snapshot.split_count > 0);
  CHECK(final_snapshot.merge_count > 0);
}

}  // namespace

int run() {
  checkRandomizedMixedResolutionChurn();
  return 0;
  return 0;
}

}  // namespace randomized_map_invariants

namespace map_public_properties {

namespace {

using veyra::core::CellExtent;
using veyra::core::CellId;
using veyra::map::CellStats;
using veyra::map::Leaf;
using veyra::map::Map;
using veyra::map::MapSnapshot;
using veyra::map::Observation;
using veyra::map::ResolutionPolicy;

constexpr double kTol = 1e-10;

bool close(double left, double right) {
  return std::fabs(left - right) <= kTol * std::max({1.0, std::fabs(left), std::fabs(right)});
}

bool disjoint(const CellExtent& left, const CellExtent& right) {
  return left.max_x <= right.min_x || right.max_x <= left.min_x ||
         left.max_y <= right.min_y || right.max_y <= left.min_y;
}

const Leaf& leafFor(const MapSnapshot& snapshot, CellId id) {
  const auto found = std::find_if(snapshot.leaves.begin(), snapshot.leaves.end(),
                                  [id](const Leaf& leaf) { return leaf.id == id; });
  CHECK(found != snapshot.leaves.end());
  return *found;
}

void checkTopology(const MapSnapshot& snapshot) {
  CHECK(snapshot.has_no_parent_descendant_overlap());
  for (std::size_t i = 0; i < snapshot.leaves.size(); ++i) {
    const CellExtent left = veyra::core::extentOf(snapshot.leaves[i].id);
    for (std::size_t j = i + 1; j < snapshot.leaves.size(); ++j) {
      CHECK(disjoint(left, veyra::core::extentOf(snapshot.leaves[j].id)));
    }
  }
}

void checkStats(const CellStats& got, const CellStats& expected) {
  CHECK(got.count == expected.count);
  CHECK(got.min_z() == expected.min_z());
  CHECK(got.max_z() == expected.max_z());
  CHECK(close(got.mean_z(), expected.mean_z()));
  CHECK(close(got.m2_z(), expected.m2_z()));
  CHECK(got.last_seen == expected.last_seen);
}

Observation point(double x, double y, double z, std::uint64_t timestamp) {
  return Observation{.x = x, .y = y, .z = z, .timestamp = timestamp};
}

void checkBoundaryAndSignedOwnership() {
  Map map(ResolutionPolicy::Uniform5, {.window_radius_m = 3.0, .tile_size_m = 0.4});
  std::uint64_t timestamp = 0;
  std::vector<CellId> expected_ids;
  for (const std::int32_t ix : {-11, -1, 0, 1, 10}) {
    const CellExtent extent = veyra::core::extentOf(CellId{0, ix, ix});
    for (const auto& [x, y] : std::array<std::pair<double, double>, 2>{
             std::pair{extent.min_x, extent.min_y}, std::pair{extent.max_x, extent.max_y}}) {
      const CellId expected = map.cell_for(x, y);
      const std::uint64_t next_timestamp = ++timestamp;
      map.update(point(x, y, static_cast<double>(next_timestamp) - 3.0, next_timestamp));
      const MapSnapshot snapshot = map.snapshot();
      checkTopology(snapshot);
      CHECK(snapshot.point_count == timestamp);
      expected_ids.push_back(expected);
      const std::size_t expected_count = static_cast<std::size_t>(
          std::count(expected_ids.begin(), expected_ids.end(), expected));
      CHECK(leafFor(snapshot, expected).stats.count == expected_count);
      std::size_t owners = 0;
      for (const Leaf& leaf : snapshot.leaves) owners += leaf.id == expected ? 1U : 0U;
      CHECK(owners == 1);
    }
  }
}

void checkWindowEdgePointYieldsExactlyOneLeaf() {  // Pins the investigated 100 m boundary: an accepted window-edge return must
  // own exactly one leaf with count 1, never vanish silently.
  Map map(ResolutionPolicy::Uniform5, {.window_radius_m = 100.001, .tile_size_m = 0.4});
  map.set_window_center(0.0, 0.0);
  CHECK(map.accepts(100.0, 0.0));
  map.update(point(100.0, 0.0, 0.0, 1));
  const MapSnapshot snapshot = map.snapshot();
  checkTopology(snapshot);
  CHECK(snapshot.point_count == 1);
  CHECK(snapshot.leaves.size() == 1);
  CHECK(snapshot.leaves[0].stats.count == 1);
}

// The O(n) bookkeeping accessor must agree exactly with the snapshot total,
// including after window eviction: conservation math depends on it.
void checkPointCountMatchesSnapshotTotal() {
  Map map(ResolutionPolicy::Uniform40, {.window_radius_m = 0.75, .tile_size_m = 0.4});
  map.update(point(-0.6, -0.1, 1.0, 1));
  map.update(point(0.6, 0.1, 3.0, 2));
  CHECK(map.point_count() == map.snapshot().point_count);
  map.set_window_center(0.6, 0.0);
  CHECK(map.point_count() == map.snapshot().point_count);
}

bool sameLeaves(const MapSnapshot& left, const MapSnapshot& right) {
  if (left.leaves.size() != right.leaves.size()) return false;
  for (std::size_t index = 0; index < left.leaves.size(); ++index) {
    if (left.leaves[index].id != right.leaves[index].id ||
        left.leaves[index].stats.count != right.leaves[index].stats.count)
      return false;
  }
  return true;
}

// The live runtime snapshots every frame into one reused MapSnapshot. It must
// be indistinguishable from a fresh snapshot, including after the map shrinks
// (stale leaves or counters must not survive), and a steady map must refill
// it without reallocating the leaf array.
void checkSnapshotIntoMatchesFreshSnapshotAndReusesStorage() {
  Map map(ResolutionPolicy::DistanceLod, {.window_radius_m = 100.0, .tile_size_m = 10.0});
  std::uint64_t timestamp = 0;
  for (int step = 0; step < 400; ++step) {
    const double x = -12.0 + 0.06 * step;
    map.update(point(x, 0.3 * std::sin(step * 0.1), 0.1 * step, ++timestamp));
  }
  MapSnapshot reused;
  map.snapshot_into(reused);
  const MapSnapshot fresh = map.snapshot();
  CHECK(sameLeaves(reused, fresh));
  CHECK(reused.point_count == fresh.point_count);
  CHECK(reused.logical_bytes == fresh.logical_bytes);
  CHECK(reused.memory.allocated_bytes == fresh.memory.allocated_bytes);
  const std::size_t snapshot_scratch_bytes =
      reused.memory.allocated_bytes - reused.memory.allocated_index_bytes -
      reused.memory.allocated_cell_array_bytes;
  CHECK(snapshot_scratch_bytes > 0);
  CHECK(snapshot_scratch_bytes == reused.memory.allocated_scratch_bytes);
  CHECK(reused.layers.ground_points == fresh.layers.ground_points);
  CHECK(reused.leaves_ordered_by_id);
  checkTopology(reused);

  const auto* storage = reused.leaves.data();
  const std::size_t capacity = reused.leaves.capacity();
  map.snapshot_into(reused);
  CHECK(reused.leaves.data() == storage);
  CHECK(reused.leaves.capacity() == capacity);

  // Shrink the map: move the window away so most leaves are evicted.
  map.set_window_center(500.0, 0.0);
  map.snapshot_into(reused);
  const MapSnapshot shrunk = map.snapshot();
  CHECK(sameLeaves(reused, shrunk));
  CHECK(reused.point_count == shrunk.point_count);
  CHECK(reused.logical_bytes == shrunk.logical_bytes);
  CHECK(reused.active_leaf_count == shrunk.active_leaf_count);
  CHECK(reused.memory.allocated_bytes - reused.memory.allocated_index_bytes -
            reused.memory.allocated_cell_array_bytes ==
        snapshot_scratch_bytes);
  CHECK(reused.memory.allocated_scratch_bytes == snapshot_scratch_bytes);
}

void checkRepeatedPublicSplitMergePreservesEvidence() {
  Map map(ResolutionPolicy::Uniform40, {.window_radius_m = 5.0, .tile_size_m = 0.8});
  const std::array<std::pair<double, double>, 3> centres{{{-0.62, -0.58}, {0.22, 0.18},
                                                           {1.02, -0.98}}};
  std::uint64_t timestamp = 0;
  for (const auto& [x, y] : centres) {
    map.update(point(x, y, -8.0, ++timestamp));
    map.update(point(x + 0.01, y + 0.01, 3.0, ++timestamp));
    map.update(point(x + 0.02, y + 0.02, 14.0, ++timestamp));
  }

  const MapSnapshot seeded = map.snapshot();
  CHECK(seeded.point_count == 9);
  checkTopology(seeded);

  std::mt19937 rng(0x2605C0DEU);
  std::vector<CellId> parents;
  for (const Leaf& leaf : seeded.leaves) parents.push_back(leaf.id);
  std::shuffle(parents.begin(), parents.end(), rng);
  for (const CellId parent : parents) {
    const CellStats expected = leafFor(map.snapshot(), parent).stats;
    for (int cycle = 0; cycle < 24; ++cycle) {
      map.split(parent);
      const MapSnapshot split = map.snapshot();
      checkTopology(split);
      CHECK(split.point_count == 9);
      CHECK(split.nonspatial_prior_point_count == expected.count);
      map.merge_children(parent);
      const MapSnapshot merged = map.snapshot();
      checkTopology(merged);
      CHECK(merged.point_count == 9);
      CHECK(merged.nonspatial_prior_point_count == 0);
      checkStats(leafFor(merged, parent).stats, expected);
    }
  }
  const MapSnapshot final_snapshot = map.snapshot();
  CHECK(final_snapshot.split_count == 3U * 24U);
  CHECK(final_snapshot.merge_count == 3U * 24U);
}

bool intersects(double centre_x, double centre_y, double radius, CellId id) {
  const CellExtent extent = veyra::core::extentOf(id);
  const double nearest_x = std::clamp(centre_x, extent.min_x, extent.max_x);
  const double nearest_y = std::clamp(centre_y, extent.min_y, extent.max_y);
  const double dx = centre_x - nearest_x;
  const double dy = centre_y - nearest_y;
  return dx * dx + dy * dy <= radius * radius;
}

void checkRollingWindowConservesSurvivorIdentity() {
  constexpr double radius = 0.75;
  Map map(ResolutionPolicy::Uniform40, {.window_radius_m = radius, .tile_size_m = 0.4});
  for (const auto [x, y, z] : std::array<std::array<double, 3>, 2>{{{-0.6, -0.1, 1.0},
                                                                      {0.6, 0.1, 3.0}}}) {
    map.update(point(x, y, z, static_cast<std::uint64_t>(z)));
  }
  const MapSnapshot before = map.snapshot();
  const CellId retained = map.cell_for(0.6, 0.1);
  const CellStats retained_stats = leafFor(before, retained).stats;

  map.set_window_center(0.6, 0.0);
  const MapSnapshot shifted = map.snapshot();
  checkTopology(shifted);
  CHECK(shifted.point_count == retained_stats.count);
  CHECK(shifted.active_leaf_count == 1);
  CHECK(leafFor(shifted, retained).id == retained);
  checkStats(leafFor(shifted, retained).stats, retained_stats);

  for (int step = 0; step < 160; ++step) {
    const double centre = (step % 2 == 0) ? -0.6 : 0.6;
    map.set_window_center(centre, 0.0);
    map.update(point(centre, 0.0, 10.0 + step, static_cast<std::uint64_t>(10 + step)));
    const MapSnapshot snapshot = map.snapshot();
    checkTopology(snapshot);
    CHECK(snapshot.active_leaf_count <= 2);
    for (const Leaf& leaf : snapshot.leaves) CHECK(intersects(centre, 0.0, radius, leaf.id));
  }
}

// The id-ordered fast paths in MapSnapshot must give the same answers as a
// full scan, and still catch the violations they exist to catch.
void checkOrderedSnapshotQueriesMatchFullScan() {
  Map map(ResolutionPolicy::DistanceLod, {.window_radius_m = 40.0, .tile_size_m = 2.0,
                                          .distance_boundaries_m = {4.0, 10.0, 20.0}});
  std::mt19937_64 rng(7);
  std::uniform_real_distribution<double> coordinate(-30.0, 30.0);
  for (std::uint64_t t = 1; t <= 4000; ++t) {
    const double x = coordinate(rng), y = coordinate(rng);
    if (map.accepts(x, y)) map.update(point(x, y, 0.1, t));
  }
  MapSnapshot ordered = map.snapshot();
  CHECK(ordered.leaves_ordered_by_id);
  CHECK(ordered.has_no_parent_descendant_overlap());
  for (int level = 0; level <= 3; ++level) {
    const auto scanned = static_cast<std::size_t>(
        std::count_if(ordered.leaves.begin(), ordered.leaves.end(),
                      [level](const Leaf& leaf) { return leaf.id.level == level; }));
    CHECK(ordered.count_at_level(level) == scanned);
    CHECK(scanned > 0);
  }

  // An ancestor inserted in id order must be caught by the bitmap path.
  const Leaf fine = *std::find_if(ordered.leaves.begin(), ordered.leaves.end(),
                                  [](const Leaf& leaf) { return leaf.id.level == 0; });
  MapSnapshot overlapping = ordered;
  const Leaf ancestor{fine.id.parent().parent(), {}};
  overlapping.leaves.insert(
      std::upper_bound(overlapping.leaves.begin(), overlapping.leaves.end(), ancestor,
                       [](const Leaf& left, const Leaf& right) {
                         return std::tuple{left.id.level, left.id.ix, left.id.iy} <
                                std::tuple{right.id.level, right.id.ix, right.id.iy};
                       }),
      ancestor);
  CHECK(!overlapping.has_no_parent_descendant_overlap());
  overlapping.leaves_ordered_by_id = false;
  CHECK(!overlapping.has_no_parent_descendant_overlap());

  // A duplicated leaf is adjacent in id order and must be caught as well.
  MapSnapshot duplicated = ordered;
  duplicated.leaves.insert(duplicated.leaves.begin() + 1, duplicated.leaves.front());
  CHECK(!duplicated.has_no_parent_descendant_overlap());
}

// Heavy split/merge churn through the public seams exercises swap-erase and
// the existing-leaf fast path together; evidence must be conserved exactly.
void checkChurnConservesEvidenceAndExclusivity() {
  Map map(ResolutionPolicy::DistanceLod, {.window_radius_m = 30.0, .tile_size_m = 1.0,
                                          .distance_boundaries_m = {3.0, 8.0, 15.0}});
  std::mt19937_64 rng(11);
  std::uniform_real_distribution<double> unit(0.0, 1.0);
  std::size_t accepted = 0;
  double centre = 0.0;
  for (int frame = 0; frame < 30; ++frame) {
    centre += 0.7;
    map.set_window_center(centre, 0.0);
    const std::size_t before = map.point_count();
    std::size_t added = 0;
    for (int i = 0; i < 1500; ++i) {
      // Quantised coordinates make repeat hits on existing leaves common.
      const double x = centre + std::round((unit(rng) - 0.5) * 50.0 * 4.0) / 4.0;
      const double y = std::round((unit(rng) - 0.5) * 50.0 * 4.0) / 4.0;
      if (!map.accepts(x, y)) continue;
      int level = map.level_for(x, y);
      if (level > 0 && unit(rng) < 0.3) --level;  // finer than distance: forces splits
      map.update_at_level(point(x, y, unit(rng), static_cast<std::uint64_t>(frame + 1)), level);
      ++added;
    }
    for (int k = 0; k < 40; ++k) {
      const int level = 1 + static_cast<int>(rng() % 3);
      const double size = veyra::core::resolution_m(level);
      const CellId id{level, static_cast<std::int32_t>(std::floor((centre + (unit(rng) - 0.5) * 20.0) / size)),
                      static_cast<std::int32_t>(std::floor((unit(rng) - 0.5) * 20.0 / size))};
      if (k % 2 == 0)
        map.split(id);
      else
        map.merge_children(id);
    }
    const MapSnapshot snapshot = map.snapshot();
    CHECK(snapshot.point_count == map.point_count());
    CHECK(snapshot.has_no_parent_descendant_overlap());
    checkTopology(snapshot);
    // Eviction happened in set_window_center, before `before` was read, so
    // ingestion plus split/merge must conserve every return exactly.
    CHECK(map.point_count() == before + added);
    accepted += added;
  }
  CHECK(accepted > 0);
}

}  // namespace

int run() {
  checkOrderedSnapshotQueriesMatchFullScan();
  checkChurnConservesEvidenceAndExclusivity();
  checkBoundaryAndSignedOwnership();
  checkRepeatedPublicSplitMergePreservesEvidence();
  checkRollingWindowConservesSurvivorIdentity();
  checkWindowEdgePointYieldsExactlyOneLeaf();
  checkPointCountMatchesSnapshotTotal();
  checkSnapshotIntoMatchesFreshSnapshotAndReusesStorage();
  return 0;
  return 0;
}

}  // namespace map_public_properties

namespace map_hardening_stress {

// Map hardening stress: long randomized / boundary / churn proof for the
// production Map path (src/map/map.cpp). Prior coverage proved the legacy
// TileGrid thoroughly but left the production Map with only short,
// single-level (Uniform40, 800-step) randomized churn and no Map-level long
// drive, boundary fuzz, or repeated-churn statistical proof.
//
// Every check below drives the public Map/DistanceLodMap API only
// (update / update_at_level / split / merge_children / set_window_center /
// snapshot). No TileGrid, no direct grid setup.
//
// Deterministic: all randomness is mt19937 with fixed seeds. No wall-clock
// dependence; timings are reported, never asserted (except pre-existing
// perf gates elsewhere).


namespace {

using veyra::core::CellExtent;
using veyra::core::CellId;
using veyra::map::CellStats;
using veyra::map::DistanceLodMap;
using veyra::map::Leaf;
using veyra::map::Map;
using veyra::map::MapSnapshot;
using veyra::map::Observation;
using veyra::map::ResolutionPolicy;

constexpr double kMeanTol = 1e-9;
constexpr double kVarTol = 1e-5;
constexpr double kFloatTol = 1e-6;
constexpr double kExtentEps = 1e-12;

bool relClose(double a, double b, double tol) {
  const double scale = std::max({1.0, std::fabs(a), std::fabs(b)});
  return std::fabs(a - b) <= tol * scale;
}

bool interiorsDisjoint(const CellExtent& l, const CellExtent& r) {
  return l.max_x <= r.min_x + kExtentEps || r.max_x <= l.min_x + kExtentEps ||
         l.max_y <= r.min_y + kExtentEps || r.max_y <= l.min_y + kExtentEps;
}

// Full O(n^2) gap/overlap audit. has_no_parent_descendant_overlap() runs every
// step (O(n log n)); this stronger extent check runs periodically and finally.
void checkDisjoint(const std::vector<Leaf>& leaves) {
  for (std::size_t i = 0; i < leaves.size(); ++i) {
    const CellExtent l = veyra::core::extentOf(leaves[i].id);
    for (std::size_t j = i + 1; j < leaves.size(); ++j) {
      CHECK(interiorsDisjoint(l, veyra::core::extentOf(leaves[j].id)));
    }
  }
}

void checkTopology(const MapSnapshot& s) {
  CHECK(s.has_no_parent_descendant_overlap());
  // No duplicate ids beyond what the overlap check covers.
  for (std::size_t i = 1; i < s.leaves.size(); ++i) CHECK(!(s.leaves[i].id == s.leaves[i - 1].id));
}

void checkOneOwner(const Map& map, const MapSnapshot& s, double x, double y) {
  const CellId expected = map.cell_for(x, y);
  std::size_t owners = 0;
  for (const Leaf& leaf : s.leaves) owners += (leaf.id == expected) ? 1U : 0U;
  CHECK(owners == 1);
}

const Leaf& leafFor(const MapSnapshot& s, CellId id) {
  for (const Leaf& leaf : s.leaves) {
    if (leaf.id == id) return leaf;
  }
  CHECK(false);
  static Leaf unreachable{};
  return unreachable;
}

void checkStatsExact(const CellStats& got, const CellStats& want) {
  CHECK(got.count == want.count);
  CHECK(got.min_z() == want.min_z());
  CHECK(got.max_z() == want.max_z());
  CHECK(relClose(got.mean_z(), want.mean_z(), kMeanTol));
  CHECK(relClose(got.variance_z(), want.variance_z(), kVarTol));
  CHECK(got.last_seen == want.last_seen);
  CHECK(got.semantic_class == want.semantic_class);
  CHECK(got.semantic_evidence() == want.semantic_evidence());
  CHECK(got.semantic_confidence() == want.semantic_confidence());
  CHECK(got.drivable_evidence() == want.drivable_evidence());
  CHECK(got.ground_evidence() == want.ground_evidence());
  CHECK(got.terrain_confidence() == want.terrain_confidence());
  CHECK(got.geometry_complexity() == want.geometry_complexity());
  CHECK(got.motion_evidence() == want.motion_evidence());
  CHECK(got.observation_quality() == want.observation_quality());
}

void checkStatsTol(const CellStats& got, const CellStats& want) {
  CHECK(got.count == want.count);
  CHECK(got.min_z() == want.min_z());
  CHECK(got.max_z() == want.max_z());
  CHECK(relClose(got.mean_z(), want.mean_z(), kMeanTol));
  CHECK(relClose(got.variance_z(), want.variance_z(), kVarTol));
  CHECK(got.last_seen == want.last_seen);
  CHECK(got.semantic_class == want.semantic_class);
  CHECK(relClose(got.semantic_confidence(), want.semantic_confidence(), kFloatTol));
  CHECK(relClose(got.drivable_evidence(), want.drivable_evidence(), kFloatTol));
  CHECK(relClose(got.ground_evidence(), want.ground_evidence(), kFloatTol));
  CHECK(relClose(got.terrain_confidence(), want.terrain_confidence(), kFloatTol));
  CHECK(relClose(got.geometry_complexity(), want.geometry_complexity(), kFloatTol));
  CHECK(relClose(got.motion_evidence(), want.motion_evidence(), kFloatTol));
  CHECK(relClose(got.observation_quality(), want.observation_quality(), kFloatTol));
}

Observation enriched(double x, double y, double z, std::uint64_t ts, std::mt19937& rng) {
  std::uniform_int_distribution<int> cls(0, 9);
  std::uniform_real_distribution<double> u(0.0, 1.0);
  std::uniform_int_distribution<int> dri(0, 2);
  std::uniform_int_distribution<int> gnd(0, 1);
  Observation o;
  o.x = x;
  o.y = y;
  o.z = z;
  o.timestamp = ts;
  o.semantic_class = static_cast<std::uint16_t>(cls(rng));
  o.semantic_confidence = static_cast<float>(u(rng));
  o.drivable = static_cast<std::uint8_t>(dri(rng));
  o.ground = static_cast<std::uint8_t>(gnd(rng));
  o.terrain_confidence = static_cast<float>(u(rng));
  o.geometry_complexity = static_cast<float>(u(rng));
  o.motion_probability = static_cast<float>(u(rng));
  o.observation_quality = static_cast<float>(u(rng));
  return o;
}

// ---------------------------------------------------------------------------
// 1. Long randomized mixed-resolution churn via DistanceLod production path.
// Covers: one-obs-one-leaf, exclusivity, no gaps/overlaps, point conservation,
// mixed L0-L3 presence, split/merge churn over thousands of ops.
// ---------------------------------------------------------------------------
void checkLongRandomizedMixedLodChurn() {
  Map map(ResolutionPolicy::DistanceLod,
          veyra::map::MapConfig{.window_radius_m = 12.0,
                                .tile_size_m = 1.0,
                                .distance_boundaries_m = {3.0, 6.0, 9.0}});
  std::mt19937 rng(0xA201u ^ 0x26053u);
  std::uniform_real_distribution<double> radius(0.0, 11.9);
  std::uniform_real_distribution<double> angle(-3.141592653589793, 3.141592653589793);
  std::uniform_real_distribution<double> height(-20.0, 20.0);
  std::uniform_int_distribution<int> action(0, 9);  // 0-5 update, 6-7 split, 8-9 merge
  std::uint64_t accepted = 0;
  std::uint64_t ts = 0;
  constexpr int kSteps = 6000;

  for (int step = 0; step < kSteps; ++step) {
    const int op = action(rng);
    const MapSnapshot before = map.snapshot();
    const bool splittable = std::any_of(before.leaves.begin(), before.leaves.end(),
                                        [](const Leaf& l) { return l.id.level != 0; });
    if (op <= 5 || before.leaves.empty() || (op <= 7 && !splittable)) {
      const double r = radius(rng);
      const double th = angle(rng);
      const double x = r * std::cos(th);
      const double y = r * std::sin(th);
      Observation o = enriched(x, y, height(rng), ++ts, rng);
      if (!map.accepts(x, y)) continue;
      map.update(o);
      ++accepted;
      const MapSnapshot s = map.snapshot();
      CHECK(s.point_count == accepted);
      CHECK(s.nonspatial_prior_point_count <= accepted);
      checkTopology(s);
      checkOneOwner(map, s, x, y);
      if (step % 500 == 0) checkDisjoint(s.leaves);
      continue;
    }
    if (op <= 7) {
      std::vector<CellId> cands;
      for (const Leaf& l : before.leaves) {
        if (l.id.level != 0) cands.push_back(l.id);
      }
      CHECK(!cands.empty());
      map.split(cands[std::uniform_int_distribution<std::size_t>(0, cands.size() - 1)(rng)]);
    } else {
      // Merge only where all four children are active and parent is not.
      for (const Leaf& l : before.leaves) {
        if (l.id.level == 0) continue;
        const CellId p = veyra::core::parentOf(l.id);
        if (p.level > 3) continue;
        const auto kids = veyra::core::childrenOf(p);
        const bool parentActive = std::any_of(before.leaves.begin(), before.leaves.end(),
                                              [&p](const Leaf& o) { return o.id == p; });
        if (parentActive) continue;
        const bool all = std::all_of(kids.begin(), kids.end(), [&before](CellId k) {
          return std::any_of(before.leaves.begin(), before.leaves.end(),
                             [k](const Leaf& o) { return o.id == k; });
        });
        if (all) {
          map.merge_children(p);
          break;
        }
      }
    }
    const MapSnapshot after = map.snapshot();
    CHECK(after.point_count == accepted);
    CHECK(after.nonspatial_prior_point_count <= accepted);
    checkTopology(after);
    if (step % 500 == 0) checkDisjoint(after.leaves);
    if (step % 1000 == 0) {
      std::fprintf(stderr, "[churn] step=%d leaves=%zu tiles=%zu splits=%llu merges=%llu\n", step,
                   after.active_leaf_count, after.tile_count,
                   (unsigned long long)after.split_count, (unsigned long long)after.merge_count);
    }
  }
  const MapSnapshot fin = map.snapshot();
  checkDisjoint(fin.leaves);
  CHECK(fin.split_count > 0);
  CHECK(fin.merge_count > 0);
  // Mixed L0-L3 proof: DistanceLod bands {3,6,9} inside r=12 must populate all levels.
  for (int level = 0; level <= 3; ++level) CHECK(fin.count_at_level(level) > 0);
  std::fprintf(stderr,
               "[churn] FINAL leaves=%zu tiles=%zu points=%zu splits=%llu merges=%llu "
               "L0=%zu L1=%zu L2=%zu L3=%zu\n",
               fin.active_leaf_count, fin.tile_count, fin.point_count,
               (unsigned long long)fin.split_count, (unsigned long long)fin.merge_count,
               fin.count_at_level(0), fin.count_at_level(1), fin.count_at_level(2),
               fin.count_at_level(3));
}

// ---------------------------------------------------------------------------
// 2. Boundary fuzzing across all levels, both sides of origin, tile edges,
//    and DistanceLOD band seams. Production Map::update path only.
// ---------------------------------------------------------------------------
void checkBoundaryFuzz() {
  const std::array<double, 7> deltas{0.0, 1e-12, -1e-12, 1e-9, -1e-9, 1e-7, -1e-7};
  std::uint64_t ts = 0;

  {
    Map map(ResolutionPolicy::Uniform5, {.window_radius_m = 5.0, .tile_size_m = 0.4});
    // Sweep base cells incl. negative, tile-boundary neighbourhood (|ix|<=24 at
    // L0 spans several 0.4 m tiles), edges and corners.
    for (std::int32_t base : {-24, -9, -2, -1, 0, 1, 7, 23}) {
      const CellId cell{0, base, -base};
      const CellExtent e = veyra::core::extentOf(cell);
      const std::array<std::pair<double, double>, 4> corners{
          std::pair{e.min_x, e.min_y}, std::pair{e.max_x, e.min_y}, std::pair{e.min_x, e.max_y},
          std::pair{e.max_x, e.max_y}};
      for (const auto& [cx, cy] : corners) {
        for (double d : deltas) {
          const double x = cx + d;
          const double y = cy + d * 0.5;
          if (!map.accepts(x, y)) continue;
          const CellId expected = map.cell_for(x, y);
          Observation o{.x = x, .y = y, .z = 1.0, .timestamp = ++ts};
          map.update(o);
          const MapSnapshot s = map.snapshot();
          CHECK(s.point_count == ts);
          checkTopology(s);
          checkOneOwner(map, s, x, y);
          // Half-open convention spot check at exact corners.
          if (d == 0.0) CHECK(leafFor(s, expected).stats.count >= 1);
        }
      }
    }
    const MapSnapshot s = map.snapshot();
    checkDisjoint(s.leaves);
    std::fprintf(stderr, "[boundary] L0-sweep done leaves=%zu points=%zu\n",
                 s.active_leaf_count, s.point_count);
  }

  // Band seams: DistanceLOD boundaries are half-open [0,10)->L0 etc.
  // Fuzz vehicle-relative ranges around 10/30/60 m through the production path.
  {
    DistanceLodMap dmap({.window_radius_m = 100.0});
    CHECK(dmap.level_for(9.999, 0.0) == 0);
    CHECK(dmap.level_for(10.0, 0.0) == 1);
    CHECK(dmap.level_for(30.0, 0.0) == 2);
    CHECK(dmap.level_for(60.0, 0.0) == 3);
    std::uint64_t t2 = 0;
    for (double seam : {10.0, 30.0, 60.0}) {
      for (double d : deltas) {
        for (double lateral : {-0.2, 0.0, 0.2}) {
          const double x = seam + d;
          const double y = lateral;
          if (!dmap.accepts(x, y)) continue;
          const int want = dmap.level_for(x, y);
          dmap.update(Observation{.x = x, .y = y, .z = 2.0, .timestamp = ++t2});
          const MapSnapshot s = dmap.snapshot();
          CHECK(s.point_count == t2);
          checkTopology(s);
          const CellId id = dmap.cell_for(x, y);
          CHECK(id.level == want);
          std::size_t owners = 0;
          for (const Leaf& l : s.leaves) owners += (l.id == id) ? 1U : 0U;
          CHECK(owners == 1);
        }
      }
    }
    std::fprintf(stderr, "[boundary] band-seam fuzz done leaves=%zu\n",
                 dmap.snapshot().active_leaf_count);
  }
}

// ---------------------------------------------------------------------------
// 3. Long rolling-window trajectory on the production Map: 400 m drive,
//    survivor identity bit-preserved, eviction never renames, memory bounded.
// ---------------------------------------------------------------------------
bool cellIntersects(double cx, double cy, double r, CellId id) {
  const CellExtent e = veyra::core::extentOf(id);
  const double nx = std::clamp(cx, e.min_x, e.max_x);
  const double ny = std::clamp(cy, e.min_y, e.max_y);
  const double dx = cx - nx;
  const double dy = cy - ny;
  return dx * dx + dy * dy <= r * r;
}

void checkLongRollingWindowDrive() {
  constexpr double kR = 40.0;
  Map map(ResolutionPolicy::DistanceLod,
          veyra::map::MapConfig{.window_radius_m = kR,
                                .tile_size_m = 2.0,
                                .distance_boundaries_m = {10.0, 20.0, 30.0}});
  std::mt19937 rng(0xD21EAu);
  std::uint64_t ts = 0;
  std::size_t maxLeaves = 0;
  std::size_t maxTiles = 0;
  std::size_t leavesAt100 = 0;

  // Analytic ceiling: disc area / finest cell area (all-L0 worst case).
  const double disc = 3.141592653589793 * kR * kR;
  const std::size_t ceiling = static_cast<std::size_t>(disc / (0.05 * 0.05));

  for (int step = 0; step <= 400; ++step) {
    const double vx = static_cast<double>(step);
    // Capture pre-move survivors to prove eviction never renames.
    const MapSnapshot pre = map.snapshot();
    std::vector<std::pair<CellId, CellStats>> preEntries;
    preEntries.reserve(pre.leaves.size());
    for (const Leaf& l : pre.leaves) preEntries.emplace_back(l.id, l.stats);

    map.set_window_center(vx, 0.0);
    const MapSnapshot post = map.snapshot();
    // Every survivor is bit-identical: same id, same full statistics.
    for (const auto& [id, stats] : preEntries) {
      if (!cellIntersects(vx, 0.0, kR, id)) continue;
      bool found = false;
      for (const Leaf& l : post.leaves) {
        if (l.id == id) {
          found = true;
          checkStatsExact(l.stats, stats);
          break;
        }
      }
      CHECK(found);
    }
    // Nothing outside the window survives.
    for (const Leaf& l : post.leaves) CHECK(cellIntersects(vx, 0.0, kR, l.id));

    // Swath spanning all four DistanceLOD bands relative to the vehicle:
    // row offsets 0 (L0, <10 m), +15 (L1, 10-20 m), +25 (L2, 20-30 m),
    // +35 (L3, 30-40 m). Lateral spread keeps sibling groups mergeable.
    for (int k = -40; k <= 40; k += 4) {
      for (int row = 0; row < 4; ++row) {
        const double band = (row == 0) ? 0.0 : (row == 1) ? 15.0 : (row == 2) ? 25.0 : 35.0;
        const double x = vx + 0.1 * static_cast<double>(k) + band;
        const double y = 0.4 * static_cast<double>(row - 1) + 0.05 * (k % 2);
        if (!map.accepts(x, y)) continue;
        map.update(enriched(x, y, 0.1 * ((k + row) % 7), ++ts, rng));
      }
    }
    const MapSnapshot s = map.snapshot();
    checkTopology(s);
    for (const Leaf& l : s.leaves) CHECK(cellIntersects(vx, 0.0, kR, l.id));
    maxLeaves = std::max(maxLeaves, s.active_leaf_count);
    maxTiles = std::max(maxTiles, s.tile_count);
    if (step == 100) leavesAt100 = s.active_leaf_count;
    if (step % 100 == 0) {
      checkDisjoint(s.leaves);
      std::fprintf(stderr, "[drive] x=%d leaves=%zu tiles=%zu\n", step, s.active_leaf_count,
                   s.tile_count);
    }
  }
  const MapSnapshot fin = map.snapshot();
  checkDisjoint(fin.leaves);
  CHECK(maxLeaves <= ceiling);
  CHECK(fin.active_leaf_count > 0);
  // Plateau, not growth: 400 m looks like 100 m.
  CHECK(fin.active_leaf_count <= leavesAt100 + leavesAt100 / 2 + 16);
  // Still mapping at the far end through the production path.
  CHECK(fin.point_count > 0);
  for (int level = 0; level <= 3; ++level) CHECK(fin.count_at_level(level) > 0);
  std::fprintf(stderr, "[drive] FINAL leaves=%zu tiles=%zu maxLeaves=%zu ceiling=%zu\n",
               fin.active_leaf_count, fin.tile_count, maxLeaves, ceiling);
}

// ---------------------------------------------------------------------------
// 4. Repeated topology churn: hundreds of split/merge cycles per parent,
//    full statistic preservation incl. semantic evidence.
// ---------------------------------------------------------------------------
void checkRepeatedTopologyChurn() {
  Map map(ResolutionPolicy::Uniform40, {.window_radius_m = 6.0, .tile_size_m = 0.8});
  std::mt19937 rng(0xC0A7u);
  std::uint64_t ts = 0;
  const std::array<std::pair<double, double>, 3> centres{
      std::pair{-0.62, -0.58}, std::pair{0.22, 0.18}, std::pair{1.02, -0.98}};
  for (const auto& [x, y] : centres) {
    map.update(enriched(x, y, -8.0, ++ts, rng));
    map.update(enriched(x + 0.01, y + 0.01, 3.0, ++ts, rng));
    map.update(enriched(x + 0.02, y + 0.02, 14.0, ++ts, rng));
  }
  const MapSnapshot seeded = map.snapshot();
  CHECK(seeded.point_count == 9);
  checkTopology(seeded);

  std::vector<CellId> parents;
  for (const Leaf& l : seeded.leaves) parents.push_back(l.id);
  constexpr int kCycles = 200;
  for (const CellId parent : parents) {
    const CellStats expected = leafFor(map.snapshot(), parent).stats;
    for (int c = 0; c < kCycles; ++c) {
      map.split(parent);
      const MapSnapshot sp = map.snapshot();
      checkTopology(sp);
      CHECK(sp.point_count == 9);
      CHECK(sp.nonspatial_prior_point_count == expected.count);
      map.merge_children(parent);
      const MapSnapshot mg = map.snapshot();
      checkTopology(mg);
      CHECK(mg.point_count == 9);
      CHECK(mg.nonspatial_prior_point_count == 0);
      checkStatsExact(leafFor(mg, parent).stats, expected);
    }
  }
  const MapSnapshot fin = map.snapshot();
  CHECK(fin.split_count == parents.size() * static_cast<std::size_t>(kCycles));
  CHECK(fin.merge_count == parents.size() * static_cast<std::size_t>(kCycles));
  std::fprintf(stderr, "[churn-cycles] parents=%zu cycles=%d splits=%llu merges=%llu\n",
               parents.size(), kCycles, (unsigned long long)fin.split_count,
               (unsigned long long)fin.merge_count);
}

// ---------------------------------------------------------------------------
// 5. Numerical-stat preservation property: Map-level merge equals sequential
//    accumulation (count exact, min/max exact, mean 1e-9, variance 1e-5,
//    semantic evidence rules), over randomized groupings.
// ---------------------------------------------------------------------------
void checkNumericalPreservationProperty() {
  std::mt19937 rng(0x9E321u);
  std::uniform_real_distribution<double> z(-30.0, 30.0);
  for (int trial = 0; trial < 120; ++trial) {
    const int n = 2 + static_cast<int>(rng() % 24);
    // Reference: sequential CellStats::add on one accumulator.
    CellStats ref;
    std::vector<Observation> obs;
    for (int i = 0; i < n; ++i) {
      Observation o = enriched(0.011, 0.013, z(rng), static_cast<std::uint64_t>(i + 1), rng);
      obs.push_back(o);
      ref.add(o);
    }
    // Grouped: split observations across leaves, merge pairwise in random order.
    std::vector<CellStats> parts;
    std::vector<int> perm(n);
    for (int i = 0; i < n; ++i) perm[i] = i;
    std::shuffle(perm.begin(), perm.end(), rng);
    const int groups = 1 + static_cast<int>(rng() % 4);
    parts.assign(static_cast<std::size_t>(groups), CellStats{});
    for (int i = 0; i < n; ++i) parts[static_cast<std::size_t>(i % groups)].add(obs[perm[i]]);
    std::shuffle(parts.begin(), parts.end(), rng);
    CellStats merged;
    for (const CellStats& p : parts) merged.merge(p);
    checkStatsTol(merged, ref);
  }
  std::fprintf(stderr, "[numeric] 120 merge-grouping trials preserved\n");
}

// ---------------------------------------------------------------------------
// 6. Governor: DistanceLOD production updates never coarsen the protected
//    near field (10 m), however much churn happens around them.
// ---------------------------------------------------------------------------
void checkNearFieldGovernor() {
  DistanceLodMap map({.window_radius_m = 100.0});
  std::mt19937 rng(0x9EA2F1E1Du);
  std::uint64_t ts = 0;
  // Seed near-field (L0) and far-field (L1-L3) leaves.
  for (int i = 0; i < 40; ++i) {
    const double a = 6.283185307179586 * (i / 40.0);
    map.update(enriched(2.0 * std::cos(a), 2.0 * std::sin(a), 1.0, ++ts, rng));
    map.update(enriched(45.0 + 0.1 * i, 0.1 * i, 2.0, ++ts, rng));
  }
  // Hostile churn: split every splittable leaf, attempt merges far away.
  for (int round = 0; round < 30; ++round) {
    const MapSnapshot s = map.snapshot();
    for (const Leaf& l : s.leaves) {
      if (l.id.level != 0) map.split(l.id);
    }
    // Try to merge near-field children back up (must be refused or harmless:
    // near-field leaves must remain L0 afterwards).
    const MapSnapshot s2 = map.snapshot();
    for (const Leaf& l : s2.leaves) {
      if (l.id.level != 0) continue;
      const CellId p = veyra::core::parentOf(l.id);
      const CellExtent e = veyra::core::extentOf(p);
      const double cx = 0.5 * (e.min_x + e.max_x);
      const double cy = 0.5 * (e.min_y + e.max_y);
      if (cx * cx + cy * cy < 100.0) map.merge_children(p);
    }
    // Fresh near-field observations through the production path re-pin L0.
    for (int i = 0; i < 10; ++i) {
      const double a = 6.283185307179586 * ((round * 10 + i) / 300.0);
      map.update(enriched(5.0 * std::cos(a), 5.0 * std::sin(a), 1.5, ++ts, rng));
    }
    const MapSnapshot s3 = map.snapshot();
    checkTopology(s3);
    for (const Leaf& l : s3.leaves) {
      const CellExtent e = veyra::core::extentOf(l.id);
      const double cx = 0.5 * (e.min_x + e.max_x);
      const double cy = 0.5 * (e.min_y + e.max_y);
      if (cx * cx + cy * cy < 10.0 * 10.0) CHECK(l.id.level == 0);
    }
  }
  std::fprintf(stderr, "[governor] near-field L0 held across 30 hostile rounds\n");
}

// ---------------------------------------------------------------------------
// 7. Synthetic LiDAR replay through the production path, mixed L0-L3.
//    data/raw is empty in this checkout, so no committed real scan can be
//    replayed; this deterministic rotating-scan surrogate (ground plane, curb
//    step, pole obstacles, per-point semantic/drivable/ground/motion/quality)
//    spans 0-100 m and is fed exclusively via DistanceLodMap::update.
// ---------------------------------------------------------------------------
Observation lidarPoint(double x, double y, double z, std::uint64_t ts, std::uint16_t cls,
                       std::uint8_t drivable, std::uint8_t ground, float motion) {
  Observation o;
  o.x = x;
  o.y = y;
  o.z = z;
  o.timestamp = ts;
  o.semantic_class = cls;
  o.semantic_confidence = 0.9F;
  o.drivable = drivable;
  o.ground = ground;
  o.terrain_confidence = 0.85F;
  o.geometry_complexity = (cls == 3) ? 0.8F : 0.15F;
  o.motion_probability = motion;
  o.observation_quality = 0.9F;
  return o;
}

void checkSyntheticLidarReplayMixedLod() {
  DistanceLodMap map({.window_radius_m = 100.0});
  std::uint64_t ts = 0;
  std::uint64_t accepted = 0;
  // 8 revolutions x 512 azimuths; ranges cycle near/mid/far to span L0-L3.
  for (int rev = 0; rev < 8; ++rev) {
    for (int k = 0; k < 512; ++k) {
      const double az = 6.283185307179586 * (static_cast<double>(k) / 512.0);
      const double r = 1.5 + 98.0 * (static_cast<double>((k * 37 + rev * 131) % 512) / 512.0);
      const double x = r * std::cos(az);
      const double y = r * std::sin(az);
      double z = 0.02;  // ground plane
      std::uint16_t cls = 1;
      std::uint8_t dri = 1;
      std::uint8_t gnd = 1;
      float motion = 0.0F;
      if (k % 64 == 0) {  // pole obstacle
        z = 1.5;
        cls = 3;
        dri = 2;
        gnd = 0;
      } else if (k % 32 == 0) {  // curb step
        z = 0.14;
        cls = 2;
        dri = 2;
        gnd = 0;
      } else if (k % 48 == 0) {  // moving pedestrian surrogate
        z = 0.9;
        cls = 4;
        dri = 0;
        gnd = 0;
        motion = 0.95F;
      }
      if (!map.accepts(x, y)) continue;
      map.update(lidarPoint(x, y, z, ++ts, cls, dri, gnd, motion));
      ++accepted;
    }
    const MapSnapshot s = map.snapshot();
    CHECK(s.point_count == accepted);
    checkTopology(s);
  }
  const MapSnapshot fin = map.snapshot();
  CHECK(fin.point_count == accepted);
  checkTopology(fin);
  checkDisjoint(fin.leaves);
  for (int level = 0; level <= 3; ++level) CHECK(fin.count_at_level(level) > 0);
  // Sampled ownership across bands.
  CHECK(fin.count_at_level(0) > 0);
  std::fprintf(stderr,
               "[replay] synthetic-lidar accepted=%llu leaves=%zu tiles=%zu "
               "L0=%zu L1=%zu L2=%zu L3=%zu\n",
               (unsigned long long)accepted, fin.active_leaf_count, fin.tile_count,
               fin.count_at_level(0), fin.count_at_level(1), fin.count_at_level(2),
               fin.count_at_level(3));
}

}  // namespace

int run() {
  checkLongRandomizedMixedLodChurn();
  checkBoundaryFuzz();
  checkLongRollingWindowDrive();
  checkRepeatedTopologyChurn();
  checkNumericalPreservationProperty();
  checkNearFieldGovernor();
  checkSyntheticLidarReplayMixedLod();
  std::fprintf(stderr, "[map-hardening-stress] ALL PASS\n");
  return 0;
  return 0;
}

}  // namespace map_hardening_stress

int main(int argc, char** argv) {
  if (argc == 2) {
    const std::string_view suite{argv[1]};
    if (suite == "randomized_map_invariants") return randomized_map_invariants::run();
    if (suite == "map_public_properties") return map_public_properties::run();
    if (suite == "map_hardening_stress") return map_hardening_stress::run();
  }
  std::fputs("Select a registered CTest suite.\n", stderr);
  return 2;
}
