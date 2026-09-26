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

double radial_range_rate_mps(double velocity_x, double velocity_y, double offset_x,
                             double offset_y) noexcept {
  if (!std::isfinite(velocity_x) || !std::isfinite(velocity_y) || !std::isfinite(offset_x) ||
      !std::isfinite(offset_y)) {
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
      !std::isfinite(telemetry.target_frame_time_ms) || telemetry.target_frame_time_ms < 0.0) {
    throw std::invalid_argument(
        "resource telemetry must contain measured non-negative frame time and a target");
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
    if (colon == std::string::npos)
      throw std::invalid_argument("invalid YAML entry in " + path.string());
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
    if (index == boundaries.size())
      throw std::invalid_argument("distance_boundaries_m must have three values");
    boundaries[index++] = yaml_double(trim(item), "distance_boundaries_m");
  }
  if (index != boundaries.size())
    throw std::invalid_argument("distance_boundaries_m must have three values");
  return boundaries;
}

void require_keys(const std::unordered_map<std::string, std::string>& values,
                  const std::unordered_set<std::string>& expected,
                  const std::unordered_set<std::string>& optional = {}) {
  for (const auto& key : expected) {
    if (!values.contains(key))
      throw std::invalid_argument("missing required policy config key " + key);
  }
  for (const auto& [key, value] : values) {
    static_cast<void>(value);
    if (!expected.contains(key) && !optional.contains(key))
      throw std::invalid_argument("unknown policy config key " + key);
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
      !std::isfinite(distance_boundaries_m[0]) || !std::isfinite(distance_boundaries_m[1]) ||
      !std::isfinite(distance_boundaries_m[2]) || distance_boundaries_m[0] <= 0.0 ||
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
      u.max_level_changes_per_decision <= 0 || u.max_level_changes_per_decision > 3 ||
      !std::isfinite(u.prediction_horizon_s) || u.prediction_horizon_s < 0.0 ||
      u.max_promotion_depth < 0 || u.max_promotion_depth > 3 || u.max_state_cells == 0 ||
      u.state_ttl_frames == 0) {
    throw std::invalid_argument("invalid utility policy configuration");
  }
}

LodPolicy::LodPolicy(PolicyConfig config) : config_(config) { config_.validate(); }

void LodPolicy::begin_frame(std::uint64_t frame_id) {
  if (frame_id_ && frame_id <= *frame_id_)
    throw std::invalid_argument("policy frame IDs must increase; reset before replay");
  frame_id_ = frame_id;
  std::erase_if(states_, [&](const auto& entry) {
    return frame_id - entry.second.last_frame > config_.utility.state_ttl_frames;
  });
}

void LodPolicy::reset() noexcept {
  states_.clear();
  frame_id_.reset();
  implicit_frame_id_ = 0;
  promotion_telemetry_ = {};
}

void LodPolicy::enable_promotion_telemetry(const bool enabled) noexcept {
  promotion_telemetry_enabled_ = enabled;
  if (!enabled) promotion_telemetry_ = {};
}

void LodPolicy::record_promotion_budget_effects(const std::uint64_t suppressed,
                                                const std::uint64_t actions_requested,
                                                const std::uint64_t actions_applied) noexcept {
  if (!promotion_telemetry_enabled_) return;
  promotion_telemetry_.budget_suppressed += suppressed;
  promotion_telemetry_.governor_actions_requested += actions_requested;
  promotion_telemetry_.governor_actions_applied += actions_applied;
}

PolicyDecision LodPolicy::decide(const DecisionInput& input) {
  if (!std::isfinite(input.range_m) || input.range_m < 0.0 || input.active_level < 0 ||
      input.active_level > 3) {
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
      return {
          .baseline_level = 0, .requested_level = 0, .action = action_for(input.active_level, 0)};
    case LodMode::Uniform40:
      return {
          .baseline_level = 3, .requested_level = 3, .action = action_for(input.active_level, 3)};
    case LodMode::DistanceLod:
      return {.baseline_level = baseline,
              .requested_level = baseline,
              .action = action_for(input.active_level, baseline)};
    case LodMode::UtilityLod: {
      const auto& u = config_.utility;
      const bool uncertainty_gate = input.observation_quality >= u.min_observation_quality &&
                                    input.point_density >= u.min_point_density;
      const double score =
          uncertainty_gate
              ? std::clamp(input.geometry_complexity * u.geometry_weight +
                               input.semantic_importance * u.semantic_weight +
                               input.motion * u.motion_weight +
                               input.traversability_risk * u.traversability_risk_weight +
                               input.semantic_uncertainty * u.uncertainty_weight,
                           0.0, 1.0)
              : 0.0;
      const bool important_mover =
          uncertainty_gate && input.motion >= 0.5 &&
          (input.semantic_importance > 0.0 || input.traversability_risk > 0.0);
      const double predicted_range =
          std::max(0.0, input.range_m + input.range_rate_mps * u.prediction_horizon_s);
      const int predicted_baseline =
          important_mover ? distance_level(config_, predicted_range) : baseline;
      const bool predictive_refinement = predicted_baseline < baseline;
      const int promotion_goal = std::max(0, baseline - u.max_promotion_depth);
      auto record_evidence = [&](const int requested, const bool transition) {
        if (!promotion_telemetry_enabled_) return;
        auto& telemetry = promotion_telemetry_;
        ++telemetry.decisions;
        uncertainty_gate ? ++telemetry.gate_passed : ++telemetry.gate_failed;
        if (input.safety_critical) ++telemetry.safety_decisions;
        if (predictive_refinement) ++telemetry.predictive_decisions;
        const std::array<double, 5> raw{input.geometry_complexity, input.semantic_importance,
                                        input.motion, input.traversability_risk,
                                        input.semantic_uncertainty};
        const std::array<double, 5> weights{u.geometry_weight, u.semantic_weight, u.motion_weight,
                                            u.traversability_risk_weight, u.uncertainty_weight};
        for (std::size_t i = 0; i < raw.size(); ++i) {
          telemetry.signal_min[i] = telemetry.decisions == 1
                                        ? raw[i]
                                        : std::min(telemetry.signal_min[i], raw[i]);
          telemetry.signal_max[i] = telemetry.decisions == 1
                                        ? raw[i]
                                        : std::max(telemetry.signal_max[i], raw[i]);
          telemetry.signal_raw_sum[i] += raw[i];
          telemetry.signal_weighted_sum[i] += raw[i] * weights[i];
          if (raw[i] == 0.0) ++telemetry.signal_exact_zero_count[i];
          if (raw[i] >= 0.99) ++telemetry.signal_near_one_count[i];
          const auto bin = static_cast<std::size_t>(
              std::min(19.0, std::floor(std::clamp(raw[i], 0.0, 1.0) * 20.0)));
          ++telemetry.signal_histogram[i][bin];
        }
        const auto score_bin = static_cast<std::size_t>(
            std::min(19.0, std::floor(std::clamp(score, 0.0, 1.0) * 20.0)));
        ++telemetry.utility_histogram[score_bin];
        telemetry.utility_min = telemetry.decisions == 1
                                    ? score
                                    : std::min(telemetry.utility_min, score);
        telemetry.utility_max = telemetry.decisions == 1
                                    ? score
                                    : std::max(telemetry.utility_max, score);
        if (score >= u.split_threshold) ++telemetry.utility_above_split_count;
        if (score <= u.merge_threshold) ++telemetry.utility_below_merge_count;
        if (score == 0.0) ++telemetry.utility_exact_zero_count;
        if (score >= 0.99) ++telemetry.utility_near_one_count;
        if (transition && requested < baseline) {
          ++telemetry.promotion_transitions[static_cast<std::size_t>(input.active_level)]
                                           [static_cast<std::size_t>(requested)]
                                           [static_cast<std::size_t>(baseline)];
          std::size_t reason_mask = 0;
          for (std::size_t i = 0; i < raw.size(); ++i)
            if (raw[i] * weights[i] > 1e-9) reason_mask |= std::size_t{1} << i;
          if (input.safety_critical) reason_mask |= std::size_t{1} << 5;
          if (predictive_refinement) reason_mask |= std::size_t{1} << 6;
          ++telemetry.transition_reason_masks[reason_mask];
        }
      };
      const auto frame = frame_id_ ? *frame_id_ : ++implicit_frame_id_;
      auto found = states_.find(input.state_cell);
      if (found == states_.end() && states_.size() >= u.max_state_cells) {
        const int target = input.safety_critical ? promotion_goal : baseline;
        record_evidence(target, false);
        return {.baseline_level = baseline,
                .requested_level = target,
                .uncertainty_gate_passed = uncertainty_gate,
                .utility_score = score,
                .action = action_for(input.active_level, target)};
      }
      auto& tracked = states_[input.state_cell];
      if (!tracked.seen || tracked.last_frame != frame) {
        // Missing observations do not count as consecutive evidence.
        if (tracked.seen && frame - tracked.last_frame > 1) {
          tracked.current.high_frames = 0;
          tracked.current.low_frames = 0;
        }
        tracked.frame_start = tracked.current;
        tracked.last_frame = frame;
        tracked.seen = true;
        tracked.frame_score = 0.0;
        tracked.frame_predictive = false;
        tracked.frame_safety = false;
        tracked.frame_goal = 3;
        tracked.frame_promotion_counted = false;
      }
      tracked.frame_score = std::max(tracked.frame_score, score);
      tracked.frame_predictive = tracked.frame_predictive || predictive_refinement;
      tracked.frame_safety = tracked.frame_safety || input.safety_critical;
      tracked.frame_goal = std::min(tracked.frame_goal, promotion_goal);
      // Re-evaluate from the frame-start state with max evidence: repeated
      // points cannot consume extra hysteresis/cooldown frames.
      tracked.current = tracked.frame_start;
      auto& state = tracked.current;
      state.ema = state.initialized
                      ? u.ema_alpha * tracked.frame_score + (1.0 - u.ema_alpha) * state.ema
                      : tracked.frame_score;
      state.initialized = true;
      const bool transitions_allowed = state.cooldown_remaining == 0;
      if (!transitions_allowed) --state.cooldown_remaining;

      if (!transitions_allowed) {
        state.high_frames = 0;
        state.low_frames = 0;
      } else if (!state.promoted) {
        state.low_frames = 0;
        state.high_frames =
            (state.ema >= u.split_threshold || tracked.frame_predictive || tracked.frame_safety)
                ? state.high_frames + 1
                : 0;
        if (transitions_allowed && state.high_frames >= u.split_consecutive_frames) {
          state.promoted = true;
          state.promoted_level = tracked.frame_goal;
          state.cooldown_remaining = u.cooldown_frames;
          state.high_frames = 0;
        }
      } else {
        state.high_frames = 0;
        state.low_frames =
            state.ema <= u.merge_threshold && !tracked.frame_predictive && !tracked.frame_safety
                ? state.low_frames + 1
                : 0;
        if (transitions_allowed && state.low_frames >= u.merge_consecutive_frames) {
          state.promoted = false;
          state.cooldown_remaining = u.cooldown_frames;
          state.low_frames = 0;
        }
      }

      // A low point early in a frame cannot demote a region whose later
      // points still contain a hazard. Commit demotion on the next frame.
      const auto& output_state = frame_id_ && !state.promoted && tracked.frame_start.promoted
                                     ? tracked.frame_start
                                     : state;
      const int target = output_state.promoted
                             ? std::clamp(output_state.promoted_level, promotion_goal, baseline)
                             : baseline;
      const int requested = std::min(
          baseline, bounded_level(input.active_level, target, u.max_level_changes_per_decision));
      const bool promotion_transition = state.promoted && !tracked.frame_start.promoted &&
                                        !tracked.frame_promotion_counted && requested < baseline;
      if (promotion_transition) tracked.frame_promotion_counted = true;
      record_evidence(requested, promotion_transition);
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
      !std::isfinite(near_field_radius_m) || near_field_radius_m < 10.0 ||
      !std::isfinite(target_frame_time_ms) || target_frame_time_ms <= 0.0 ||
      !unit_interval(pressure_ratio) || !unit_interval(recovery_ratio) ||
      recovery_ratio >= pressure_ratio || pressure_ratio <= 0.0 ||
      overload_consecutive_frames <= 0 || recovery_consecutive_frames <= 0) {
    throw std::invalid_argument("invalid resource governor configuration");
  }
}

ResourceGovernor::ResourceGovernor(ResourceGovernorConfig config) : config_(config) {
  config_.validate();
}

std::vector<GovernorAction> ResourceGovernor::decide(
    const ResourceTelemetry& telemetry, const std::vector<GovernorCandidate>& candidates) {
  validate_telemetry(telemetry);
  const double target = telemetry.target_frame_time_ms > 0.0 ? telemetry.target_frame_time_ms
                                                             : config_.target_frame_time_ms;
  double load = std::max(
      {static_cast<double>(telemetry.active_cells) / static_cast<double>(config_.max_active_cells),
       static_cast<double>(telemetry.logical_bytes) /
           static_cast<double>(config_.max_logical_bytes),
       telemetry.frame_time_ms / target});
  if (config_.max_rss_bytes && telemetry.rss_bytes)
    load = std::max(load, static_cast<double>(*telemetry.rss_bytes) /
                              static_cast<double>(config_.max_rss_bytes));
  if (override_ == GovernorOverride::Disabled) {
    status_.state = GovernorState::Disabled;
    status_.allow_optional_splits = true;
    status_.overload_frames = status_.recovery_frames = 0;
    return {};
  }
  const bool was_limited = !status_.allow_optional_splits;
  status_.overload_frames = load > 1.0
                                ? (status_.overload_frames < config_.overload_consecutive_frames
                                       ? status_.overload_frames + 1
                                       : status_.overload_frames)
                                : 0;
  const bool overloaded = status_.overload_frames >= config_.overload_consecutive_frames ||
                          override_ == GovernorOverride::Conserve;
  if (overloaded) {
    status_.state = GovernorState::Overloaded;
    status_.allow_optional_splits = false;
    status_.recovery_frames = 0;
  } else if (load >= config_.pressure_ratio) {
    status_.state = GovernorState::ApproachingBudget;
    status_.allow_optional_splits = false;
    status_.recovery_frames = 0;
  } else if (was_limited) {
    status_.recovery_frames = load <= config_.recovery_ratio
                                  ? (status_.recovery_frames < config_.recovery_consecutive_frames
                                         ? status_.recovery_frames + 1
                                         : status_.recovery_frames)
                                  : 0;
    status_.allow_optional_splits = status_.recovery_frames >= config_.recovery_consecutive_frames;
    status_.state =
        status_.allow_optional_splits ? GovernorState::Normal : GovernorState::Recovering;
  } else {
    status_.state = GovernorState::Normal;
    status_.allow_optional_splits = true;
  }
  if (!was_limited && !status_.allow_optional_splits) ++status_.interventions;
  if (!overloaded) return {};

  std::vector<GovernorCandidate> eligible;
  eligible.reserve(candidates.size());
  for (const auto& candidate : candidates) {
    core::validate_level(candidate.active_level);
    if (!std::isfinite(candidate.range_m) || candidate.range_m < 0.0 ||
        !unit_interval(candidate.utility_score)) {
      throw std::invalid_argument("invalid governor candidate");
    }
    const bool protected_near_field = candidate.range_m <= config_.near_field_radius_m;
    if (!protected_near_field && !candidate.safety_critical && candidate.active_level < 3) {
      eligible.push_back(candidate);
    }
  }
  std::sort(eligible.begin(), eligible.end(),
            [](const GovernorCandidate& left, const GovernorCandidate& right) {
              if (left.utility_score != right.utility_score)
                return left.utility_score < right.utility_score;
              if (left.range_m != right.range_m) return left.range_m > right.range_m;
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
  status_.actions_requested += actions.size();
  return actions;
}

void ResourceGovernor::reset() noexcept {
  status_ = {};
  override_ = GovernorOverride::Automatic;
}

void ResourceGovernor::set_override(GovernorOverride mode) noexcept {
  override_ = mode;
  status_.overload_frames = 0;
  status_.recovery_frames = 0;
  if (mode == GovernorOverride::Disabled) {
    status_.state = GovernorState::Disabled;
    status_.allow_optional_splits = true;
  } else if (mode == GovernorOverride::Conserve) {
    status_.state = GovernorState::Overloaded;
    status_.allow_optional_splits = false;
  } else {
    status_.state = GovernorState::Normal;
    status_.allow_optional_splits = true;
  }
}

void ResourceGovernor::record_applied_actions(std::size_t count) {
  if (count > status_.actions_requested - status_.actions_applied)
    throw std::invalid_argument("applied governor actions exceed requested actions");
  status_.actions_applied += count;
}

PolicyConfig load_policy_config(const std::filesystem::path& path) {
  const auto values = parse_flat_yaml(path);
  const auto mode_it = values.find("mode");
  if (mode_it == values.end())
    throw std::invalid_argument("missing required policy config key mode");
  PolicyConfig config = PolicyConfig::defaults();
  if (mode_it->second == "distance_lod") {
    require_keys(values, {"mode", "distance_boundaries_m", "max_range_m"});
    config.mode = LodMode::DistanceLod;
  } else if (mode_it->second == "utility_lod") {
    require_keys(
        values,
        {"mode", "distance_boundaries_m", "max_range_m", "utility.geometry_weight",
         "utility.semantic_weight", "utility.motion_weight", "utility.traversability_risk_weight",
         "utility.uncertainty_weight", "utility.min_observation_quality",
         "utility.min_point_density", "utility.ema_alpha", "utility.split_threshold",
         "utility.merge_threshold", "utility.split_consecutive_frames",
         "utility.merge_consecutive_frames", "utility.cooldown_frames",
         "utility.max_level_changes_per_decision", "utility.prediction_horizon_s"},
        {"utility.max_promotion_depth", "utility.max_state_cells", "utility.state_ttl_frames"});
    config.mode = LodMode::UtilityLod;
  } else {
    throw std::invalid_argument("unsupported policy mode " + mode_it->second);
  }
  config.distance_boundaries_m = yaml_boundaries(values.at("distance_boundaries_m"));
  config.max_range_m = yaml_double(values.at("max_range_m"), "max_range_m");
  if (config.mode == LodMode::UtilityLod) {
    auto& u = config.utility;
    u.geometry_weight =
        yaml_double(values.at("utility.geometry_weight"), "utility.geometry_weight");
    u.semantic_weight =
        yaml_double(values.at("utility.semantic_weight"), "utility.semantic_weight");
    u.motion_weight = yaml_double(values.at("utility.motion_weight"), "utility.motion_weight");
    u.traversability_risk_weight = yaml_double(values.at("utility.traversability_risk_weight"),
                                               "utility.traversability_risk_weight");
    u.uncertainty_weight =
        yaml_double(values.at("utility.uncertainty_weight"), "utility.uncertainty_weight");
    u.min_observation_quality = yaml_double(values.at("utility.min_observation_quality"),
                                            "utility.min_observation_quality");
    u.min_point_density =
        yaml_double(values.at("utility.min_point_density"), "utility.min_point_density");
    u.ema_alpha = yaml_double(values.at("utility.ema_alpha"), "utility.ema_alpha");
    u.split_threshold =
        yaml_double(values.at("utility.split_threshold"), "utility.split_threshold");
    u.merge_threshold =
        yaml_double(values.at("utility.merge_threshold"), "utility.merge_threshold");
    u.split_consecutive_frames =
        yaml_int(values.at("utility.split_consecutive_frames"), "utility.split_consecutive_frames");
    u.merge_consecutive_frames =
        yaml_int(values.at("utility.merge_consecutive_frames"), "utility.merge_consecutive_frames");
    u.cooldown_frames = yaml_int(values.at("utility.cooldown_frames"), "utility.cooldown_frames");
    u.max_level_changes_per_decision = yaml_int(values.at("utility.max_level_changes_per_decision"),
                                                "utility.max_level_changes_per_decision");
    u.prediction_horizon_s =
        yaml_double(values.at("utility.prediction_horizon_s"), "utility.prediction_horizon_s");
    if (values.contains("utility.max_promotion_depth"))
      u.max_promotion_depth =
          yaml_int(values.at("utility.max_promotion_depth"), "utility.max_promotion_depth");
    if (values.contains("utility.max_state_cells"))
      u.max_state_cells =
          yaml_size(values.at("utility.max_state_cells"), "utility.max_state_cells");
    if (values.contains("utility.state_ttl_frames"))
      u.state_ttl_frames =
          yaml_size(values.at("utility.state_ttl_frames"), "utility.state_ttl_frames");
  }
  config.validate();
  return config;
}

ResourceGovernorConfig load_resource_governor_config(const std::filesystem::path& path) {
  const auto values = parse_flat_yaml(path);
  require_keys(
      values,
      {"max_active_cells", "max_logical_bytes", "near_field_radius_m", "max_actions_per_frame"},
      {"max_rss_bytes", "target_frame_time_ms", "pressure_ratio", "recovery_ratio",
       "overload_consecutive_frames", "recovery_consecutive_frames"});
  ResourceGovernorConfig config{
      .max_active_cells = yaml_size(values.at("max_active_cells"), "max_active_cells"),
      .max_logical_bytes = yaml_size(values.at("max_logical_bytes"), "max_logical_bytes"),
      .near_field_radius_m = yaml_double(values.at("near_field_radius_m"), "near_field_radius_m"),
      .max_actions_per_frame =
          yaml_size(values.at("max_actions_per_frame"), "max_actions_per_frame")};
  if (values.contains("max_rss_bytes"))
    config.max_rss_bytes = yaml_size(values.at("max_rss_bytes"), "max_rss_bytes");
  if (values.contains("target_frame_time_ms"))
    config.target_frame_time_ms =
        yaml_double(values.at("target_frame_time_ms"), "target_frame_time_ms");
  if (values.contains("pressure_ratio"))
    config.pressure_ratio = yaml_double(values.at("pressure_ratio"), "pressure_ratio");
  if (values.contains("recovery_ratio"))
    config.recovery_ratio = yaml_double(values.at("recovery_ratio"), "recovery_ratio");
  if (values.contains("overload_consecutive_frames"))
    config.overload_consecutive_frames =
        yaml_int(values.at("overload_consecutive_frames"), "overload_consecutive_frames");
  if (values.contains("recovery_consecutive_frames"))
    config.recovery_consecutive_frames =
        yaml_int(values.at("recovery_consecutive_frames"), "recovery_consecutive_frames");
  config.validate();
  return config;
}

}  // namespace veyra::policy
