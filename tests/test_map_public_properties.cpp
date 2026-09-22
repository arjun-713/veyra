#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <random>
#include <tuple>
#include <vector>

#include "check.hpp"
#include "veyra/core/types.hpp"
#include "veyra/map/map.hpp"

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
    for (const auto [x, y] : std::array<std::pair<double, double>, 2>{
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

void checkRepeatedPublicSplitMergePreservesEvidence() {
  Map map(ResolutionPolicy::Uniform40, {.window_radius_m = 5.0, .tile_size_m = 0.8});
  const std::array<std::pair<double, double>, 3> centres{{{-0.62, -0.58}, {0.22, 0.18},
                                                           {1.02, -0.98}}};
  std::uint64_t timestamp = 0;
  for (const auto [x, y] : centres) {
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

int main() {
  checkOrderedSnapshotQueriesMatchFullScan();
  checkChurnConservesEvidenceAndExclusivity();
  checkBoundaryAndSignedOwnership();
  checkRepeatedPublicSplitMergePreservesEvidence();
  checkRollingWindowConservesSurvivorIdentity();
  return 0;
}
