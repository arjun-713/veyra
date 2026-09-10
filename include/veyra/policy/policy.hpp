#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <unordered_map>
#include <vector>

#include "veyra/core/types.hpp"

namespace veyra::policy {

enum class LodMode { Uniform5, Uniform40, DistanceLod, UtilityLod };
enum class ResolutionAction { Keep, Split, Merge };

struct DecisionInput {
  double range_m = 0.0;
  int active_level = 0;
  core::CellId state_cell{3, 0, 0};
  bool safety_critical = false;
  double geometry_complexity = 0.0;
  double semantic_importance = 0.0;
  double motion = 0.0;
  double traversability_risk = 0.0;
  double semantic_uncertainty = 0.0;
  double observation_quality = 0.0;
  double point_density = 0.0;
  double range_rate_mps = 0.0;
};

struct PolicyDecision {
  int baseline_level = 0;
  int requested_level = 0;
  bool uncertainty_gate_passed = false;
  bool predicted_refinement = false;
  double utility_score = 0.0;
  ResolutionAction action = ResolutionAction::Keep;
};

struct UtilityConfig {
  double geometry_weight = 0.20;
  double semantic_weight = 0.30;
  double motion_weight = 0.15;
  double traversability_risk_weight = 0.25;
  double uncertainty_weight = 0.10;
  double min_observation_quality = 0.50;
  double min_point_density = 0.50;
  double ema_alpha = 1.0;
  double split_threshold = 0.50;
  double merge_threshold = 0.30;
  int split_consecutive_frames = 1;
  int merge_consecutive_frames = 1;
  int cooldown_frames = 0;
  int max_level_changes_per_decision = 1;
  double prediction_horizon_s = 1.0;
};

struct PolicyConfig {
  LodMode mode = LodMode::DistanceLod;
  std::array<double, 3> distance_boundaries_m{10.0, 30.0, 60.0};
  double max_range_m = 100.0;
  UtilityConfig utility{};

  [[nodiscard]] static PolicyConfig defaults();
  [[nodiscard]] PolicyConfig with_mode(LodMode requested_mode) const;
  void validate() const;
};

class LodPolicy {
 public:
  explicit LodPolicy(PolicyConfig config = PolicyConfig::defaults());
  [[nodiscard]] PolicyDecision decide(const DecisionInput& input);

 private:
  struct AdaptationState {
    bool initialized = false;
    bool promoted = false;
    double ema = 0.0;
    int high_frames = 0;
    int low_frames = 0;
    int cooldown_remaining = 0;
    int promoted_level = 3;
  };

  PolicyConfig config_;
  std::unordered_map<core::CellId, AdaptationState, core::CellIdHash> states_;
};

struct ResourceGovernorConfig {
  std::size_t max_active_cells = 1;
  std::size_t max_logical_bytes = 1;
  double near_field_radius_m = 10.0;
  std::size_t max_actions_per_frame = 1;

  void validate() const;
};

struct ResourceTelemetry {
  std::size_t active_cells = 0;
  std::size_t logical_bytes = 0;
  double frame_time_ms = 0.0;
  double target_frame_time_ms = 0.0;
};

struct GovernorCandidate {
  core::CellId cell;
  double range_m = 0.0;
  double utility_score = 0.0;
  int active_level = 0;
  bool safety_critical = false;
};

struct GovernorAction {
  core::CellId cell;
  ResolutionAction action = ResolutionAction::Keep;
};

class ResourceGovernor {
 public:
  explicit ResourceGovernor(ResourceGovernorConfig config);
  [[nodiscard]] std::vector<GovernorAction> decide(
      const ResourceTelemetry& telemetry, const std::vector<GovernorCandidate>& candidates) const;

 private:
  ResourceGovernorConfig config_;
};

[[nodiscard]] PolicyConfig load_policy_config(const std::filesystem::path& path);
[[nodiscard]] ResourceGovernorConfig load_resource_governor_config(const std::filesystem::path& path);

// Radial component of a world-frame XY velocity along the robot-to-point
// offset. Negative means approaching, positive means receding. A zero-length
// offset or any non-finite input fails safe to exactly zero so predictive
// refinement is never derived from garbage velocity evidence.
[[nodiscard]] double radial_range_rate_mps(double velocity_x, double velocity_y,
                                           double offset_x, double offset_y) noexcept;

}  // namespace veyra::policy
