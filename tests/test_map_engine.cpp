#include <cassert>
#include <chrono>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <vector>

#include "veyra/map/map.hpp"
#include "veyra/map/fusion.hpp"

using veyra::map::DistanceLodMap;
using veyra::map::Map;
using veyra::map::Observation;
using veyra::map::Uniform40Map;
using veyra::map::Uniform5Map;

namespace {

#if defined(__SANITIZE_ADDRESS__) || defined(__SANITIZE_UNDEFINED__)
constexpr bool kSanitizerBuild = true;
#elif defined(__clang__)
constexpr bool kSanitizerBuild = __has_feature(address_sanitizer) ||
                                 __has_feature(undefined_behavior_sanitizer);
#else
constexpr bool kSanitizerBuild = false;
#endif

}  // namespace

void test_distance_lod_dense_update_budget() {
  DistanceLodMap map({.window_radius_m = 100.0});
  constexpr int sample_count = 36000;
  const auto started = std::chrono::steady_clock::now();
  for (int i = 0; i < sample_count; ++i) {
    const double angle = static_cast<double>(i % 1024) * 0.006135923151542565;
    const double radius = 2.0 + static_cast<double>((i * 7919) % 9800) / 100.0;
    map.update(Observation{.x = radius * std::cos(angle),
                           .y = radius * std::sin(angle),
                           .z = static_cast<double>(i % 37) * 0.01});
  }
  const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - started);
  const auto snapshot = map.snapshot();
  assert(snapshot.point_count == sample_count);
  assert(snapshot.has_no_parent_descendant_overlap());
  // Sanitizer instrumentation changes allocator and container costs enough
  // to invalidate this release-performance gate. Correctness remains tested
  // above; the timing gate is retained for normal Debug/Release builds.
  if (!kSanitizerBuild) {
    assert(elapsed < std::chrono::milliseconds(2000));
  }
}

void test_split_merge_preserves_all_statistics() {
  DistanceLodMap map({.window_radius_m = 100.0});
  map.update(Observation{.x = 70.01, .y = 0.01, .z = -2.0, .timestamp = 3});
  map.update(Observation{.x = 70.02, .y = 0.02, .z = 4.0, .timestamp = 8});
  const auto before = map.snapshot();
  assert(before.point_count == 2);
  const auto parent = before.leaves.front().id;
  map.split(parent);
  const auto split = map.snapshot();
  assert(split.point_count == before.point_count);
  assert(split.has_no_parent_descendant_overlap());
  map.merge_children(parent);
  const auto after = map.snapshot();
  assert(after.point_count == before.point_count);
  assert(after.leaves.size() == 1);
  const auto& stats = after.leaves.front().stats;
  assert(stats.count == 2);
  assert(std::abs(stats.mean_z() - 1.0) < 1e-12);
  assert(std::abs(stats.m2_z() - 18.0) < 1e-12);
  assert(std::abs(stats.variance_z() - 18.0) < 1e-12);
  assert(stats.min_z() == -2.0);
  assert(stats.max_z() == 4.0);
  assert(stats.last_seen == 8);
}

void test_split_never_invents_a_child_location_for_parent_evidence() {
  DistanceLodMap map({.window_radius_m = 100.0});
  map.update(Observation{.x = 70.01, .y = 0.01, .z = -2.0, .timestamp = 3});
  map.update(Observation{.x = 70.02, .y = 0.02, .z = 4.0, .timestamp = 8});

  const auto parent = map.snapshot().leaves.front().id;
  map.split(parent);

  // The two observations have only parent-level spatial support.  A split
  // must not fabricate a more precise position by assigning them to a child.
  const auto split = map.snapshot();
  assert(split.active_leaf_count == 4);
  for (const auto& leaf : split.leaves) {
    assert(leaf.stats.count == 0);
  }
  assert(split.point_count == 2);
}

void test_dense_snapshot_invariant_check_is_bounded() {
  Uniform5Map map({.window_radius_m = 100.0});
  constexpr int side = 120;
  for (int iy = -side / 2; iy < side / 2; ++iy) {
    for (int ix = -side / 2; ix < side / 2; ++ix) {
      map.update(Observation{.x = (static_cast<double>(ix) + 0.25) * 0.05,
                             .y = (static_cast<double>(iy) + 0.25) * 0.05,
                             .z = 1.0});
    }
  }
  const auto snapshot = map.snapshot();
  assert(snapshot.active_leaf_count == static_cast<std::size_t>(side * side));
  const auto started = std::chrono::steady_clock::now();
  assert(snapshot.has_no_parent_descendant_overlap());
  const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - started);
  assert(elapsed < std::chrono::milliseconds(100));
}

void test_policy_compatible_uniform_baselines_and_distance_seams() {
  Map uniform5(veyra::map::ResolutionPolicy::Uniform5);
  Map uniform40(veyra::map::ResolutionPolicy::Uniform40);
  Map distance(veyra::map::ResolutionPolicy::DistanceLod);
  assert(uniform5.cell_for(-0.001, -0.001).level == 0);
  assert(uniform40.cell_for(-0.001, -0.001).level == 3);
  assert(distance.level_for(9.999, 0.0) == 0);
  assert(distance.level_for(10.0, 0.0) == 1);
  assert(distance.level_for(30.0, 0.0) == 2);
  assert(distance.level_for(60.0, 0.0) == 3);

  uniform5.update(Observation{.x = 0.01, .y = 0.01, .z = 1.0});
  uniform40.update(Observation{.x = 0.01, .y = 0.01, .z = 1.0});
  distance.update(Observation{.x = 0.01, .y = 0.01, .z = 1.0});
  assert(uniform5.snapshot().count_at_level(0) == 1);
  assert(uniform40.snapshot().count_at_level(3) == 1);
  assert(distance.snapshot().count_at_level(0) == 1);

  Uniform40Map legacy_uniform40;
  legacy_uniform40.update(Observation{.x = -0.01, .y = -0.01, .z = 2.0});
  assert(legacy_uniform40.cell_for(-0.01, -0.01).level == 3);
  assert(legacy_uniform40.snapshot().point_count == 1);
}

void test_cell_statistics_preserve_enriched_observation_evidence() {
  veyra::map::Uniform5Map map;
  map.update({.x = 1.0,
              .y = 2.0,
              .z = 0.5,
              .timestamp = 42,
              .semantic_class = 7,
              .semantic_confidence = 0.8F,
              .drivable = 1,
              .ground = 1,
              .terrain_confidence = 0.7F,
              .motion_probability = 0.6F,
              .observation_quality = 0.9F});
  const auto snapshot = map.snapshot();
  assert(snapshot.leaves.size() == 1);
  const auto& stats = snapshot.leaves.front().stats;
  assert(stats.semantic_class == 7);
  assert(stats.semantic_evidence == 0.8F);
  assert(stats.drivable_evidence == 0.7F);
  assert(stats.ground_evidence == 0.7F);
  assert(stats.motion_evidence == 0.6F);
  assert(stats.observation_quality == 0.9F);
  assert(stats.last_seen == 42);
}

void test_geometry_complexity_is_fused_and_survives_split_merge() {
  DistanceLodMap map({.window_radius_m = 100.0});
  map.update(Observation{.x = 70.01, .y = 0.01, .z = 1.0, .geometry_complexity = 0.25F});
  map.update(Observation{.x = 70.02, .y = 0.02, .z = 3.0, .geometry_complexity = 0.75F});

  const auto parent = map.snapshot().leaves.front().id;
  map.split(parent);
  const auto split = map.snapshot();
  assert(split.point_count == 2);
  assert(split.has_no_parent_descendant_overlap());

  map.merge_children(parent);
  const auto merged = map.snapshot();
  assert(merged.point_count == 2);
  assert(merged.leaves.size() == 1);
  assert(std::abs(merged.leaves.front().stats.geometry_complexity - 0.5F) < 1e-6F);
}

void test_split_merge_cycles_and_policy_transitions_preserve_statistics() {
  DistanceLodMap map({.window_radius_m = 100.0});
  map.update(Observation{.x = 70.01, .y = 0.01, .z = -2.0, .timestamp = 3});
  map.update(Observation{.x = 70.02, .y = 0.02, .z = 4.0, .timestamp = 8});
  const auto parent = map.snapshot().leaves.front().id;
  for (int cycle = 0; cycle < 8; ++cycle) {
    map.split(parent);
    const auto split = map.snapshot();
    assert(split.active_leaf_count == 4);
    assert(split.nonspatial_prior_point_count == 2);
    assert(split.point_count == 2);
    assert(split.has_no_parent_descendant_overlap());
    map.merge_children(parent);
    const auto merged = map.snapshot();
    assert(merged.active_leaf_count == 1);
    assert(merged.nonspatial_prior_point_count == 0);
    assert(merged.point_count == 2);
    assert(std::abs(merged.leaves.front().stats.mean_z() - 1.0) < 1e-12);
    assert(std::abs(merged.leaves.front().stats.m2_z() - 18.0) < 1e-12);
    assert(merged.leaves.front().stats.min_z() == -2.0);
    assert(merged.leaves.front().stats.max_z() == 4.0);
  }

  DistanceLodMap transition({.window_radius_m = 100.0});
  transition.update(Observation{.x = 20.01, .y = 0.01, .z = 1.0, .timestamp = 1});
  transition.set_window_center(15.0, 0.0);
  transition.update(Observation{.x = 20.01, .y = 0.01, .z = 3.0, .timestamp = 2});
  const auto refined = transition.snapshot();
  assert(refined.point_count == 2);
  assert(refined.nonspatial_prior_point_count == 1);
  assert(refined.has_no_parent_descendant_overlap());

  DistanceLodMap merge_from_children({.window_radius_m = 100.0});
  merge_from_children.update(Observation{.x = 70.01, .y = 0.01, .z = -2.0, .timestamp = 3});
  merge_from_children.update(Observation{.x = 70.02, .y = 0.02, .z = 4.0, .timestamp = 8});
  const auto coarse_parent = merge_from_children.snapshot().leaves.front().id;
  merge_from_children.split(coarse_parent);
  merge_from_children.set_window_center(20.0, 0.0);
  merge_from_children.update(Observation{.x = 70.25, .y = 0.01, .z = 10.0, .timestamp = 11});
  merge_from_children.merge_children(coarse_parent);
  const auto merged_children = merge_from_children.snapshot();
  assert(merged_children.point_count == 3);
  assert(merged_children.nonspatial_prior_point_count == 0);
  assert(std::abs(merged_children.leaves.front().stats.mean_z() - 4.0) < 1e-12);
  assert(std::abs(merged_children.leaves.front().stats.m2_z() - 72.0) < 1e-12);
  assert(merged_children.leaves.front().stats.min_z() == -2.0);
  assert(merged_children.leaves.front().stats.max_z() == 10.0);
}

void test_exact_cell_window_eviction_stale_cleanup_and_real_tiles() {
  const veyra::map::MapConfig config{.window_radius_m = 1.0, .tile_size_m = 0.5};
  Uniform5Map map(config);
  map.update(Observation{.x = 0.99, .y = 0.0, .z = 1.0, .timestamp = 3});
  const auto retained_id = map.snapshot().leaves.front().id;

  // The cell [0.95, 1.00] intersects the shifted circular window even though
  // its center is just outside it, so center-based eviction would be wrong.
  map.set_window_center(1.98, 0.0);
  assert(map.snapshot().active_leaf_count == 1);
  assert(map.snapshot().leaves.front().id == retained_id);
  map.set_window_center(2.01, 0.0);
  assert(map.snapshot().active_leaf_count == 0);
  assert(map.snapshot().tile_count == 0);

  map.set_window_center(0.0, 0.0);
  map.update(Observation{.x = 0.10, .y = 0.10, .z = 1.0, .timestamp = 3});
  map.update(Observation{.x = 0.60, .y = 0.10, .z = 2.0, .timestamp = 10});
  const auto allocated = map.snapshot();
  assert(allocated.tile_count == 2);
  assert(allocated.memory.logical_payload_bytes ==
         allocated.active_leaf_count * sizeof(veyra::map::Leaf));
  assert(allocated.memory.allocated_cell_array_bytes >= allocated.memory.logical_payload_bytes);
  assert(allocated.memory.allocated_bytes >= allocated.memory.allocated_cell_array_bytes);
  assert(allocated.memory.allocated_overhead_bytes ==
         allocated.memory.allocated_bytes - allocated.memory.allocated_cell_array_bytes);

  map.evict_stale_before(10);
  const auto cleaned = map.snapshot();
  assert(cleaned.point_count == 1);
  assert(cleaned.active_leaf_count == 1);
  assert(cleaned.tile_count == 1);
  assert(cleaned.leaves.front().stats.last_seen == 10);
}

void test_window_containment_is_queryable_for_stream_ingest() {
  Map query(veyra::map::ResolutionPolicy::DistanceLod, {.window_radius_m = 100.0});
  assert(query.accepts(0.0, 0.0));
  assert(query.accepts(100.0, 0.0));
  assert(!query.accepts(101.0, 0.0));
  assert(!query.accepts(std::numeric_limits<double>::quiet_NaN(), 0.0));
  // Direct update stays fail-closed; stream ingestors pre-check instead.
  bool threw = false;
  try {
    query.update(Observation{.x = 101.0, .y = 0.0, .z = 0.0});
  } catch (const std::out_of_range&) {
    threw = true;
  }
  assert(threw);
  DistanceLodMap wrapped({.window_radius_m = 100.0});
  assert(wrapped.accepts(0.0, 0.0));
  assert(!wrapped.accepts(0.0, 150.0));
  Uniform5Map uniform5({.window_radius_m = 100.0});
  Uniform40Map uniform40({.window_radius_m = 100.0});
  assert(uniform5.accepts(0.0, 0.0) && !uniform5.accepts(200.0, 0.0));
  assert(uniform40.accepts(0.0, 0.0) && !uniform40.accepts(200.0, 0.0));
}

int main() {
  test_window_containment_is_queryable_for_stream_ingest();
  test_distance_lod_dense_update_budget();
  test_split_merge_preserves_all_statistics();
  test_split_never_invents_a_child_location_for_parent_evidence();
  test_dense_snapshot_invariant_check_is_bounded();
  test_policy_compatible_uniform_baselines_and_distance_seams();
  test_cell_statistics_preserve_enriched_observation_evidence();
  test_geometry_complexity_is_fused_and_survives_split_merge();
  test_split_merge_cycles_and_policy_transitions_preserve_statistics();
  test_exact_cell_window_eviction_stale_cleanup_and_real_tiles();
  Uniform5Map uniform({.window_radius_m = 100.0});
  assert(uniform.cell_for(0.0, 0.0) == uniform.cell_for(0.049, 0.049));
  assert(uniform.cell_for(-0.001, -0.001).ix == -1);
  assert(uniform.cell_for(-0.001, -0.001).iy == -1);
  assert(uniform.cell_for(0.05, 0.05).ix == 1);

  uniform.update(Observation{.x = -0.001, .y = -0.001, .z = 1.0});
  uniform.update(Observation{.x = -0.001, .y = -0.001, .z = 3.0});
  const auto uniform_snapshot = uniform.snapshot();
  assert(uniform_snapshot.active_leaf_count == 1);
  assert(uniform_snapshot.point_count == 2);
  const auto& stats = uniform_snapshot.leaves.front().stats;
  assert(std::abs(stats.mean_z() - 2.0) < 1e-12);
  assert(std::abs(stats.variance_z() - 2.0) < 1e-12);

  DistanceLodMap adaptive({.window_radius_m = 100.0});
  adaptive.update(Observation{.x = 1.0, .y = 0.0, .z = 2.0});
  adaptive.update(Observation{.x = 20.0, .y = 0.0, .z = 4.0});
  adaptive.update(Observation{.x = 70.0, .y = 0.0, .z = 8.0});
  const auto adaptive_snapshot = adaptive.snapshot();
  assert(adaptive_snapshot.point_count == 3);
  assert(adaptive_snapshot.count_at_level(0) == 1);
  assert(adaptive_snapshot.count_at_level(1) == 1);
  assert(adaptive_snapshot.count_at_level(3) == 1);
  assert(adaptive_snapshot.has_no_parent_descendant_overlap());
  assert(adaptive_snapshot.topology_change_count == 0);

  DistanceLodMap coarsening({.window_radius_m = 100.0});
  coarsening.update(Observation{.x = 1.0, .y = 0.0, .z = 2.0});
  coarsening.set_window_center(-10.0, 0.0);
  coarsening.update(Observation{.x = 1.0, .y = 0.0, .z = 6.0});
  const auto coarsened = coarsening.snapshot();
  assert(coarsened.point_count == 2);
  assert(coarsened.active_leaf_count == 1);
  assert(coarsened.leaves.front().id.level == 1);
  assert(std::abs(coarsened.leaves.front().stats.mean_z() - 4.0) < 1e-12);
  assert(coarsened.has_no_parent_descendant_overlap());

  DistanceLodMap conservation({.window_radius_m = 100.0});
  constexpr int sample_count = 512;
  for (int i = 0; i < sample_count; ++i) {
    const double x = -60.0 + static_cast<double>((i * 37) % 1200) / 10.0;
    const double y = -60.0 + static_cast<double>((i * 71) % 1200) / 10.0;
    conservation.update(Observation{.x = x, .y = y, .z = static_cast<double>(i)});
  }
  assert(conservation.snapshot().point_count == sample_count);
  assert(conservation.snapshot().has_no_parent_descendant_overlap());

  auto coarse_leaf = adaptive_snapshot.leaves.back().id;
  adaptive.split(coarse_leaf);
  assert(adaptive.snapshot().has_no_parent_descendant_overlap());
  assert(adaptive.snapshot().topology_change_count == 1);
  assert(adaptive.snapshot().split_count == 1);
  assert(adaptive.snapshot().merge_count == 0);
  const auto before_merge = adaptive.snapshot().point_count;
  adaptive.merge_children(coarse_leaf);
  assert(adaptive.snapshot().point_count == before_merge);
  assert(adaptive.snapshot().topology_change_count == 2);
  assert(adaptive.snapshot().split_count == 1);
  assert(adaptive.snapshot().merge_count == 1);

  bool out_of_range = false;
  try {
    adaptive.update(Observation{.x = 101.0, .y = 0.0, .z = 1.0});
  } catch (const std::out_of_range&) {
    out_of_range = true;
  }
  assert(out_of_range);
  assert(adaptive.snapshot().point_count == before_merge);

  bool rejected = false;
  try {
    uniform.update(Observation{.x = NAN, .y = 0.0, .z = 0.0});
  } catch (const std::invalid_argument&) {
    rejected = true;
  }
  assert(rejected);

  bool bad_level = false;
  try {
    (void)veyra::core::resolution_m(4);
  } catch (const std::invalid_argument&) {
    bad_level = true;
  }
  assert(bad_level);

  bool bad_config = false;
  try {
    Uniform5Map invalid({.window_radius_m = 0.0});
  } catch (const std::invalid_argument&) {
    bad_config = true;
  }
  assert(bad_config);
}
