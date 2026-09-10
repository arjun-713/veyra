#include "veyra/map/map.hpp"
#include "veyra/metrics/metrics.hpp"
#include "veyra/policy/policy.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

namespace {

using Clock = veyra::metrics::MetricsCollector::Clock;

struct Options {
  std::string policy;
  std::string output;
  double window_radius = 100.0;
  std::array<double, 4> levels{0.05, 0.10, 0.20, 0.40};
  std::array<double, 3> boundaries{10.0, 30.0, 60.0};
  std::uint64_t warmup_frames = 0;
  bool engine = false;
  bool include_leaf_details = false;
  std::string utility_config = VEYRA_SOURCE_DIR "/configs/utility_lod.yaml";
  std::string governor_config = VEYRA_SOURCE_DIR "/configs/resource_governor.yaml";
};

struct NumericSummary {
  std::uint64_t count = 0;
  double sum = 0.0;
  double min = std::numeric_limits<double>::infinity();
  double max = -std::numeric_limits<double>::infinity();

  void add(std::optional<double> value) {
    if (!value.has_value()) {
      return;
    }
    ++count;
    sum += *value;
    min = std::min(min, *value);
    max = std::max(max, *value);
  }
};

struct InputSummary {
  bool pose_available = false;
  bool enriched_fields_available = false;
  std::optional<std::uint64_t> timestamp_us;
  std::optional<std::uint64_t> pose_timestamp_us;
  std::optional<std::uint64_t> source_index;
  std::array<double, 3> pose_translation{};
  std::uint64_t point_count = 0;
  std::map<std::string, NumericSummary> quality;
  std::uint64_t ground_true_count = 0;
  std::array<std::uint64_t, 3> drivable_counts{};
  std::array<std::uint64_t, 4> motion_state_counts{};
};

struct FrameMetric {
  InputSummary input;
  std::map<std::string, std::int64_t> stages_ns;
  std::uint64_t topology_churn = 0;
  std::array<std::size_t, 4> cells_by_level{};
  std::optional<std::uint64_t> rss_bytes;
};

struct Result {
  int protocol_version = 2;
  std::string policy;
  std::string digest;
  std::uint64_t input_frames = 0;
  std::uint64_t warmup_frames = 0;
  std::uint64_t input_points = 0;
  // Points that arrived intact but fell outside the active window. They are
  // counted here — never thrown into a frame abort — so identical selections
  // stay comparable across policies and bridges never deadlock on one
  // marginal return.
  std::uint64_t rejected_out_of_window = 0;
  bool include_leaf_details = false;
  std::uint64_t late_frames = 0;
  std::optional<std::uint64_t> dropped_frames;
  bool source_indices_complete = true;
  veyra::map::MapSnapshot snapshot;
  veyra::metrics::MetricsReport metrics;
  std::vector<FrameMetric> frame_metrics;
};

enum class PolicyKind { kUniform5, kUniform40, kDistanceLod, kUtilityLod };

class MapPolicyAdapter {
 public:
  MapPolicyAdapter(PolicyKind kind, veyra::map::MapConfig config,
                   const Options& options)
      : kind_(kind), config_(config),
        map_(make_storage(kind, config)),
        utility_(kind == PolicyKind::kUtilityLod
                     ? std::optional<veyra::policy::LodPolicy>{veyra::policy::load_policy_config(options.utility_config)}
                     : std::nullopt),
        governor_(kind == PolicyKind::kUtilityLod
                      ? std::optional<veyra::policy::ResourceGovernor>{veyra::policy::load_resource_governor_config(options.governor_config)}
                      : std::nullopt) {}

  [[nodiscard]] bool accepts(double x, double y) const {
    return std::visit([x, y](const auto &map) { return map.accepts(x, y); }, map_);
  }

  void update(const veyra::map::Observation &observation) {    if (kind_ != PolicyKind::kUtilityLod) {
      std::visit([&observation](auto &map) { map.update(observation); }, map_);
      return;
    }
    auto& map = std::get<veyra::map::Map>(map_);
    const double offset_x = observation.x - center_x_;
    const double offset_y = observation.y - center_y_;
    const double range = std::hypot(offset_x, offset_y);
    const auto baseline_cell = map.cell_for(observation.x, observation.y);
    const auto decision = utility_->decide({
        .range_m = range,
        .active_level = map.level_for(observation.x, observation.y),
        .state_cell = baseline_cell,
        .safety_critical = observation.drivable == 2,
        .geometry_complexity = static_cast<double>(observation.geometry_complexity),
        .semantic_importance = observation.semantic_class == 0 ? 0.0 : static_cast<double>(observation.semantic_confidence),
        .motion = static_cast<double>(observation.motion_probability),
        .traversability_risk = observation.drivable == 2 ? static_cast<double>(observation.terrain_confidence) : 0.0,
        .semantic_uncertainty = 1.0 - static_cast<double>(observation.semantic_confidence),
        .observation_quality = static_cast<double>(observation.observation_quality),
        .point_density = 1.0,
        .range_rate_mps = veyra::policy::radial_range_rate_mps(
            static_cast<double>(observation.velocity_x),
            static_cast<double>(observation.velocity_y), offset_x, offset_y),
    });
    map.update_at_level(observation, decision.requested_level);
  }

  void set_window_center(double x, double y) {
    center_x_ = x;
    center_y_ = y;
    std::visit([x, y](auto &map) { map.set_window_center(x, y); }, map_);
  }

  [[nodiscard]] veyra::map::MapSnapshot snapshot() const {
    return std::visit([](const auto &map) { return map.snapshot(); }, map_);
  }

  [[nodiscard]] bool uses_stateful_policy() const noexcept { return utility_.has_value(); }

  void apply_governor(const veyra::map::MapSnapshot& snapshot, double frame_time_ms) {
    if (!governor_.has_value()) return;
    std::vector<veyra::policy::GovernorCandidate> candidates;
    candidates.reserve(snapshot.leaves.size());
    for (const auto& leaf : snapshot.leaves) {
      const double resolution = veyra::core::resolution_m(leaf.id.level);
      const double x = (static_cast<double>(leaf.id.ix) + 0.5) * resolution;
      const double y = (static_cast<double>(leaf.id.iy) + 0.5) * resolution;
      candidates.push_back({.cell = leaf.id,
                            .range_m = std::hypot(x - center_x_, y - center_y_),
                            .utility_score = std::clamp(static_cast<double>(leaf.stats.observation_quality), 0.0, 1.0),
                            .active_level = leaf.id.level,
                            .safety_critical = leaf.stats.drivable_evidence < 0.0F});
    }
    const auto actions = governor_->decide(
        {.active_cells = snapshot.active_leaf_count,
         .logical_bytes = snapshot.logical_bytes,
         .frame_time_ms = frame_time_ms,
         .target_frame_time_ms = 100.0}, candidates);
    auto& map = std::get<veyra::map::Map>(map_);
    for (const auto& action : actions) {
      if (action.action == veyra::policy::ResolutionAction::Merge) map.merge_children(action.cell.parent());
    }
  }

 private:
  using Storage = std::variant<veyra::map::Uniform5Map, veyra::map::Uniform40Map,
                               veyra::map::DistanceLodMap, veyra::map::Map>;
  static Storage make_storage(PolicyKind kind, veyra::map::MapConfig config) {
    switch (kind) {
      case PolicyKind::kUniform5: return veyra::map::Uniform5Map{config};
      case PolicyKind::kUniform40: return veyra::map::Uniform40Map{config};
      case PolicyKind::kDistanceLod: return veyra::map::DistanceLodMap{config};
      case PolicyKind::kUtilityLod: return veyra::map::Map{veyra::map::ResolutionPolicy::DistanceLod, config};
    }
    throw std::logic_error("unknown policy kind");
  }
  PolicyKind kind_;
  veyra::map::MapConfig config_;
  Storage map_;
  std::optional<veyra::policy::LodPolicy> utility_;
  std::optional<veyra::policy::ResourceGovernor> governor_;
  double center_x_ = 0.0;
  double center_y_ = 0.0;
};

// Stream ingestion shared by batch execution and the persistent engine.
// A point outside the active window is a counted, documented rejection, not
// a frame abort: one marginal return must never strand a whole frame (or a
// whole pipe). Malformed records still throw via parse_observation_record.
bool ingest_observation(MapPolicyAdapter &map, const veyra::map::Observation &observation,
                        std::uint64_t &rejected_out_of_window) {
  if (!map.accepts(observation.x, observation.y)) {
    ++rejected_out_of_window;
    return false;
  }
  map.update(observation);
  return true;
}

double real_value(const std::string &value, const char *name) {
  std::size_t used = 0;
  const auto result = std::stod(value, &used);
  if (used != value.size() || !std::isfinite(result)) {
    throw std::invalid_argument(std::string("invalid ") + name);
  }
  return result;
}

std::optional<double> optional_real_value(const std::string &value,
                                          const char *name) {
  return value == "NA" ? std::nullopt
                       : std::optional<double>{real_value(value, name)};
}

std::uint64_t uint_value(const std::string &value, const char *name) {
  std::size_t used = 0;
  const auto result = std::stoull(value, &used);
  if (used != value.size()) {
    throw std::invalid_argument(std::string("invalid ") + name);
  }
  return result;
}

std::optional<std::uint64_t> optional_uint_value(const std::string &value,
                                                  const char *name) {
  return value == "NA" ? std::nullopt
                       : std::optional<std::uint64_t>{uint_value(value, name)};
}

std::int64_t int_value(const std::string &value, const char *name) {
  std::size_t used = 0;
  const auto result = std::stoll(value, &used);
  if (used != value.size()) {
    throw std::invalid_argument(std::string("invalid ") + name);
  }
  return result;
}

void require_end(std::istringstream &input, const char *record) {
  std::string extra;
  if (input >> extra) {
    throw std::invalid_argument(std::string("malformed ") + record + " record");
  }
}

PolicyKind parse_policy(std::string_view name) {
  if (name == "uniform5") {
    return PolicyKind::kUniform5;
  }
  if (name == "uniform40") return PolicyKind::kUniform40;
  if (name == "distance_lod") {
    return PolicyKind::kDistanceLod;
  }
  if (name == "utility_lod") return PolicyKind::kUtilityLod;
  throw std::invalid_argument("unknown policy: " + std::string(name));
}

Options parse_options(int argc, char **argv) {
  Options options;
  for (int index = 1; index < argc; ++index) {
    const std::string_view arg(argv[index]);
    const auto needs_value = arg == "--policy" || arg == "--output" ||
                             arg == "--window-radius" || arg == "--levels" ||
                             arg == "--distance-boundaries" ||
                             arg == "--warmup-frames" || arg == "--utility-config" ||
                             arg == "--governor-config";
    if (needs_value && index + 1 >= argc) {
      throw std::invalid_argument("missing option value");
    }
    if (arg == "--policy") {
      options.policy = argv[++index];
    } else if (arg == "--output") {
      options.output = argv[++index];
    } else if (arg == "--window-radius") {
      options.window_radius = real_value(argv[++index], "window radius");
    } else if (arg == "--warmup-frames") {
      options.warmup_frames = uint_value(argv[++index], "warmup frames");
    } else if (arg == "--engine") {
      options.engine = true;
    } else if (arg == "--include-leaf-details") {
      options.include_leaf_details = true;
    } else if (arg == "--utility-config") {
      options.utility_config = argv[++index];
    } else if (arg == "--governor-config") {
      options.governor_config = argv[++index];
    } else if (arg == "--levels") {
      std::istringstream values(argv[++index]);
      char comma = 0;
      if (!(values >> options.levels[0] >> comma) || comma != ',' ||
          !(values >> options.levels[1] >> comma) || comma != ',' ||
          !(values >> options.levels[2] >> comma) || comma != ',' ||
          !(values >> options.levels[3]) || !values.eof()) {
        throw std::invalid_argument("levels must be a,b,c,d");
      }
    } else if (arg == "--distance-boundaries") {
      std::istringstream values(argv[++index]);
      char comma = 0;
      if (!(values >> options.boundaries[0] >> comma) || comma != ',' ||
          !(values >> options.boundaries[1] >> comma) || comma != ',' ||
          !(values >> options.boundaries[2]) || !values.eof()) {
        throw std::invalid_argument("distance boundaries must be a,b,c");
      }
    } else {
      throw std::invalid_argument("usage: --policy uniform5|distance_lod [--warmup-frames N] [--output path]");
    }
  }
  (void)parse_policy(options.policy);
  if (!(options.window_radius > 0.0) || !std::isfinite(options.window_radius)) {
    throw std::invalid_argument("invalid window radius");
  }
  for (std::size_t index = 0; index < options.levels.size(); ++index) {
    if (!std::isfinite(options.levels[index]) ||
        options.levels[index] != 0.05 * static_cast<double>(1ULL << index)) {
      throw std::invalid_argument("levels do not match the supported dyadic map");
    }
  }
  return options;
}

std::int64_t duration_ns(Clock::time_point started) {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - started).count();
}

void observe_quality(InputSummary &summary, std::string_view name,
                     std::optional<double> value) {
  summary.quality[std::string(name)].add(value);
}

// This is the sole protocol-to-map observation mapping. Both batch execution
// and the long-lived engine consume it, preventing a viewer-specific lossy
// interpretation of V2 semantic, terrain, motion, and quality evidence.
veyra::map::Observation parse_observation_record(std::istringstream &input,
                                                  int stream_version,
                                                  InputSummary &summary) {
  std::vector<std::string> fields;
  for (std::string field; input >> field;) fields.push_back(std::move(field));
  const std::size_t expected_fields = stream_version == 1 ? 6U : 19U;
  if (fields.size() != expected_fields) throw std::invalid_argument("malformed point record");
  const auto x = real_value(fields[0], "x");
  const auto y = real_value(fields[1], "y");
  const auto z = real_value(fields[2], "z");
  const auto intensity = stream_version == 1 ? std::optional<double>{}
      : std::optional<double>{real_value(fields[3], "intensity")};
  const auto semantic = uint_value(fields[stream_version == 1 ? 3 : 4], "semantic class");
  const auto semantic_confidence = real_value(fields[stream_version == 1 ? 4 : 5], "semantic confidence");
  const auto ground = stream_version == 1 ? 0 : uint_value(fields[6], "ground");
  const auto drivable = uint_value(fields[stream_version == 1 ? 5 : 7], "drivable");
  const auto slope = stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[8], "slope");
  const auto roughness = stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[9], "roughness");
  const auto height_complexity = stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[10], "height complexity");
  const auto terrain_confidence = stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[11], "terrain confidence");
  const auto step = stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[12], "step");
  const auto motion_probability = stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[13], "motion probability");
  const auto motion_state = stream_version == 1 ? 3 : uint_value(fields[14], "motion state");
  const auto velocity_x = stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[15], "velocity x");
  const auto velocity_y = stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[16], "velocity y");
  const auto observation_quality = stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[17], "observation quality");
  const auto raw_semantic = stream_version == 1 ? static_cast<std::int64_t>(semantic) : int_value(fields[18], "raw semantic class");
  if (semantic > 65535 || semantic_confidence < 0.0 || semantic_confidence > 1.0 ||
      ground > 1 || drivable > 2 || motion_state > 3 || raw_semantic < 0) {
    throw std::invalid_argument("point values out of range");
  }
  for (const auto confidence : {terrain_confidence, motion_probability, observation_quality}) {
    if (confidence.has_value() && (*confidence < 0.0 || *confidence > 1.0)) {
      throw std::invalid_argument("point confidence values out of range");
    }
  }
  ++summary.point_count;
  summary.ground_true_count += ground;
  ++summary.drivable_counts.at(drivable);
  ++summary.motion_state_counts.at(motion_state);
  observe_quality(summary, "intensity", intensity);
  observe_quality(summary, "semantic_class", static_cast<double>(semantic));
  observe_quality(summary, "semantic_confidence", semantic_confidence);
  observe_quality(summary, "slope", slope);
  observe_quality(summary, "roughness", roughness);
  observe_quality(summary, "height_complexity", height_complexity);
  observe_quality(summary, "terrain_confidence", terrain_confidence);
  observe_quality(summary, "step", step);
  observe_quality(summary, "motion_probability", motion_probability);
  observe_quality(summary, "velocity_x", velocity_x);
  observe_quality(summary, "velocity_y", velocity_y);
  observe_quality(summary, "observation_quality", observation_quality);
  observe_quality(summary, "raw_semantic_class", static_cast<double>(raw_semantic));
  return {.x = x,
          .y = y,
          .z = z,
          .timestamp = summary.timestamp_us.value_or(0),
          .semantic_class = static_cast<std::uint16_t>(semantic),
          .semantic_confidence = static_cast<float>(semantic_confidence),
          .drivable = static_cast<std::uint8_t>(drivable),
          .ground = static_cast<std::uint8_t>(ground),
          .terrain_confidence = static_cast<float>(terrain_confidence.value_or(0.0)),
          .geometry_complexity = static_cast<float>(height_complexity.value_or(0.0)),
          .motion_probability = static_cast<float>(motion_probability.value_or(0.0)),
          .observation_quality = static_cast<float>(observation_quality.value_or(0.0)),
          .velocity_x = static_cast<float>(velocity_x.value_or(0.0)),
          .velocity_y = static_cast<float>(velocity_y.value_or(0.0))};
}

Result run(const Options &options) {
  const veyra::map::MapConfig config{
      .window_radius_m = options.window_radius,
      .tile_size_m = 10.0,
      .distance_boundaries_m = options.boundaries,
  };
  MapPolicyAdapter map(parse_policy(options.policy), config, options);
  veyra::metrics::MetricsCollector metrics{Clock::time_point{}};

  Result result;
  result.policy = options.policy;
  result.include_leaf_details = options.include_leaf_details;
  bool header = false;
  bool metadata = false;
  bool open = false;
  bool trailer = false;
  int stream_version = 0;
  std::uint64_t expected_points = 0;
  std::uint64_t points = 0;
  std::optional<std::uint64_t> previous_timestamp;
  std::optional<std::uint64_t> previous_source_index;
  std::uint64_t previous_topology_changes = 0;
  std::chrono::nanoseconds measured_elapsed{0};
  std::chrono::nanoseconds parse_duration{0};
  std::chrono::nanoseconds window_duration{0};
  std::chrono::nanoseconds update_duration{0};
  InputSummary input_summary;
  std::string line;

  while (std::getline(std::cin, line)) {
    if (line.empty()) {
      continue;
    }
    std::istringstream input(line);
    std::string kind;
    input >> kind;
    if (kind == "VEYRA_STREAM") {
      std::string version;
      input >> version;
      require_end(input, "stream header");
      if (header || (version != "1" && version != "2")) {
        throw std::invalid_argument("invalid stream header");
      }
      stream_version = version == "1" ? 1 : 2;
      result.protocol_version = stream_version;
      header = true;
    } else if (kind == "H") {
      if (!header || metadata || open || trailer || !(input >> result.digest) || result.digest.empty()) {
        throw std::invalid_argument("invalid stream metadata");
      }
      require_end(input, "stream metadata");
      metadata = true;
    } else if (kind == "F") {
      const auto started = Clock::now();
      if (!header || !metadata || open || trailer) {
        throw std::invalid_argument("invalid frame marker");
      }
      std::string timestamp, pose_timestamp, source_index, count;
      std::array<double, 16> pose{};
      pose = {1.0, 0.0, 0.0, 0.0,
              0.0, 1.0, 0.0, 0.0,
              0.0, 0.0, 1.0, 0.0,
              0.0, 0.0, 0.0, 1.0};
      if (stream_version == 1) {
        if (!(input >> timestamp >> count)) {
          throw std::invalid_argument("malformed legacy frame marker");
        }
        require_end(input, "legacy frame marker");
      } else {
        if (!(input >> timestamp >> pose_timestamp >> source_index)) {
          throw std::invalid_argument("malformed frame marker");
        }
        for (double &element : pose) {
          std::string value;
          if (!(input >> value)) {
            throw std::invalid_argument("malformed frame pose");
          }
          element = real_value(value, "pose element");
        }
        if (!(input >> count)) {
          throw std::invalid_argument("malformed frame marker");
        }
        require_end(input, "frame marker");
      }
      input_summary = InputSummary{};
      input_summary.timestamp_us = optional_uint_value(timestamp, "frame timestamp");
      input_summary.pose_available = stream_version == 2;
      input_summary.enriched_fields_available = stream_version == 2;
      if (stream_version == 2) {
        input_summary.pose_timestamp_us = optional_uint_value(pose_timestamp, "pose timestamp");
        input_summary.source_index = optional_uint_value(source_index, "source index");
      }
      input_summary.pose_translation = {pose[3], pose[7], pose[11]};
      bool late = input_summary.timestamp_us.has_value() && previous_timestamp.has_value() &&
                  *input_summary.timestamp_us <= *previous_timestamp;
      if (input_summary.timestamp_us.has_value()) {
        previous_timestamp = input_summary.timestamp_us;
      }
      if (!input_summary.source_index.has_value()) {
        result.source_indices_complete = false;
      } else if (previous_source_index.has_value()) {
        late = late || *input_summary.source_index <= *previous_source_index;
      }
      if (input_summary.source_index.has_value() && previous_source_index.has_value() &&
          *input_summary.source_index > *previous_source_index + 1) {
        const auto gap = *input_summary.source_index - *previous_source_index - 1;
        result.dropped_frames = result.dropped_frames.value_or(0) + gap;
      }
      if (input_summary.source_index.has_value()) {
        previous_source_index = input_summary.source_index;
      }
      result.late_frames += late ? 1 : 0;
      expected_points = uint_value(count, "frame point count");
      points = 0;
      parse_duration = std::chrono::nanoseconds{duration_ns(started)};
      const auto window_started = Clock::now();
      map.set_window_center(pose[3], pose[7]);
      window_duration = std::chrono::nanoseconds{duration_ns(window_started)};
      update_duration = std::chrono::nanoseconds{0};
      open = true;
    } else if (kind == "P") {
      const auto parse_started = Clock::now();
      if (!open) throw std::invalid_argument("point outside frame");
      auto observation = parse_observation_record(input, stream_version, input_summary);
      observation.timestamp = input_summary.timestamp_us.value_or(result.input_frames);
      parse_duration += std::chrono::nanoseconds{duration_ns(parse_started)};
      const auto update_started = Clock::now();
      if (ingest_observation(map, observation, result.rejected_out_of_window)) {
        ++result.input_points;
      }
      update_duration += std::chrono::nanoseconds{duration_ns(update_started)};
      ++points;
    } else if (kind == "E") {
      const auto parse_started = Clock::now();
      require_end(input, "frame end");
      if (!open || points != expected_points) {
        throw std::invalid_argument("frame point count mismatch");
      }
      parse_duration += std::chrono::nanoseconds{duration_ns(parse_started)};
      const auto snapshot_started = Clock::now();
      auto snapshot = map.snapshot();
      map.apply_governor(snapshot, static_cast<double>((parse_duration + window_duration + update_duration).count()) / 1'000'000.0);
      snapshot = map.snapshot();
      const auto snapshot_duration = std::chrono::nanoseconds{duration_ns(snapshot_started)};
      const auto topology_churn = snapshot.topology_change_count - previous_topology_changes;
      previous_topology_changes = snapshot.topology_change_count;
      const auto rss = veyra::metrics::read_process_rss_bytes();
      metrics.observe_rss_bytes(rss);
      const bool is_warmup = result.input_frames < options.warmup_frames;
      ++result.input_frames;
      if (is_warmup) {
        ++result.warmup_frames;
      } else {
        const auto frame_pipeline = parse_duration + window_duration + update_duration + snapshot_duration;
        measured_elapsed += frame_pipeline;
        metrics.record_duration("protocol_parse_and_validate", parse_duration);
        metrics.record_duration("map_window_follow", window_duration);
        metrics.record_duration("map_update", update_duration);
        metrics.record_duration("snapshot_and_topology", snapshot_duration);
        metrics.record_duration("frame_pipeline", frame_pipeline);
        metrics.record_value("topology_churn", static_cast<std::int64_t>(topology_churn));
        for (int level = 0; level < 4; ++level) {
          metrics.record_value("cells_level_" + std::to_string(level),
                               static_cast<std::int64_t>(snapshot.count_at_level(level)));
        }
        metrics.record_frame();
        result.frame_metrics.push_back(FrameMetric{
            .input = std::move(input_summary),
            .stages_ns = {{"protocol_parse_and_validate", parse_duration.count()},
                          {"map_window_follow", window_duration.count()},
                          {"map_update", update_duration.count()},
                          {"snapshot_and_topology", snapshot_duration.count()},
                          {"frame_pipeline", frame_pipeline.count()}},
            .topology_churn = topology_churn,
            .cells_by_level = {snapshot.count_at_level(0), snapshot.count_at_level(1),
                               snapshot.count_at_level(2), snapshot.count_at_level(3)},
            .rss_bytes = rss,
        });
      }
      result.snapshot = snapshot;
      open = false;
    } else if (kind == "D") {
      std::string trailer_digest;
      input >> trailer_digest;
      require_end(input, "stream trailer");
      if (!header || !metadata || open || trailer || trailer_digest != result.digest) {
        throw std::invalid_argument("invalid stream trailer");
      }
      trailer = true;
    } else {
      throw std::invalid_argument("unknown stream record: " + kind);
    }
  }
  if (!header || !metadata || result.digest.empty() || open || !trailer ||
      result.input_frames == 0 || result.frame_metrics.empty()) {
    throw std::invalid_argument("incomplete, empty, or fully warmed-up stream");
  }
  if (!result.source_indices_complete) {
    result.dropped_frames = std::nullopt;
  } else if (!result.dropped_frames.has_value()) {
    result.dropped_frames = 0;
  }
  metrics.set_logical_map_bytes(result.snapshot.logical_bytes);
  metrics.set_allocated_map_bytes(result.snapshot.memory.allocated_bytes);
  result.metrics = metrics.report(Clock::time_point{} + measured_elapsed);
  return result;
}

std::string escape(std::string_view value) {
  std::string result;
  for (const char character : value) {
    if (character == '\\' || character == '"') {
      result += '\\';
    }
    result += character;
  }
  return result;
}

void write_optional_uint(std::ostringstream &out,
                         std::optional<std::uint64_t> value) {
  if (value.has_value()) {
    out << *value;
  } else {
    out << "null";
  }
}

void write_optional_double(std::ostringstream &out, std::optional<double> value) {
  if (value.has_value()) {
    out << *value;
  } else {
    out << "null";
  }
}

void write_numeric_summary(std::ostringstream &out, const NumericSummary &summary) {
  out << "{\"count\":" << summary.count << ",\"mean\":";
  if (summary.count == 0) {
    out << "null,\"min\":null,\"max\":null}";
    return;
  }
  out << summary.sum / static_cast<double>(summary.count) << ",\"min\":"
      << summary.min << ",\"max\":" << summary.max << '}';
}

void write_duration_statistics(std::ostringstream &out,
                               const veyra::metrics::DurationStatistics &stats) {
  out << "{\"count\":" << stats.count << ",\"mean\":" << stats.mean_ns
      << ",\"min\":" << stats.min_ns << ",\"max\":" << stats.max_ns
      << ",\"p50\":" << stats.p50_ns << ",\"p95\":" << stats.p95_ns
      << ",\"p99\":" << stats.p99_ns << '}';
}

void write_value_statistics(std::ostringstream &out,
                            const veyra::metrics::ValueStatistics &stats) {
  out << "{\"count\":" << stats.count << ",\"mean\":" << stats.mean
      << ",\"min\":" << stats.min << ",\"max\":" << stats.max
      << ",\"p50\":" << stats.p50 << ",\"p95\":" << stats.p95
      << ",\"p99\":" << stats.p99 << '}';
}

void write_input_summary(std::ostringstream &out, const InputSummary &input) {
  out << "{\"pose_available\":" << (input.pose_available ? "true" : "false")
      << ",\"enriched_fields_available\":"
      << (input.enriched_fields_available ? "true" : "false") << ",\"timestamp_us\":";
  write_optional_uint(out, input.timestamp_us);
  out << ",\"pose_timestamp_us\":";
  write_optional_uint(out, input.pose_timestamp_us);
  out << ",\"source_index\":";
  write_optional_uint(out, input.source_index);
  out << ",\"pose_translation_xyz\":[" << input.pose_translation[0] << ','
      << input.pose_translation[1] << ',' << input.pose_translation[2]
      << "],\"point_count\":" << input.point_count << ",\"ground\":{\"true_count\":"
      << input.ground_true_count << ",\"false_count\":"
      << input.point_count - input.ground_true_count << "},\"drivable_counts\":{\"unknown\":"
      << input.drivable_counts[0] << ",\"drivable\":" << input.drivable_counts[1]
      << ",\"non_drivable\":" << input.drivable_counts[2]
      << "},\"motion_state_counts\":{\"static\":" << input.motion_state_counts[0]
      << ",\"possibly_moving\":" << input.motion_state_counts[1]
      << ",\"moving\":" << input.motion_state_counts[2]
      << ",\"unknown\":" << input.motion_state_counts[3] << "},\"quality\":{";
  bool first = true;
  for (const auto &[name, summary] : input.quality) {
    if (!std::exchange(first, false)) {
      out << ',';
    }
    out << '"' << escape(name) << "\":";
    write_numeric_summary(out, summary);
  }
  out << "}}";
}

std::string render(const Result &result) {
  const auto &snapshot = result.snapshot;
  const auto &metrics = result.metrics;
  std::ostringstream out;
  out << std::setprecision(17);
  out << "{\"schema_version\":2,\"protocol_version\":" << result.protocol_version
      << ",\"policy\":\""
      << escape(result.policy) << "\",\"stream_digest\":\"" << escape(result.digest)
      << "\",\"input_frames\":" << result.input_frames << ",\"warmup_frames\":"
      << result.warmup_frames << ",\"measured_frames\":" << result.frame_metrics.size()
      << ",\"frames\":" << result.frame_metrics.size()
      << ",\"input_points\":" << result.input_points << ",\"snapshot\":{\"active_leaf_count\":"
      << snapshot.active_leaf_count << ",\"tile_count\":" << snapshot.tile_count
      << ",\"point_count\":" << snapshot.point_count << ",\"logical_bytes\":"
      << snapshot.logical_bytes << ",\"memory\":{\"logical_payload_bytes\":"
      << snapshot.memory.logical_payload_bytes << ",\"retained_prior_payload_bytes\":"
      << snapshot.memory.retained_prior_payload_bytes << ",\"allocated_cell_array_bytes\":"
      << snapshot.memory.allocated_cell_array_bytes << ",\"allocated_tile_bytes\":"
      << snapshot.memory.allocated_tile_bytes << ",\"allocated_index_bytes\":"
      << snapshot.memory.allocated_index_bytes << ",\"allocated_overhead_bytes\":"
      << snapshot.memory.allocated_overhead_bytes << ",\"allocated_bytes\":"
      << snapshot.memory.allocated_bytes << "},\"levels\":{";
  for (int level = 0; level < 4; ++level) {
    if (level > 0) {
      out << ',';
    }
    out << '"' << level << "\":" << snapshot.count_at_level(level);
  }
  out << "},\"nonspatial_prior_point_count\":"
      << snapshot.nonspatial_prior_point_count
      << ",\"invariant_no_parent_descendant_overlap\":"
      << (snapshot.has_no_parent_descendant_overlap() ? "true" : "false");
  if (result.include_leaf_details) {
    out << ",\"leaves\":[";
    for (std::size_t index = 0; index < snapshot.leaves.size(); ++index) {
      if (index > 0) out << ',';
      const auto &leaf = snapshot.leaves[index];
      out << "{\"level\":" << leaf.id.level << ",\"ix\":" << leaf.id.ix
          << ",\"iy\":" << leaf.id.iy << ",\"count\":"
          << leaf.stats.count << ",\"mean_z\":" << leaf.stats.mean_z << '}';
    }
    out << ']';
  }
  out << "},\"metrics\":{\"frame_count\":" << metrics.frame_count
      << ",\"elapsed_seconds\":" << metrics.elapsed_seconds << ",\"fps\":";
  write_optional_double(out, metrics.fps);
  out << ",\"stage_latency_ns\":{";
  bool first = true;
  const std::map<std::string, veyra::metrics::DurationStatistics> sorted_durations(
      metrics.durations.begin(), metrics.durations.end());
  for (const auto &[name, stats] : sorted_durations) {
    if (!std::exchange(first, false)) {
      out << ',';
    }
    out << '"' << escape(name) << "\":";
    write_duration_statistics(out, stats);
  }
  out << '}';
  const auto map_update = metrics.durations.find("map_update");
  if (map_update != metrics.durations.end()) {
    out << ",\"map_update_latency_ns\":";
    write_duration_statistics(out, map_update->second);
  }
  out << ",\"topology\":{\"total_change_count\":"
      << snapshot.topology_change_count << ",\"per_level_cells_final\":{";
  for (int level = 0; level < 4; ++level) {
    if (level > 0) {
      out << ',';
    }
    out << '"' << level << "\":" << snapshot.count_at_level(level);
  }
  out << "},\"per_frame\":{";
  first = true;
  const std::map<std::string, veyra::metrics::ValueStatistics> sorted_values(
      metrics.values.begin(), metrics.values.end());
  for (const auto &[name, stats] : sorted_values) {
    if (!std::exchange(first, false)) {
      out << ',';
    }
    out << '"' << escape(name) << "\":";
    write_value_statistics(out, stats);
  }
  out << "}},\"memory\":{\"logical_map_bytes\":" << metrics.logical_map_bytes
      << ",\"allocated_map_bytes\":";
  write_optional_uint(out, metrics.allocated_map_bytes);
  out << ",\"allocated_map_bytes_available\":"
      << (metrics.allocated_map_bytes.has_value() ? "true" : "false")
      << ",\"allocated_map_bytes_reason\":\""
      << (metrics.allocated_map_bytes.has_value()
              ? "public map allocator measurement"
              : "allocator measurement unavailable")
      << "\""
      << ",\"current_rss_bytes\":";
  write_optional_uint(out, metrics.current_rss_bytes);
  out << ",\"peak_rss_bytes\":";
  write_optional_uint(out, metrics.peak_rss_bytes);
  out << "},\"measured_rss_bytes\":";
  write_optional_uint(out, metrics.current_rss_bytes);
  out << ",\"stream\":{\"late_frames\":" << result.late_frames
      << ",\"rejected_out_of_window\":" << result.rejected_out_of_window
      << ",\"dropped_frames\":";
  write_optional_uint(out, result.dropped_frames);
  out << ",\"source_index_complete\":"
      << (result.source_indices_complete ? "true" : "false") << "}}";
  out << ",\"frame_metrics\":[";
  for (std::size_t index = 0; index < result.frame_metrics.size(); ++index) {
    if (index > 0) {
      out << ',';
    }
    const auto &frame = result.frame_metrics[index];
    out << "{\"input\":";
    write_input_summary(out, frame.input);
    out << ",\"stages_ns\":{";
    first = true;
    for (const auto &[name, duration] : frame.stages_ns) {
      if (!std::exchange(first, false)) {
        out << ',';
      }
      out << '"' << escape(name) << "\":" << duration;
    }
    out << "},\"topology_churn\":" << frame.topology_churn
        << ",\"cells_by_level\":[" << frame.cells_by_level[0] << ','
        << frame.cells_by_level[1] << ',' << frame.cells_by_level[2] << ','
        << frame.cells_by_level[3] << "],\"rss_bytes\":";
    write_optional_uint(out, frame.rss_bytes);
    out << '}';
  }
  out << "]}\n";
  return out.str();
}

// Stateful counterpart to the batch stream reader. It deliberately consumes
// the same parse_observation_record mapping as run(), but retains the real map
// and policy objects between F/P/E transactions.
class PersistentEngineSession {
 public:
  explicit PersistentEngineSession(const Options& options) : options_(options) { reset(); }

  void reset() {
    const veyra::map::MapConfig config{.window_radius_m = options_.window_radius,
                                       .tile_size_m = 10.0,
                                       .distance_boundaries_m = options_.boundaries};
    map_ = std::make_unique<MapPolicyAdapter>(parse_policy(options_.policy), config, options_);
    metrics_ = std::make_unique<veyra::metrics::MetricsCollector>(Clock::time_point{});
    result_ = Result{};
    result_.policy = options_.policy;
    result_.include_leaf_details = options_.include_leaf_details;
    result_.digest = "engine-session";
    result_.protocol_version = 2;
    open_ = false;
    expected_points_ = points_ = 0;
    previous_timestamp_.reset();
    previous_source_index_.reset();
    previous_topology_changes_ = 0;
    measured_elapsed_ = std::chrono::nanoseconds{0};
    parse_duration_ = window_duration_ = update_duration_ = std::chrono::nanoseconds{0};
    input_summary_ = InputSummary{};
  }

  void ingest(std::string_view line) {
    std::istringstream input{std::string(line)};
    std::string kind;
    input >> kind;
    if (kind == "F") {
      begin_frame(input);
    } else if (kind == "P") {
      add_point(input);
    } else if (kind == "E") {
      end_frame(input);
    } else {
      throw std::invalid_argument("unknown engine record");
    }
  }

  [[nodiscard]] const Result& result() const noexcept { return result_; }
  [[nodiscard]] std::uint64_t frame_count() const noexcept { return result_.input_frames; }
  [[nodiscard]] bool frame_open() const noexcept { return open_; }

 private:
  void begin_frame(std::istringstream& input) {
    const auto started = Clock::now();
    if (open_) throw std::invalid_argument("nested engine frame");
    std::string timestamp, pose_timestamp, source_index, count;
    std::array<double, 16> pose{};
    if (!(input >> timestamp >> pose_timestamp >> source_index)) {
      throw std::invalid_argument("malformed frame marker");
    }
    for (double& element : pose) {
      std::string value;
      if (!(input >> value)) throw std::invalid_argument("malformed frame pose");
      element = real_value(value, "pose element");
    }
    if (!(input >> count)) throw std::invalid_argument("malformed frame marker");
    require_end(input, "frame marker");
    input_summary_ = InputSummary{};
    input_summary_.timestamp_us = optional_uint_value(timestamp, "frame timestamp");
    input_summary_.pose_timestamp_us = optional_uint_value(pose_timestamp, "pose timestamp");
    input_summary_.source_index = optional_uint_value(source_index, "source index");
    input_summary_.pose_available = true;
    input_summary_.enriched_fields_available = true;
    input_summary_.pose_translation = {pose[3], pose[7], pose[11]};
    bool late = input_summary_.timestamp_us.has_value() && previous_timestamp_.has_value() &&
                *input_summary_.timestamp_us <= *previous_timestamp_;
    if (input_summary_.timestamp_us.has_value()) previous_timestamp_ = input_summary_.timestamp_us;
    if (!input_summary_.source_index.has_value()) {
      result_.source_indices_complete = false;
    } else if (previous_source_index_.has_value()) {
      late = late || *input_summary_.source_index <= *previous_source_index_;
    }
    if (input_summary_.source_index.has_value() && previous_source_index_.has_value() &&
        *input_summary_.source_index > *previous_source_index_ + 1) {
      result_.dropped_frames = result_.dropped_frames.value_or(0) +
                               *input_summary_.source_index - *previous_source_index_ - 1;
    }
    if (input_summary_.source_index.has_value()) previous_source_index_ = input_summary_.source_index;
    result_.late_frames += late ? 1 : 0;
    expected_points_ = uint_value(count, "frame point count");
    points_ = 0;
    parse_duration_ = std::chrono::nanoseconds{duration_ns(started)};
    const auto window_started = Clock::now();
    map_->set_window_center(pose[3], pose[7]);
    window_duration_ = std::chrono::nanoseconds{duration_ns(window_started)};
    update_duration_ = std::chrono::nanoseconds{0};
    open_ = true;
  }

  void add_point(std::istringstream& input) {
    const auto parse_started = Clock::now();
    if (!open_) throw std::invalid_argument("engine point outside frame");
    auto observation = parse_observation_record(input, 2, input_summary_);
    observation.timestamp = input_summary_.timestamp_us.value_or(result_.input_frames);
    parse_duration_ += std::chrono::nanoseconds{duration_ns(parse_started)};
    const auto update_started = Clock::now();
    if (ingest_observation(*map_, observation, result_.rejected_out_of_window)) {
      ++result_.input_points;
    }
    update_duration_ += std::chrono::nanoseconds{duration_ns(update_started)};
    ++points_;
  }

  void end_frame(std::istringstream& input) {
    const auto parse_started = Clock::now();
    require_end(input, "frame end");
    if (!open_ || points_ != expected_points_) {
      throw std::invalid_argument("frame point count mismatch");
    }
    parse_duration_ += std::chrono::nanoseconds{duration_ns(parse_started)};
    const auto snapshot_started = Clock::now();
    auto snapshot = map_->snapshot();
    map_->apply_governor(snapshot, static_cast<double>((parse_duration_ + window_duration_ + update_duration_).count()) / 1'000'000.0);
    snapshot = map_->snapshot();
    const auto snapshot_duration = std::chrono::nanoseconds{duration_ns(snapshot_started)};
    const auto topology_churn = snapshot.topology_change_count - previous_topology_changes_;
    previous_topology_changes_ = snapshot.topology_change_count;
    const auto rss = veyra::metrics::read_process_rss_bytes();
    metrics_->observe_rss_bytes(rss);
    const bool is_warmup = result_.input_frames < options_.warmup_frames;
    ++result_.input_frames;
    if (is_warmup) {
      ++result_.warmup_frames;
    } else {
      const auto frame_pipeline = parse_duration_ + window_duration_ + update_duration_ + snapshot_duration;
      measured_elapsed_ += frame_pipeline;
      metrics_->record_duration("protocol_parse_and_validate", parse_duration_);
      metrics_->record_duration("map_window_follow", window_duration_);
      metrics_->record_duration("map_update", update_duration_);
      metrics_->record_duration("snapshot_and_topology", snapshot_duration);
      metrics_->record_duration("frame_pipeline", frame_pipeline);
      metrics_->record_value("topology_churn", static_cast<std::int64_t>(topology_churn));
      for (int level = 0; level < 4; ++level) {
        metrics_->record_value("cells_level_" + std::to_string(level),
                               static_cast<std::int64_t>(snapshot.count_at_level(level)));
      }
      metrics_->record_frame();
      result_.frame_metrics.push_back(FrameMetric{.input = std::move(input_summary_),
          .stages_ns = {{"protocol_parse_and_validate", parse_duration_.count()},
                        {"map_window_follow", window_duration_.count()},
                        {"map_update", update_duration_.count()},
                        {"snapshot_and_topology", snapshot_duration.count()},
                        {"frame_pipeline", frame_pipeline.count()}},
          .topology_churn = topology_churn,
          .cells_by_level = {snapshot.count_at_level(0), snapshot.count_at_level(1),
                             snapshot.count_at_level(2), snapshot.count_at_level(3)},
          .rss_bytes = rss});
    }
    result_.snapshot = snapshot;
    if (!result_.source_indices_complete) result_.dropped_frames = std::nullopt;
    else if (!result_.dropped_frames.has_value()) result_.dropped_frames = 0;
    metrics_->set_logical_map_bytes(snapshot.logical_bytes);
    metrics_->set_allocated_map_bytes(snapshot.memory.allocated_bytes);
    result_.metrics = metrics_->report(Clock::time_point{} + measured_elapsed_);
    open_ = false;
  }

  Options options_;
  std::unique_ptr<MapPolicyAdapter> map_;
  std::unique_ptr<veyra::metrics::MetricsCollector> metrics_;
  Result result_;
  bool open_ = false;
  std::uint64_t expected_points_ = 0;
  std::uint64_t points_ = 0;
  std::optional<std::uint64_t> previous_timestamp_;
  std::optional<std::uint64_t> previous_source_index_;
  std::uint64_t previous_topology_changes_ = 0;
  std::chrono::nanoseconds measured_elapsed_{0};
  std::chrono::nanoseconds parse_duration_{0};
  std::chrono::nanoseconds window_duration_{0};
  std::chrono::nanoseconds update_duration_{0};
  InputSummary input_summary_;
};

// Decimated leaf dump for map-layer rendering. Keys are compact by design:
// l=level, ix/iy=cell indices, z=mean elevation, c=semantic class,
// m=motion evidence, q=observation quality, d=signed drivable evidence.
// Sampling strides the snapshot order; cell_count reports what is actually
// returned so the caller can distinguish a decimated view from the map.
std::string render_cells(const veyra::map::MapSnapshot& snapshot, std::size_t budget) {
  const std::size_t total = snapshot.leaves.size();
  const std::size_t stride = std::max<std::size_t>(1, (total + budget - 1) / budget);
  const std::size_t shown = (total + stride - 1) / stride;
  std::ostringstream out;
  out << std::setprecision(6) << std::fixed;
  out << "{\"status\":\"available\",\"cell_count\":" << shown << ",\"total_leaves\":" << total
      << ",\"cells\":[";
  bool first = true;
  for (std::size_t index = 0; index < total; index += stride) {
    const auto& leaf = snapshot.leaves[index];
    if (!std::exchange(first, false)) out << ',';
    out << "{\"l\":" << leaf.id.level << ",\"ix\":" << leaf.id.ix << ",\"iy\":" << leaf.id.iy
        << ",\"z\":" << leaf.stats.mean_z << ",\"c\":" << leaf.stats.semantic_class
        << ",\"m\":" << leaf.stats.motion_evidence << ",\"q\":" << leaf.stats.observation_quality
        << ",\"d\":" << leaf.stats.drivable_evidence << '}';
  }
  out << "]}";
  return out.str();
}

// Long-lived line protocol for the viewer/runtime. Frames retain the exact V2
// F/P/E records used by the batch benchmark, so there is one observation
// mapping rather than a viewer-specific approximation. A response is emitted
// after every completed frame; R resets the state and C closes it.
//
// Error discipline: a malformed record aborts its frame with exactly ONE
// unavailable line, then the engine drains the rest of that frame silently
// until the next frame/command boundary. Without the drain, thousands of
// per-record errors would fill the response pipe while the writer is still
// sending the frame — a mutual deadlock neither side can escape.
int run_engine(const Options& options) {
  PersistentEngineSession session(options);
  bool started = false;
  bool draining = false;
  std::string line;
  while (std::getline(std::cin, line)) {
    try {
      if (line == "VEYRA_ENGINE 2") {
        if (started) throw std::invalid_argument("duplicate engine header");
        started = true;
        std::cout << "{\"status\":\"ready\",\"protocol_version\":2}\n" << std::flush;
        continue;
      }
      if (!started) throw std::invalid_argument("missing engine header");
      if (draining) {
        if (!line.empty() && line[0] != 'P' && line != "E") draining = false;
        if (draining) continue;
      }
      if (line == "R") {
        session.reset();
        std::cout << "{\"status\":\"available\",\"event\":\"reset\"}\n" << std::flush;
        continue;
      }
      if (line == "S") {
        std::string report = render(session.result());
        report.insert(1, "\"status\":\"available\",");
        std::cout << report << std::flush;
        continue;
      }
      if (line == "C") {
        if (session.frame_open()) throw std::invalid_argument("cannot close an open frame");
        std::cout << "{\"status\":\"closed\"}\n" << std::flush;
        return 0;
      }
      if (line == "M" || line.rfind("M ", 0) == 0) {
        std::size_t budget = 32768;
        if (line.size() > 1) {
          std::istringstream args(line.substr(1));
          std::uint64_t parsed = 0;
          if (!(args >> parsed) || parsed == 0 || parsed > 100000) {
            throw std::invalid_argument("invalid map cell budget");
          }
          require_end(args, "map cells request");
          budget = static_cast<std::size_t>(parsed);
        }
        std::cout << render_cells(session.result().snapshot, budget) << '\n' << std::flush;
        continue;
      }
      if (line.empty()) continue;
      std::istringstream record(line);
      std::string kind;
      record >> kind;
      if (kind != "F" && kind != "P" && kind != "E") {
        throw std::invalid_argument("unknown engine record");
      }
      session.ingest(line);
      if (kind == "E") {
        std::string report = render(session.result());
        report.insert(1, "\"status\":\"available\",");
        std::cout << report << std::flush;
      }
    } catch (const std::exception& error) {
      std::cout << "{\"status\":\"unavailable\",\"reason\":\""
                << escape(error.what()) << "\"}\n" << std::flush;
      session.reset();
      draining = true;
    }
  }
  return 0;
}

}  // namespace

int main(int argc, char **argv) {
  try {
    const auto options = parse_options(argc, argv);
    if (options.engine) return run_engine(options);
    const auto output = render(run(options));
    if (options.output.empty()) {
      std::cout << output;
    } else {
      std::ofstream file(options.output);
      if (!file) {
        throw std::runtime_error("cannot open output");
      }
      file << output;
    }
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "veyra_benchmark: " << error.what() << '\n';
    return 2;
  }
}
