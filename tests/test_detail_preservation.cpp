#include <array>
#include <cmath>
#include <numbers>
#include <stdexcept>

#include "check.hpp"
#include "veyra/map/map.hpp"

using veyra::core::CellId;
using veyra::map::Map;
using veyra::map::Observation;
using veyra::map::ResolutionPolicy;

namespace {
void spatial_statistics_survive_split_merge_cycles() {
  Map map{ResolutionPolicy::Uniform40};
  map.configure_detail_preservation(1);
  const std::array regions{CellId{3, -2, -1}};
  map.select_detail_regions(regions);
  for (int y = 0; y < 8; ++y) {
    for (int x = 0; x < 8; ++x) {
      Observation point;
      point.x = -0.8 + (x + 0.5) * 0.05;
      point.y = -0.4 + (y + 0.5) * 0.05;
      point.z = x + y;
      point.timestamp = 10;
      point.semantic_class = x < 4 ? 6 : 18;
      point.semantic_confidence = 1.0F;
      point.ground = y < 4 ? 1 : 0;
      point.height_above_ground = y < 4 ? 0.0F : (x < 4 ? 1.0F : 3.0F);
      map.update(point);
    }
  }
  const auto before = map.snapshot();
  CHECK(before.point_count == 64);
  CHECK(before.memory.detail_sketch_logical_bytes > 64 * sizeof(veyra::map::CellStats));
  CHECK(before.logical_bytes == before.memory.logical_payload_bytes +
        before.memory.retained_prior_payload_bytes + before.memory.detail_sketch_logical_bytes);
  for (int cycle = 0; cycle < 3; ++cycle) {
    map.split(regions[0]);
    const auto split = map.snapshot();
    CHECK(split.point_count == 64);
    CHECK(split.nonspatial_prior_point_count == 0);
    CHECK(split.has_no_parent_descendant_overlap());
    CHECK(split.leaves.size() == 4);
    for (const auto& leaf : split.leaves) {
      const int x = leaf.id.ix + 4;
      const int y = leaf.id.iy + 2;
      CHECK(leaf.stats.count == 16);
      CHECK(std::abs(leaf.stats.mean_z() - (3.0 + 4 * x + 4 * y)) < 1e-5);
      CHECK(leaf.stats.semantic_class == (x == 0 ? 6 : 18));
      CHECK(leaf.stats.ground.count == (y == 0 ? 16 : 0));
      CHECK(leaf.stats.overhead.count == (y == 1 && x == 1 ? 16 : 0));
    }
    map.merge_children(regions[0]);
    const auto merged = map.snapshot();
    CHECK(merged.point_count == 64);
    CHECK(std::abs(merged.leaves[0].stats.mean_z() - before.leaves[0].stats.mean_z()) < 1e-5);
    CHECK(std::abs(merged.leaves[0].stats.variance_z() - before.leaves[0].stats.variance_z()) < 1e-5);
  }
  // Nested splits use the same measured bins, not a replicated parent prior.
  map.update_at_level({.x = -0.775, .y = -0.375, .z = 0.0}, 0);
  const auto fine = map.snapshot();
  CHECK(fine.point_count == 65);
  CHECK(fine.nonspatial_prior_point_count == 0);
  CHECK(fine.has_no_parent_descendant_overlap());
  CHECK(fine.detail_rehydrated_splits == 6);
}

void incomplete_or_evicted_history_is_never_invented() {
  Map map{ResolutionPolicy::Uniform40, {.tile_size_m = 0.15}};
  map.update_at_level({.x = 40.29, .y = 0.29, .z = 1.0}, 0);
  map.configure_detail_preservation(1);
  const std::array regions{CellId{3, 100, 0}};
  map.select_detail_regions(regions); // admission after history: incomplete
  map.update({.x = 40.29, .y = 0.29, .z = 9.0});
  map.split(regions[0]);
  CHECK(map.snapshot().nonspatial_prior_point_count == 2);
  CHECK(map.point_count() == 2);
  CHECK(map.snapshot().detail_rehydrated_splits == 0);

  Map eviction{ResolutionPolicy::Uniform40};
  eviction.configure_detail_preservation(1);
  eviction.select_detail_regions(regions);
  eviction.update({.x = 40.01, .y = 0.01, .z = 1.0});
  eviction.select_detail_regions({});
  eviction.select_detail_regions(regions);
  eviction.split(regions[0]);
  CHECK(eviction.snapshot().nonspatial_prior_point_count == 1);
  CHECK(eviction.point_count() == 1);
}

void eviction_cannot_resurrect_old_evidence() {
  for (const bool stale : {false, true}) {
    Map map{ResolutionPolicy::Uniform40};
    map.configure_detail_preservation(1);
    const std::array regions{CellId{3, 100, 0}};
    map.select_detail_regions(regions);
    map.update({.x = 40.01, .y = 0.01, .z = 8.0, .timestamp = 1});
    if (stale) {
      map.evict_stale_before(2);
    } else {
      map.set_window_center(-100.0, 0.0);
      map.set_window_center(0.0, 0.0);
    }
    CHECK(map.point_count() == 0);
    map.update({.x = 40.21, .y = 0.21, .z = 1.0, .timestamp = 3});
    map.split(regions[0]);
    CHECK(map.point_count() == 1);
    CHECK(map.snapshot().detail_rehydrated_splits == 0);
  }
}

void bounds_and_accounting_are_explicit() {
  Map map{ResolutionPolicy::Uniform40};
  CHECK(map.snapshot().memory.detail_sketch_allocated_bytes == 0);
  const auto baseline_allocated = map.snapshot().memory.allocated_bytes;
  map.configure_detail_preservation(1);
  const auto allocated = map.snapshot().memory.detail_sketch_allocated_bytes;
  CHECK(allocated > 64 * sizeof(veyra::map::CellStats));
  CHECK(map.snapshot().memory.allocated_bytes == baseline_allocated + allocated);
  for (int x = 0; x < 10; ++x) {
    const std::array regions{CellId{3, x, 0}};
    map.select_detail_regions(regions);
    CHECK(map.snapshot().detail_sketch_regions == 1);
    CHECK(map.snapshot().memory.detail_sketch_allocated_bytes == allocated);
  }
  bool refused = false;
  try {
    const std::array regions{CellId{3, 0, 0}, CellId{3, 1, 0}};
    map.select_detail_regions(regions);
  } catch (const std::invalid_argument&) { refused = true; }
  CHECK(refused);
  map.configure_detail_preservation(0);
  CHECK(map.snapshot().memory.detail_sketch_allocated_bytes == 0);
}

void visibility_clearing_invalidates_replay() {
  Map map{ResolutionPolicy::Uniform40};
  map.configure_detail_preservation(1);
  const std::array regions{CellId{3, 25, 0}};
  map.select_detail_regions(regions);
  for (const double z : {0.2, 1.8}) {
    Observation observation{.x = 10.2, .y = 0.2, .z = z};
    observation.height_above_ground = static_cast<float>(z);
    map.update(observation);
  }
  veyra::map::SensorPose pose{0.0, 0.0, 1.8};
  veyra::map::DepthImage image{1440, 64, -25.0 * std::numbers::pi / 180.0,
                                         15.0 * std::numbers::pi / 180.0};
  for (double z = 0.0; z <= 2.0; z += 0.02) image.insert(20.4, 0.4, z, pose);
  CHECK(map.clear_free_space(image, pose).cleared == 1);
  map.split(regions[0]);
  CHECK(map.snapshot().detail_rehydrated_splits == 0);
  CHECK(map.snapshot().nonspatial_prior_point_count == 2);
  CHECK(map.point_count() == 2);
}
} // namespace

int main() {
  spatial_statistics_survive_split_merge_cycles();
  incomplete_or_evicted_history_is_never_invented();
  eviction_cannot_resurrect_old_evidence();
  bounds_and_accounting_are_explicit();
  visibility_clearing_invalidates_replay();
}
