#define main veyra_benchmark_program_main
#include "../src/runtime/engine.cpp"
#undef main
#include "check.hpp"

namespace {
int level_at(const veyra::map::MapSnapshot& snapshot, double x, double y) {
  for (const auto& leaf : snapshot.leaves) {
    const double res = veyra::core::resolution_m(leaf.id.level);
    if (static_cast<std::int64_t>(std::floor(x / res)) == leaf.id.ix &&
        static_cast<std::int64_t>(std::floor(y / res)) == leaf.id.iy) return leaf.id.level;
  }
  return -1;
}

void selective_semantics_refine_actual_world_regions() {
  Options options;
  options.promotion_telemetry = true;
  MapPolicyAdapter utility{PolicyKind::kUtilityLod, {}, options};
  MapPolicyAdapter distance{PolicyKind::kDistanceLod, {}, options};
  for (int frame = 0; frame < 3; ++frame) {
    utility.set_window_center(0.0, 0.0);
    distance.set_window_center(0.0, 0.0);
    // Dense repeated evidence at equal nominal range. No geometry, terrain
    // risk or motion can accidentally make the semantic-only assertion pass.
    for (int sample = 0; sample < 10; ++sample) {
      for (int region = 0; region < 4; ++region) {
        veyra::map::Observation point;
        point.x = 45.05;
        point.y = 0.05 + 0.8 * region;
        point.semantic_class = region == 0 ? 9 : (region == 1 ? 6 : (region == 2 ? 18 : 1));
        point.semantic_confidence = region == 3 ? 0.9F : 1.0F;
        point.observation_quality = 1.0F;
        utility.update(point);
        distance.update(point);
      }
    }
  }
  const auto actual = utility.snapshot();
  const auto baseline = distance.snapshot();
  CHECK(level_at(actual, 45.05, 0.05) == 2); // flat road stays DistanceLOD
  for (double y : {0.85, 1.65, 2.45}) {
    CHECK(level_at(baseline, 45.05, y) == 2);
    CHECK(level_at(actual, 45.05, y) == 1); // person/pole/car in correct footprint
  }
  CHECK(actual.point_count == baseline.point_count);
  CHECK(actual.has_no_parent_descendant_overlap());
}

void sparse_far_and_low_confidence_do_not_refine() {
  Options options;
  options.promotion_telemetry = true;
  MapPolicyAdapter utility{PolicyKind::kUtilityLod, {}, options};
  for (int frame = 0; frame < 3; ++frame) {
    utility.set_window_center(0.0, 0.0);
    veyra::map::Observation sparse;
    sparse.x = 80.05;
    sparse.y = 0.05;
    sparse.semantic_class = 6;
    sparse.semantic_confidence = sparse.observation_quality = 1.0F;
    sparse.geometry_complexity = sparse.motion_probability = 1.0F;
    utility.update(sparse);
    for (int sample = 0; sample < 10; ++sample) {
      auto uncertain = sparse;
      uncertain.y = 0.85;
      uncertain.semantic_confidence = 0.2F;
      uncertain.geometry_complexity = uncertain.motion_probability = 0.0F;
      utility.update(uncertain);
    }
  }
  CHECK(level_at(utility.snapshot(), 80.05, 0.05) == 3);
  CHECK(level_at(utility.snapshot(), 80.05, 0.85) == 3);
  CHECK(utility.promotion_telemetry()->density_failed > 0);
}

void complete_frame_support_is_order_independent() {
  Options options;
  MapPolicyAdapter forward{PolicyKind::kUtilityLod, {}, options};
  MapPolicyAdapter reverse{PolicyKind::kUtilityLod, {}, options};
  std::vector<veyra::map::Observation> points(5);
  for (auto& point : points) {
    point.x = 45.15;
    point.y = 4.05;
    point.semantic_class = 9;
    point.semantic_confidence = point.observation_quality = 1.0F;
  }
  points.front().x = 45.05;
  points.front().semantic_class = 6;
  for (int frame = 0; frame < 3; ++frame) {
    forward.set_window_center(0.0, 0.0);
    reverse.set_window_center(0.0, 0.0);
    forward.prepare_frame(points);
    reverse.prepare_frame(points);
    for (const auto& point : points) forward.update(point);
    for (auto it = points.rbegin(); it != points.rend(); ++it) reverse.update(*it);
  }
  CHECK(level_at(forward.snapshot(), 45.05, 4.05) == 1);
  CHECK(level_at(reverse.snapshot(), 45.05, 4.05) == 1);
  CHECK(forward.snapshot().point_count == 15);
  CHECK(reverse.snapshot().point_count == 15);
}
} // namespace

int main() {
  selective_semantics_refine_actual_world_regions();
  sparse_far_and_low_confidence_do_not_refine();
  complete_frame_support_is_order_independent();
  const auto directory = std::filesystem::temp_directory_path() / "veyra-policy-adapter-test";
  std::filesystem::create_directories(directory);
  const auto governor_path = directory / "governor.yaml";
  {
    std::ofstream output{governor_path};
    output << "max_active_cells: 1\nmax_logical_bytes: 1\nnear_field_radius_m: 10\n"
              "max_actions_per_frame: 64\noverload_consecutive_frames: 1\n";
  }
  Options options;
  options.policy = "utility_lod";
  options.governor_config = governor_path.string();
  MapPolicyAdapter adapter{PolicyKind::kUtilityLod, {}, options};
  for (int frame = 0; frame < 3; ++frame) {
    adapter.set_window_center(0.0, 0.0);
    for (int y = 0; y < 2; ++y) {
      for (int x = 0; x < 2; ++x) {
        veyra::map::Observation point;
        point.x = 70.05 + 0.2 * x;
        point.y = 0.05 + 0.2 * y;
        point.semantic_class = 1;
        point.semantic_confidence = 1.0F;
        point.geometry_complexity = 1.0F;
        point.motion_probability = 1.0F;
        point.observation_quality = 1.0F;
        point.terrain_confidence = 1.0F;
        point.drivable = x == 1 && y == 1 ? 2 : 1;
        adapter.update(point);
      }
    }
  }
  const auto before = adapter.snapshot();
  CHECK(before.active_leaf_count == 4);
  adapter.apply_governor(before, 200.0);
  const auto after = adapter.snapshot();
  // A low-utility sibling must not authorize merging the hazardous sibling.
  CHECK(after.active_leaf_count == 4);
  CHECK(after.point_count == before.point_count);
  std::filesystem::remove_all(directory);
}
