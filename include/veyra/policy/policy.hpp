#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <optional>
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

// Fixed-size, opt-in aggregates for benchmark diagnostics. Transition bins are
// indexed by active, requested, and baseline level respectively.
struct PromotionTelemetry {
  std::uint64_t decisions = 0;
  std::uint64_t gate_passed = 0;
  std::uint64_t gate_failed = 0;
  std::uint64_t safety_decisions = 0;
  std::uint64_t predictive_decisions = 0;
  std::uint64_t budget_suppressed = 0;
  std::uint64_t governor_actions_requested = 0;
  std::uint64_t governor_actions_applied = 0;
  std::array<std::array<std::array<std::uint64_t, 4>, 4>, 4> promotion_transitions{};
  std::array<double, 5> signal_raw_sum{};
  std::array<double, 5> signal_weighted_sum{};
  std::array<double, 5> signal_min{};
  std::array<double, 5> signal_max{};
  // Twenty equal-width bins on [0,1], with 1.0 in the final bin.
  std::array<std::array<std::uint64_t, 20>, 5> signal_histogram{};
  std::array<std::uint64_t, 5> signal_exact_zero_count{};
  std::array<std::uint64_t, 5> signal_near_one_count{};
  std::array<std::uint64_t, 20> utility_histogram{};
  std::uint64_t utility_exact_zero_count = 0;
  std::uint64_t utility_near_one_count = 0;
  double utility_min = 0.0;
  double utility_max = 0.0;
  std::uint64_t utility_above_split_count = 0;
  std::uint64_t utility_below_merge_count = 0;
  // Bits 0-4: geometry, semantic, motion, terrain, uncertainty;
  // bit 5: safety override; bit 6: predictive refinement.
  std::array<std::uint64_t, 128> transition_reason_masks{};
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
  int max_promotion_depth = 1;
  std::size_t max_state_cells = 65536;
  std::uint64_t state_ttl_frames = 120;
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
  // Explicit frame IDs make hysteresis independent of point count. IDs must increase.
  void begin_frame(std::uint64_t frame_id);
  void reset() noexcept;
  void enable_promotion_telemetry(bool enabled) noexcept;
  void record_promotion_budget_effects(std::uint64_t suppressed,
                                      std::uint64_t actions_requested,
                                      std::uint64_t actions_applied) noexcept;
  [[nodiscard]] const PromotionTelemetry& promotion_telemetry() const noexcept {
    return promotion_telemetry_;
  }
  [[nodiscard]] std::size_t retained_state_count() const noexcept { return states_.size(); }

 private:
  struct TemporalState {
    bool initialized = false;
    bool promoted = false;
    double ema = 0.0;
    int high_frames = 0;
    int low_frames = 0;
    int cooldown_remaining = 0;
    int promoted_level = 3;
  };

  struct AdaptationState {
    TemporalState current{};
    TemporalState frame_start{};
    std::uint64_t last_frame = 0;
    bool seen = false;
    double frame_score = 0.0;
    bool frame_predictive = false;
    bool frame_safety = false;
    int frame_goal = 3;
    bool frame_promotion_counted = false;
  };

  PolicyConfig config_;
  std::optional<std::uint64_t> frame_id_;
  std::uint64_t implicit_frame_id_ = 0;
  std::unordered_map<core::CellId, AdaptationState, core::CellIdHash> states_;
  bool promotion_telemetry_enabled_ = false;
  PromotionTelemetry promotion_telemetry_{};
};

struct ResourceGovernorConfig {
  std::size_t max_active_cells = 1;
  std::size_t max_logical_bytes = 1;
  double near_field_radius_m = 10.0;
  std::size_t max_actions_per_frame = 1;
  std::size_t max_rss_bytes = 0;  // Zero disables the RSS budget.
  double target_frame_time_ms = 100.0;
  double pressure_ratio = 0.90;
  double recovery_ratio = 0.75;
  int overload_consecutive_frames = 3;
  int recovery_consecutive_frames = 5;

  void validate() const;
};

struct ResourceTelemetry {
  std::size_t active_cells = 0;
  std::size_t logical_bytes = 0;
  double frame_time_ms = 0.0;
  double target_frame_time_ms = 0.0;  // Zero uses the configured target.
  std::optional<std::size_t> rss_bytes = std::nullopt;
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

enum class GovernorState { Normal, ApproachingBudget, Overloaded, Recovering, Disabled };
enum class GovernorOverride { Automatic, Disabled, Conserve };

struct GovernorStatus {
  GovernorState state = GovernorState::Normal;
  bool allow_optional_splits = true;
  int overload_frames = 0;
  int recovery_frames = 0;
  std::uint64_t interventions = 0;
  std::uint64_t actions_requested = 0;
  std::uint64_t actions_applied = 0;
};

class ResourceGovernor {
 public:
  explicit ResourceGovernor(ResourceGovernorConfig config);
  [[nodiscard]] std::vector<GovernorAction> decide(
      const ResourceTelemetry& telemetry, const std::vector<GovernorCandidate>& candidates);
  [[nodiscard]] const GovernorStatus& status() const noexcept { return status_; }
  [[nodiscard]] const ResourceGovernorConfig& config() const noexcept { return config_; }
  void reset() noexcept;
  void set_override(GovernorOverride mode) noexcept;
  void record_applied_actions(std::size_t count);

 private:
  ResourceGovernorConfig config_;
  GovernorStatus status_{};
  GovernorOverride override_ = GovernorOverride::Automatic;
};

[[nodiscard]] PolicyConfig load_policy_config(const std::filesystem::path& path);
[[nodiscard]] ResourceGovernorConfig load_resource_governor_config(
    const std::filesystem::path& path);

// Radial component of a world-frame XY velocity along the robot-to-point
// offset. Negative means approaching, positive means receding. A zero-length
// offset or any non-finite input fails safe to exactly zero so predictive
// refinement is never derived from garbage velocity evidence.
[[nodiscard]] double radial_range_rate_mps(double velocity_x, double velocity_y, double offset_x,
                                           double offset_y) noexcept;

}  // namespace veyra::policy
