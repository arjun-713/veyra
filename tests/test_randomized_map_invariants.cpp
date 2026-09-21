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
  for (const auto [x, y] : std::array<std::pair<double, double>, 6>{
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

int main() {
  checkRandomizedMixedResolutionChurn();
  return 0;
}
