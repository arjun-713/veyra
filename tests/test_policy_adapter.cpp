#define main veyra_benchmark_program_main
#include "../src/runtime/engine.cpp"
#undef main
#include "check.hpp"

int main() {
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
