// Native regression suites. CTest runs each section in a fresh process.
#include <cstdio>
#include <string_view>
#define main veyra_benchmark_program_main
#include "../src/runtime/engine.cpp"
#undef main
#include <cassert>
#include <filesystem>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <vector>
#include "veyra/core/types.hpp"
#include "veyra/policy/policy.hpp"
#include "check.hpp"
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include "veyra/map/resolution_pass.hpp"
#include "veyra/map/rolling_window.hpp"
#include "veyra/map/tile_grid.hpp"
#include <algorithm>
#include <array>
#include "veyra/map/fusion.hpp"
#include "veyra/map/observation.hpp"

namespace policy {

namespace {

using veyra::policy::DecisionInput;
using veyra::policy::GovernorCandidate;
using veyra::policy::LodMode;
using veyra::policy::LodPolicy;
using veyra::policy::PolicyConfig;
using veyra::policy::ResolutionAction;
using veyra::policy::ResourceGovernor;
using veyra::policy::ResourceGovernorConfig;
using veyra::policy::ResourceTelemetry;

void uniform_and_distance_modes_have_one_consistent_level_contract() {
  auto config = PolicyConfig::defaults();
  LodPolicy uniform5{config.with_mode(LodMode::Uniform5)};
  LodPolicy uniform40{config.with_mode(LodMode::Uniform40)};
  LodPolicy distance{config.with_mode(LodMode::DistanceLod)};

  const auto uniform5_decision = uniform5.decide(DecisionInput{.range_m = 75.0, .active_level = 3});
  const auto uniform40_decision =
      uniform40.decide(DecisionInput{.range_m = 2.0, .active_level = 0});
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

  const auto flat_road = utility.decide(DecisionInput{.range_m = 70.0,
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

  const auto safety_critical = utility.decide(DecisionInput{
      .range_m = 70.0, .active_level = 3, .state_cell = {3, 4, 4}, .safety_critical = true});
  assert(safety_critical.requested_level < safety_critical.baseline_level);
}

void utility_consumes_each_documented_signal_with_configurable_weights() {
  auto config = PolicyConfig::defaults().with_mode(LodMode::UtilityLod);
  config.utility.split_threshold = 0.5;
  config.utility.min_observation_quality = 0.5;
  config.utility.min_point_density = 0.5;

  const auto check_signal = [&](const auto configure, DecisionInput input) {
    input.observation_quality = 1.0;
    input.point_density = 1.0;
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
  check_signal([](auto& c) { c.utility.uncertainty_weight = 1.0; }, {.range_m = 70.0,
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
                                                         .observation_quality = 1.0,
                                                         .point_density = 1.0,
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
                                  .semantic_importance = 1.0,
                                  .observation_quality = 1.0,
                                  .point_density = 1.0};
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
  config.overload_consecutive_frames = 1;
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
      {.cell = {1, 3, 3},
       .range_m = 80.0,
       .utility_score = 0.9,
       .active_level = 1,
       .safety_critical = true},
      {.cell = {1, 4, 4}, .range_m = 90.0, .utility_score = 0.1, .active_level = 1},
  };
  const auto actions = governor.decide(measured_pressure, candidates);
  assert(actions.size() == 2);
  assert((actions[0].cell == veyra::core::CellId{1, 2, 2}));
  assert((actions[1].cell == veyra::core::CellId{1, 4, 4}));
  for (const auto& action : actions) {
    assert(action.action == ResolutionAction::Merge);
    assert(action.cell != candidates[0].cell);
    assert(action.cell != candidates[2].cell);
  }
}

void governor_degrades_low_value_before_more_distant_hazards() {
  ResourceGovernor governor{{.max_active_cells = 10,
                             .max_logical_bytes = 1000,
                             .near_field_radius_m = 10.0,
                             .max_actions_per_frame = 1}};
  const std::vector<GovernorCandidate> candidates{
      {.cell = {1, 100, 0}, .range_m = 90.0, .utility_score = 0.9, .active_level = 1},
      {.cell = {1, 101, 0}, .range_m = 40.0, .utility_score = 0.1, .active_level = 1}};
  std::vector<veyra::policy::GovernorAction> actions;
  for (int frame = 0; frame < 5; ++frame)
    actions = governor.decide({.active_cells = 100,
                               .logical_bytes = 10000,
                               .frame_time_ms = 20.0,
                               .target_frame_time_ms = 10.0},
                              candidates);
  assert(actions.size() == 1);
  assert(actions.front().cell == candidates[1].cell);
}

void noisy_motion_cannot_predict_refinement_and_near_field_restores_baseline() {
  LodPolicy policy{PolicyConfig::defaults().with_mode(LodMode::UtilityLod)};
  const auto noisy = policy.decide({.range_m = 70.0,
                                    .active_level = 3,
                                    .semantic_importance = 0.1,
                                    .motion = 0.1,
                                    .range_rate_mps = -100.0});
  assert(!noisy.predicted_refinement);
  const auto near = policy.decide({.range_m = 5.0, .active_level = 3, .state_cell = {3, 1, 0}});
  assert(near.requested_level == 0);
}

void promotion_telemetry_aggregates_gates_signals_and_level_transitions() {
  auto config = PolicyConfig::defaults().with_mode(LodMode::UtilityLod);
  config.utility.semantic_weight = 1.0;
  LodPolicy policy{config};
  policy.enable_promotion_telemetry(true);
  DecisionInput input{.range_m = 70.0,
                      .active_level = 3,
                      .state_cell = {3, 90, 0},
                      .semantic_importance = 1.0};
  static_cast<void>(policy.decide(input));
  input.observation_quality = input.point_density = 1.0;
  const auto decision = policy.decide(input);
  assert(decision.requested_level == 2);
  const auto& telemetry = policy.promotion_telemetry();
  assert(telemetry.decisions == 2);
  assert(telemetry.gate_passed == 1);
  assert(telemetry.gate_failed == 1);
  assert(telemetry.signal_raw_sum[1] == 2.0);
  assert(telemetry.signal_weighted_sum[1] == 2.0);
  assert(telemetry.signal_histogram[1][19] == 2);
  assert(telemetry.signal_exact_zero_count[0] == 2);
  assert(telemetry.signal_near_one_count[1] == 2);
  assert(telemetry.signal_min[1] == 1.0);
  assert(telemetry.signal_max[1] == 1.0);
  assert(telemetry.utility_histogram[0] == 1);
  assert(telemetry.utility_histogram[19] == 1);
  assert(telemetry.utility_exact_zero_count == 1);
  assert(telemetry.utility_near_one_count == 1);
  assert(telemetry.utility_min == 0.0);
  assert(telemetry.utility_max == 1.0);
  assert(telemetry.utility_above_split_count == 1);
  assert(telemetry.transition_reason_masks[1U << 1] == 1);
  assert(telemetry.promotion_transitions[3][2][3] == 1);
  assert(telemetry.safety_decisions == 0);
  assert(telemetry.predictive_decisions == 0);
}

void utility_requires_quality_and_accumulates_late_frame_hazards() {
  auto config = PolicyConfig::defaults().with_mode(LodMode::UtilityLod);
  config.utility.semantic_weight = 1.0;
  config.utility.split_consecutive_frames = 2;
  LodPolicy policy{config};
  DecisionInput high{.range_m = 70.0, .active_level = 3, .semantic_importance = 1.0};
  policy.begin_frame(1);
  assert(policy.decide(high).requested_level == 3);
  policy.begin_frame(2);
  assert(policy.decide(high).requested_level == 3);
  high.observation_quality = high.point_density = 1.0;
  assert(policy.decide(high).requested_level == 3);
  policy.begin_frame(3);
  auto low = high;
  low.semantic_importance = 0.0;
  assert(policy.decide(low).requested_level == 3);
  assert(policy.decide(high).requested_level == 2);
  assert(policy.decide(low).requested_level == 2);
  bool threw = false;
  try {
    policy.begin_frame(3);
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  assert(threw);
}

void demotion_waits_for_complete_frame_evidence() {
  auto config = PolicyConfig::defaults().with_mode(LodMode::UtilityLod);
  config.utility.semantic_weight = 1.0;
  config.utility.merge_consecutive_frames = 1;
  LodPolicy policy{config};
  DecisionInput high{.range_m = 70.0,
                     .active_level = 3,
                     .semantic_importance = 1.0,
                     .observation_quality = 1.0,
                     .point_density = 1.0};
  policy.begin_frame(1);
  assert(policy.decide(high).requested_level == 2);
  high.active_level = 2;
  auto low = high;
  low.semantic_importance = 0.0;
  policy.begin_frame(2);
  assert(policy.decide(low).requested_level == 2);
  assert(policy.decide(high).requested_level == 2);
  policy.begin_frame(3);
  assert(policy.decide(low).requested_level == 2);
  policy.begin_frame(4);
  assert(policy.decide(low).requested_level == 3);
}

void explicit_frames_bound_hysteresis_state_and_promotion_depth() {
  auto config = PolicyConfig::defaults().with_mode(LodMode::UtilityLod);
  config.utility.semantic_weight = 1.0;
  config.utility.split_consecutive_frames = 2;
  config.utility.max_promotion_depth = 2;
  config.utility.max_state_cells = 2;
  config.utility.state_ttl_frames = 2;
  LodPolicy policy{config};
  const DecisionInput high{.range_m = 70.0,
                           .active_level = 3,
                           .semantic_importance = 1.0,
                           .observation_quality = 1.0,
                           .point_density = 1.0};
  policy.begin_frame(1);
  for (int point = 0; point < 100; ++point) assert(policy.decide(high).requested_level == 3);
  policy.begin_frame(2);
  assert(policy.decide(high).requested_level == 2);
  auto refined = high;
  refined.active_level = 2;
  assert(policy.decide(refined).requested_level == 1);
  for (int cell = 1; cell < 20; ++cell) {
    auto other = high;
    other.state_cell.ix = cell;
    static_cast<void>(policy.decide(other));
  }
  assert(policy.retained_state_count() <= 2);
  policy.begin_frame(5);
  assert(policy.retained_state_count() == 0);
  assert(policy.decide(high).requested_level == 3);
  policy.reset();
  assert(policy.retained_state_count() == 0);
  policy.begin_frame(0);
  assert(policy.decide(high).requested_level == 3);
}

void governor_waits_for_sustained_overload_and_recovers_with_hysteresis() {
  ResourceGovernorConfig config{.max_active_cells = 100,
                                .max_logical_bytes = 1000,
                                .near_field_radius_m = 10.0,
                                .max_actions_per_frame = 1};
  config.max_rss_bytes = 2000;
  config.overload_consecutive_frames = 3;
  config.recovery_consecutive_frames = 2;
  ResourceGovernor governor{config};
  const std::vector<GovernorCandidate> candidates{
      {.cell = {1, 300, 0}, .range_m = 30.0, .utility_score = 0.1, .active_level = 1}};
  ResourceTelemetry telemetry{
      .active_cells = 95, .logical_bytes = 500, .frame_time_ms = 5.0, .target_frame_time_ms = 10.0};
  assert(governor.decide(telemetry, candidates).empty());
  assert(!governor.status().allow_optional_splits);
  telemetry.active_cells = 40;
  telemetry.rss_bytes = 3000;
  assert(governor.decide(telemetry, candidates).empty());
  assert(governor.decide(telemetry, candidates).empty());
  assert(governor.decide(telemetry, candidates).size() == 1);
  assert(governor.status().actions_requested == 1);
  governor.record_applied_actions(1);
  assert(governor.status().actions_applied == 1);
  telemetry.rss_bytes = 500;
  assert(governor.decide(telemetry, candidates).empty());
  assert(!governor.status().allow_optional_splits);
  assert(governor.decide(telemetry, candidates).empty());
  assert(governor.status().allow_optional_splits);
  governor.set_override(veyra::policy::GovernorOverride::Conserve);
  assert(governor.decide(telemetry, candidates).size() == 1);
  governor.set_override(veyra::policy::GovernorOverride::Disabled);
  assert(governor.decide(telemetry, candidates).empty());
  assert(governor.status().allow_optional_splits);
  governor.reset();
  assert(governor.status().actions_requested == 0);
}

void yaml_configs_drive_the_validated_policy_contract() {
  const auto root = std::filesystem::path{VEYRA_SOURCE_DIR};
  const auto distance = veyra::policy::load_policy_config(root / "configs/distance_lod.yaml");
  const auto utility = veyra::policy::load_policy_config(root / "configs/utility_lod.yaml");
  const auto governor =
      veyra::policy::load_resource_governor_config(root / "configs/resource_governor.yaml");
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

void utility_only_promotes_relative_to_the_distance_baseline() {
  // UtilityLOD may refine (lower level number) but must never coarsen beyond
  // the distance baseline, under any signal combination, quality gate state,
  // safety flag, or hysteresis age. Safety evidence may promote without the
  // observation-quality gate; nothing may demote below the baseline.
  const double ranges[] = {2.0, 9.9, 10.0, 20.0, 29.9, 30.0, 45.0, 59.9, 60.0, 75.0, 99.0};
  const double signals[] = {0.0, 0.25, 0.5, 0.75, 1.0};
  const double qualities[] = {0.0, 0.49, 0.5, 1.0};
  for (const double range : ranges) {
    for (const double geometry : signals) {
      for (const double semantic : signals) {
        for (const double motion : signals) {
          for (const double risk : signals) {
            for (const double uncertainty : signals) {
              for (const double quality : qualities) {
                for (const bool safety : {false, true}) {
                  for (const double range_rate : {0.0, -20.0}) {
                    auto config = PolicyConfig::defaults().with_mode(LodMode::UtilityLod);
                    LodPolicy policy{config};
                    policy.begin_frame(1);
                    DecisionInput input{};
                    input.range_m = range;
                    input.active_level = 3;
                    input.state_cell = {3, 7, 7};
                    input.safety_critical = safety;
                    input.geometry_complexity = geometry;
                    input.semantic_importance = semantic;
                    input.motion = motion;
                    input.traversability_risk = risk;
                    input.semantic_uncertainty = uncertainty;
                    input.observation_quality = quality;
                    input.point_density = quality;
                    input.range_rate_mps = range_rate;
                    const auto decision = policy.decide(input);
                    assert(decision.requested_level <= decision.baseline_level);
                    const bool gate_closed = quality < 0.5;
                    if (gate_closed && !safety && range_rate == 0.0 &&
                        input.active_level == decision.baseline_level) {
                      assert(decision.requested_level == decision.baseline_level);
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
  // Hysteresis-aged policies obey the same bound through promotion and decay.
  for (const double range : {5.0, 20.0, 45.0, 75.0}) {
    auto config = PolicyConfig::defaults().with_mode(LodMode::UtilityLod);
    config.utility.semantic_weight = 1.0;
    config.utility.split_consecutive_frames = 2;
    config.utility.merge_consecutive_frames = 2;
    LodPolicy policy{config};
    DecisionInput high{};
    high.range_m = range;
    high.active_level = 3;
    high.semantic_importance = 1.0;
    high.observation_quality = 1.0;
    high.point_density = 1.0;
    DecisionInput low = high;
    low.semantic_importance = 0.0;
    std::uint64_t frame = 0;
    for (int step = 0; step < 4; ++step) {
      policy.begin_frame(++frame);
      for (int level = 0; level <= 3; ++level) {
        high.active_level = level;
        const auto promoted = policy.decide(high);
        assert(promoted.requested_level <= promoted.baseline_level);
      }
    }
    for (int step = 0; step < 6; ++step) {
      policy.begin_frame(++frame);
      for (int level = 0; level <= 3; ++level) {
        low.active_level = level;
        const auto decayed = policy.decide(low);
        assert(decayed.requested_level <= decayed.baseline_level);
      }
    }
  }
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

void utility_diagnostics_separate_quality_density_and_effective_contributions() {
  const auto config = PolicyConfig::defaults().with_mode(LodMode::UtilityLod);
  LodPolicy observed{config};
  LodPolicy plain{config};
  observed.enable_promotion_telemetry(true);
  for (std::uint64_t frame = 1; frame <= 4; ++frame) {
    observed.begin_frame(frame);
    plain.begin_frame(frame);
    DecisionInput input{.range_m = 45.0, .active_level = 2,
                        .state_cell = {3, 100, 0}, .semantic_importance = 1.0,
                        .observation_quality = frame == 1 ? 0.0 : 1.0,
                        .point_density = frame == 2 ? 0.0 : 1.0,
                        .semantic_class = 6};
    const auto expected = plain.decide(input);
    const auto actual = observed.decide(input);
    assert(actual.requested_level == expected.requested_level);
    assert(actual.utility_score == expected.utility_score);
    assert(actual.action == expected.action);
  }
  const auto& telemetry = observed.promotion_telemetry();
  assert(telemetry.quality_failed == 1);
  assert(telemetry.density_failed == 1);
  assert(telemetry.support_histogram[0][0] == 1);
  assert(telemetry.support_histogram[1][0] == 1);
  assert(telemetry.class_decisions[6] == 4);
  assert(telemetry.class_gate_failed[6] == 2);
  assert(telemetry.signal_effective_weighted_sum[1] == 2 * config.utility.semantic_weight);
  assert(telemetry.decision_reasons[static_cast<std::size_t>(veyra::policy::UtilityDecisionReason::QualityGate)] == 1);
  assert(telemetry.decision_reasons[static_cast<std::size_t>(veyra::policy::UtilityDecisionReason::DensityGate)] == 1);
  // With adequate support, semantics now has its own reachable admission path;
  // recording it as score-too-low would hide the actual production decision.
  assert(telemetry.decision_reasons[static_cast<std::size_t>(veyra::policy::UtilityDecisionReason::CriticalSemanticPromotion)] == 1);
  assert(telemetry.decision_reasons[static_cast<std::size_t>(veyra::policy::UtilityDecisionReason::RetainedPromotion)] == 1);
  assert(telemetry.critical_semantic_decisions == 2);
  assert(plain.promotion_telemetry().decisions == 0);
  observed.enable_promotion_telemetry(false);
  assert(observed.promotion_telemetry().decisions == 0);
}

void utility_diagnostics_identify_dwell_admission_and_protected_baseline() {
  auto config = veyra::policy::load_policy_config(
      std::filesystem::path{VEYRA_SOURCE_DIR} / "configs" / "utility_lod.yaml");
  LodPolicy observed{config};
  observed.enable_promotion_telemetry(true);
  DecisionInput input{.range_m = 45.0, .active_level = 2,
                      .state_cell = {3, 100, 0}, .geometry_complexity = 1.0,
                      .semantic_importance = 1.0, .traversability_risk = 1.0,
                      .observation_quality = 1.0, .point_density = 1.0,
                      .semantic_class = 18};
  observed.begin_frame(1);
  assert(observed.decide(input).requested_level == 2);
  observed.begin_frame(2);
  assert(observed.decide(input).requested_level == 1);
  input.range_m = 5.0;
  input.active_level = 0;
  input.state_cell = {3, 0, 0};
  assert(observed.decide(input).requested_level == 0);
  const auto& reasons = observed.promotion_telemetry().decision_reasons;
  assert(reasons[static_cast<std::size_t>(veyra::policy::UtilityDecisionReason::InsufficientDwell)] == 1);
  assert(reasons[static_cast<std::size_t>(veyra::policy::UtilityDecisionReason::Promoted)] == 1);
  assert(reasons[static_cast<std::size_t>(veyra::policy::UtilityDecisionReason::ProtectedBaseline)] == 1);
}

}  // namespace

int run() {
  {
    const auto config = veyra::policy::load_policy_config(
        std::filesystem::path{VEYRA_SOURCE_DIR} / "configs" / "utility_lod.yaml");
    const auto& u = config.utility;
    assert(veyra::policy::semantic_importance(u, 0, 1.0) == 0.0);
    assert(veyra::policy::semantic_importance(u, 999, 1.0) == 0.0);
    assert(veyra::policy::semantic_importance(u, 9, 1.0) <
           veyra::policy::semantic_importance(u, 6, 0.9));
    assert(veyra::policy::semantic_importance(u, 6, 0.2) == 0.2);
    assert(veyra::policy::normalized_point_density(u, 0, 80.0) == 0.0);
    assert(veyra::policy::normalized_point_density(u, 1, 80.0) < u.min_point_density);
    assert(veyra::policy::normalized_point_density(u, 2, 80.0) > u.min_point_density);
    assert(veyra::policy::normalized_point_density(u, 1, 10.0) <
           veyra::policy::normalized_point_density(u, 1, 80.0));
    auto ablated = config;
    ablated.utility.semantic_weight = 0.0;
    LodPolicy geometry_only{ablated};
    for (std::uint64_t frame = 1; frame <= 3; ++frame) {
      geometry_only.begin_frame(frame);
      const auto decision = geometry_only.decide({
          .range_m = 45.0, .active_level = 2, .state_cell = {3, 100, 0},
          .semantic_importance = 1.0, .observation_quality = 1.0,
          .point_density = 1.0, .semantic_class = 6});
      assert(decision.requested_level == 2);
    }
    auto invalid = config;
    invalid.utility.semantic_class_importance[0] = 1.0;
    bool threw = false;
    try { invalid.validate(); } catch (const std::invalid_argument&) { threw = true; }
    assert(threw);
    invalid = config;
    invalid.utility.density_min_expected_count = 0.0;
    threw = false;
    try { invalid.validate(); } catch (const std::invalid_argument&) { threw = true; }
    assert(threw);
  }
  utility_diagnostics_separate_quality_density_and_effective_contributions();
  utility_diagnostics_identify_dwell_admission_and_protected_baseline();
  utility_requires_quality_and_accumulates_late_frame_hazards();
  demotion_waits_for_complete_frame_evidence();
  explicit_frames_bound_hysteresis_state_and_promotion_depth();
  governor_waits_for_sustained_overload_and_recovers_with_hysteresis();
  governor_degrades_low_value_before_more_distant_hazards();
  noisy_motion_cannot_predict_refinement_and_near_field_restores_baseline();
  promotion_telemetry_aggregates_gates_signals_and_level_transitions();
  radial_range_rate_from_velocity_is_signed_along_the_robot_offset();
  uniform_and_distance_modes_have_one_consistent_level_contract();
  invalid_policy_configuration_is_rejected();
  utility_promotes_hazards_but_gates_noisy_sparse_uncertainty();
  utility_only_promotes_relative_to_the_distance_baseline();
  utility_consumes_each_documented_signal_with_configurable_weights();
  motion_prediction_and_hysteresis_prevent_lod_thrash();
  resource_governor_uses_measured_pressure_and_preserves_near_field_and_hazards();
  yaml_configs_drive_the_validated_policy_contract();
  return 0;
}

}  // namespace policy

namespace policy_adapter {

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

void mixed_scan_preserves_support_and_topology_independent_of_order() {
  Options options;
  MapPolicyAdapter forward{PolicyKind::kUtilityLod, {}, options};
  MapPolicyAdapter reverse{PolicyKind::kUtilityLod, {}, options};
  std::vector<veyra::map::Observation> points(6);
  for (std::size_t i = 0; i < points.size(); ++i) {
    auto& point = points[i];
    point.x = 44.85 + 0.1 * (i % 3);
    point.y = i < 3 ? 4.05 : 4.85;
    point.z = static_cast<double>(i);
    point.semantic_class = i == 2 ? 6 : 9;
    point.semantic_confidence = point.observation_quality = 1.0F;
  }
  // Dwell is unchanged: the second scan is the first eligible promotion.
  for (int frame = 0; frame < 2; ++frame) {
    forward.set_window_center(0.0, 0.0);
    reverse.set_window_center(0.0, 0.0);
    forward.prepare_frame(points);
    reverse.prepare_frame(points);
    for (const auto& point : points) forward.update(point);
    for (auto it = points.rbegin(); it != points.rend(); ++it) reverse.update(*it);
  }
  const auto a = forward.snapshot();
  const auto b = reverse.snapshot();
  CHECK(a.has_no_parent_descendant_overlap());
  CHECK(b.has_no_parent_descendant_overlap());
  CHECK(a.point_count == 12);
  CHECK(b.point_count == 12);
  // All current-scan points in the promoted physical footprint must retain
  // spatial support, even when they preceded the critical observation.
  CHECK(level_at(a, 44.85, 4.05) == 1);
  CHECK(level_at(b, 44.85, 4.05) == 1);
  CHECK(level_at(a, 44.85, 4.85) == 2);
  CHECK(level_at(b, 44.85, 4.85) == 2);
  for (const auto& snapshot : {a, b}) {
    std::uint64_t supported = 0;
    for (const auto& leaf : snapshot.leaves) {
      const double resolution = veyra::core::resolution_m(leaf.id.level);
      if (static_cast<double>(leaf.id.iy) * resolution >= 4.0 &&
          static_cast<double>(leaf.id.iy) * resolution < 4.4) {
        supported += leaf.stats.count;
      }
    }
    CHECK(supported == 3); // exactly this scan, not fabricated parent history
    CHECK(snapshot.merge_count == 0);
  }
  CHECK(a.active_leaf_count == b.active_leaf_count);
  CHECK(a.split_count == b.split_count);
}

// Order-sensitive digest of every active leaf's identity and core evidence.
std::uint64_t map_digest(const veyra::map::MapSnapshot& snapshot) {
  std::uint64_t h = 1469598103934665603ULL;
  const auto mix = [&h](std::uint64_t value) {
    h ^= value;
    h *= 1099511628211ULL;
  };
  for (const auto& leaf : snapshot.leaves) {
    mix(static_cast<std::uint64_t>(leaf.id.level));
    mix(static_cast<std::uint64_t>(static_cast<std::uint32_t>(leaf.id.ix)));
    mix(static_cast<std::uint64_t>(static_cast<std::uint32_t>(leaf.id.iy)));
    mix(leaf.stats.count);
    mix(std::bit_cast<std::uint64_t>(leaf.stats.mean_z()));
    mix(leaf.stats.semantic_class);
  }
  mix(snapshot.point_count);
  mix(snapshot.split_count);
  mix(snapshot.merge_count);
  return h;
}

// A small multi-region scan: critical classes, road, out-of-window returns and
// repeated regions, with the vehicle moving so baselines change between frames.
std::vector<veyra::map::Observation> synthetic_scan(int frame) {
  std::vector<veyra::map::Observation> points;
  for (int i = 0; i < 400; ++i) {
    veyra::map::Observation point;
    const double angle = 0.0157 * i;
    const double range = 5.0 + 0.23 * (i % 300) + 0.05 * frame;
    point.x = range * std::cos(angle) + 0.4 * frame;
    point.y = range * std::sin(angle);
    point.z = 0.01 * (i % 17);
    point.semantic_class = i % 7 == 0 ? 6 : (i % 11 == 0 ? 18 : 9);
    point.semantic_confidence = 1.0F;
    point.observation_quality = i % 13 == 0 ? 0.2F : 1.0F;
    point.geometry_complexity = static_cast<float>(i % 5) * 0.2F;
    point.drivable = i % 29 == 0 ? 2 : 1;
    point.terrain_confidence = 1.0F;
    point.timestamp = static_cast<std::uint64_t>(frame + 1);
    points.push_back(point);
  }
  veyra::map::Observation outside;
  outside.x = 500.0;
  outside.y = 500.0;
  points.push_back(outside);  // rejected: outside the window
  // Repeat a few returns so regions receive several decisions per frame.
  for (int i = 0; i < 40; ++i) points.push_back(points[static_cast<std::size_t>(i * 7)]);
  return points;
}

// The prepared integration resolves each return's region once and reuses it.
// It must reproduce the per-return update() path exactly: same leaves, same
// evidence, same topology counters, same rejections.
void prepared_integration_matches_per_point_update() {
  Options options;
  MapPolicyAdapter reference{PolicyKind::kUtilityLod, {}, options};
  MapPolicyAdapter prepared{PolicyKind::kUtilityLod, {}, options};
  std::uint64_t reference_rejected = 0;
  std::uint64_t prepared_rejected = 0;
  std::uint64_t accepted = 0;
  for (int frame = 0; frame < 8; ++frame) {
    const auto points = synthetic_scan(frame);
    reference.set_window_center(0.4 * frame, 0.0);
    prepared.set_window_center(0.4 * frame, 0.0);
    reference.prepare_frame(points);
    for (const auto& point : points) (void)ingest_observation(reference, point, reference_rejected);
    prepared.prepare_frame(points);
    prepared.integrate_prepared_frame(points, prepared_rejected,
                                      [&](const veyra::map::Observation&) { ++accepted; });
    CHECK(map_digest(reference.snapshot()) == map_digest(prepared.snapshot()));
  }
  CHECK(reference_rejected == prepared_rejected);
  CHECK(reference_rejected == 8);
  CHECK(accepted == prepared.snapshot().point_count);
}

std::filesystem::path write_governor(const std::filesystem::path& directory) {
  std::filesystem::create_directories(directory);
  const auto path = directory / "governor.yaml";
  std::ofstream output{path};
  // Cell and byte budgets are far away; only frame time can create pressure.
  output << "max_active_cells: 100000000\nmax_logical_bytes: 100000000000\n"
            "near_field_radius_m: 10\nmax_actions_per_frame: 64\n"
            "target_frame_time_ms: 10\noverload_consecutive_frames: 3\n";
  return path;
}

struct GovernedRun {
  std::uint64_t digest = 0;
  bool allow_optional_splits = true;
};

// Replays the same scans while reporting a caller-chosen "measured" frame time,
// standing in for wall-clock noise between two otherwise identical runs.
GovernedRun governed_run(const std::filesystem::path& governor, bool deterministic,
                         double reported_frame_time_ms) {
  Options options;
  options.policy = "utility_lod";
  options.governor_config = governor.string();
  options.deterministic_governor = deterministic;
  MapPolicyAdapter adapter{PolicyKind::kUtilityLod, {}, options};
  CHECK(adapter.deterministic_governor() == deterministic);
  std::uint64_t rejected = 0;
  for (int frame = 0; frame < 8; ++frame) {
    const auto points = synthetic_scan(frame);
    adapter.set_window_center(0.4 * frame, 0.0);
    adapter.prepare_frame(points);
    adapter.integrate_prepared_frame(points, rejected, [](const veyra::map::Observation&) {});
    (void)adapter.apply_governor(adapter.snapshot(), reported_frame_time_ms);
  }
  return {map_digest(adapter.snapshot()), adapter.governor_status()->allow_optional_splits};
}

// Determinism: in deterministic mode the governor's decisions, and so the map,
// depend only on the input stream -- not on how long the frames took.
void deterministic_governor_ignores_wall_clock_evidence() {
  const auto directory =
      std::filesystem::temp_directory_path() / "veyra-policy-adapter-determinism";
  const auto governor = write_governor(directory);
  const auto fast = governed_run(governor, true, 0.5);
  const auto slow = governed_run(governor, true, 5000.0);
  const auto again = governed_run(governor, true, 0.5);
  CHECK(fast.digest == slow.digest);
  CHECK(fast.digest == again.digest);
  CHECK(fast.allow_optional_splits && slow.allow_optional_splits);
  // Control: with wall-clock feedback the same stream yields a different map,
  // proving the test exercises the path deterministic mode removes.
  const auto wall_fast = governed_run(governor, false, 0.5);
  const auto wall_slow = governed_run(governor, false, 5000.0);
  CHECK(wall_fast.digest == fast.digest);
  CHECK(!wall_slow.allow_optional_splits);
  CHECK(wall_fast.digest != wall_slow.digest);
  std::filesystem::remove_all(directory);
}
} // namespace

int run() {
  prepared_integration_matches_per_point_update();
  deterministic_governor_ignores_wall_clock_evidence();
  selective_semantics_refine_actual_world_regions();
  sparse_far_and_low_confidence_do_not_refine();
  complete_frame_support_is_order_independent();
  mixed_scan_preserves_support_and_topology_independent_of_order();
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
  return 0;
}

}  // namespace policy_adapter

namespace near_field_protection {

// Invariant test for the safety floor: cells within kNearFieldRadiusM of the
// vehicle are never coarsened, whatever any policy asks.
//
// This is a refusal enforced by the pass, not a rule DistanceLOD happens to
// obey -- a future UtilityLOD or a resource governor under memory pressure
// must be unable to coarsen the near field. The tests therefore drive it with
// a deliberately hostile policy rather than the distance one.
//
// Each group names the production bug it catches.


namespace {

using veyra::core::CellId;
using veyra::map::MapWindow;
using veyra::map::PassContext;
using veyra::map::TileGrid;

// Uniform40 asks for level 3 everywhere, so it tries to coarsen every cell in
// the map including the near field. That is exactly the request the floor
// exists to refuse.
veyra::policy::LodPolicy hostilePolicy() {
  return veyra::policy::LodPolicy{
      veyra::policy::PolicyConfig::defaults().with_mode(veyra::policy::LodMode::Uniform40)};
}

// 15. A hostile policy cannot coarsen a cell inside the near-field radius.
//     Catches: near-field protection missing entirely, and protection applied
//     as a policy preference rather than a refusal -- a policy that ignores it
//     would then win.
void checkHostilePolicyCannotCoarsenNearField() {
  TileGrid grid{MapWindow{0.0, 0.0, 60.0}};
  // A near cell, well inside 10 m, and a far cell well outside it.
  const CellId near_cell{0, 20, 0};  // 1.0 m out
  const CellId far_cell{0, 800, 0};  // 40 m out
  grid.findOrCreate(near_cell);
  grid.findOrCreate(far_cell);

  veyra::policy::LodPolicy pol = hostilePolicy();
  const veyra::map::PolicyStats s = veyra::map::applyPolicy(grid, pol, PassContext{0.0, 0.0});

  CHECK(s.near_field_protected > 0);
  // The near cell is still there, still at level 0.
  CHECK(grid.find(near_cell) != nullptr);
  const veyra::map::LeafHit hit = veyra::map::activeLeafCovering(grid, 1.0, 0.0);
  CHECK(hit.found);
  CHECK(hit.id.level == 0);
}

// A square block of level-0 cells, so whole sibling groups exist and a merge
// has something legal to collapse.
void fillBlock(TileGrid& grid, std::int32_t x0, std::int32_t y0, std::int32_t n) {
  for (std::int32_t iy = y0; iy < y0 + n; ++iy) {
    for (std::int32_t ix = x0; ix < x0 + n; ++ix) {
      grid.findOrCreate(CellId{0, ix, iy});
    }
  }
}

// 16. The near field follows the vehicle, not the origin. After the vehicle
//     has driven away, the block it now stands in is protected and the block
//     back at the origin is not.
//     Catches: a distance measured from the world origin, which looks correct
//     for exactly as long as the vehicle never moves -- the same class of bug
//     as the fixed map box PR D removed.
void checkNearFieldFollowsTheVehicle() {
  TileGrid grid{MapWindow{0.0, 0.0, 80.0}};
  fillBlock(grid, 0, 0, 8);    // at the origin
  fillBlock(grid, 800, 0, 8);  // 40 m out
  CHECK(grid.statistics().occupied_cells == 128);

  grid.recenter(40.0, 0.0);
  veyra::policy::LodPolicy pol = hostilePolicy();
  const veyra::map::PolicyStats s = veyra::map::applyPolicy(grid, pol, PassContext{40.0, 0.1});

  CHECK(s.near_field_protected > 0);
  CHECK(s.merges > 0);

  // Where the vehicle stands, the map is still at its finest ...
  const veyra::map::LeafHit near_hit = veyra::map::activeLeafCovering(grid, 40.1, 0.1);
  CHECK(near_hit.found);
  CHECK(near_hit.id.level == 0);

  // ... and back at the origin, 40 m away, the hostile policy was allowed to
  // coarsen. Both halves matter: measuring from the origin inverts them.
  const veyra::map::LeafHit far_hit = veyra::map::activeLeafCovering(grid, 0.1, 0.1);
  CHECK(far_hit.found);
  CHECK(far_hit.id.level > 0);
}

}  // namespace

int run() {
  checkHostilePolicyCannotCoarsenNearField();
  checkNearFieldFollowsTheVehicle();
  return 0;
  return 0;
}

}  // namespace near_field_protection

namespace resolution_pass {

// Invariant test for the resolution policy pass: the point of the project.
// Until this exists the map is a competent uniform grid; after it, resolution
// follows distance.
//
// The policy itself is veyra::policy::LodPolicy, which already carries the
// DistanceLOD bands. This file tests the bands' contract and the pass that
// applies them to the grid. Each group names the production bug it catches.


namespace {

using veyra::core::CellId;
using veyra::map::MapWindow;
using veyra::map::PassContext;
using veyra::map::PolicyStats;
using veyra::map::TileGrid;
using veyra::policy::LodMode;
using veyra::policy::LodPolicy;
using veyra::policy::PolicyConfig;

LodPolicy distancePolicy() {
  return LodPolicy{PolicyConfig::defaults().with_mode(LodMode::DistanceLod)};
}

int levelAt(LodPolicy& pol, double range_m) {
  veyra::policy::DecisionInput in;
  in.range_m = range_m;
  in.active_level = 0;
  in.state_cell = CellId{0, 0, 0};
  return pol.decide(in).baseline_level;
}

void fillStrip(TileGrid& grid, std::int32_t ix_end) {
  for (std::int32_t iy = 0; iy < 8; ++iy) {
    for (std::int32_t ix = 0; ix < ix_end; ++ix) {
      grid.findOrCreate(CellId{0, ix, iy});
    }
  }
}

// Runs the pass until it stops doing work, or gives up. Returns the number of
// passes; the caller asserts it converged.
std::size_t runToConvergence(TileGrid& grid, LodPolicy& pol, const PassContext& ctx,
                             std::size_t max_passes) {
  for (std::size_t i = 1; i <= max_passes; ++i) {
    const PolicyStats s = veyra::map::applyPolicy(grid, pol, ctx);
    if (s.splits == 0 && s.merges == 0) {
      return i;
    }
  }
  return max_passes + 1;
}

// 1. The distance bands, and their half-open boundaries. Exactly 10.0 m is in
//    the second band, not the first, matching [min, max) everywhere else in
//    this codebase.
//    Catches: a boundary comparison flipped to <=, which would silently move
//    a whole band's worth of cells by one level.
void checkDistanceBands() {
  LodPolicy pol = distancePolicy();
  CHECK(levelAt(pol, 0.0) == 0);
  CHECK(levelAt(pol, 9.999) == 0);
  CHECK(levelAt(pol, 10.0) == 1);  // half-open: the boundary belongs upward
  CHECK(levelAt(pol, 29.999) == 1);
  CHECK(levelAt(pol, 30.0) == 2);
  CHECK(levelAt(pol, 59.999) == 2);
  CHECK(levelAt(pol, 60.0) == 3);
  CHECK(levelAt(pol, 99.0) == 3);
}

// 2. The thresholds in code match configs/distance_lod.yaml, which reads
//    ranges_m: [[0, 10], [10, 30], [30, 60], [60, 100]].
//    The YAML is documentation -- parsing it would be a new dependency, which
//    AGENTS.md gates. This assertion is what stops the two diverging silently.
//    Catches: a threshold edited in one place only.
void checkThresholdsMatchTheConfigFile() {
  const PolicyConfig cfg = PolicyConfig::defaults();
  CHECK(cfg.distance_boundaries_m[0] == 10.0);
  CHECK(cfg.distance_boundaries_m[1] == 30.0);
  CHECK(cfg.distance_boundaries_m[2] == 60.0);
  CHECK(cfg.max_range_m == 100.0);
}

// 3. A policy asking for something the grid will not do leaves the map
//    unchanged, and the refusal is counted rather than swallowed.
//    Catches: a pass that honours a request split or merge declined, which
//    would break invariant 2 while reporting success.
void checkRefusalsAreCountedNotSwallowed() {
  TileGrid grid{MapWindow{0.0, 0.0, 80.0}};
  // A lone cell 40 m out: Uniform40 wants it coarser, but merge needs all four
  // siblings and there is only one, so the grid must refuse.
  grid.findOrCreate(CellId{0, 800, 0});
  const veyra::map::GridStats before = grid.statistics();

  LodPolicy hostile{PolicyConfig::defaults().with_mode(LodMode::Uniform40)};
  const PolicyStats s = veyra::map::applyPolicy(grid, hostile, PassContext{0.0, 0.0});

  CHECK(s.refused > 0);
  CHECK(s.merges == 0);
  const veyra::map::GridStats after = grid.statistics();
  CHECK(after.occupied_cells == before.occupied_cells);
  CHECK(grid.find(CellId{0, 800, 0}) != nullptr);
}

// 4. The point of the project: a uniform level-0 strip becomes fine near the
//    vehicle and coarse far away.
//    Catches: a pass that does nothing, and one that coarsens uniformly --
//    either of which leaves a map that is not adaptive.
void checkLevelDistributionBecomesAdaptive() {
  TileGrid grid{MapWindow{0.0, 0.0, 120.0}};
  fillStrip(grid, 1600);  // 0 .. 80 m of level-0 cells, 8 rows
  const std::size_t uniform_cells = grid.statistics().occupied_cells;
  CHECK(uniform_cells == 8U * 1600U);

  LodPolicy pol = distancePolicy();
  const std::size_t passes = runToConvergence(grid, pol, PassContext{0.0, 0.2}, 400);
  CHECK(passes <= 400);

  std::array<std::size_t, 4> per_level{};
  grid.forEachActiveLeaf([&per_level](CellId id, const veyra::map::Cell&) {
    CHECK(id.level >= 0 && id.level <= 3);
    ++per_level[static_cast<std::size_t>(id.level)];
  });

  // Every band is represented, and the map shrank.
  CHECK(per_level[0] > 0);
  CHECK(per_level[1] > 0);
  CHECK(per_level[2] > 0);
  CHECK(per_level[3] > 0);
  CHECK(grid.statistics().occupied_cells < uniform_cells);

  // Resolution actually follows distance: near is finest, far is coarsest.
  const veyra::map::LeafHit near_hit = veyra::map::activeLeafCovering(grid, 2.0, 0.2);
  CHECK(near_hit.found);
  CHECK(near_hit.id.level == 0);
  const veyra::map::LeafHit far_hit = veyra::map::activeLeafCovering(grid, 70.0, 0.2);
  CHECK(far_hit.found);
  CHECK(far_hit.id.level == 3);
}

// 5. Hysteresis. A vehicle oscillating across a band boundary must not split
//    and merge the same cells on alternate frames.
//    Catches: a zero margin, which turns a stationary boundary into
//    allocation churn on the hot path -- AGENTS.md forbids it.
void checkHysteresisPreventsThrash() {
  TileGrid grid{MapWindow{0.0, 0.0, 60.0}};
  fillStrip(grid, 400);  // 0 .. 20 m, spanning the 10 m boundary

  LodPolicy pol = distancePolicy();
  CHECK(runToConvergence(grid, pol, PassContext{0.0, 0.2}, 400) <= 400);

  // Now jitter the vehicle either side of the boundary, indefinitely.
  //
  // The property is that the work *stops*, not that it never starts. A margin
  // rule makes oscillation converge: the first jitter can still move cells
  // that were sitting inside the margin, and once moved they stay moved,
  // because coming back would have to clear the margin in the other
  // direction. Measured here: 16 merges on the second frame, then nothing,
  // for as long as the jitter continues.
  //
  // Making even that first adjustment free would need a per-cell dwell
  // counter, which is state the pass deliberately does not keep.
  std::size_t settling = 0;
  std::size_t after_settling = 0;
  std::size_t held = 0;
  for (int frame = 0; frame < 20; ++frame) {
    const double dx = (frame % 2 == 0) ? 0.4 : -0.4;
    const PolicyStats s = veyra::map::applyPolicy(grid, pol, PassContext{dx, 0.2});
    const std::size_t ops = s.splits + s.merges;
    if (frame < 2) {
      settling += ops;
    } else {
      after_settling += ops;
    }
    held += s.held_by_hysteresis;
  }
  // Settled, and stays settled however long the vehicle keeps jittering.
  CHECK(after_settling == 0);
  // The margin is genuinely engaging rather than the map simply having
  // nothing left to do -- cells are being held back on every frame.
  CHECK(held > 0);
  CHECK(settling < 64);
}

// 6. The per-frame cap bounds the work, and the backlog is reported rather
//    than dropped.
//    Catches: a cap that is ignored, which turns a map-wide reshuffle into a
//    latency spike; and one that silently discards the remainder.
void checkPerFrameCapIsRespected() {
  TileGrid grid{MapWindow{0.0, 0.0, 120.0}};
  fillStrip(grid, 1600);

  LodPolicy pol = distancePolicy();
  const PolicyStats s = veyra::map::applyPolicy(grid, pol, PassContext{0.0, 0.2});

  CHECK(s.splits + s.merges <= veyra::map::kMaxOpsPerPass);
  CHECK(s.deferred > 0);  // far more work than one pass may do
  CHECK(s.examined > s.splits + s.merges);
}

// 7. Idempotence. Once converged, a pass with no motion does nothing.
//    Catches: a pass that keeps toggling cells, which would burn the operation
//    budget every frame while making no progress.
void checkIdempotentWhenConverged() {
  TileGrid grid{MapWindow{0.0, 0.0, 120.0}};
  fillStrip(grid, 800);

  LodPolicy pol = distancePolicy();
  CHECK(runToConvergence(grid, pol, PassContext{0.0, 0.2}, 400) <= 400);

  const veyra::map::GridStats before = grid.statistics();
  const PolicyStats again = veyra::map::applyPolicy(grid, pol, PassContext{0.0, 0.2});
  CHECK(again.splits == 0);
  CHECK(again.merges == 0);
  const veyra::map::GridStats after = grid.statistics();
  CHECK(after.occupied_cells == before.occupied_cells);
  CHECK(after.tiles == before.tiles);
}

// Invariant 2, checked directly: no active cell may sit beneath another
// active cell. Returns the number of violations so the caller can report it.
std::size_t countAncestorViolations(const TileGrid& grid) {
  std::size_t bad = 0;
  grid.forEachActiveLeaf([&grid, &bad](CellId id, const veyra::map::Cell&) {
    CellId up = id;
    while (up.level < veyra::map::kMaxLevel) {
      up = veyra::core::parentOf(up);
      if (grid.find(up) != nullptr) {
        ++bad;
        return;
      }
    }
  });
  return bad;
}

veyra::map::Observation point(double x, double y) {
  veyra::map::Observation o;
  o.x = x;
  o.y = y;
  o.z = 0.1F;
  o.semantic_class = 1;
  o.semantic_confidence = 1.0F;
  return o;
}

// 17. The whole loop over a simulated drive: integrate, recentre, apply the
//     policy, repeatedly. Memory stays bounded, and the exclusivity invariant
//     holds at every single step.
//     Catches: any interaction between fusion, the window and the pass that
//     is invisible when each is tested alone.
void checkFullLoopOverADrive() {
  constexpr double kR = 25.0;
  TileGrid grid{MapWindow{0.0, 0.0, kR}};
  LodPolicy pol = distancePolicy();

  std::size_t max_cells = 0;
  std::size_t max_bytes = 0;
  std::size_t worst_violation = 0;

  for (int step = 0; step <= 120; ++step) {
    const double vx = static_cast<double>(step);
    grid.recenter(vx, 0.0);

    // A swath, not a single row. A one-cell-tall line can never be merged --
    // merge needs all four siblings -- so a line-shaped drive would coarsen
    // nothing and this test would pass without exercising the interaction it
    // exists to cover.
    std::vector<veyra::map::Observation> batch;
    // One point per 5 cm cell. At coarser spacing the swath is a comb with no
    // 2x2 sibling blocks, merge refuses every request, and this test passes
    // while coarsening nothing at all.
    for (int k = -400; k <= 400; ++k) {
      for (int r = 0; r < 8; ++r) {
        batch.push_back(point(vx + 0.05 * static_cast<double>(k), 0.05 * static_cast<double>(r)));
      }
    }
    veyra::map::integrate(grid, batch, static_cast<std::uint32_t>(step));
    veyra::map::applyPolicy(grid, pol, PassContext{vx, 0.0});

    const veyra::map::GridStats gs = grid.statistics();
    max_cells = std::max(max_cells, gs.occupied_cells);
    max_bytes = std::max(max_bytes, gs.allocated_bytes);
    worst_violation = std::max(worst_violation, countAncestorViolations(grid));
  }

  // Invariant 2 holds at every step of a 200 m drive.
  CHECK(worst_violation == 0);

  // ... and the detector above can actually fire, so that zero means
  // something. A cell placed directly beneath an active parent is exactly the
  // violation being ruled out.
  {
    TileGrid probe{MapWindow{0.0, 0.0, 50.0}};
    probe.findOrCreate(CellId{1, 5, 5});
    probe.findOrCreate(CellId{0, 10, 10});  // a child of the cell above
    CHECK(countAncestorViolations(probe) > 0);
  }

  // The drive really did coarsen -- otherwise the interaction above is untested.
  std::array<std::size_t, 4> per_level{};
  grid.forEachActiveLeaf([&per_level](CellId id, const veyra::map::Cell&) {
    ++per_level[static_cast<std::size_t>(id.level)];
  });
  CHECK(per_level[1] + per_level[2] + per_level[3] > 0);

  // Bounded: a disc of radius 25 m holds at most pi * 25^2 / 0.05^2 cells even
  // if every one of them were at level 0.
  CHECK(max_cells <= 785399U);
  CHECK(grid.statistics().occupied_cells > 0);
  CHECK(max_bytes > 0);

  // Still mapping 120 m from where it started.
  const veyra::map::LeafHit hit = veyra::map::activeLeafCovering(grid, 120.0, 0.1);
  CHECK(hit.found);
}

}  // namespace

int run() {
  checkDistanceBands();
  checkThresholdsMatchTheConfigFile();
  checkRefusalsAreCountedNotSwallowed();
  checkLevelDistributionBecomesAdaptive();
  checkHysteresisPreventsThrash();
  checkPerFrameCapIsRespected();
  checkIdempotentWhenConverged();
  checkFullLoopOverADrive();
  return 0;
  return 0;
}

}  // namespace resolution_pass

int main(int argc, char** argv) {
  if (argc == 2) {
    const std::string_view suite{argv[1]};
    if (suite == "policy") return policy::run();
    if (suite == "policy_adapter") return policy_adapter::run();
    if (suite == "near_field_protection") return near_field_protection::run();
    if (suite == "resolution_pass") return resolution_pass::run();
  }
  std::fputs("Select a registered CTest suite.\n", stderr);
  return 2;
}
