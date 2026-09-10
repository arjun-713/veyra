#include "veyra/policy/policy.hpp"
#include "veyra/core/types.hpp"

#include <cassert>
#include <filesystem>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <vector>

namespace {

using veyra::policy::DecisionInput;
using veyra::policy::LodMode;
using veyra::policy::LodPolicy;
using veyra::policy::PolicyConfig;
using veyra::policy::ResourceGovernor;
using veyra::policy::ResourceGovernorConfig;
using veyra::policy::ResourceTelemetry;
using veyra::policy::GovernorCandidate;
using veyra::policy::ResolutionAction;

void uniform_and_distance_modes_have_one_consistent_level_contract() {
  auto config = PolicyConfig::defaults();
  LodPolicy uniform5{config.with_mode(LodMode::Uniform5)};
  LodPolicy uniform40{config.with_mode(LodMode::Uniform40)};
  LodPolicy distance{config.with_mode(LodMode::DistanceLod)};

  const auto uniform5_decision = uniform5.decide(DecisionInput{.range_m = 75.0, .active_level = 3});
  const auto uniform40_decision = uniform40.decide(DecisionInput{.range_m = 2.0, .active_level = 0});
  assert(uniform5_decision.requested_level == 0);
  assert(uniform5_decision.action == ResolutionAction::Split);
  assert(uniform40_decision.requested_level == 3);
  assert(uniform40_decision.action == ResolutionAction::Merge);
  assert(distance.decide(DecisionInput{.range_m = 5.0, .active_level = 0}).baseline_level == 0);
  assert(distance.decide(DecisionInput{.range_m = 20.0, .active_level = 1}).baseline_level == 1);
  assert(distance.decide(DecisionInput{.range_m = 45.0, .active_level = 2}).baseline_level == 2);
  assert(distance.decide(DecisionInput{.range_m = 75.0, .active_level = 3}).baseline_level == 3);
}

void invalid_policy_configuration_is_rejected() {
  auto config = PolicyConfig::defaults();
  config.distance_boundaries_m = {10.0, 10.0, 60.0};

  bool threw = false;
  try {
    LodPolicy invalid{config};
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  assert(threw);
}

void utility_promotes_hazards_but_gates_noisy_sparse_uncertainty() {
  auto config = PolicyConfig::defaults().with_mode(LodMode::UtilityLod);
  config.utility.split_consecutive_frames = 1;
  config.utility.cooldown_frames = 0;
  LodPolicy utility{config};

  const auto flat_road = utility.decide(
      DecisionInput{.range_m = 70.0,
                    .active_level = 3,
                    .state_cell = {3, 1, 1},
                    .observation_quality = 1.0,
                    .point_density = 1.0});
  assert(flat_road.baseline_level == 3);
  assert(flat_road.requested_level == 3);

  const auto pedestrian = utility.decide(DecisionInput{.range_m = 70.0,
                                                        .active_level = 3,
                                                        .state_cell = {3, 2, 2},
                                                        .semantic_importance = 1.0,
                                                        .traversability_risk = 1.0,
                                                        .observation_quality = 0.9,
                                                        .point_density = 0.9});
  assert(pedestrian.requested_level < pedestrian.baseline_level);

  const auto noisy_sparse = utility.decide(DecisionInput{.range_m = 70.0,
                                                          .active_level = 3,
                                                          .state_cell = {3, 3, 3},
                                                          .semantic_uncertainty = 1.0,
                                                          .observation_quality = 0.1,
                                                          .point_density = 0.1});
  assert(!noisy_sparse.uncertainty_gate_passed);
  assert(noisy_sparse.requested_level == noisy_sparse.baseline_level);

  const auto safety_critical = utility.decide(DecisionInput{.range_m = 70.0,
                                                             .active_level = 3,
                                                             .state_cell = {3, 4, 4},
                                                             .safety_critical = true});
  assert(safety_critical.requested_level < safety_critical.baseline_level);
}

void utility_consumes_each_documented_signal_with_configurable_weights() {
  auto config = PolicyConfig::defaults().with_mode(LodMode::UtilityLod);
  config.utility.split_threshold = 0.5;
  config.utility.min_observation_quality = 0.5;
  config.utility.min_point_density = 0.5;

  const auto check_signal = [&](const auto configure, const DecisionInput input) {
    auto one_signal = config;
    one_signal.utility.geometry_weight = 0.0;
    one_signal.utility.semantic_weight = 0.0;
    one_signal.utility.motion_weight = 0.0;
    one_signal.utility.traversability_risk_weight = 0.0;
    one_signal.utility.uncertainty_weight = 0.0;
    configure(one_signal);
    LodPolicy policy{one_signal};
    const auto decision = policy.decide(input);
    assert(decision.utility_score == 1.0);
    assert(decision.requested_level < decision.baseline_level);
  };

  check_signal([](auto& c) { c.utility.geometry_weight = 1.0; },
               {.range_m = 70.0, .active_level = 3, .geometry_complexity = 1.0});
  check_signal([](auto& c) { c.utility.semantic_weight = 1.0; },
               {.range_m = 70.0, .active_level = 3, .semantic_importance = 1.0});
  check_signal([](auto& c) { c.utility.motion_weight = 1.0; },
               {.range_m = 70.0, .active_level = 3, .motion = 1.0});
  check_signal([](auto& c) { c.utility.traversability_risk_weight = 1.0; },
               {.range_m = 70.0, .active_level = 3, .traversability_risk = 1.0});
  check_signal([](auto& c) { c.utility.uncertainty_weight = 1.0; },
               {.range_m = 70.0,
                .active_level = 3,
                .semantic_uncertainty = 1.0,
                .observation_quality = 1.0,
                .point_density = 1.0});
}

void motion_prediction_and_hysteresis_prevent_lod_thrash() {
  auto predictive_config = PolicyConfig::defaults().with_mode(LodMode::UtilityLod);
  predictive_config.utility.split_consecutive_frames = 1;
  predictive_config.utility.cooldown_frames = 0;
  LodPolicy predictive{predictive_config};
  const auto predicted = predictive.decide(DecisionInput{.range_m = 70.0,
                                                          .active_level = 3,
                                                          .semantic_importance = 1.0,
                                                          .motion = 1.0,
                                                          .range_rate_mps = -20.0});
  assert(predicted.predicted_refinement);
  assert(predicted.requested_level == 2);
  assert(predicted.action == ResolutionAction::Split);

  auto hysteresis_config = PolicyConfig::defaults().with_mode(LodMode::UtilityLod);
  hysteresis_config.utility.ema_alpha = 1.0;
  hysteresis_config.utility.split_threshold = 0.5;
  hysteresis_config.utility.merge_threshold = 0.25;
  hysteresis_config.utility.split_consecutive_frames = 2;
  hysteresis_config.utility.merge_consecutive_frames = 2;
  hysteresis_config.utility.cooldown_frames = 2;
  hysteresis_config.utility.semantic_weight = 1.0;
  LodPolicy hysteresis{hysteresis_config};
  const auto key = veyra::core::CellId{3, 9, 4};
  const auto high = DecisionInput{.range_m = 70.0,
                                  .active_level = 3,
                                  .state_cell = key,
                                  .semantic_importance = 1.0};
  assert(hysteresis.decide(high).requested_level == 3);
  assert(hysteresis.decide(high).requested_level == 2);

  const auto low = DecisionInput{.range_m = 70.0, .active_level = 2, .state_cell = key};
  assert(hysteresis.decide(low).requested_level == 2);
  assert(hysteresis.decide(low).requested_level == 2);
  assert(hysteresis.decide(low).requested_level == 2);
  const auto merge = hysteresis.decide(low);
  assert(merge.requested_level == 3);
  assert(merge.action == ResolutionAction::Merge);
}

void resource_governor_uses_measured_pressure_and_preserves_near_field_and_hazards() {
  ResourceGovernorConfig config{.max_active_cells = 100,
                                .max_logical_bytes = 10'000,
                                .near_field_radius_m = 10.0,
                                .max_actions_per_frame = 2};
  ResourceGovernor governor{config};
  const ResourceTelemetry under_budget{.active_cells = 99,
                                       .logical_bytes = 9'999,
                                       .frame_time_ms = 9.0,
                                       .target_frame_time_ms = 10.0};
  assert(governor.decide(under_budget, {}).empty());

  const ResourceTelemetry measured_pressure{.active_cells = 120,
                                             .logical_bytes = 12'000,
                                             .frame_time_ms = 18.0,
                                             .target_frame_time_ms = 10.0};
  const std::vector<GovernorCandidate> candidates{
      {.cell = {0, 1, 1}, .range_m = 5.0, .utility_score = 0.0, .active_level = 0},
      {.cell = {1, 2, 2}, .range_m = 70.0, .utility_score = 0.0, .active_level = 1},
      {.cell = {1, 3, 3}, .range_m = 80.0, .utility_score = 0.9, .active_level = 1, .safety_critical = true},
      {.cell = {1, 4, 4}, .range_m = 90.0, .utility_score = 0.1, .active_level = 1},
  };
  const auto actions = governor.decide(measured_pressure, candidates);
  assert(actions.size() == 2);
  assert((actions[0].cell == veyra::core::CellId{1, 4, 4}));
  assert((actions[1].cell == veyra::core::CellId{1, 2, 2}));
  for (const auto& action : actions) {
    assert(action.action == ResolutionAction::Merge);
    assert(action.cell != candidates[0].cell);
    assert(action.cell != candidates[2].cell);
  }
}

void yaml_configs_drive_the_validated_policy_contract() {
  const auto root = std::filesystem::path{VEYRA_SOURCE_DIR};
  const auto distance = veyra::policy::load_policy_config(root / "configs/distance_lod.yaml");
  const auto utility = veyra::policy::load_policy_config(root / "configs/utility_lod.yaml");
  const auto governor = veyra::policy::load_resource_governor_config(root / "configs/resource_governor.yaml");
  assert(distance.mode == LodMode::DistanceLod);
  assert(distance.distance_boundaries_m[2] == 60.0);
  assert(utility.mode == LodMode::UtilityLod);
  assert(utility.utility.ema_alpha == 0.35);
  assert(utility.utility.split_consecutive_frames == 2);
  assert(governor.max_active_cells == 250000);
  assert(governor.max_actions_per_frame == 64);

  const auto invalid = std::filesystem::temp_directory_path() / "veyra-invalid-policy.yaml";
  {
    std::ofstream stream{invalid};
    stream << "mode: utility_lod\n"
              "distance_boundaries_m: [10.0, 8.0, 60.0]\n";
  }
  bool threw = false;
  try {
    static_cast<void>(veyra::policy::load_policy_config(invalid));
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  std::filesystem::remove(invalid);
  assert(threw);
}

void radial_range_rate_from_velocity_is_signed_along_the_robot_offset() {
  // Approaching movers yield a negative range rate, receding movers a
  // positive one. Degenerate or non-finite inputs fail safe to zero so no
  // promotion is ever derived from garbage velocity evidence.
  const double quiet = veyra::policy::radial_range_rate_mps(0.0, 0.0, 10.0, 0.0);
  assert(quiet == 0.0);
  const double approaching = veyra::policy::radial_range_rate_mps(-5.0, 0.0, 10.0, 0.0);
  assert(approaching == -5.0);
  const double receding = veyra::policy::radial_range_rate_mps(5.0, 0.0, 10.0, 0.0);
  assert(receding == 5.0);
  const double tangential = veyra::policy::radial_range_rate_mps(0.0, 5.0, 10.0, 0.0);
  assert(tangential == 0.0);
  const double diagonal = veyra::policy::radial_range_rate_mps(3.0, 4.0, 3.0, 4.0);
  assert(diagonal == 5.0);
  assert(veyra::policy::radial_range_rate_mps(5.0, 5.0, 0.0, 0.0) == 0.0);
  const double nan = std::numeric_limits<double>::quiet_NaN();
  const double inf = std::numeric_limits<double>::infinity();
  assert(veyra::policy::radial_range_rate_mps(nan, 0.0, 10.0, 0.0) == 0.0);
  assert(veyra::policy::radial_range_rate_mps(0.0, inf, 10.0, 0.0) == 0.0);
  assert(veyra::policy::radial_range_rate_mps(1.0, 0.0, nan, 0.0) == 0.0);
}

}  // namespace

int main() {
  radial_range_rate_from_velocity_is_signed_along_the_robot_offset();
  uniform_and_distance_modes_have_one_consistent_level_contract();
  invalid_policy_configuration_is_rejected();
  utility_promotes_hazards_but_gates_noisy_sparse_uncertainty();
  utility_consumes_each_documented_signal_with_configurable_weights();
  motion_prediction_and_hysteresis_prevent_lod_thrash();
  resource_governor_uses_measured_pressure_and_preserves_near_field_and_hazards();
  yaml_configs_drive_the_validated_policy_contract();
}
