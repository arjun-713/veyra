#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <random>
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
  CHECK(got.min_z == expected.min_z);
  CHECK(got.max_z == expected.max_z);
  CHECK(close(got.mean_z, expected.mean_z));
  CHECK(close(got.m2_z, expected.m2_z));
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

}  // namespace

int main() {
  checkBoundaryAndSignedOwnership();
  checkRepeatedPublicSplitMergePreservesEvidence();
  checkRollingWindowConservesSurvivorIdentity();
  return 0;
}
