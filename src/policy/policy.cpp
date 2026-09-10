#include "veyra/policy/policy.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>

namespace veyra::policy {

double radial_range_rate_mps(double velocity_x, double velocity_y,
                             double offset_x, double offset_y) noexcept {
  if (!std::isfinite(velocity_x) || !std::isfinite(velocity_y) ||
      !std::isfinite(offset_x) || !std::isfinite(offset_y)) {
    return 0.0;
  }
  const double range = std::hypot(offset_x, offset_y);
  if (!(range > 0.0) || !std::isfinite(range)) {
    return 0.0;
  }
  return (velocity_x * offset_x + velocity_y * offset_y) / range;
}

namespace {

bool unit_interval(const double value) {
  return std::isfinite(value) && value >= 0.0 && value <= 1.0;
}

void validate_signal(const double value, const char* name) {
  if (!unit_interval(value)) {
    throw std::invalid_argument(std::string{name} + " must be in [0,1]");
  }
}

int distance_level(const PolicyConfig& config, const double range_m) {
  if (range_m < config.distance_boundaries_m[0]) return 0;
  if (range_m < config.distance_boundaries_m[1]) return 1;
  if (range_m < config.distance_boundaries_m[2]) return 2;
  return 3;
}

ResolutionAction action_for(const int active_level, const int requested_level) {
  if (requested_level < active_level) return ResolutionAction::Split;
  if (requested_level > active_level) return ResolutionAction::Merge;
  return ResolutionAction::Keep;
}

int bounded_level(const int active_level, const int target_level, const int maximum_change) {
  if (target_level < active_level) return std::max(target_level, active_level - maximum_change);
  if (target_level > active_level) return std::min(target_level, active_level + maximum_change);
  return active_level;
}

void validate_telemetry(const ResourceTelemetry& telemetry) {
  if (!std::isfinite(telemetry.frame_time_ms) || telemetry.frame_time_ms < 0.0 ||
      !std::isfinite(telemetry.target_frame_time_ms) || telemetry.target_frame_time_ms <= 0.0) {
    throw std::invalid_argument("resource telemetry must contain measured non-negative frame time and a target");
  }
}

std::string trim(std::string value) {
  const auto first = value.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) return {};
  const auto last = value.find_last_not_of(" \t\r\n");
  return value.substr(first, last - first + 1);
}

std::unordered_map<std::string, std::string> parse_flat_yaml(const std::filesystem::path& path) {
  std::ifstream stream{path};
  if (!stream) throw std::invalid_argument("cannot open policy config: " + path.string());

  std::unordered_map<std::string, std::string> values;
  std::string line;
  std::string section;
  while (std::getline(stream, line)) {
    const auto comment = line.find('#');
    const auto without_comment = trim(line.substr(0, comment));
    if (without_comment.empty()) continue;
    const auto colon = without_comment.find(':');
    if (colon == std::string::npos) throw std::invalid_argument("invalid YAML entry in " + path.string());
    const auto key = trim(without_comment.substr(0, colon));
    const auto value = trim(without_comment.substr(colon + 1));
    if (key.empty()) throw std::invalid_argument("empty YAML key in " + path.string());
    if (value.empty()) {
      section = key;
      continue;
    }
    const auto qualified = line.empty() || line.front() == ' ' ? section + "." + key : key;
    if (!values.emplace(qualified, value).second) {
      throw std::invalid_argument("duplicate YAML key " + qualified);
    }
  }
  return values;
}

double yaml_double(const std::string& value, const std::string& key) {
  std::size_t consumed = 0;
  try {
    const double parsed = std::stod(value, &consumed);
    if (consumed != value.size() || !std::isfinite(parsed)) throw std::invalid_argument("invalid");
    return parsed;
  } catch (const std::exception&) {
    throw std::invalid_argument("invalid numeric value for " + key);
  }
}

std::size_t yaml_size(const std::string& value, const std::string& key) {
  std::size_t consumed = 0;
  try {
    const auto parsed = std::stoull(value, &consumed);
    if (consumed != value.size()) throw std::invalid_argument("invalid");
    return static_cast<std::size_t>(parsed);
  } catch (const std::exception&) {
    throw std::invalid_argument("invalid unsigned value for " + key);
  }
}

int yaml_int(const std::string& value, const std::string& key) {
  std::size_t consumed = 0;
  try {
    const int parsed = std::stoi(value, &consumed);
    if (consumed != value.size()) throw std::invalid_argument("invalid");
    return parsed;
  } catch (const std::exception&) {
    throw std::invalid_argument("invalid integer value for " + key);
  }
}

std::array<double, 3> yaml_boundaries(const std::string& value) {
  if (value.size() < 5 || value.front() != '[' || value.back() != ']') {
    throw std::invalid_argument("distance_boundaries_m must have three values");
  }
  std::array<double, 3> boundaries{};
  std::stringstream values{value.substr(1, value.size() - 2)};
  std::string item;
  std::size_t index = 0;
  while (std::getline(values, item, ',')) {
    if (index == boundaries.size()) throw std::invalid_argument("distance_boundaries_m must have three values");
    boundaries[index++] = yaml_double(trim(item), "distance_boundaries_m");
  }
  if (index != boundaries.size()) throw std::invalid_argument("distance_boundaries_m must have three values");
  return boundaries;
}

void require_keys(const std::unordered_map<std::string, std::string>& values,
                  const std::unordered_set<std::string>& expected) {
  for (const auto& key : expected) {
    if (!values.contains(key)) throw std::invalid_argument("missing required policy config key " + key);
  }
  for (const auto& [key, value] : values) {
    static_cast<void>(value);
    if (!expected.contains(key)) throw std::invalid_argument("unknown policy config key " + key);
  }
}

}  // namespace

PolicyConfig PolicyConfig::defaults() { return {}; }

PolicyConfig PolicyConfig::with_mode(const LodMode requested_mode) const {
  auto copy = *this;
  copy.mode = requested_mode;
  return copy;
}

void PolicyConfig::validate() const {
  if (!std::isfinite(max_range_m) || max_range_m <= 0.0 ||
      !std::isfinite(distance_boundaries_m[0]) ||
      !std::isfinite(distance_boundaries_m[1]) ||
      !std::isfinite(distance_boundaries_m[2]) ||
      distance_boundaries_m[0] <= 0.0 ||
      distance_boundaries_m[0] >= distance_boundaries_m[1] ||
      distance_boundaries_m[1] >= distance_boundaries_m[2] ||
      distance_boundaries_m[2] >= max_range_m) {
    throw std::invalid_argument("distance boundaries must be strictly increasing within range");
  }
  const auto& u = utility;
  if (!unit_interval(u.geometry_weight) || !unit_interval(u.semantic_weight) ||
      !unit_interval(u.motion_weight) || !unit_interval(u.traversability_risk_weight) ||
      !unit_interval(u.uncertainty_weight) || !unit_interval(u.min_observation_quality) ||
      !unit_interval(u.min_point_density) || !unit_interval(u.ema_alpha) ||
      !unit_interval(u.merge_threshold) || !unit_interval(u.split_threshold) ||
      u.merge_threshold >= u.split_threshold || u.split_consecutive_frames <= 0 ||
      u.merge_consecutive_frames <= 0 || u.cooldown_frames < 0 ||
      u.max_level_changes_per_decision <= 0 || !std::isfinite(u.prediction_horizon_s) ||
      u.prediction_horizon_s < 0.0) {
    throw std::invalid_argument("invalid utility policy configuration");
  }
}

LodPolicy::LodPolicy(PolicyConfig config) : config_(config) { config_.validate(); }

PolicyDecision LodPolicy::decide(const DecisionInput& input) {
  if (!std::isfinite(input.range_m) || input.range_m < 0.0 ||
      input.active_level < 0 || input.active_level > 3) {
    throw std::invalid_argument("decision input must contain a finite range and valid level");
  }
  validate_signal(input.geometry_complexity, "geometry_complexity");
  validate_signal(input.semantic_importance, "semantic_importance");
  validate_signal(input.motion, "motion");
  validate_signal(input.traversability_risk, "traversability_risk");
  validate_signal(input.semantic_uncertainty, "semantic_uncertainty");
  validate_signal(input.observation_quality, "observation_quality");
  validate_signal(input.point_density, "point_density");
  if (!std::isfinite(input.range_rate_mps)) {
    throw std::invalid_argument("range_rate_mps must be finite");
  }
  core::validate_level(input.state_cell.level);

  const int baseline = distance_level(config_, input.range_m);

  switch (config_.mode) {
    case LodMode::Uniform5:
      return {.baseline_level = 0, .requested_level = 0, .action = action_for(input.active_level, 0)};
    case LodMode::Uniform40:
      return {.baseline_level = 3, .requested_level = 3, .action = action_for(input.active_level, 3)};
    case LodMode::DistanceLod:
      return {.baseline_level = baseline,
              .requested_level = baseline,
              .action = action_for(input.active_level, baseline)};
    case LodMode::UtilityLod: {
      const auto& u = config_.utility;
      const bool uncertainty_gate = input.observation_quality >= u.min_observation_quality &&
                                    input.point_density >= u.min_point_density;
      const double score = input.geometry_complexity * u.geometry_weight +
                           input.semantic_importance * u.semantic_weight + input.motion * u.motion_weight +
                           input.traversability_risk * u.traversability_risk_weight +
                           (uncertainty_gate ? input.semantic_uncertainty * u.uncertainty_weight : 0.0);
      const bool important_mover = input.motion > 0.0 &&
                                   (input.semantic_importance > 0.0 || input.traversability_risk > 0.0);
      const double predicted_range = std::max(0.0, input.range_m + input.range_rate_mps * u.prediction_horizon_s);
      const int predicted_baseline = important_mover ? distance_level(config_, predicted_range) : baseline;
      const bool predictive_refinement = predicted_baseline < baseline;
      const int promotion_goal = std::min(std::max(0, baseline - 1), predicted_baseline);

      auto& state = states_[input.state_cell];
      state.ema = state.initialized ? u.ema_alpha * score + (1.0 - u.ema_alpha) * state.ema : score;
      state.initialized = true;
      const bool transitions_allowed = state.cooldown_remaining == 0;
      if (!transitions_allowed) --state.cooldown_remaining;

      if (!transitions_allowed) {
        state.high_frames = 0;
        state.low_frames = 0;
      } else if (!state.promoted) {
        state.low_frames = 0;
        state.high_frames = (state.ema >= u.split_threshold || predictive_refinement || input.safety_critical)
                                ? state.high_frames + 1
                                : 0;
        if (transitions_allowed && state.high_frames >= u.split_consecutive_frames) {
          state.promoted = true;
          state.promoted_level = promotion_goal;
          state.cooldown_remaining = u.cooldown_frames;
          state.high_frames = 0;
        }
      } else {
        state.high_frames = 0;
        state.low_frames = state.ema <= u.merge_threshold ? state.low_frames + 1 : 0;
        if (transitions_allowed && state.low_frames >= u.merge_consecutive_frames) {
          state.promoted = false;
          state.cooldown_remaining = u.cooldown_frames;
          state.low_frames = 0;
        }
      }

      const int target = state.promoted ? std::min(baseline, state.promoted_level) : baseline;
      const int requested = bounded_level(input.active_level, target, u.max_level_changes_per_decision);
      return {.baseline_level = baseline,
              .requested_level = requested,
              .uncertainty_gate_passed = uncertainty_gate,
              .predicted_refinement = predictive_refinement,
              .utility_score = score,
              .action = action_for(input.active_level, requested)};
    }
  }
  throw std::logic_error("unknown LOD mode");
}

void ResourceGovernorConfig::validate() const {
  if (max_active_cells == 0 || max_logical_bytes == 0 || max_actions_per_frame == 0 ||
      !std::isfinite(near_field_radius_m) || near_field_radius_m < 0.0) {
    throw std::invalid_argument("invalid resource governor configuration");
  }
}

ResourceGovernor::ResourceGovernor(ResourceGovernorConfig config) : config_(config) { config_.validate(); }

std::vector<GovernorAction> ResourceGovernor::decide(
    const ResourceTelemetry& telemetry, const std::vector<GovernorCandidate>& candidates) const {
  validate_telemetry(telemetry);
  const bool pressure = telemetry.active_cells > config_.max_active_cells ||
                        telemetry.logical_bytes > config_.max_logical_bytes ||
                        telemetry.frame_time_ms > telemetry.target_frame_time_ms;
  if (!pressure) return {};

  std::vector<GovernorCandidate> eligible;
  eligible.reserve(candidates.size());
  for (const auto& candidate : candidates) {
    core::validate_level(candidate.active_level);
    if (!std::isfinite(candidate.range_m) || candidate.range_m < 0.0 || !unit_interval(candidate.utility_score)) {
      throw std::invalid_argument("invalid governor candidate");
    }
    const bool protected_near_field = candidate.range_m <= config_.near_field_radius_m;
    if (!protected_near_field && !candidate.safety_critical && candidate.active_level < 3) {
      eligible.push_back(candidate);
    }
  }
  std::sort(eligible.begin(), eligible.end(), [](const GovernorCandidate& left, const GovernorCandidate& right) {
    if (left.range_m != right.range_m) return left.range_m > right.range_m;
    if (left.utility_score != right.utility_score) return left.utility_score < right.utility_score;
    if (left.cell.level != right.cell.level) return left.cell.level < right.cell.level;
    if (left.cell.ix != right.cell.ix) return left.cell.ix < right.cell.ix;
    return left.cell.iy < right.cell.iy;
  });

  std::vector<GovernorAction> actions;
  actions.reserve(std::min(config_.max_actions_per_frame, eligible.size()));
  for (const auto& candidate : eligible) {
    if (actions.size() == config_.max_actions_per_frame) break;
    actions.push_back({.cell = candidate.cell, .action = ResolutionAction::Merge});
  }
  return actions;
}

PolicyConfig load_policy_config(const std::filesystem::path& path) {
  const auto values = parse_flat_yaml(path);
  const auto mode_it = values.find("mode");
  if (mode_it == values.end()) throw std::invalid_argument("missing required policy config key mode");
  PolicyConfig config = PolicyConfig::defaults();
  if (mode_it->second == "distance_lod") {
    require_keys(values, {"mode", "distance_boundaries_m", "max_range_m"});
    config.mode = LodMode::DistanceLod;
  } else if (mode_it->second == "utility_lod") {
    require_keys(values, {"mode", "distance_boundaries_m", "max_range_m",
                          "utility.geometry_weight", "utility.semantic_weight", "utility.motion_weight",
                          "utility.traversability_risk_weight", "utility.uncertainty_weight",
                          "utility.min_observation_quality", "utility.min_point_density", "utility.ema_alpha",
                          "utility.split_threshold", "utility.merge_threshold",
                          "utility.split_consecutive_frames", "utility.merge_consecutive_frames",
                          "utility.cooldown_frames", "utility.max_level_changes_per_decision",
                          "utility.prediction_horizon_s"});
    config.mode = LodMode::UtilityLod;
  } else {
    throw std::invalid_argument("unsupported policy mode " + mode_it->second);
  }
  config.distance_boundaries_m = yaml_boundaries(values.at("distance_boundaries_m"));
  config.max_range_m = yaml_double(values.at("max_range_m"), "max_range_m");
  if (config.mode == LodMode::UtilityLod) {
    auto& u = config.utility;
    u.geometry_weight = yaml_double(values.at("utility.geometry_weight"), "utility.geometry_weight");
    u.semantic_weight = yaml_double(values.at("utility.semantic_weight"), "utility.semantic_weight");
    u.motion_weight = yaml_double(values.at("utility.motion_weight"), "utility.motion_weight");
    u.traversability_risk_weight = yaml_double(values.at("utility.traversability_risk_weight"), "utility.traversability_risk_weight");
    u.uncertainty_weight = yaml_double(values.at("utility.uncertainty_weight"), "utility.uncertainty_weight");
    u.min_observation_quality = yaml_double(values.at("utility.min_observation_quality"), "utility.min_observation_quality");
    u.min_point_density = yaml_double(values.at("utility.min_point_density"), "utility.min_point_density");
    u.ema_alpha = yaml_double(values.at("utility.ema_alpha"), "utility.ema_alpha");
    u.split_threshold = yaml_double(values.at("utility.split_threshold"), "utility.split_threshold");
    u.merge_threshold = yaml_double(values.at("utility.merge_threshold"), "utility.merge_threshold");
    u.split_consecutive_frames = yaml_int(values.at("utility.split_consecutive_frames"), "utility.split_consecutive_frames");
    u.merge_consecutive_frames = yaml_int(values.at("utility.merge_consecutive_frames"), "utility.merge_consecutive_frames");
    u.cooldown_frames = yaml_int(values.at("utility.cooldown_frames"), "utility.cooldown_frames");
    u.max_level_changes_per_decision = yaml_int(values.at("utility.max_level_changes_per_decision"), "utility.max_level_changes_per_decision");
    u.prediction_horizon_s = yaml_double(values.at("utility.prediction_horizon_s"), "utility.prediction_horizon_s");
  }
  config.validate();
  return config;
}

ResourceGovernorConfig load_resource_governor_config(const std::filesystem::path& path) {
  const auto values = parse_flat_yaml(path);
  require_keys(values, {"max_active_cells", "max_logical_bytes", "near_field_radius_m", "max_actions_per_frame"});
  ResourceGovernorConfig config{.max_active_cells = yaml_size(values.at("max_active_cells"), "max_active_cells"),
                                .max_logical_bytes = yaml_size(values.at("max_logical_bytes"), "max_logical_bytes"),
                                .near_field_radius_m = yaml_double(values.at("near_field_radius_m"), "near_field_radius_m"),
                                .max_actions_per_frame = yaml_size(values.at("max_actions_per_frame"), "max_actions_per_frame")};
  config.validate();
  return config;
}

}  // namespace veyra::policy
