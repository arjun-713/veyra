#include "veyra/runtime/engine.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <numbers>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <unordered_map>
#include <variant>
#include <vector>

#if defined(_WIN32)
#include <io.h>
#else
#include <unistd.h>

#include <cerrno>
#endif

#include "veyra/map/map.hpp"
#include "veyra/metrics/metrics.hpp"
#include "veyra/policy/policy.hpp"

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
  bool binary_input = false;
  // Visibility clearing is off by default. It changes what the map reports
  // about dynamic objects, so a benchmark comparing policies must opt in
  // deliberately and on both sides rather than inherit it silently.
  bool clearing_enabled = false;
  double sensor_height_m = 1.8;
  bool include_leaf_details = false;
  bool promotion_telemetry = false;
  // Withholds wall-clock evidence (frame time, process RSS) from the resource
  // governor so its decisions -- and therefore the map -- depend only on the
  // input stream. Cell and logical-byte budgets are still enforced; measured
  // frame time is still reported, it just no longer feeds back into topology.
  // Benchmarks use this so repeated runs produce identical maps.
  bool deterministic_governor = false;
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
  // Transparent comparator: per-point updates look fields up by string_view.
  std::map<std::string, NumericSummary, std::less<>> quality;
  std::uint64_t ground_true_count = 0;
  std::array<std::uint64_t, 3> drivable_counts{};
  std::array<std::uint64_t, 4> motion_state_counts{};
};

struct FrameMetric {
  InputSummary input;
  std::map<std::string, std::int64_t> stages_ns;
  std::uint64_t accepted_points = 0;
  std::uint64_t map_point_count_before_update = 0;
  bool point_conservation = false;
  std::uint64_t topology_churn = 0;
  std::uint64_t splits = 0;
  std::uint64_t merges = 0;
  std::uint64_t governor_interventions = 0;
  std::uint64_t governor_actions_applied = 0;
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
  // The persistent viewer response exposes the most recently ingested frame
  // even during warmup, when it is intentionally absent from frame_metrics.
  std::optional<InputSummary> last_input;
  std::optional<veyra::policy::GovernorStatus> governor;
  // Last frame's visibility-clearing outcome. Absent when clearing is off.
  std::optional<veyra::map::ClearingStats> clearing;
  std::optional<veyra::policy::ResourceGovernorConfig> governor_config;
  std::optional<veyra::policy::PromotionTelemetry> promotion_telemetry;
  bool governor_deterministic = false;
};

// Open-addressed CellId -> dense slot index for per-frame bookkeeping.
//
// The adapter looks a region up once per return, several times per return
// before this existed, and std::unordered_map allocated a node per region per
// frame. Clearing is O(1) by epoch, so the table (sized to the largest frame
// seen, never beyond what the caller inserts) is reused without being wiped.
// It carries no evidence: it only maps a cell to the position of its record in
// a caller-owned dense vector, so iteration order never depends on it.
class FlatCellIndex {
 public:
  static constexpr std::uint32_t kAbsent = std::numeric_limits<std::uint32_t>::max();

  void clear() noexcept {
    size_ = 0;
    if (++epoch_ == 0) {
      // Epoch wrapped: stale stamps could alias the new epoch.
      for (auto& bucket : buckets_) bucket.epoch = 0;
      epoch_ = 1;
    }
  }

  [[nodiscard]] std::size_t size() const noexcept { return size_; }

  [[nodiscard]] std::uint32_t find(veyra::core::CellId id) const noexcept {
    if (buckets_.empty()) return kAbsent;
    const std::size_t mask = buckets_.size() - 1;
    for (std::size_t at = hash(id) & mask;; at = (at + 1) & mask) {
      const Bucket& bucket = buckets_[at];
      if (bucket.epoch != epoch_) return kAbsent;
      if (bucket.id == id) return bucket.slot;
    }
  }

  // Inserts `slot` for an id the caller has just checked is absent.
  void insert(veyra::core::CellId id, std::uint32_t slot) {
    if ((size_ + 1) * 2 > buckets_.size()) grow();
    place(id, slot);
    ++size_;
  }

 private:
  struct Bucket {
    veyra::core::CellId id{};
    std::uint32_t slot = 0;
    std::uint32_t epoch = 0;
  };

  static std::size_t hash(veyra::core::CellId id) noexcept {
    std::uint64_t h = (static_cast<std::uint64_t>(static_cast<std::uint32_t>(id.ix)) << 32U) ^
                      static_cast<std::uint32_t>(id.iy) ^
                      (static_cast<std::uint64_t>(static_cast<std::uint32_t>(id.level)) << 61U);
    h ^= h >> 33U;
    h *= 0xff51afd7ed558ccdULL;
    h ^= h >> 33U;
    h *= 0xc4ceb9fe1a85ec53ULL;
    h ^= h >> 33U;
    return static_cast<std::size_t>(h);
  }

  void place(veyra::core::CellId id, std::uint32_t slot) noexcept {
    const std::size_t mask = buckets_.size() - 1;
    std::size_t at = hash(id) & mask;
    while (buckets_[at].epoch == epoch_) at = (at + 1) & mask;
    buckets_[at] = {id, slot, epoch_};
  }

  void grow() {
    std::vector<Bucket> old;
    old.swap(buckets_);
    buckets_.assign(std::max<std::size_t>(1024, old.size() * 2), Bucket{});
    const std::uint32_t live = epoch_;
    epoch_ = 1;
    for (const auto& bucket : old) {
      if (bucket.epoch == live) place(bucket.id, bucket.slot);
    }
  }

  std::vector<Bucket> buckets_;
  std::size_t size_ = 0;
  std::uint32_t epoch_ = 1;
};

enum class PolicyKind { kUniform5, kUniform40, kDistanceLod, kUtilityLod };

class MapPolicyAdapter {
 public:
  MapPolicyAdapter(PolicyKind kind, veyra::map::MapConfig config, const Options& options)
      : kind_(kind),
        config_(config),
        map_(make_storage(kind, config)),
        utility_(kind == PolicyKind::kUtilityLod
                     ? std::optional<veyra::policy::LodPolicy>{veyra::policy::load_policy_config(
                           options.utility_config)}
                     : std::nullopt),
        governor_(
            kind == PolicyKind::kUtilityLod
                ? std::optional<
                      veyra::policy::ResourceGovernor>{veyra::policy::load_resource_governor_config(
                      options.governor_config)}
                : std::nullopt) {
    options_promotion_telemetry_ = options.promotion_telemetry;
    deterministic_governor_ = options.deterministic_governor;
    if (utility_) utility_->enable_promotion_telemetry(options.promotion_telemetry);
  }

  [[nodiscard]] bool accepts(double x, double y) const {
    return std::visit([x, y](const auto& map) { return map.accepts(x, y); }, map_);
  }

  // Full-frame support before allocation: identical evidence regardless of
  // point ordering. Only bounded counts survive until the next frame.
  //
  // Each return's 40 cm policy region is resolved once here and remembered by
  // position, so the per-return work after this is an array read rather than
  // repeated hashing. Decisions are still taken point by point in stream order,
  // because LodPolicy::decide folds evidence incrementally and the order is
  // part of its contract.
  void prepare_frame(const std::vector<veyra::map::Observation>& observations) {
    if (!utility_) return;
    clear_frame_regions();
    point_slots_.resize(observations.size());
    for (std::size_t index = 0; index < observations.size(); ++index) {
      const auto& observation = observations[index];
      point_slots_[index] = accepts(observation.x, observation.y)
                                ? add_support_slot(policy_cell(observation.x, observation.y))
                                : kRejectedPoint;
    }
    support_prepared_ = true;
    // Resolve the complete scan before mutating topology. Otherwise a late
    // critical return splits already-fused evidence into a non-spatial prior,
    // or a later baseline request coarsens an earlier critical return.
    for (std::size_t index = 0; index < observations.size(); ++index) {
      const std::uint32_t slot = point_slots_[index];
      if (slot == kRejectedPoint) continue;
      const auto& observation = observations[index];
      if (slot == FlatCellIndex::kAbsent) {
        (void)requested_level(observation, policy_cell(observation.x, observation.y), 0);
        continue;
      }
      auto& region = regions_[slot];
      region.level = std::min(region.level, requested_level(observation, region.cell, region.count));
    }
  }

  // Integrates the frame most recently passed to prepare_frame(), in order.
  // Equivalent to ingest_observation() per return, reusing the regions
  // prepare_frame() resolved instead of recomputing them.
  template <typename OnAccepted>
  void integrate_prepared_frame(const std::vector<veyra::map::Observation>& observations,
                                std::uint64_t& rejected_out_of_window, OnAccepted&& on_accepted) {
    if (!utility_ || !support_prepared_ || point_slots_.size() != observations.size()) {
      for (const auto& observation : observations) {
        if (!accepts(observation.x, observation.y)) {
          ++rejected_out_of_window;
          continue;
        }
        update(observation);
        on_accepted(observation);
      }
      return;
    }
    auto& map = std::get<veyra::map::Map>(map_);
    for (std::size_t index = 0; index < observations.size(); ++index) {
      const std::uint32_t slot = point_slots_[index];
      if (slot == kRejectedPoint) {
        ++rejected_out_of_window;
        continue;
      }
      const auto& observation = observations[index];
      const int level =
          slot != FlatCellIndex::kAbsent
              ? regions_[slot].level
              : requested_level(observation, policy_cell(observation.x, observation.y), 0);
      map.update_at_level(observation, level);
      on_accepted(observation);
    }
  }

  void update(const veyra::map::Observation& observation) {
    if (kind_ != PolicyKind::kUtilityLod) {
      std::visit([&observation](auto& map) { map.update(observation); }, map_);
      return;
    }
    auto& map = std::get<veyra::map::Map>(map_);
    const auto cell = policy_cell(observation.x, observation.y);
    const std::uint32_t slot = region_index_.find(cell);
    int level = 0;
    if (support_prepared_ && slot != FlatCellIndex::kAbsent) {
      level = regions_[slot].level;
    } else {
      const std::size_t count =
          support_prepared_ ? support_count(slot) : add_support_count(cell, slot);
      level = requested_level(observation, cell, count);
    }
    map.update_at_level(observation, level);
  }

 private:
  static constexpr std::uint32_t kRejectedPoint = FlatCellIndex::kAbsent - 1;

  int requested_level(const veyra::map::Observation& observation,
                      veyra::core::CellId baseline_cell, std::size_t count) {
    auto& map = std::get<veyra::map::Map>(map_);
    const double offset_x = observation.x - center_x_;
    const double offset_y = observation.y - center_y_;
    const double range = std::hypot(offset_x, offset_y);
    const auto& utility_config = utility_->utility_config();
    const auto active_level = map.level_for(observation.x, observation.y);
    const auto decision = utility_->decide({
        .range_m = range,
        .active_level = active_level,
        .state_cell = baseline_cell,
        .safety_critical = observation.drivable == 2,
        .geometry_complexity = static_cast<double>(observation.geometry_complexity),
        .semantic_importance = veyra::policy::semantic_importance(
            utility_config, observation.semantic_class, observation.semantic_confidence),
        .motion = static_cast<double>(observation.motion_probability),
        .traversability_risk =
            observation.drivable == 2 ? static_cast<double>(observation.terrain_confidence) : 0.0,
        .semantic_uncertainty = 1.0 - static_cast<double>(observation.semantic_confidence),
        .observation_quality = static_cast<double>(observation.observation_quality),
        .point_density = veyra::policy::normalized_point_density(utility_config, count, range),
        .range_rate_mps = veyra::policy::radial_range_rate_mps(
            static_cast<double>(observation.velocity_x),
            static_cast<double>(observation.velocity_y), offset_x, offset_y),
        .semantic_class = observation.semantic_class,
    });
    int requested_level = decision.requested_level;
    if (governor_ && !governor_->status().allow_optional_splits && observation.drivable != 2) {
      requested_level =
          std::max(requested_level,
                   std::min(decision.baseline_level, map.level_for(observation.x, observation.y)));
    }
    if (utility_ && options_promotion_telemetry_ && requested_level > decision.requested_level)
      utility_->record_promotion_budget_effects(1, 0, 0);
    return requested_level;
  }

 public:
  void set_window_center(double x, double y) {
    if (utility_) utility_->begin_frame(frame_id_++);
    center_x_ = x;
    center_y_ = y;
    clear_frame_regions();
    std::visit([x, y](auto& map) { map.set_window_center(x, y); }, map_);
  }

  // Runs visibility clearing on whichever map variant is active.
  //
  // Uniform and distance wrappers hold a Map internally, so clearing is
  // available to every policy rather than only the one that happens to expose
  // the underlying type -- a dynamic-object correction that applied to just
  // one policy would make the benchmark comparison meaningless.
  veyra::map::ClearingStats clear_free_space(const veyra::map::DepthImage& image,
                                             const veyra::map::SensorPose& pose) {
    return std::visit([&](auto& map) { return map.clear_free_space(image, pose); }, map_);
  }

  [[nodiscard]] veyra::map::MapSnapshot snapshot() const {
    return std::visit([](const auto& map) { return map.snapshot(); }, map_);
  }

  void snapshot_into(veyra::map::MapSnapshot& out) const {
    std::visit([&out](const auto& map) { map.snapshot_into(out); }, map_);
  }

  // O(n) conservation bookkeeping without the snapshot's leaf sort.
  [[nodiscard]] std::uint64_t point_count() const {
    return std::visit([](const auto& map) { return map.point_count(); }, map_);
  }

  [[nodiscard]] bool uses_stateful_policy() const noexcept { return utility_.has_value(); }
  [[nodiscard]] bool deterministic_governor() const noexcept { return deterministic_governor_; }

  // Returns whether the map changed, so callers re-snapshot only when needed.
  bool apply_governor(const veyra::map::MapSnapshot& snapshot, double frame_time_ms) {
    if (!governor_.has_value()) return false;
    // Groups live in a reused dense vector indexed by parent. Candidate order
    // is irrelevant downstream: ResourceGovernor::decide ranks by a total order
    // over distinct cells, so the chosen merges match the previous ordered-map
    // grouping exactly while avoiding one tree node per group per frame.
    auto& groups = governor_groups_;
    groups.clear();
    governor_group_index_.clear();
    for (const auto& leaf : snapshot.leaves) {
      if (leaf.id.level >= 3) continue;
      const auto parent = leaf.id.parent();
      std::uint32_t slot = governor_group_index_.find(parent);
      if (slot == FlatCellIndex::kAbsent) {
        slot = static_cast<std::uint32_t>(groups.size());
        governor_group_index_.insert(parent, slot);
        groups.push_back(SiblingGroup{});
      }
      auto& group = groups[slot];
      if (group.count == 0) {
        const double resolution = veyra::core::resolution_m(parent.level);
        const double min_x = static_cast<double>(parent.ix) * resolution;
        const double min_y = static_cast<double>(parent.iy) * resolution;
        // Protect any square intersecting the safety disk, including siblings
        // whose centers lie outside it.
        const double dx = std::max({min_x - center_x_, 0.0, center_x_ - min_x - resolution});
        const double dy = std::max({min_y - center_y_, 0.0, center_y_ - min_y - resolution});
        group.candidate.cell = leaf.id;
        group.candidate.active_level = leaf.id.level;
        group.candidate.range_m = std::hypot(dx, dy);
      }
      ++group.count;
      const double risk = leaf.stats.drivable_evidence() < 0.0F
                              ? static_cast<double>(leaf.stats.terrain_confidence())
                              : 0.0;
      const auto& u = utility_->utility_config();
      const double utility = u.geometry_weight * leaf.stats.geometry_complexity() +
                             u.semantic_weight * veyra::policy::semantic_importance(
                                 u, leaf.stats.semantic_class, leaf.stats.semantic_confidence()) +
                             u.motion_weight * leaf.stats.motion_evidence() +
                             u.traversability_risk_weight * risk;
      group.candidate.utility_score =
          std::max(group.candidate.utility_score, std::clamp(utility, 0.0, 1.0));
      group.candidate.safety_critical =
          group.candidate.safety_critical || leaf.stats.drivable_evidence() < 0.0F;
    }
    auto& candidates = governor_candidates_;
    candidates.clear();
    for (const auto& group : groups) {
      if (group.count == 4) candidates.push_back(group.candidate);
    }
    // Deterministic mode: frame time and RSS are wall-clock/process evidence
    // that differ between identical runs, so they are withheld (zero frame
    // time contributes no load; absent RSS is unavailable, not zero).
    const auto actions = governor_->decide(
        {.active_cells = snapshot.active_leaf_count,
         .logical_bytes = snapshot.logical_bytes,
         .frame_time_ms = deterministic_governor_ ? 0.0 : frame_time_ms,
         .rss_bytes = deterministic_governor_ ? std::nullopt
                                              : veyra::metrics::read_process_rss_bytes()},
        candidates);
    auto& map = std::get<veyra::map::Map>(map_);
    for (const auto& action : actions) {
      if (action.action == veyra::policy::ResolutionAction::Merge)
        map.merge_children(action.cell.parent());
    }
    // Candidates are disjoint, complete sibling groups from this exact
    // snapshot; no concurrent mutations can invalidate them.
    governor_->record_applied_actions(actions.size());
    if (utility_) utility_->record_promotion_budget_effects(0, actions.size(), actions.size());
    return !actions.empty();
  }

  [[nodiscard]] std::optional<veyra::policy::GovernorStatus> governor_status() const {
    return governor_ ? std::optional{governor_->status()} : std::nullopt;
  }

  [[nodiscard]] std::optional<veyra::policy::ResourceGovernorConfig> governor_config() const {
    return governor_ ? std::optional{governor_->config()} : std::nullopt;
  }

  [[nodiscard]] std::optional<veyra::policy::PromotionTelemetry> promotion_telemetry() const {
    return utility_ && options_promotion_telemetry_ ? std::optional{utility_->promotion_telemetry()}
                                                    : std::nullopt;
  }

  void set_governor_override(veyra::policy::GovernorOverride mode) {
    if (governor_) governor_->set_override(mode);
  }

 private:
  veyra::core::CellId policy_cell(double x, double y) const {
    auto cell = std::get<veyra::map::Map>(map_).cell_for(x, y);
    while (cell.level < 3) cell = cell.parent();
    return cell;
  }
  void clear_frame_regions() noexcept {
    regions_.clear();
    region_index_.clear();
    point_slots_.clear();
    support_prepared_ = false;
  }
  [[nodiscard]] std::size_t support_count(std::uint32_t slot) const noexcept {
    return slot == FlatCellIndex::kAbsent ? 0 : regions_[slot].count;
  }
  // Counts one more return in `cell`'s region and returns the new count, or 0
  // when the region is untracked because the frame's region budget is full.
  std::size_t add_support_count(veyra::core::CellId cell, std::uint32_t slot) {
    if (slot != FlatCellIndex::kAbsent) return ++regions_[slot].count;
    if (regions_.size() >= utility_->utility_config().max_state_cells) return 0;
    region_index_.insert(cell, static_cast<std::uint32_t>(regions_.size()));
    regions_.push_back(FrameRegion{cell, 1, 3});
    return 1;
  }
  // As add_support_count(), returning the region's slot (kAbsent if untracked).
  std::uint32_t add_support_slot(veyra::core::CellId cell) {
    const std::uint32_t slot = region_index_.find(cell);
    if (slot != FlatCellIndex::kAbsent) {
      ++regions_[slot].count;
      return slot;
    }
    if (regions_.size() >= utility_->utility_config().max_state_cells) return FlatCellIndex::kAbsent;
    const auto inserted = static_cast<std::uint32_t>(regions_.size());
    region_index_.insert(cell, inserted);
    regions_.push_back(FrameRegion{cell, 1, 3});
    return inserted;
  }
  using Storage = std::variant<veyra::map::Uniform5Map, veyra::map::Uniform40Map,
                               veyra::map::DistanceLodMap, veyra::map::Map>;
  static Storage make_storage(PolicyKind kind, veyra::map::MapConfig config) {
    switch (kind) {
      case PolicyKind::kUniform5:
        return veyra::map::Uniform5Map{config};
      case PolicyKind::kUniform40:
        return veyra::map::Uniform40Map{config};
      case PolicyKind::kDistanceLod:
        return veyra::map::DistanceLodMap{config};
      case PolicyKind::kUtilityLod:
        return veyra::map::Map{veyra::map::ResolutionPolicy::DistanceLod, config};
    }
    throw std::logic_error("unknown policy kind");
  }
  struct SiblingGroup {
    veyra::policy::GovernorCandidate candidate{};
    std::size_t count = 0;
  };
  // Governor grouping scratch, reused every frame (bounded by active leaves).
  std::vector<SiblingGroup> governor_groups_;
  FlatCellIndex governor_group_index_;
  std::vector<veyra::policy::GovernorCandidate> governor_candidates_;
  PolicyKind kind_;
  veyra::map::MapConfig config_;
  Storage map_;
  std::optional<veyra::policy::LodPolicy> utility_;
  std::optional<veyra::policy::ResourceGovernor> governor_;
  std::uint64_t frame_id_ = 0;
  double center_x_ = 0.0;
  double center_y_ = 0.0;
  bool options_promotion_telemetry_ = false;
  bool deterministic_governor_ = false;
  struct FrameRegion {
    veyra::core::CellId cell{3, 0, 0};
    std::size_t count = 0;
    int level = 3;
  };
  // Bounded by max_state_cells regions and one slot per return of the
  // current frame; storage is reused across frames.
  std::vector<FrameRegion> regions_;
  FlatCellIndex region_index_;
  std::vector<std::uint32_t> point_slots_;
  bool support_prepared_ = false;
};

// Stream ingestion shared by batch execution and the persistent engine.
// A point outside the active window is a counted, documented rejection, not
// a frame abort: one marginal return must never strand a whole frame (or a
// whole pipe). Malformed records still throw via parse_observation_record.
bool ingest_observation(MapPolicyAdapter& map, const veyra::map::Observation& observation,
                        std::uint64_t& rejected_out_of_window) {
  if (!map.accepts(observation.x, observation.y)) {
    ++rejected_out_of_window;
    return false;
  }
  map.update(observation);
  return true;
}

double real_value(const std::string& value, const char* name) {
  std::size_t used = 0;
  const auto result = std::stod(value, &used);
  if (used != value.size() || !std::isfinite(result)) {
    throw std::invalid_argument(std::string("invalid ") + name);
  }
  return result;
}

std::optional<double> optional_real_value(const std::string& value, const char* name) {
  return value == "NA" ? std::nullopt : std::optional<double>{real_value(value, name)};
}

std::uint64_t uint_value(const std::string& value, const char* name) {
  std::size_t used = 0;
  const auto result = std::stoull(value, &used);
  if (used != value.size()) {
    throw std::invalid_argument(std::string("invalid ") + name);
  }
  return result;
}

std::optional<std::uint64_t> optional_uint_value(const std::string& value, const char* name) {
  return value == "NA" ? std::nullopt : std::optional<std::uint64_t>{uint_value(value, name)};
}

std::int64_t int_value(const std::string& value, const char* name) {
  std::size_t used = 0;
  const auto result = std::stoll(value, &used);
  if (used != value.size()) {
    throw std::invalid_argument(std::string("invalid ") + name);
  }
  return result;
}

void require_end(std::istringstream& input, const char* record) {
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

Options parse_options(int argc, char** argv) {
  Options options;
  for (int index = 1; index < argc; ++index) {
    const std::string_view arg(argv[index]);
    const auto needs_value = arg == "--policy" || arg == "--output" || arg == "--window-radius" ||
                             arg == "--sensor-height" || arg == "--levels" ||
                             arg == "--distance-boundaries" || arg == "--warmup-frames" ||
                             arg == "--utility-config" || arg == "--governor-config";
    if (needs_value && index + 1 >= argc) {
      throw std::invalid_argument("missing option value");
    }
    if (arg == "--policy") {
      options.policy = argv[++index];
    } else if (arg == "--output") {
      options.output = argv[++index];
    } else if (arg == "--sensor-height") {
      options.sensor_height_m = real_value(argv[++index], "sensor height");
    } else if (arg == "--window-radius") {
      options.window_radius = real_value(argv[++index], "window radius");
    } else if (arg == "--warmup-frames") {
      options.warmup_frames = uint_value(argv[++index], "warmup frames");
    } else if (arg == "--engine") {
      options.engine = true;
    } else if (arg == "--binary-input") {
      options.binary_input = true;
    } else if (arg == "--clear-free-space") {
      options.clearing_enabled = true;
    } else if (arg == "--include-leaf-details") {
      options.include_leaf_details = true;
    } else if (arg == "--promotion-telemetry") {
      options.promotion_telemetry = true;
    } else if (arg == "--deterministic-governor") {
      options.deterministic_governor = true;
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
      throw std::invalid_argument(
          "usage: --policy uniform5|distance_lod [--warmup-frames N] [--output path]");
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

void observe_quality(InputSummary& summary, std::string_view name, std::optional<double> value) {
  // Called ~15 times per point; building a std::string key each time was a
  // measurable share of frame parsing.
  auto entry = summary.quality.find(name);
  if (entry == summary.quality.end())
    entry = summary.quality.emplace(std::string(name), NumericSummary{}).first;
  entry->second.add(value);
}

constexpr std::array<const char*, 22> kFieldNames{"x",
                                                  "y",
                                                  "z",
                                                  "intensity",
                                                  "semantic_class",
                                                  "semantic_confidence",
                                                  "ground",
                                                  "drivable",
                                                  "slope",
                                                  "roughness",
                                                  "height_complexity",
                                                  "terrain_confidence",
                                                  "step",
                                                  "motion_probability",
                                                  "motion_state",
                                                  "velocity_x",
                                                  "velocity_y",
                                                  "observation_quality",
                                                  "raw_semantic_class",
                                                  "height_above_ground",
                                                  "ground_gradient_x",
                                                  "ground_gradient_y"};
constexpr std::array<std::size_t, 16> kQualityFields{3U,  4U,  5U,  8U,  9U,  10U, 11U, 12U,
                                                     13U, 15U, 16U, 17U, 18U, 19U, 20U, 21U};
// The quality accumulators a frame updates, resolved once instead of looked up
// by name for every field of every point. std::map nodes are stable, and
// entries are only ever added, so the pointers stay valid for the frame.
using QualitySlots = std::array<NumericSummary*, kQualityFields.size()>;

QualitySlots resolve_quality(InputSummary& summary) {
  QualitySlots slots{};
  for (std::size_t k = 0; k < kQualityFields.size(); ++k) {
    const std::string_view name = kFieldNames[kQualityFields[k]];
    auto entry = summary.quality.find(name);
    if (entry == summary.quality.end())
      entry = summary.quality.emplace(std::string(name), NumericSummary{}).first;
    slots[k] = &entry->second;
  }
  return slots;
}

// This is the sole protocol-to-map observation mapping. Both batch execution
// and the long-lived engine consume it, preventing a viewer-specific lossy
// interpretation of V2 semantic, terrain, motion, and quality evidence.
veyra::map::Observation observation_values(const std::array<double, 22>& v, InputSummary& summary,
                                           const QualitySlots* quality = nullptr) {
  for (std::size_t i : {0U, 1U, 2U, 3U, 4U, 5U, 6U, 7U, 14U, 18U}) {
    if (!std::isfinite(v[i])) throw std::invalid_argument("nonfinite required point value");
  }
  for (std::size_t i : {4U, 6U, 7U, 14U, 18U}) {
    if (v[i] < 0 || std::floor(v[i]) != v[i]) throw std::invalid_argument("invalid point integer");
  }
  if (v[4] > 65535 || v[6] > 1 || v[7] > 2 || v[14] > 3 || v[18] > 2147483647.)
    throw std::invalid_argument("point values out of range");
  for (std::size_t i : {5U, 11U, 13U, 17U}) {
    if (!std::isnan(v[i]) && (v[i] < 0 || v[i] > 1))
      throw std::invalid_argument("point confidence values out of range");
  }
  for (double value : v)
    if (std::isinf(value)) throw std::invalid_argument("infinite point value");
  ++summary.point_count;
  summary.ground_true_count += static_cast<std::uint64_t>(v[6]);
  ++summary.drivable_counts.at(static_cast<std::size_t>(v[7]));
  ++summary.motion_state_counts.at(static_cast<std::size_t>(v[14]));
  for (std::size_t k = 0; k < kQualityFields.size(); ++k) {
    const std::size_t i = kQualityFields[k];
    const auto sample = std::isnan(v[i]) ? std::nullopt : std::optional<double>{v[i]};
    if (quality != nullptr)
      (*quality)[k]->add(sample);
    else
      observe_quality(summary, kFieldNames[i], sample);
  }
  const auto value = [&](std::size_t i) {
    return static_cast<float>(std::isnan(v[i]) ? 0.0 : v[i]);
  };
  return {.x = v[0],
          .y = v[1],
          .z = v[2],
          .timestamp = summary.timestamp_us.value_or(0),
          .semantic_class = static_cast<std::uint16_t>(v[4]),
          .raw_semantic_class = static_cast<std::int32_t>(v[18]),
          .semantic_confidence = value(5),
          .drivable = static_cast<std::uint8_t>(v[7]),
          .ground = static_cast<std::uint8_t>(v[6]),
          // NOT value(19): NaN is the sentinel meaning "perception had no
          // ground model for this return". value() maps NaN to 0, which is a
          // genuine height and would silently file the scene into the obstacle
          // layer. The NaN must survive to CellStats::add, which counts it.
          .height_above_ground = static_cast<float>(v[19]),
          .terrain_confidence = value(11),
          .geometry_complexity = value(10),
          .motion_probability = value(13),
          .motion_state = static_cast<std::uint8_t>(v[14]),
          .observation_quality = value(17),
          .velocity_x = value(15),
          .velocity_y = value(16),
          .ground_gradient_x = static_cast<float>(v[20]),
          .ground_gradient_y = static_cast<float>(v[21])};
}

// Decode one packed little-endian scalar from memory and advance the cursor.
template <typename T>
T take_scalar(const unsigned char*& cursor) {
  std::array<unsigned char, sizeof(T)> bytes{};
  std::memcpy(bytes.data(), cursor, sizeof(T));
  cursor += sizeof(T);
  if constexpr (std::endian::native == std::endian::big) std::reverse(bytes.begin(), bytes.end());
  T value;
  std::memcpy(&value, bytes.data(), sizeof(T));
  return value;
}

// Read packed scalars without unaligned loads, struct padding or host-endian assumptions.
template <typename T>
T read_scalar(std::istream& input) {
  std::array<unsigned char, sizeof(T)> bytes{};
  if (!input.read(reinterpret_cast<char*>(bytes.data()), bytes.size()))
    throw std::invalid_argument("truncated binary frame");
  const unsigned char* cursor = bytes.data();
  return take_scalar<T>(cursor);
}

// libc++ ignores sync_with_stdio(false): std::cin stays an unbuffered stdio
// wrapper that takes a lock and calls getc() per byte, which dominated binary
// frame ingestion (~7 MB per 100k-point frame). This buffer reads whatever the
// pipe has available, so the line protocol never blocks waiting for a full
// buffer, and bulk reads become memcpy.
class FdInputBuffer final : public std::streambuf {
 public:
  explicit FdInputBuffer(int fd) : fd_(fd), buffer_(1U << 20U) {}

 protected:
  int_type underflow() override {
    if (gptr() < egptr()) return traits_type::to_int_type(*gptr());
    std::ptrdiff_t count = 0;
    do {
#if defined(_WIN32)
      count = _read(fd_, buffer_.data(), static_cast<unsigned>(buffer_.size()));
#else
      count = ::read(fd_, buffer_.data(), buffer_.size());
#endif
    }
#if defined(_WIN32)
    while (false);
#else
    while (count < 0 && errno == EINTR);
#endif
    if (count <= 0) return traits_type::eof();
    setg(buffer_.data(), buffer_.data(), buffer_.data() + count);
    return traits_type::to_int_type(*gptr());
  }

  std::streamsize xsgetn(char* out, std::streamsize count) override {
    std::streamsize copied = 0;
    while (copied < count) {
      if (gptr() == egptr() && traits_type::eq_int_type(underflow(), traits_type::eof())) break;
      const auto chunk = std::min<std::streamsize>(count - copied, egptr() - gptr());
      std::memcpy(out + copied, gptr(), static_cast<std::size_t>(chunk));
      setg(eback(), gptr() + chunk, egptr());
      copied += chunk;
    }
    return copied;
  }

 private:
  int fd_;
  std::vector<char> buffer_;
};

veyra::map::Observation parse_observation_record(std::istringstream& input, int stream_version,
                                                 InputSummary& summary) {
  std::vector<std::string> fields;
  for (std::string field; input >> field;) fields.push_back(std::move(field));
  const std::size_t expected_fields =
      stream_version == 1 ? 6U : (stream_version == 4 ? 22U : (stream_version == 3 ? 20U : 19U));
  if (fields.size() != expected_fields) throw std::invalid_argument("malformed point record");
  if (stream_version >= 2) {
    // V2 records carry no height above ground. It defaults to NaN rather than
    // 0 so a V2 producer is counted as "ground model unavailable" instead of
    // being mistaken for one reporting ground level.
    std::array<double, 22> values{};
    values[19] = std::numeric_limits<double>::quiet_NaN();
    values[20] = std::numeric_limits<double>::quiet_NaN();
    values[21] = std::numeric_limits<double>::quiet_NaN();
    for (std::size_t i = 0; i < fields.size(); ++i)
      values[i] = fields[i] == "NA" ? std::numeric_limits<double>::quiet_NaN()
                                    : real_value(fields[i], "point value");
    return observation_values(values, summary);
  }
  const auto x = real_value(fields[0], "x");
  const auto y = real_value(fields[1], "y");
  const auto z = real_value(fields[2], "z");
  const auto intensity = stream_version == 1
                             ? std::optional<double>{}
                             : std::optional<double>{real_value(fields[3], "intensity")};
  const auto semantic = uint_value(fields[stream_version == 1 ? 3 : 4], "semantic class");
  const auto semantic_confidence =
      real_value(fields[stream_version == 1 ? 4 : 5], "semantic confidence");
  const auto ground = stream_version == 1 ? 0 : uint_value(fields[6], "ground");
  const auto drivable = uint_value(fields[stream_version == 1 ? 5 : 7], "drivable");
  const auto slope =
      stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[8], "slope");
  const auto roughness =
      stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[9], "roughness");
  const auto height_complexity = stream_version == 1
                                     ? std::optional<double>{}
                                     : optional_real_value(fields[10], "height complexity");
  const auto terrain_confidence = stream_version == 1
                                      ? std::optional<double>{}
                                      : optional_real_value(fields[11], "terrain confidence");
  const auto step =
      stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[12], "step");
  const auto motion_probability = stream_version == 1
                                      ? std::optional<double>{}
                                      : optional_real_value(fields[13], "motion probability");
  const auto motion_state = stream_version == 1 ? 3 : uint_value(fields[14], "motion state");
  const auto velocity_x =
      stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[15], "velocity x");
  const auto velocity_y =
      stream_version == 1 ? std::optional<double>{} : optional_real_value(fields[16], "velocity y");
  const auto observation_quality = stream_version == 1
                                       ? std::optional<double>{}
                                       : optional_real_value(fields[17], "observation quality");
  const auto raw_semantic = stream_version == 1 ? static_cast<std::int64_t>(semantic)
                                                : int_value(fields[18], "raw semantic class");
  if (semantic > 65535 || semantic_confidence < 0.0 || semantic_confidence > 1.0 || ground > 1 ||
      drivable > 2 || motion_state > 3 || raw_semantic < 0) {
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
          .raw_semantic_class = static_cast<std::int32_t>(raw_semantic),
          .semantic_confidence = static_cast<float>(semantic_confidence),
          .drivable = static_cast<std::uint8_t>(drivable),
          .ground = static_cast<std::uint8_t>(ground),
          .terrain_confidence = static_cast<float>(terrain_confidence.value_or(0.0)),
          .geometry_complexity = static_cast<float>(height_complexity.value_or(0.0)),
          .motion_probability = static_cast<float>(motion_probability.value_or(0.0)),
          .motion_state = static_cast<std::uint8_t>(motion_state),
          .observation_quality = static_cast<float>(observation_quality.value_or(0.0)),
          .velocity_x = static_cast<float>(velocity_x.value_or(0.0)),
          .velocity_y = static_cast<float>(velocity_y.value_or(0.0)),
          .ground_gradient_x = std::numeric_limits<float>::quiet_NaN(),
          .ground_gradient_y = std::numeric_limits<float>::quiet_NaN()};
}

Result run(const Options& options) {
  const veyra::map::MapConfig config{
      .window_radius_m = options.window_radius,
      .tile_size_m = 10.0,
      .distance_boundaries_m = options.boundaries,
  };
  MapPolicyAdapter map(parse_policy(options.policy), config, options);
  veyra::metrics::MetricsCollector metrics{Clock::time_point{}};

  Result result;
  result.policy = options.policy;
  result.governor_config = map.governor_config();
  result.governor_deterministic = options.deterministic_governor;
  result.include_leaf_details = options.include_leaf_details;
  bool header = false;
  bool metadata = false;
  bool open = false;
  bool trailer = false;
  int stream_version = 0;
  // 1440 x 64 over [-25, +15] degrees: a quarter-degree azimuth step and 64
  // elevation rows, close to a 64-beam spinning unit. Bins coarser than the
  // sensor's angular resolution would merge distinct beams; finer would leave
  // gaps between them that read as "nothing measured" and suppress clearing.
  veyra::map::DepthImage scan_image{1440, 64, -25.0 * std::numbers::pi / 180.0,
                                    15.0 * std::numbers::pi / 180.0};
  veyra::map::SensorPose sensor_pose{};
  // False until a frame supplies a finite sensor pose; clearing never runs on
  // a fabricated pose (mirrors PersistentEngineSession::pose_valid_).
  bool pose_valid = false;
  std::uint64_t expected_points = 0;
  std::uint64_t points = 0;
  std::uint64_t frame_rejected_before = 0;
  std::uint64_t map_point_count_before_update = 0;
  std::optional<std::uint64_t> previous_timestamp;
  std::optional<std::uint64_t> previous_source_index;
  std::uint64_t previous_topology_changes = 0;
  std::uint64_t previous_splits = 0;
  std::uint64_t previous_merges = 0;
  std::uint64_t previous_governor_interventions = 0;
  std::uint64_t previous_governor_actions = 0;
  std::chrono::nanoseconds measured_elapsed{0};
  std::chrono::nanoseconds parse_duration{0};
  std::chrono::nanoseconds window_duration{0};
  std::chrono::nanoseconds update_duration{0};
  InputSummary input_summary;
  std::vector<veyra::map::Observation> pending_points;
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
      if (header || (version != "1" && version != "2" && version != "3" && version != "4")) {
        throw std::invalid_argument("invalid stream header");
      }
      stream_version = version == "1" ? 1 : (version == "4" ? 4 : (version == "3" ? 3 : 2));
      result.protocol_version = stream_version;
      header = true;
    } else if (kind == "H") {
      if (!header || metadata || open || trailer || !(input >> result.digest) ||
          result.digest.empty()) {
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
      pose = {1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0};
      if (stream_version == 1) {
        if (!(input >> timestamp >> count)) {
          throw std::invalid_argument("malformed legacy frame marker");
        }
        require_end(input, "legacy frame marker");
      } else {
        if (!(input >> timestamp >> pose_timestamp >> source_index)) {
          throw std::invalid_argument("malformed frame marker");
        }
        for (double& element : pose) {
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
      // >= 2, not == 2. V3 is V2 plus a trailing field, so everything V2
      // carries is still present. Testing for equality here silently reported
      // V3 streams as having no pose and no enriched evidence.
      input_summary.pose_available = stream_version >= 2;
      input_summary.enriched_fields_available = stream_version >= 2;
      if (stream_version >= 2) {
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
      if (options.policy == "utility_lod" && expected_points > 2'000'000)
        throw std::invalid_argument("utility frame exceeds point limit");
      pending_points.clear();
      points = 0;
      parse_duration = std::chrono::nanoseconds{duration_ns(started)};
      const auto window_started = Clock::now();
      // Rebuilt, not reallocated: the raster is the same shape every frame, so
      // clearing it keeps this off the allocator on the hot path.
      scan_image.clear();
      sensor_pose = {pose[3], pose[7], pose[11] + options.sensor_height_m};
      pose_valid = std::isfinite(sensor_pose.x) && std::isfinite(sensor_pose.y) &&
                   std::isfinite(sensor_pose.z);
      map.set_window_center(pose[3], pose[7]);
      map_point_count_before_update = map.point_count();
      frame_rejected_before = result.rejected_out_of_window;
      window_duration = std::chrono::nanoseconds{duration_ns(window_started)};
      update_duration = std::chrono::nanoseconds{0};
      open = true;
    } else if (kind == "P") {
      const auto parse_started = Clock::now();
      if (!open) throw std::invalid_argument("point outside frame");
      auto observation = parse_observation_record(input, stream_version, input_summary);
      observation.timestamp = input_summary.timestamp_us.value_or(result.input_frames);
      parse_duration += std::chrono::nanoseconds{duration_ns(parse_started)};
      if (options.policy == "utility_lod") {
        if (points >= expected_points) throw std::invalid_argument("frame point count exceeded");
        pending_points.push_back(observation);
        ++points;
        continue;
      }
      const auto update_started = Clock::now();
      if (ingest_observation(map, observation, result.rejected_out_of_window)) {
        ++result.input_points;
        // Every accepted return is one beam's endpoint, so the raster is built
        // from the same points the map ingests. Rejected points are excluded on
        // purpose: a return outside the window cannot license clearing inside it.
        if (pose_valid) scan_image.insert(observation, sensor_pose);
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
      if (options.policy == "utility_lod") {
        const auto update_started = Clock::now();
        map.prepare_frame(pending_points);
        map.integrate_prepared_frame(pending_points, result.rejected_out_of_window,
                                     [&](const veyra::map::Observation& observation) {
                                       ++result.input_points;
                                       scan_image.insert(observation, sensor_pose);
                                     });
        update_duration += std::chrono::nanoseconds{duration_ns(update_started)};
      }
      // Visibility clearing runs after the frame is integrated and before the
      // snapshot, so the published map reflects both what this scan added and
      // what it contradicted. Its cost is counted in update_duration, where
      // every other per-frame map cost already is.
      // Missing/invalid pose or an empty raster skips honestly: no evidence is
      // not evidence of absence, so nothing is cleared (mirrors end_frame).
      if (options.clearing_enabled && pose_valid && scan_image.filled_bins() > 0) {
        const auto clearing_started = Clock::now();
        result.clearing = map.clear_free_space(scan_image, sensor_pose);
        update_duration += std::chrono::nanoseconds{duration_ns(clearing_started)};
      } else {
        result.clearing.reset();
      }
      const auto snapshot_started = Clock::now();
      auto snapshot = map.snapshot();
      if (map.apply_governor(
              snapshot,
              static_cast<double>((parse_duration + window_duration + update_duration).count()) /
                  1'000'000.0))
        snapshot = map.snapshot();
      result.governor = map.governor_status();
      const auto governor_interventions =
          result.governor ? result.governor->interventions - previous_governor_interventions : 0;
      const auto governor_actions =
          result.governor ? result.governor->actions_applied - previous_governor_actions : 0;
      if (result.governor) {
        previous_governor_interventions = result.governor->interventions;
        previous_governor_actions = result.governor->actions_applied;
      }
      const auto snapshot_duration = std::chrono::nanoseconds{duration_ns(snapshot_started)};
      const auto topology_churn = snapshot.topology_change_count - previous_topology_changes;
      const auto splits = snapshot.split_count - previous_splits;
      const auto merges = snapshot.merge_count - previous_merges;
      previous_topology_changes = snapshot.topology_change_count;
      previous_splits = snapshot.split_count;
      previous_merges = snapshot.merge_count;
      const auto rss = veyra::metrics::read_process_rss_bytes();
      const auto frame_rejected = result.rejected_out_of_window - frame_rejected_before;
      const auto accepted_points = points - frame_rejected;
      const bool point_conservation =
          snapshot.point_count == map_point_count_before_update + accepted_points;
      metrics.observe_rss_bytes(rss);
      const bool is_warmup = result.input_frames < options.warmup_frames;
      ++result.input_frames;
      if (is_warmup) {
        ++result.warmup_frames;
      } else {
        const auto frame_pipeline =
            parse_duration + window_duration + update_duration + snapshot_duration;
        measured_elapsed += frame_pipeline;
        metrics.record_duration("protocol_parse_and_validate", parse_duration);
        metrics.record_duration("map_window_follow", window_duration);
        metrics.record_duration("map_update", update_duration);
        metrics.record_duration("snapshot_and_topology", snapshot_duration);
        metrics.record_duration("frame_pipeline", frame_pipeline);
        metrics.record_value("topology_churn", static_cast<std::int64_t>(topology_churn));
        metrics.record_value("splits", static_cast<std::int64_t>(splits));
        metrics.record_value("merges", static_cast<std::int64_t>(merges));
        metrics.record_value("governor_interventions",
                             static_cast<std::int64_t>(governor_interventions));
        metrics.record_value("governor_actions_applied",
                             static_cast<std::int64_t>(governor_actions));
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
            .accepted_points = accepted_points,
            .map_point_count_before_update = map_point_count_before_update,
            .point_conservation = point_conservation,
            .topology_churn = topology_churn,
            .splits = splits,
            .merges = merges,
            .governor_interventions = governor_interventions,
            .governor_actions_applied = governor_actions,
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
  result.promotion_telemetry = map.promotion_telemetry();
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

void write_optional_uint(std::ostringstream& out, std::optional<std::uint64_t> value) {
  if (value.has_value()) {
    out << *value;
  } else {
    out << "null";
  }
}

void write_optional_double(std::ostringstream& out, std::optional<double> value) {
  if (value.has_value()) {
    out << *value;
  } else {
    out << "null";
  }
}

void write_numeric_summary(std::ostringstream& out, const NumericSummary& summary) {
  out << "{\"count\":" << summary.count << ",\"mean\":";
  if (summary.count == 0) {
    out << "null,\"min\":null,\"max\":null}";
    return;
  }
  out << summary.sum / static_cast<double>(summary.count) << ",\"min\":" << summary.min
      << ",\"max\":" << summary.max << '}';
}

void write_duration_statistics(std::ostringstream& out,
                               const veyra::metrics::DurationStatistics& stats) {
  out << "{\"count\":" << stats.count << ",\"mean\":" << stats.mean_ns
      << ",\"min\":" << stats.min_ns << ",\"max\":" << stats.max_ns << ",\"p50\":" << stats.p50_ns
      << ",\"p95\":" << stats.p95_ns << ",\"p99\":" << stats.p99_ns << '}';
}

void write_value_statistics(std::ostringstream& out, const veyra::metrics::ValueStatistics& stats) {
  out << "{\"count\":" << stats.count << ",\"mean\":" << stats.mean << ",\"min\":" << stats.min
      << ",\"max\":" << stats.max << ",\"p50\":" << stats.p50 << ",\"p95\":" << stats.p95
      << ",\"p99\":" << stats.p99 << '}';
}

void write_input_summary(std::ostringstream& out, const InputSummary& input) {
  out << "{\"pose_available\":" << (input.pose_available ? "true" : "false")
      << ",\"enriched_fields_available\":" << (input.enriched_fields_available ? "true" : "false")
      << ",\"timestamp_us\":";
  write_optional_uint(out, input.timestamp_us);
  out << ",\"pose_timestamp_us\":";
  write_optional_uint(out, input.pose_timestamp_us);
  out << ",\"source_index\":";
  write_optional_uint(out, input.source_index);
  out << ",\"pose_translation_xyz\":[" << input.pose_translation[0] << ','
      << input.pose_translation[1] << ',' << input.pose_translation[2]
      << "],\"point_count\":" << input.point_count
      << ",\"ground\":{\"true_count\":" << input.ground_true_count
      << ",\"false_count\":" << input.point_count - input.ground_true_count
      << "},\"drivable_counts\":{\"unknown\":" << input.drivable_counts[0]
      << ",\"drivable\":" << input.drivable_counts[1]
      << ",\"non_drivable\":" << input.drivable_counts[2]
      << "},\"motion_state_counts\":{\"static\":" << input.motion_state_counts[0]
      << ",\"possibly_moving\":" << input.motion_state_counts[1]
      << ",\"moving\":" << input.motion_state_counts[2]
      << ",\"unknown\":" << input.motion_state_counts[3] << "},\"quality\":{";
  bool first = true;
  for (const auto& [name, summary] : input.quality) {
    if (!std::exchange(first, false)) {
      out << ',';
    }
    out << '"' << escape(name) << "\":";
    write_numeric_summary(out, summary);
  }
  out << "}}";
}

std::string render(const Result& result) {
  const auto& snapshot = result.snapshot;
  const auto& metrics = result.metrics;
  std::ostringstream out;
  out << std::setprecision(17);
  out << "{\"schema_version\":2,\"protocol_version\":" << result.protocol_version
      << ",\"policy\":\"" << escape(result.policy) << "\",\"stream_digest\":\""
      << escape(result.digest) << "\",\"input_frames\":" << result.input_frames
      << ",\"warmup_frames\":" << result.warmup_frames
      << ",\"measured_frames\":" << metrics.frame_count << ",\"frames\":" << metrics.frame_count
      << ",\"input_points\":" << result.input_points;
  if (result.last_input.has_value()) {
    out << ",\"input\":";
    write_input_summary(out, *result.last_input);
  }
  out << ",\"snapshot\":{\"active_leaf_count\":" << snapshot.active_leaf_count
      << ",\"tile_count\":" << snapshot.tile_count << ",\"point_count\":" << snapshot.point_count
      << ",\"logical_bytes\":" << snapshot.logical_bytes
      << ",\"memory\":{\"logical_payload_bytes\":" << snapshot.memory.logical_payload_bytes
      << ",\"retained_prior_payload_bytes\":" << snapshot.memory.retained_prior_payload_bytes
      << ",\"allocated_cell_array_bytes\":" << snapshot.memory.allocated_cell_array_bytes
      << ",\"allocated_tile_bytes\":" << snapshot.memory.allocated_tile_bytes
      << ",\"allocated_index_bytes\":" << snapshot.memory.allocated_index_bytes
      << ",\"allocated_scratch_bytes\":" << snapshot.memory.allocated_scratch_bytes
      << ",\"allocated_overhead_bytes\":" << snapshot.memory.allocated_overhead_bytes
      << ",\"allocated_bytes\":" << snapshot.memory.allocated_bytes << "},\"levels\":{";
  for (int level = 0; level < 4; ++level) {
    if (level > 0) {
      out << ',';
    }
    out << '"' << level << "\":" << snapshot.count_at_level(level);
  }
  out << "},\"nonspatial_prior_point_count\":" << snapshot.nonspatial_prior_point_count
      << ",\"split_count\":" << snapshot.split_count << ",\"merge_count\":" << snapshot.merge_count
      << ",\"invariant_no_parent_descendant_overlap\":"
      << (snapshot.has_no_parent_descendant_overlap() ? "true" : "false")
      // Layer telemetry. `unmodelled_returns` is the field that makes a
      // producer which stopped supplying height_above_ground visible instead
      // of silently degrading the map into one undifferentiated obstacle blob.
      << ",\"layers\":{\"ground_points\":" << snapshot.layers.ground_points
      << ",\"obstacle_points\":" << snapshot.layers.obstacle_points
      << ",\"overhead_points\":" << snapshot.layers.overhead_points
      << ",\"unmodelled_returns\":" << snapshot.layers.unmodelled_returns
      << ",\"rejected_outliers\":" << snapshot.layers.rejected_outliers
      << ",\"cells_with_ground\":" << snapshot.layers.cells_with_ground
      << ",\"occluded_ground_cells\":" << snapshot.layers.occluded_ground_cells
      << ",\"occupied_cells\":" << snapshot.layers.occupied_cells
      << ",\"free_cells\":" << snapshot.layers.free_cells << '}';
  if (result.clearing.has_value()) {
    // Reported in full, not just the cleared count. "Spared by elevation" is
    // the number that says how often a projected 2D sweep would have erased
    // something real, and a clearing pass that cannot show its refusals is
    // not auditable.
    const auto& clearing = *result.clearing;
    out << ",\"clearing\":{\"examined\":" << clearing.examined
        << ",\"cleared\":" << clearing.cleared << ",\"armed\":" << clearing.armed
        << ",\"occluded\":" << clearing.occluded << ",\"no_evidence\":" << clearing.no_evidence
        << ",\"spared_by_elevation\":" << clearing.spared_by_elevation << '}';
  }
  if (result.include_leaf_details) {
    out << ",\"leaves\":[";
    for (std::size_t index = 0; index < snapshot.leaves.size(); ++index) {
      if (index > 0) out << ',';
      const auto& leaf = snapshot.leaves[index];
      out << "{\"level\":" << leaf.id.level << ",\"ix\":" << leaf.id.ix << ",\"iy\":" << leaf.id.iy
          << ",\"count\":" << leaf.stats.count << ",\"mean_z\":" << leaf.stats.mean_z()
          << ",\"semantic_class\":" << leaf.stats.semantic_class
          << ",\"semantic_confidence\":" << leaf.stats.semantic_confidence()
          << ",\"ground_evidence\":" << leaf.stats.ground_evidence()
          << ",\"drivable_evidence\":" << leaf.stats.drivable_evidence()
          << ",\"ground_count\":" << leaf.stats.ground.count
          << ",\"ground_mean_z\":" << leaf.stats.ground.mean_z
          << ",\"ground_stddev_m\":" << leaf.stats.ground.stddev_z()
          << ",\"ground_last_seen\":" << leaf.stats.ground.last_seen
          << ",\"ground_gradient_x\":" << leaf.stats.ground_gradient_x()
          << ",\"ground_gradient_y\":" << leaf.stats.ground_gradient_y()
          << ",\"ground_gradient_count\":" << leaf.stats.ground_gradient_count
          << ",\"obstacle_count\":" << leaf.stats.obstacle.count
          << ",\"obstacle_min_z\":" << leaf.stats.obstacle.min_z
          << ",\"obstacle_max_z\":" << leaf.stats.obstacle.max_z
          << ",\"overhead_count\":" << leaf.stats.overhead.count
          << ",\"overhead_min_z\":" << leaf.stats.overhead.min_z
          << ",\"overhead_max_z\":" << leaf.stats.overhead.max_z
          << ",\"terrain_confidence\":" << leaf.stats.terrain_confidence()
          << ",\"geometry_complexity\":" << leaf.stats.geometry_complexity()
          << ",\"motion_evidence\":" << leaf.stats.motion_evidence()
          << ",\"observation_quality\":" << leaf.stats.observation_quality()
          << ",\"sorted_envelope_m\":" << leaf.stats.sorted_envelope_m
          << ",\"occupancy_logodds\":" << leaf.stats.occupancy_logodds << '}';
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
  for (const auto& [name, stats] : sorted_durations) {
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
  out << ",\"topology\":{\"total_change_count\":" << snapshot.topology_change_count
      << ",\"total_split_count\":" << snapshot.split_count
      << ",\"total_merge_count\":" << snapshot.merge_count << ",\"per_level_cells_final\":{";
  for (int level = 0; level < 4; ++level) {
    if (level > 0) {
      out << ',';
    }
    out << '"' << level << "\":" << snapshot.count_at_level(level);
  }
  out << "},\"per_frame\":{";
  first = true;
  const std::map<std::string, veyra::metrics::ValueStatistics> sorted_values(metrics.values.begin(),
                                                                             metrics.values.end());
  for (const auto& [name, stats] : sorted_values) {
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
      << (metrics.allocated_map_bytes.has_value() ? "public map allocator measurement"
                                                  : "allocator measurement unavailable")
      << "\""
      << ",\"current_rss_bytes\":";
  write_optional_uint(out, metrics.current_rss_bytes);
  out << ",\"peak_rss_bytes\":";
  write_optional_uint(out, metrics.peak_rss_bytes);
  out << "},\"measured_rss_bytes\":";
  write_optional_uint(out, metrics.current_rss_bytes);
  out << ",\"stream\":{\"late_frames\":" << result.late_frames
      << ",\"rejected_out_of_window\":" << result.rejected_out_of_window << ",\"dropped_frames\":";
  write_optional_uint(out, result.dropped_frames);
  out << ",\"source_index_complete\":" << (result.source_indices_complete ? "true" : "false")
      << "}}";
  out << ",\"frame_metrics\":[";
  for (std::size_t index = 0; index < result.frame_metrics.size(); ++index) {
    if (index > 0) {
      out << ',';
    }
    const auto& frame = result.frame_metrics[index];
    out << "{\"input\":";
    write_input_summary(out, frame.input);
    out << ",\"stages_ns\":{";
    first = true;
    for (const auto& [name, duration] : frame.stages_ns) {
      if (!std::exchange(first, false)) {
        out << ',';
      }
      out << '"' << escape(name) << "\":" << duration;
    }
    out << "},\"accepted_points\":" << frame.accepted_points
        << ",\"map_point_count_before_update\":" << frame.map_point_count_before_update
        << ",\"point_conservation\":{\"holds\":" << (frame.point_conservation ? "true" : "false")
        << ",\"scope\":\"active_window_after_frame\"}"
        << ",\"topology_churn\":" << frame.topology_churn << ",\"splits\":" << frame.splits
        << ",\"merges\":" << frame.merges
        << ",\"governor_interventions\":" << frame.governor_interventions
        << ",\"governor_actions_applied\":" << frame.governor_actions_applied
        << ",\"cells_by_level\":[" << frame.cells_by_level[0] << ',' << frame.cells_by_level[1]
        << ',' << frame.cells_by_level[2] << ',' << frame.cells_by_level[3] << "],\"rss_bytes\":";
    write_optional_uint(out, frame.rss_bytes);
    out << '}';
  }
  out << ']';
  if (result.promotion_telemetry) {
    const auto& telemetry = *result.promotion_telemetry;
    constexpr std::array<std::string_view, 5> signal_names{
        "geometry", "semantic", "motion", "traversability_risk", "semantic_uncertainty"};
    out << ",\"promotion_telemetry\":{\"decisions\":" << telemetry.decisions
        << ",\"gate_passed\":" << telemetry.gate_passed
        << ",\"gate_failed\":" << telemetry.gate_failed
        << ",\"diagnostics_version\":1,\"quality_failed\":" << telemetry.quality_failed
        << ",\"density_failed\":" << telemetry.density_failed
        << ",\"safety_decisions\":" << telemetry.safety_decisions
        << ",\"predictive_decisions\":" << telemetry.predictive_decisions
        << ",\"critical_semantic_decisions\":" << telemetry.critical_semantic_decisions
        << ",\"budget_suppressed\":" << telemetry.budget_suppressed
        << ",\"governor_actions_requested\":" << telemetry.governor_actions_requested
        << ",\"governor_actions_applied\":" << telemetry.governor_actions_applied
        << ",\"signals\":{";
    for (std::size_t i = 0; i < signal_names.size(); ++i) {
      if (i) out << ',';
      out << '\"' << signal_names[i] << "\":{\"raw_sum\":" << telemetry.signal_raw_sum[i]
          << ",\"weighted_sum\":" << telemetry.signal_weighted_sum[i]
          << ",\"effective_weighted_sum\":" << telemetry.signal_effective_weighted_sum[i]
          << ",\"min\":" << telemetry.signal_min[i]
          << ",\"max\":" << telemetry.signal_max[i]
          << ",\"exact_zero_count\":" << telemetry.signal_exact_zero_count[i]
          << ",\"near_one_count\":" << telemetry.signal_near_one_count[i] << ",\"histogram\":[";
      for (std::size_t bin = 0; bin < 20; ++bin) {
        if (bin) out << ',';
        out << telemetry.signal_histogram[i][bin];
      }
      out << "]}";
    }
    out << "},\"utility_exact_zero_count\":" << telemetry.utility_exact_zero_count
        << ",\"utility_near_one_count\":" << telemetry.utility_near_one_count
        << ",\"utility_min\":" << telemetry.utility_min
        << ",\"utility_max\":" << telemetry.utility_max
        << ",\"utility_above_split_count\":" << telemetry.utility_above_split_count
        << ",\"utility_below_merge_count\":" << telemetry.utility_below_merge_count
        << ",\"utility_histogram\":[";
    for (std::size_t bin = 0; bin < 20; ++bin) {
      if (bin) out << ',';
      out << telemetry.utility_histogram[bin];
    }
    out << "],\"transition_reason_masks\":[";
    bool first_reason = true;
    for (std::size_t mask = 0; mask < telemetry.transition_reason_masks.size(); ++mask) {
      if (!telemetry.transition_reason_masks[mask]) continue;
      if (!std::exchange(first_reason, false)) out << ',';
      out << "{\"mask\":" << mask << ",\"count\":" << telemetry.transition_reason_masks[mask]
          << '}';
    }
    out << "],\"promotion_transitions\":[";
    bool first_transition = true;
    for (std::size_t active = 0; active < 4; ++active)
      for (std::size_t requested = 0; requested < 4; ++requested)
        for (std::size_t baseline = 0; baseline < 4; ++baseline) {
          const auto count = telemetry.promotion_transitions[active][requested][baseline];
          if (!count) continue;
          if (!std::exchange(first_transition, false)) out << ',';
          out << "{\"active\":" << active << ",\"requested\":" << requested
              << ",\"baseline\":" << baseline << ",\"count\":" << count << '}';
        }
    out << "],\"decision_reasons\":{";
    for (std::size_t i = 0; i < veyra::policy::kUtilityDecisionReasons.size(); ++i) {
      if (i) out << ',';
      out << '\"' << veyra::policy::kUtilityDecisionReasons[i] << "\":" << telemetry.decision_reasons[i];
    }
    out << "},\"support_histograms\":{";
    constexpr std::array<std::string_view, 2> support_names{"observation_quality", "point_density"};
    for (std::size_t i = 0; i < support_names.size(); ++i) {
      if (i) out << ',';
      out << '\"' << support_names[i] << "\":[";
      for (std::size_t bin = 0; bin < 20; ++bin) {
        if (bin) out << ',';
        out << telemetry.support_histogram[i][bin];
      }
      out << ']';
    }
    out << "},\"classes\":[";
    for (std::size_t i = 0; i < telemetry.class_decisions.size(); ++i) {
      if (i) out << ',';
      out << "{\"id\":" << i << ",\"decisions\":" << telemetry.class_decisions[i]
          << ",\"gate_failed\":" << telemetry.class_gate_failed[i] << '}';
    }
    out << "]}";
  }
  if (result.governor) {
    const auto& governor = *result.governor;
    const char* state = "normal";
    switch (governor.state) {
      case veyra::policy::GovernorState::Normal:
        state = "normal";
        break;
      case veyra::policy::GovernorState::ApproachingBudget:
        state = "approaching_budget";
        break;
      case veyra::policy::GovernorState::Overloaded:
        state = "overloaded";
        break;
      case veyra::policy::GovernorState::Recovering:
        state = "recovering";
        break;
      case veyra::policy::GovernorState::Disabled:
        state = "disabled";
        break;
    }
    out << ",\"governor\":{\"state\":\"" << state
        << "\",\"allow_optional_splits\":" << (governor.allow_optional_splits ? "true" : "false")
        << ",\"overload_frames\":" << governor.overload_frames
        << ",\"recovery_frames\":" << governor.recovery_frames
        << ",\"interventions\":" << governor.interventions
        << ",\"actions_requested\":" << governor.actions_requested
        << ",\"actions_applied\":" << governor.actions_applied
        << ",\"deterministic\":" << (result.governor_deterministic ? "true" : "false");
    if (result.governor_config) {
      const auto& budget = *result.governor_config;
      out << ",\"budget\":{\"max_active_cells\":" << budget.max_active_cells
          << ",\"max_logical_bytes\":" << budget.max_logical_bytes
          << ",\"max_rss_bytes\":" << budget.max_rss_bytes
          << ",\"target_frame_time_ms\":" << budget.target_frame_time_ms
          << ",\"near_field_radius_m\":" << budget.near_field_radius_m
          << ",\"max_actions_per_frame\":" << budget.max_actions_per_frame << '}';
    }
    out << '}';
  }
  out << "}\n";
  return out.str();
}

// Stateful counterpart to the batch stream reader. It deliberately consumes
// the same parse_observation_record mapping as run(), but retains the real map
// and policy objects between F/P/E transactions.
class PersistentEngineSession {
 public:
  explicit PersistentEngineSession(const Options& options)
      : options_(options),
        display_utility_(veyra::policy::load_policy_config(options.utility_config).utility) {
    reset();
  }

  void reset() {
    const veyra::map::MapConfig config{.window_radius_m = options_.window_radius,
                                       .tile_size_m = 10.0,
                                       .distance_boundaries_m = options_.boundaries};
    map_ = std::make_unique<MapPolicyAdapter>(parse_policy(options_.policy), config, options_);
    metrics_ = std::make_unique<veyra::metrics::MetricsCollector>(Clock::time_point{}, 600);
    result_ = Result{};
    result_.policy = options_.policy;
    result_.governor_config = map_->governor_config();
    result_.governor_deterministic = options_.deterministic_governor;
    result_.include_leaf_details = options_.include_leaf_details;
    result_.digest = "engine-session";
    result_.protocol_version = 2;
    open_ = false;
    expected_points_ = points_ = 0;
    previous_timestamp_.reset();
    previous_source_index_.reset();
    previous_topology_changes_ = 0;
    previous_splits_ = 0;
    previous_merges_ = 0;
    previous_governor_interventions_ = 0;
    previous_governor_actions_ = 0;
    measured_elapsed_ = std::chrono::nanoseconds{0};
    parse_duration_ = window_duration_ = update_duration_ = std::chrono::nanoseconds{0};
    frame_rejected_before_ = 0;
    map_point_count_before_update_ = 0;
    input_summary_ = InputSummary{};
    scan_image_.clear();
    pose_valid_ = false;
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
  void set_digest(std::string digest) { result_.digest = std::move(digest); }
  [[nodiscard]] std::uint64_t frame_count() const noexcept { return result_.input_frames; }
  [[nodiscard]] bool frame_open() const noexcept { return open_; }
  [[nodiscard]] const veyra::policy::UtilityConfig& display_utility() const noexcept {
    return display_utility_;
  }
  void set_governor_override(veyra::policy::GovernorOverride mode) {
    map_->set_governor_override(mode);
    result_.governor = map_->governor_status();
  }

  void set_protocol_version(int version) { protocol_version_ = version; }

  void ingest_binary(std::istream& input, std::size_t count) { ingest_binary(input, count, 2); }

  void ingest_binary(std::istream& input, std::size_t count, int binary_version) {
    if (count > 2'000'000) throw std::invalid_argument("binary frame exceeds point limit");
    std::ostringstream marker;
    marker << std::setprecision(17);
    for (int i = 0; i < 3; ++i) {
      const auto stamp = read_scalar<std::uint64_t>(input);
      if (stamp == std::numeric_limits<std::uint64_t>::max())
        marker << "NA ";
      else
        marker << stamp << ' ';
    }
    for (int i = 0; i < 16; ++i) marker << read_scalar<double>(input) << ' ';
    marker << count;
    std::istringstream frame(marker.str());
    begin_frame(frame);
    // V3 adds height-above-ground; V4 adds the two ground-plane gradients.
    // Older rows keep optional values NaN, preserving unavailable state.
    constexpr std::size_t kRowBytesV2 = 67;
    const std::size_t row_bytes = binary_version >= 4
                                      ? kRowBytesV2 + 12
                                      : (binary_version >= 3 ? kRowBytesV2 + 4 : kRowBytesV2);
    std::array<unsigned char, kRowBytesV2 + 12> row{};
    // Two phases, each timed once: decode every row, then fold them into the
    // map in the same order. Timing each point separately cost four clock
    // reads per point, a visible share of the frame.
    const auto parse_started = Clock::now();
    pending_.clear();
    pending_.reserve(count);
    // Resolved only when a row exists, so an empty frame adds no entries.
    std::optional<QualitySlots> quality;
    for (std::size_t point = 0; point < count; ++point) {
      std::array<double, 22> values{};
      values[19] = std::numeric_limits<double>::quiet_NaN();
      values[20] = std::numeric_limits<double>::quiet_NaN();
      values[21] = std::numeric_limits<double>::quiet_NaN();
      if (!input.read(reinterpret_cast<char*>(row.data()), static_cast<std::streamsize>(row_bytes)))
        throw std::invalid_argument("truncated binary frame");
      const unsigned char* cursor = row.data();
      for (std::size_t i = 0; i < 4; ++i) values[i] = take_scalar<float>(cursor);
      values[4] = take_scalar<std::uint32_t>(cursor);
      values[5] = take_scalar<float>(cursor);
      values[6] = take_scalar<std::uint8_t>(cursor);
      values[7] = take_scalar<std::uint8_t>(cursor);
      for (std::size_t i = 8; i < 14; ++i) values[i] = take_scalar<float>(cursor);
      values[14] = take_scalar<std::uint8_t>(cursor);
      for (std::size_t i = 15; i < 18; ++i) values[i] = take_scalar<float>(cursor);
      values[18] = take_scalar<std::int32_t>(cursor);
      // V3 adds height-above-ground; V4 adds ground-plane direction.
      if (binary_version >= 3) values[19] = take_scalar<float>(cursor);
      if (binary_version >= 4) {
        values[20] = take_scalar<float>(cursor);
        values[21] = take_scalar<float>(cursor);
      }
      if (!quality) quality = resolve_quality(input_summary_);
      auto observation = observation_values(values, input_summary_, &*quality);
      observation.timestamp = input_summary_.timestamp_us.value_or(result_.input_frames);
      pending_.push_back(observation);
    }
    parse_duration_ += std::chrono::nanoseconds{duration_ns(parse_started)};
    const auto update_started = Clock::now();
    map_->prepare_frame(pending_);
    map_->integrate_prepared_frame(pending_, result_.rejected_out_of_window,
                                   [&](const veyra::map::Observation& observation) {
                                     ++result_.input_points;
                                     if (pose_valid_) scan_image_.insert(observation, sensor_pose_);
                                   });
    points_ += pending_.size();
    update_duration_ += std::chrono::nanoseconds{duration_ns(update_started)};
    pending_integrated_ = true;
    std::istringstream end;
    end_frame(end);
  }

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
      result_.dropped_frames = result_.dropped_frames.value_or(0) + *input_summary_.source_index -
                               *previous_source_index_ - 1;
    }
    if (input_summary_.source_index.has_value())
      previous_source_index_ = input_summary_.source_index;
    result_.late_frames += late ? 1 : 0;
    expected_points_ = uint_value(count, "frame point count");
    if (options_.policy == "utility_lod" && expected_points_ > 2'000'000)
      throw std::invalid_argument("utility frame exceeds point limit");
    pending_.clear();
    pending_integrated_ = false;
    points_ = 0;
    parse_duration_ = std::chrono::nanoseconds{duration_ns(started)};
    const auto window_started = Clock::now();
    map_->set_window_center(pose[3], pose[7]);
    map_point_count_before_update_ = map_->point_count();
    frame_rejected_before_ = result_.rejected_out_of_window;
    // Rebuilt, not reallocated: the raster is the same shape every frame, so
    // clearing it keeps this off the allocator on the hot path (mirrors run()).
    scan_image_.clear();
    sensor_pose_ = {pose[3], pose[7], pose[11] + options_.sensor_height_m};
    pose_valid_ = std::isfinite(sensor_pose_.x) && std::isfinite(sensor_pose_.y) &&
                  std::isfinite(sensor_pose_.z);
    window_duration_ = std::chrono::nanoseconds{duration_ns(window_started)};
    update_duration_ = std::chrono::nanoseconds{0};
    open_ = true;
  }

  void add_point(std::istringstream& input) {
    const auto parse_started = Clock::now();
    if (!open_) throw std::invalid_argument("engine point outside frame");
    auto observation = parse_observation_record(input, protocol_version_, input_summary_);
    observation.timestamp = input_summary_.timestamp_us.value_or(result_.input_frames);
    parse_duration_ += std::chrono::nanoseconds{duration_ns(parse_started)};
    if (options_.policy == "utility_lod") {
      if (points_ >= expected_points_) throw std::invalid_argument("frame point count exceeded");
      pending_.push_back(observation);
      ++points_;
      return;
    }
    const auto update_started = Clock::now();
    const bool accepted = ingest_observation(*map_, observation, result_.rejected_out_of_window);
    if (accepted) {
      ++result_.input_points;
      // Every accepted return is one beam's endpoint, so the raster is built
      // from the same points the map ingests. Rejected points are excluded on
      // purpose: a return outside the window cannot license clearing inside it.
      if (pose_valid_) scan_image_.insert(observation, sensor_pose_);
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
    if (options_.policy == "utility_lod" && !pending_integrated_) {
      const auto update_started = Clock::now();
      map_->prepare_frame(pending_);
      map_->integrate_prepared_frame(
          pending_, result_.rejected_out_of_window,
          [&](const veyra::map::Observation& observation) {
            ++result_.input_points;
            if (pose_valid_) scan_image_.insert(observation, sensor_pose_);
          });
      update_duration_ += std::chrono::nanoseconds{duration_ns(update_started)};
      pending_integrated_ = true;
    }
    // Visibility clearing runs after the frame is integrated and before the
    // snapshot, so the published map reflects both what this scan added and
    // what it contradicted (mirrors run()). Opt-in via --clear-free-space,
    // default off. Missing/invalid pose or an empty raster skips honestly:
    // no evidence is not evidence of absence, so nothing is cleared.
    if (options_.clearing_enabled && pose_valid_ && scan_image_.filled_bins() > 0) {
      const auto clearing_started = Clock::now();
      result_.clearing = map_->clear_free_space(scan_image_, sensor_pose_);
      update_duration_ += std::chrono::nanoseconds{duration_ns(clearing_started)};
    } else {
      result_.clearing.reset();
    }
    const auto snapshot_started = Clock::now();
    // The live session snapshots every frame into the snapshot it already
    // owns, so steady-state frames refill existing leaf storage rather than
    // allocating (and leaving behind) a new array the size of the map.
    auto& snapshot = result_.snapshot;
    map_->snapshot_into(snapshot);
    if (map_->apply_governor(
        snapshot,
        static_cast<double>((parse_duration_ + window_duration_ + update_duration_).count()) /
            1'000'000.0))
      map_->snapshot_into(snapshot);
    result_.governor = map_->governor_status();
    result_.promotion_telemetry = map_->promotion_telemetry();
    const auto governor_interventions =
        result_.governor ? result_.governor->interventions - previous_governor_interventions_ : 0;
    const auto governor_actions =
        result_.governor ? result_.governor->actions_applied - previous_governor_actions_ : 0;
    if (result_.governor) {
      previous_governor_interventions_ = result_.governor->interventions;
      previous_governor_actions_ = result_.governor->actions_applied;
    }
    const auto snapshot_duration = std::chrono::nanoseconds{duration_ns(snapshot_started)};
    const auto topology_churn = snapshot.topology_change_count - previous_topology_changes_;
    const auto splits = snapshot.split_count - previous_splits_;
    const auto merges = snapshot.merge_count - previous_merges_;
    previous_topology_changes_ = snapshot.topology_change_count;
    previous_splits_ = snapshot.split_count;
    previous_merges_ = snapshot.merge_count;
    const auto rss = veyra::metrics::read_process_rss_bytes();
    const auto frame_rejected = result_.rejected_out_of_window - frame_rejected_before_;
    const auto accepted_points = points_ - frame_rejected;
    const bool point_conservation =
        snapshot.point_count == map_point_count_before_update_ + accepted_points;
    metrics_->observe_rss_bytes(rss);
    result_.last_input = input_summary_;
    const bool is_warmup = result_.input_frames < options_.warmup_frames;
    ++result_.input_frames;
    if (is_warmup) {
      ++result_.warmup_frames;
    } else {
      const auto frame_pipeline =
          parse_duration_ + window_duration_ + update_duration_ + snapshot_duration;
      measured_elapsed_ += frame_pipeline;
      metrics_->record_duration("protocol_parse_and_validate", parse_duration_);
      metrics_->record_duration("map_window_follow", window_duration_);
      metrics_->record_duration("map_update", update_duration_);
      metrics_->record_duration("snapshot_and_topology", snapshot_duration);
      metrics_->record_duration("frame_pipeline", frame_pipeline);
      metrics_->record_value("topology_churn", static_cast<std::int64_t>(topology_churn));
      metrics_->record_value("splits", static_cast<std::int64_t>(splits));
      metrics_->record_value("merges", static_cast<std::int64_t>(merges));
      metrics_->record_value("governor_interventions",
                             static_cast<std::int64_t>(governor_interventions));
      metrics_->record_value("governor_actions_applied",
                             static_cast<std::int64_t>(governor_actions));
      for (int level = 0; level < 4; ++level) {
        metrics_->record_value("cells_level_" + std::to_string(level),
                               static_cast<std::int64_t>(snapshot.count_at_level(level)));
      }
      metrics_->record_frame();
      if (!options_.binary_input) {
        result_.frame_metrics
            .clear();  // Live reports expose only the latest frame; percentiles roll over 600.
      }
      result_.frame_metrics.push_back(
          FrameMetric{.input = std::move(input_summary_),
                      .stages_ns = {{"protocol_parse_and_validate", parse_duration_.count()},
                                    {"map_window_follow", window_duration_.count()},
                                    {"map_update", update_duration_.count()},
                                    {"snapshot_and_topology", snapshot_duration.count()},
                                    {"frame_pipeline", frame_pipeline.count()}},
                      .accepted_points = accepted_points,
                      .map_point_count_before_update = map_point_count_before_update_,
                      .point_conservation = point_conservation,
                      .topology_churn = topology_churn,
                      .splits = splits,
                      .merges = merges,
                      .governor_interventions = governor_interventions,
                      .governor_actions_applied = governor_actions,
                      .cells_by_level = {snapshot.count_at_level(0), snapshot.count_at_level(1),
                                         snapshot.count_at_level(2), snapshot.count_at_level(3)},
                      .rss_bytes = rss});
    }
    metrics_->set_logical_map_bytes(snapshot.logical_bytes);
    metrics_->set_allocated_map_bytes(snapshot.memory.allocated_bytes);
    if (!result_.source_indices_complete)
      result_.dropped_frames = std::nullopt;
    else if (!result_.dropped_frames.has_value())
      result_.dropped_frames = 0;
    result_.metrics = metrics_->report(Clock::time_point{} + measured_elapsed_);
    open_ = false;
  }

  Options options_;
  veyra::policy::UtilityConfig display_utility_;
  std::unique_ptr<MapPolicyAdapter> map_;
  std::unique_ptr<veyra::metrics::MetricsCollector> metrics_;
  Result result_;
  bool open_ = false;
  // Protocol version negotiated at the VEYRA_ENGINE handshake. V2 records
  // carry no height above ground, so their points reach the map with the NaN
  // sentinel and are counted as lacking a ground model rather than assumed to
  // be at ground level.
  int protocol_version_ = 2;
  std::uint64_t expected_points_ = 0;
  std::uint64_t points_ = 0;
  std::optional<std::uint64_t> previous_timestamp_;
  std::optional<std::uint64_t> previous_source_index_;
  std::uint64_t previous_topology_changes_ = 0;
  std::uint64_t previous_splits_ = 0;
  std::uint64_t previous_merges_ = 0;
  std::uint64_t previous_governor_interventions_ = 0;
  std::uint64_t previous_governor_actions_ = 0;
  std::uint64_t frame_rejected_before_ = 0;
  std::uint64_t map_point_count_before_update_ = 0;
  std::chrono::nanoseconds measured_elapsed_{0};
  std::chrono::nanoseconds parse_duration_{0};
  std::chrono::nanoseconds window_duration_{0};
  std::chrono::nanoseconds update_duration_{0};
  InputSummary input_summary_;
  // Decoded rows of the current binary frame; reused so frames do not allocate.
  std::vector<veyra::map::Observation> pending_;
  // One-scan depth raster for visibility clearing (mirrors run()'s scan_image:
  // 1440 x 64 over [-25, +15] degrees, close to a 64-beam spinning unit).
  // Bins coarser than the sensor's angular resolution would merge distinct
  // beams; finer would leave gaps that read as "nothing measured" and suppress
  // clearing.
  veyra::map::DepthImage scan_image_{1440, 64, -25.0 * std::numbers::pi / 180.0,
                                     15.0 * std::numbers::pi / 180.0};
  veyra::map::SensorPose sensor_pose_{};
  // False until a frame supplies a finite sensor pose; clearing never runs on
  // a fabricated pose.
  bool pose_valid_ = false;
  bool pending_integrated_ = false;
};

// Batch counterpart to run() for compact binary streams. It uses the same
// persistent session as the supervised engine, but retains every measured
// frame metric so the JSON report has the same benchmark contract as text V2.
int run_binary(const Options& options) {
  PersistentEngineSession session(options);
  bool header = false;
  bool metadata = false;
  bool trailer = false;
  int binary_version = 2;
  std::string digest;
  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.empty()) continue;
    std::istringstream input(line);
    std::string kind;
    input >> kind;
    if (kind == "VEYRA_STREAM") {
      std::string version;
      input >> version;
      require_end(input, "stream header");
      if (header || (version != "2" && version != "3" && version != "4"))
        throw std::invalid_argument("binary stream requires V2, V3, or V4");
      binary_version = version == "4" ? 4 : (version == "3" ? 3 : 2);
      header = true;
    } else if (kind == "H") {
      if (!header || metadata || trailer || !(input >> digest) || digest.empty()) {
        throw std::invalid_argument("invalid stream metadata");
      }
      require_end(input, "stream metadata");
      session.set_digest(digest);
      metadata = true;
    } else if (kind == "B") {
      if (!header || !metadata || trailer) throw std::invalid_argument("invalid binary frame");
      std::string count;
      if (!(input >> count)) throw std::invalid_argument("malformed binary frame marker");
      require_end(input, "binary frame marker");
      session.ingest_binary(std::cin, uint_value(count, "binary point count"), binary_version);
    } else if (kind == "D") {
      std::string trailer_digest;
      input >> trailer_digest;
      require_end(input, "stream trailer");
      if (!header || !metadata || trailer || trailer_digest != digest) {
        throw std::invalid_argument("invalid stream trailer");
      }
      trailer = true;
    } else {
      throw std::invalid_argument(
          "binary stream accepts only header, metadata, frames, and trailer");
    }
  }
  if (!header || !metadata || !trailer || session.frame_count() == 0 ||
      session.result().frame_metrics.empty()) {
    throw std::invalid_argument("incomplete, empty, or fully warmed-up binary stream");
  }
  std::cout << render(session.result());
  return 0;
}

// Decimated leaf dump for map-layer rendering. Coordinates and the common
// compact fields retain the original viewer contract; the descriptive
// evidence fields make the Python/desktop boundary lossless for the state
// that CellStats actually stores. cell_count reports what is actually
// returned so the caller can distinguish a decimated view from the map.
//
// Over budget, send the leaves nearest the vehicle rather than every n-th
// leaf: a uniform stride thinned the whole map into a sparse checkerboard,
// while the near field is what the display is for. Snapshot order is kept.
std::vector<std::size_t> select_display_cells(const veyra::map::MapSnapshot& snapshot,
                                              std::size_t budget, std::array<double, 2> center) {
  const std::size_t total = snapshot.leaves.size();
  std::vector<std::size_t> selected(total);
  for (std::size_t index = 0; index < total; ++index) selected[index] = index;
  if (total > budget) {
    // Per-frame scratch sized by the whole map; reused so a growing map does
    // not leave a slightly larger freed block behind on every frame.
    thread_local std::vector<double> distance;
    distance.resize(total);
    for (std::size_t index = 0; index < total; ++index) {
      const auto& id = snapshot.leaves[index].id;
      const double size = 0.05 * std::ldexp(1.0, id.level);
      const double dx = (static_cast<double>(id.ix) + 0.5) * size - center[0];
      const double dy = (static_cast<double>(id.iy) + 0.5) * size - center[1];
      distance[index] = dx * dx + dy * dy;
    }
    std::nth_element(selected.begin(), selected.begin() + static_cast<std::ptrdiff_t>(budget),
                     selected.end(), [&](std::size_t left, std::size_t right) {
                       return distance[left] < distance[right] ||
                              (distance[left] == distance[right] && left < right);
                     });
    selected.resize(budget);
    std::sort(selected.begin(), selected.end());
  }
  return selected;
}

double display_cell_utility(const veyra::map::Leaf& leaf,
                            const veyra::policy::UtilityConfig& config) {
  const double risk = leaf.stats.drivable_evidence() < 0.0F
                          ? static_cast<double>(leaf.stats.terrain_confidence())
                          : 0.0;
  const double semantic =
      veyra::policy::semantic_importance(config, leaf.stats.semantic_class,
                                         leaf.stats.semantic_confidence());
  const bool quality_gate = leaf.stats.observation_quality() >= config.min_observation_quality;
  return quality_gate
             ? std::clamp(
                   static_cast<double>(leaf.stats.geometry_complexity()) * config.geometry_weight +
                       semantic * config.semantic_weight +
                       static_cast<double>(leaf.stats.motion_evidence()) * config.motion_weight +
                       risk * config.traversability_risk_weight +
                       (1.0 - static_cast<double>(leaf.stats.semantic_confidence())) *
                           config.uncertainty_weight,
                   0.0, 1.0)
             : 0.0;
}

// Binary display cells: one header line, then `cell_count` rows of seventeen
// little-endian float32 in the visualization schema-v3 cell layout -- centre
// x, centre y, mean z, edge, class, motion, quality, drivable evidence,
// utility, semantic confidence, ground evidence, terrain confidence, geometry
// complexity, point count, min z, max z, z variance -- which is exactly the
// cell section of the desktop frame, so the runtime forwards it unparsed.
// Formatting ~50k cells as JSON and parsing them back cost more than the
// whole map update did.
void write_cells_binary(std::ostream& out, const veyra::map::MapSnapshot& snapshot,
                        std::size_t budget, const veyra::policy::UtilityConfig& config,
                        std::array<double, 2> center, bool with_layers = false) {
  const auto selected = select_display_cells(snapshot, budget, center);
  constexpr std::size_t kFloats = 17;
  constexpr std::size_t kLayerFloats = 15;
  const auto cell_bytes = selected.size() * kFloats * sizeof(float);
  const auto layer_bytes = with_layers ? selected.size() * kLayerFloats * sizeof(float) : 0;
  std::vector<unsigned char> rows(cell_bytes + layer_bytes);
  unsigned char* cursor = rows.data();
  const auto put = [&cursor](double value) {
    const auto narrow = static_cast<float>(value);
    std::array<unsigned char, sizeof(float)> bytes{};
    std::memcpy(bytes.data(), &narrow, sizeof(float));
    if constexpr (std::endian::native == std::endian::big) std::reverse(bytes.begin(), bytes.end());
    std::memcpy(cursor, bytes.data(), bytes.size());
    cursor += bytes.size();
  };
  for (const std::size_t index : selected) {
    const auto& leaf = snapshot.leaves[index];
    const double size = 0.05 * std::ldexp(1.0, leaf.id.level);
    put((static_cast<double>(leaf.id.ix) + 0.5) * size);
    put((static_cast<double>(leaf.id.iy) + 0.5) * size);
    put(leaf.stats.mean_z());
    put(size);
    put(leaf.stats.semantic_class);
    put(leaf.stats.motion_evidence());
    put(leaf.stats.observation_quality());
    put(leaf.stats.drivable_evidence());
    put(display_cell_utility(leaf, config));
    put(leaf.stats.semantic_confidence());
    put(leaf.stats.ground_evidence());
    put(leaf.stats.terrain_confidence());
    put(leaf.stats.geometry_complexity());
    put(static_cast<double>(leaf.stats.count));
    put(leaf.stats.min_z());
    put(leaf.stats.max_z());
    put(leaf.stats.variance_z());
  }
  if (with_layers) {
    for (const auto index : selected) {
      const auto& stats = snapshot.leaves[index].stats;
      for (const auto* layer : {&stats.ground, &stats.obstacle, &stats.overhead}) {
        const auto absent = std::numeric_limits<double>::quiet_NaN();
        put(layer->count);
        put(layer->empty() ? absent : layer->mean_z);
        put(layer->empty() ? absent : layer->min_z);
        put(layer->empty() ? absent : layer->max_z);
        put(layer->empty() ? absent : layer->variance_z());
      }
    }
  }
  out << "{\"status\":\"available\",\"cell_count\":" << selected.size()
      << ",\"total_leaves\":" << snapshot.leaves.size() << ",\"binary_bytes\":" << rows.size()
      << (with_layers ? ",\"physical_layers_version\":1" : "") << "}\n";
  out.write(reinterpret_cast<const char*>(rows.data()), static_cast<std::streamsize>(rows.size()));
}

std::string render_cells(const veyra::map::MapSnapshot& snapshot, std::size_t budget,
                         const veyra::policy::UtilityConfig& config,
                         std::array<double, 2> center = {}) {
  const std::size_t total = snapshot.leaves.size();
  const auto selected = select_display_cells(snapshot, budget, center);
  const std::size_t shown = selected.size();
  // Formatted with std::to_chars: identical "%.6f" text, without the
  // locale-aware ostream path that dominated this response at 50k cells.
  std::string out;
  out.reserve(64 + shown * 300);
  char scratch[64];
  const auto integer = [&](std::int64_t value) {
    const auto end = std::to_chars(scratch, scratch + sizeof(scratch), value).ptr;
    out.append(scratch, end);
  };
  const auto real = [&](double value) {
    if (!std::isfinite(value)) {
      // Match ostream's fixed formatting of non-finite values.
      out += std::isnan(value) ? "nan" : (value < 0 ? "-inf" : "inf");
      return;
    }
    const auto end =
        std::to_chars(scratch, scratch + sizeof(scratch), value, std::chars_format::fixed, 6).ptr;
    out.append(scratch, end);
  };
  out += "{\"status\":\"available\",\"cell_count\":";
  integer(static_cast<std::int64_t>(shown));
  out += ",\"total_leaves\":";
  integer(static_cast<std::int64_t>(total));
  out += ",\"cells\":[";
  bool first = true;
  for (const std::size_t index : selected) {
    const auto& leaf = snapshot.leaves[index];
    const double utility = display_cell_utility(leaf, config);
    if (!std::exchange(first, false)) out += ',';
    out += "{\"l\":";
    integer(leaf.id.level);
    out += ",\"ix\":";
    integer(leaf.id.ix);
    out += ",\"iy\":";
    integer(leaf.id.iy);
    out += ",\"z\":";
    real(leaf.stats.mean_z());
    out += ",\"zmin\":";
    real(leaf.stats.min_z());
    out += ",\"zmax\":";
    real(leaf.stats.max_z());
    out += ",\"zvar\":";
    real(leaf.stats.variance_z());
    out += ",\"n\":";
    integer(static_cast<std::int64_t>(leaf.stats.count));
    out += ",\"c\":";
    integer(leaf.stats.semantic_class);
    out += ",\"semantic_confidence\":";
    real(leaf.stats.semantic_confidence());
    out += ",\"ground_evidence\":";
    real(leaf.stats.ground_evidence());
    out += ",\"terrain_confidence\":";
    real(leaf.stats.terrain_confidence());
    out += ",\"geometry_complexity\":";
    real(leaf.stats.geometry_complexity());
    out += ",\"m\":";
    real(leaf.stats.motion_evidence());
    out += ",\"q\":";
    real(leaf.stats.observation_quality());
    out += ",\"drivable_evidence\":";
    real(leaf.stats.drivable_evidence());
    out += ",\"u\":";
    real(utility);
    out += ",\"physical_layers\":[";
    bool first_layer = true;
    for (const auto* layer : {&leaf.stats.ground, &leaf.stats.obstacle, &leaf.stats.overhead}) {
      if (!std::exchange(first_layer, false)) out += ',';
      integer(layer->count);
      for (const auto value : {layer->mean_z, static_cast<double>(layer->min_z),
                               static_cast<double>(layer->max_z), layer->variance_z()}) {
        out += ',';
        if (layer->empty()) out += "null";
        else real(value);
      }
    }
    out += ']';
    out += '}';
  }
  out += "]}";
  return out;
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
  int session_version = 2;
  bool draining = false;
  std::string line;
  while (std::getline(std::cin, line)) {
    try {
      if (line == "VEYRA_ENGINE 2" || line == "VEYRA_ENGINE 3" || line == "VEYRA_ENGINE 4") {
        if (started) throw std::invalid_argument("duplicate engine header");
        started = true;
        session_version = line.back() == '4' ? 4 : (line.back() == '3' ? 3 : 2);
        session.set_protocol_version(session_version);
        std::cout << "{\"status\":\"ready\",\"physical_layers_version\":1,\"protocol_version\":" << session_version << "}\n"
                  << std::flush;
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
      if (line.rfind("G ", 0) == 0) {
        const auto value = line.substr(2);
        if (value == "automatic")
          session.set_governor_override(veyra::policy::GovernorOverride::Automatic);
        else if (value == "disabled")
          session.set_governor_override(veyra::policy::GovernorOverride::Disabled);
        else if (value == "conserve")
          session.set_governor_override(veyra::policy::GovernorOverride::Conserve);
        else
          throw std::invalid_argument("governor override must be automatic, disabled, or conserve");
        std::string report = render(session.result());
        report.insert(1, "\"status\":\"available\",");
        std::cout << report << std::flush;
        continue;
      }
      if (line.rfind("B ", 0) == 0) {
        std::istringstream args(line.substr(2));
        std::string count;
        args >> count;
        require_end(args, "binary frame");
        try {
          session.ingest_binary(std::cin, uint_value(count, "binary point count"), session_version);
        } catch (const std::exception& error) {
          // A failed binary frame cannot be resynchronized by scanning text.
          std::cout << "{\"status\":\"unavailable\",\"reason\":\"" << escape(error.what())
                    << "\"}\n"
                    << std::flush;
          return 2;
        }
        std::string report = render(session.result());
        report.insert(1, "\"status\":\"available\",");
        std::cout << report << std::flush;
        continue;
      }
      if (line.rfind("MB ", 0) == 0 || line.rfind("ML ", 0) == 0) {
        std::istringstream args(line.substr(3));
        std::uint64_t budget = 0;
        if (!(args >> budget) || budget == 0 || budget > 100000)
          throw std::invalid_argument("invalid map cell budget");
        require_end(args, "binary map cells request");
        const auto& input = session.result().last_input;
        const std::array<double, 2> center =
            input ? std::array<double, 2>{input->pose_translation[0], input->pose_translation[1]}
                  : std::array<double, 2>{};
        write_cells_binary(std::cout, session.result().snapshot, static_cast<std::size_t>(budget),
                           session.display_utility(), center, line.rfind("ML ", 0) == 0);
        std::cout << std::flush;
        continue;
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
        // Sensor-frame input has no pose; its vehicle sits at the origin.
        const auto& input = session.result().last_input;
        const std::array<double, 2> center =
            input ? std::array<double, 2>{input->pose_translation[0], input->pose_translation[1]}
                  : std::array<double, 2>{};
        std::cout << render_cells(session.result().snapshot, budget, session.display_utility(),
                                  center)
                  << '\n'
                  << std::flush;
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
      std::cout << "{\"status\":\"unavailable\",\"reason\":\"" << escape(error.what()) << "\"}\n"
                << std::flush;
      session.reset();
      draining = true;
    }
  }
  return 0;
}

}  // namespace

int veyra::runtime::engine_main(int argc, char** argv) {
  std::ios::sync_with_stdio(false);
  static FdInputBuffer stdin_buffer(0);
  std::cin.rdbuf(&stdin_buffer);
  std::cin.tie(nullptr);
  try {
    const auto options = parse_options(argc, argv);
    if (options.binary_input) return run_binary(options);
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
  } catch (const std::exception& error) {
    std::cerr << "veyra engine: " << error.what() << '\n';
    return 2;
  }
}
