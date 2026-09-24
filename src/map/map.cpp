#include "veyra/map/map.hpp"

#include "veyra/map/terrain_query.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

namespace veyra::map {
namespace {

constexpr int kMaxLevel = 3;

struct TileKey {
  std::int32_t ix = 0;
  std::int32_t iy = 0;

  constexpr bool operator==(const TileKey&) const = default;
};

[[nodiscard]] std::size_t mix(std::uint64_t value) noexcept {
  value += 0x9e3779b97f4a7c15ULL;
  value = (value ^ (value >> 30U)) * 0xbf58476d1ce4e5b9ULL;
  value = (value ^ (value >> 27U)) * 0x94d049bb133111ebULL;
  return static_cast<std::size_t>(value ^ (value >> 31U));
}

[[nodiscard]] std::size_t hash_tile(TileKey key) noexcept {
  const auto x = static_cast<std::uint32_t>(key.ix);
  const auto y = static_cast<std::uint32_t>(key.iy);
  return mix((static_cast<std::uint64_t>(x) << 32U) | y);
}

struct StoredCell {
  core::CellId id;
  CellStats stats;
};

[[nodiscard]] bool less_id(const core::CellId& left, const core::CellId& right) noexcept {
  if (left.level != right.level) return left.level < right.level;
  if (left.ix != right.ix) return left.ix < right.ix;
  return left.iy < right.iy;
}

[[nodiscard]] bool less_entry(const StoredCell& left, const core::CellId& right) noexcept {
  return less_id(left.id, right);
}

using CellArray = std::vector<StoredCell>;

[[nodiscard]] CellArray::iterator find_entry(CellArray& cells, core::CellId id) {
  return std::lower_bound(cells.begin(), cells.end(), id, less_entry);
}

[[nodiscard]] CellArray::const_iterator find_entry(const CellArray& cells, core::CellId id) {
  return std::lower_bound(cells.begin(), cells.end(), id, less_entry);
}

struct Tile {
  std::array<CellArray, kMaxLevel + 1> leaves;
  // A prior carries a parent aggregate whose exact child allocation is
  // unknowable after a refinement. It is not an active leaf.
  std::array<CellArray, kMaxLevel + 1> priors;

  [[nodiscard]] bool empty() const {
    for (int level = 0; level <= kMaxLevel; ++level) {
      if (!leaves[level].empty() || !priors[level].empty()) return false;
    }
    return true;
  }
};

enum class SlotState : std::uint8_t { Empty, Occupied, Tombstone };

struct TileSlot {
  TileKey key;
  Tile tile;
  SlotState state = SlotState::Empty;
};

// A deterministic open-addressed sparse tile table. It has no allocation per
// cell and its primary storage can be accounted for exactly by capacity.
class SparseTileStore {
 public:
  SparseTileStore() : slots_(kInitialSlotCount) {}

  [[nodiscard]] Tile* find(TileKey key) {
    const auto index = find_slot(key);
    return index.has_value() ? &slots_[*index].tile : nullptr;
  }

  [[nodiscard]] const Tile* find(TileKey key) const {
    const auto index = find_slot(key);
    return index.has_value() ? &slots_[*index].tile : nullptr;
  }

  Tile& find_or_create(TileKey key) {
    ensure_insert_capacity();
    const std::size_t mask = slots_.size() - 1U;
    std::size_t position = hash_tile(key) & mask;
    std::optional<std::size_t> first_tombstone;
    for (;;) {
      TileSlot& slot = slots_[position];
      if (slot.state == SlotState::Empty) {
        const std::size_t destination = first_tombstone.value_or(position);
        TileSlot& created = slots_[destination];
        if (created.state == SlotState::Tombstone) --tombstones_;
        created.key = key;
        created.tile = Tile{};
        created.state = SlotState::Occupied;
        ++size_;
        return created.tile;
      }
      if (slot.state == SlotState::Tombstone) {
        if (!first_tombstone.has_value()) first_tombstone = position;
      } else if (slot.key == key) {
        return slot.tile;
      }
      position = (position + 1U) & mask;
    }
  }

  void erase_if_empty(TileKey key) {
    const auto index = find_slot(key);
    if (!index.has_value()) return;
    TileSlot& slot = slots_[*index];
    if (!slot.tile.empty()) return;
    slot.tile = Tile{};
    slot.state = SlotState::Tombstone;
    --size_;
    ++tombstones_;
  }

  template <typename Function>
  void for_each_tile(Function&& function) {
    for (TileSlot& slot : slots_) {
      if (slot.state == SlotState::Occupied) function(slot.key, slot.tile);
    }
  }

  template <typename Function>
  void for_each_tile(Function&& function) const {
    for (const TileSlot& slot : slots_) {
      if (slot.state == SlotState::Occupied) function(slot.key, slot.tile);
    }
  }

  [[nodiscard]] std::size_t size() const noexcept { return size_; }
  [[nodiscard]] std::size_t allocated_index_bytes() const noexcept {
    return slots_.capacity() * sizeof(TileSlot);
  }

 private:
  static constexpr std::size_t kInitialSlotCount = 16;

  [[nodiscard]] std::optional<std::size_t> find_slot(TileKey key) const {
    if (slots_.empty()) return std::nullopt;
    const std::size_t mask = slots_.size() - 1U;
    std::size_t position = hash_tile(key) & mask;
    for (std::size_t probes = 0; probes < slots_.size(); ++probes) {
      const TileSlot& slot = slots_[position];
      if (slot.state == SlotState::Empty) return std::nullopt;
      if (slot.state == SlotState::Occupied && slot.key == key) return position;
      position = (position + 1U) & mask;
    }
    return std::nullopt;
  }

  void ensure_insert_capacity() {
    const std::size_t projected = size_ + tombstones_ + 1U;
    if (projected * 10U < slots_.size() * 7U) return;
    const bool grow = (size_ + 1U) * 10U >= slots_.size() * 7U;
    rehash(grow ? slots_.size() * 2U : slots_.size());
  }

  void rehash(std::size_t capacity) {
    std::vector<TileSlot> old_slots = std::move(slots_);
    slots_ = std::vector<TileSlot>(capacity);
    size_ = 0;
    tombstones_ = 0;
    const std::size_t mask = slots_.size() - 1U;
    for (TileSlot& old : old_slots) {
      if (old.state != SlotState::Occupied) continue;
      std::size_t position = hash_tile(old.key) & mask;
      while (slots_[position].state == SlotState::Occupied) {
        position = (position + 1U) & mask;
      }
      slots_[position].key = old.key;
      slots_[position].tile = std::move(old.tile);
      slots_[position].state = SlotState::Occupied;
      ++size_;
    }
  }

  std::vector<TileSlot> slots_;
  std::size_t size_ = 0;
  std::size_t tombstones_ = 0;
};

[[nodiscard]] std::int32_t checked_floor_to_i32(double value, const char* message) {
  if (!std::isfinite(value) ||
      value < static_cast<double>(std::numeric_limits<std::int32_t>::min()) ||
      value > static_cast<double>(std::numeric_limits<std::int32_t>::max())) {
    throw std::out_of_range(message);
  }
  return static_cast<std::int32_t>(std::floor(value));
}

[[nodiscard]] core::CellId index(double x, double y, int level) {
  core::validate_level(level);
  const double resolution = core::resolution_m(level);
  return {level, checked_floor_to_i32(x / resolution, "x coordinate exceeds map lattice"),
          checked_floor_to_i32(y / resolution, "y coordinate exceeds map lattice")};
}

[[nodiscard]] core::CellId ancestor_at(core::CellId id, int level) {
  core::validate_level(id.level);
  core::validate_level(level);
  if (level < id.level) throw std::invalid_argument("ancestor level is finer");
  while (id.level < level) id = id.parent();
  return id;
}

[[nodiscard]] core::CellId child_at(core::CellId parent, int dx, int dy) {
  core::validate_level(parent.level);
  if (parent.level == 0 || dx < 0 || dx > 1 || dy < 0 || dy > 1) {
    throw std::invalid_argument("invalid dyadic child");
  }
  const auto child_x = static_cast<std::int64_t>(parent.ix) * 2 + dx;
  const auto child_y = static_cast<std::int64_t>(parent.iy) * 2 + dy;
  if (child_x < std::numeric_limits<std::int32_t>::min() ||
      child_x > std::numeric_limits<std::int32_t>::max() ||
      child_y < std::numeric_limits<std::int32_t>::min() ||
      child_y > std::numeric_limits<std::int32_t>::max()) {
    throw std::out_of_range("dyadic child exceeds map lattice");
  }
  return {parent.level - 1, static_cast<std::int32_t>(child_x), static_cast<std::int32_t>(child_y)};
}

}  // namespace

struct Map::Impl {
  explicit Impl(ResolutionPolicy initial_policy, MapConfig initial_config)
      : policy(initial_policy), config(initial_config) {
    if (!(config.window_radius_m > 0.0) || !std::isfinite(config.window_radius_m)) {
      throw std::invalid_argument("window radius must be finite and positive");
    }
    if (!(config.clearance_envelope_m > 0.0) || !std::isfinite(config.clearance_envelope_m)) {
      throw std::invalid_argument("clearance envelope must be finite and positive");
    }
    if (!(config.tile_size_m > 0.0) || !std::isfinite(config.tile_size_m)) {
      throw std::invalid_argument("tile size must be finite and positive");
    }
    if (policy == ResolutionPolicy::DistanceLod) {
      const auto& boundaries = config.distance_boundaries_m;
      if (!std::isfinite(boundaries[0]) || !std::isfinite(boundaries[1]) ||
          !std::isfinite(boundaries[2]) || !(boundaries[0] > 0.0) ||
          !(boundaries[0] < boundaries[1]) || !(boundaries[1] < boundaries[2]) ||
          !(boundaries[2] < config.window_radius_m)) {
        throw std::invalid_argument("distance boundaries must be ordered within the window");
      }
    }
  }

  [[nodiscard]] TileKey tile_key_for(core::CellId id) const {
    const double resolution = core::resolution_m(id.level);
    return {checked_floor_to_i32(static_cast<double>(id.ix) * resolution / config.tile_size_m,
                                 "x tile index exceeds map lattice"),
            checked_floor_to_i32(static_cast<double>(id.iy) * resolution / config.tile_size_m,
                                 "y tile index exceeds map lattice")};
  }

  [[nodiscard]] bool accepts(double x, double y) const {
    if (!std::isfinite(x) || !std::isfinite(y)) return false;
    const double dx = x - center_x;
    const double dy = y - center_y;
    return dx * dx + dy * dy <= config.window_radius_m * config.window_radius_m;
  }

  void validate_observation(const Observation& observation) const {
    if (!std::isfinite(observation.x) || !std::isfinite(observation.y) ||
        !std::isfinite(observation.z)) {
      throw std::invalid_argument("observation coordinates must be finite");
    }
    if (!accepts(observation.x, observation.y)) {
      throw std::out_of_range("observation is outside active window");
    }
  }

  [[nodiscard]] int level_for(double x, double y) const {
    if (!std::isfinite(x) || !std::isfinite(y)) {
      throw std::invalid_argument("coordinates must be finite");
    }
    switch (policy) {
      case ResolutionPolicy::Uniform5:
        return 0;
      case ResolutionPolicy::Uniform40:
        return 3;
      case ResolutionPolicy::DistanceLod: {
        const double distance = std::hypot(x - center_x, y - center_y);
        const auto& boundaries = config.distance_boundaries_m;
        if (distance < boundaries[0]) return 0;
        if (distance < boundaries[1]) return 1;
        if (distance < boundaries[2]) return 2;
        if (distance <= config.window_radius_m) return 3;
        return -1;
      }
    }
    throw std::logic_error("unknown map policy");
  }

  [[nodiscard]] std::optional<CellStats> leaf(core::CellId id) const {
    const Tile* tile = tiles.find(tile_key_for(id));
    if (tile == nullptr) return std::nullopt;
    const CellArray& entries = tile->leaves[id.level];
    const auto entry = find_entry(entries, id);
    if (entry == entries.end() || entry->id != id) return std::nullopt;
    return entry->stats;
  }

  void merge_leaf(core::CellId id, const CellStats& stats) {
    Tile& tile = tiles.find_or_create(tile_key_for(id));
    CellArray& entries = tile.leaves[id.level];
    const auto entry = find_entry(entries, id);
    if (entry != entries.end() && entry->id == id) {
      entry->stats.merge(stats);
      return;
    }
    entries.insert(entry, {id, stats});
  }

  [[nodiscard]] std::optional<CellStats> take_leaf(core::CellId id) {
    const TileKey key = tile_key_for(id);
    Tile* tile = tiles.find(key);
    if (tile == nullptr) return std::nullopt;
    CellArray& entries = tile->leaves[id.level];
    const auto entry = find_entry(entries, id);
    if (entry == entries.end() || entry->id != id) return std::nullopt;
    CellStats stats = entry->stats;
    entries.erase(entry);
    tiles.erase_if_empty(key);
    return stats;
  }

  void merge_prior(core::CellId id, const CellStats& stats) {
    if (stats.count == 0) return;
    Tile& tile = tiles.find_or_create(tile_key_for(id));
    CellArray& entries = tile.priors[id.level];
    const auto entry = find_entry(entries, id);
    if (entry != entries.end() && entry->id == id) {
      entry->stats.merge(stats);
      return;
    }
    entries.insert(entry, {id, stats});
  }

  [[nodiscard]] std::optional<CellStats> take_prior(core::CellId id) {
    const TileKey key = tile_key_for(id);
    Tile* tile = tiles.find(key);
    if (tile == nullptr) return std::nullopt;
    CellArray& entries = tile->priors[id.level];
    const auto entry = find_entry(entries, id);
    if (entry == entries.end() || entry->id != id) return std::nullopt;
    CellStats stats = entry->stats;
    entries.erase(entry);
    tiles.erase_if_empty(key);
    return stats;
  }

  [[nodiscard]] bool split_leaf(core::CellId id) {
    if (id.level == 0) return false;
    const auto parent_stats = take_leaf(id);
    if (!parent_stats.has_value()) return false;

    // A parent aggregate says nothing about how its observations partition
    // across children. Retain it explicitly as a non-spatial prior.
    merge_prior(id, *parent_stats);
    for (int dy = 0; dy < 2; ++dy) {
      for (int dx = 0; dx < 2; ++dx) merge_leaf(child_at(id, dx, dy), {});
    }
    ++topology_changes;
    ++split_count;
    return true;
  }

  void refine_ancestors(core::CellId id) {
    for (int level = kMaxLevel; level > id.level; --level) {
      (void)split_leaf(ancestor_at(id, level));
    }
  }

  [[nodiscard]] bool coarsen_to(core::CellId target) {
    CellStats merged;
    bool found_active_descendant = false;

    if (const auto own_prior = take_prior(target); own_prior.has_value()) {
      merged.merge(*own_prior);
    }
    for (int level = 0; level < target.level; ++level) {
      const int span = 1 << (target.level - level);
      const auto base_x = static_cast<std::int64_t>(target.ix) * span;
      const auto base_y = static_cast<std::int64_t>(target.iy) * span;
      for (int dy = 0; dy < span; ++dy) {
        for (int dx = 0; dx < span; ++dx) {
          const auto x = base_x + dx;
          const auto y = base_y + dy;
          if (x < std::numeric_limits<std::int32_t>::min() ||
              x > std::numeric_limits<std::int32_t>::max() ||
              y < std::numeric_limits<std::int32_t>::min() ||
              y > std::numeric_limits<std::int32_t>::max()) {
            throw std::out_of_range("descendant exceeds map lattice");
          }
          const core::CellId child{level, static_cast<std::int32_t>(x),
                                   static_cast<std::int32_t>(y)};
          if (const auto stats = take_leaf(child); stats.has_value()) {
            merged.merge(*stats);
            found_active_descendant = true;
          }
          if (const auto prior = take_prior(child); prior.has_value()) {
            merged.merge(*prior);
          }
        }
      }
    }
    if (merged.count != 0) merge_leaf(target, merged);
    if (found_active_descendant) {
      ++topology_changes;
      ++merge_count;
    }
    return found_active_descendant;
  }

  [[nodiscard]] bool cell_intersects_window(core::CellId id) const {
    const double resolution = core::resolution_m(id.level);
    const double min_x = static_cast<double>(id.ix) * resolution;
    const double min_y = static_cast<double>(id.iy) * resolution;
    const double max_x = min_x + resolution;
    const double max_y = min_y + resolution;
    const double nearest_x = std::clamp(center_x, min_x, max_x);
    const double nearest_y = std::clamp(center_y, min_y, max_y);
    const double dx = center_x - nearest_x;
    const double dy = center_y - nearest_y;
    return dx * dx + dy * dy <= config.window_radius_m * config.window_radius_m;
  }

  template <typename Predicate>
  void erase_entries_if(Predicate&& predicate) {
    std::vector<TileKey> empty_tiles;
    tiles.for_each_tile([&](TileKey key, Tile& tile) {
      for (int level = 0; level <= kMaxLevel; ++level) {
        auto remove = [&](CellArray& entries) {
          entries.erase(std::remove_if(entries.begin(), entries.end(), predicate), entries.end());
        };
        remove(tile.leaves[level]);
        remove(tile.priors[level]);
      }
      if (tile.empty()) empty_tiles.push_back(key);
    });
    for (const TileKey key : empty_tiles) tiles.erase_if_empty(key);
  }

  ResolutionPolicy policy;
  MapConfig config;
  double center_x = 0.0;
  double center_y = 0.0;
  SparseTileStore tiles;
  std::uint64_t topology_changes = 0;
  std::uint64_t split_count = 0;
  std::uint64_t merge_count = 0;
};

void CellStats::add(const Observation& observation) {
  add(observation, MapConfig{}.clearance_envelope_m);
}

// Sorts one return into exactly one of the three layers.
//
// The decision is purely local and loop-free because `height_above_ground`
// arrives already computed from perception's ground model. Deriving it here
// would be circular: the layer assignment needs a ground height, and the
// ground height is the mean of the returns assigned to the ground layer.
// The single copy of the layer-routing rule.
//
// Both the outlier gate and the router need the same answer -- the gate before
// deciding whether to fold a return in, the router immediately after -- and
// two copies of a four-branch rule is how the two drift apart. It returns a
// member pointer so const and non-const callers share one implementation
// without const_cast and without the compiler re-evaluating the branches.
HeightLayer CellStats::*CellStats::route(const Observation& observation,
                                         double envelope_m) noexcept {
  const float hag = observation.height_above_ground;
  if (observation.ground == 1) return &CellStats::ground;
  // A non-finite height means perception had no ground model here. Obstacle is
  // the fail-safe destination: mistaking clear space for an obstacle costs a
  // detour, the reverse costs a collision.
  if (!std::isfinite(hag)) return nullptr;
  // Below the fitted ground is a depression -- a pothole or a drop -- and
  // belongs to the ground layer, where it widens the roughness traversability
  // is scored against. Clamping it away would hide a hazard.
  if (hag < 0.0F) return &CellStats::ground;
  if (static_cast<double>(hag) >= envelope_m) return &CellStats::overhead;
  return &CellStats::obstacle;
}

const HeightLayer& CellStats::layer_for(const Observation& observation,
                                        double envelope_m) const {
  const auto member = route(observation, envelope_m);
  return member == nullptr ? obstacle : this->*member;
}

void CellStats::assign_to_layer(const Observation& observation, double envelope_m) {
  const auto member = route(observation, envelope_m);
  if (member == nullptr) {
    // Counted so a degraded ground stage shows up as a number in the snapshot
    // instead of as a plausible but wrong map.
    ++unmodelled_returns;
    obstacle.add(observation.z, observation.timestamp);
    return;
  }
  (this->*member).add(observation.z, observation.timestamp);
}

void CellStats::observe_occupied() { occupancy_logodds = logodds::hit(occupancy_logodds); }

void CellStats::observe_free() {
  occupancy_logodds = logodds::miss(occupancy_logodds);
  ++free_observations;
}

OccupancyState CellStats::occupancy() const { return logodds::state_of(occupancy_logodds); }

// Range-aware ingestion: the overload a production ingestor should use.
//
// Two things happen here that the plain add() cannot do. First, the return is
// tested against the layer it would join, with a gate widened by the sensor's
// own modelled uncertainty at that range -- so a far, imprecise return is
// accepted for disagreeing within its error bars and refused only for
// disagreeing beyond them. Second, an accepted return is positive evidence of
// a surface, so it drives the occupancy accumulator toward Occupied.
//
// Returns false when the gate refused the return. A refusal is a normal
// outcome, not an error: it neither throws nor mutates anything but the
// rejection counter.
bool CellStats::add(const Observation& observation, double envelope_m,
                    const SensorNoiseModel& noise, const SensorPose& pose) {
  noise.validate();
  const double range = pose.range_to(observation.x, observation.y, observation.z);
  const HeightLayer& target = layer_for(observation, envelope_m);

  if (target.count >= noise.min_returns_before_gating) {
    // Total variance is the layer's own spread plus the sensor's modelled
    // variance at this range. Using only the layer's spread would reject every
    // genuine far return once a cell had been tightly observed up close; using
    // only the sensor term would ignore that a rough surface legitimately
    // scatters. Both sources are real, so both are in the denominator.
    const double total_variance = target.variance_z() + noise.variance_at(range);
    const double sigma = std::sqrt(total_variance);
    if (sigma > 0.0) {
      const double deviation = std::fabs(observation.z - target.mean_z);
      if (deviation > noise.mahalanobis_gate * sigma) {
        if (rejected_outliers < std::numeric_limits<std::uint16_t>::max()) {
          ++rejected_outliers;
        }
        return false;
      }
    }
  }

  add(observation, envelope_m);
  return true;
}

void CellStats::add(const Observation& observation, double envelope_m) {
  if (!std::isfinite(envelope_m) || envelope_m <= 0.0) {
    throw std::invalid_argument("clearance envelope must be finite and positive");
  }
  if (count != 0 && static_cast<double>(envelope_m) != static_cast<double>(sorted_envelope_m)) {
    // Two returns sorted under different envelopes cannot be reconciled
    // without the raw points, and the map does not keep raw points.
    throw std::invalid_argument("cell already sorted under a different clearance envelope");
  }
  if (!std::isfinite(observation.z)) {
    throw std::invalid_argument("elevation must be finite");
  }
  if (!std::isfinite(observation.semantic_confidence) ||
      !std::isfinite(observation.terrain_confidence) ||
      !std::isfinite(observation.geometry_complexity) ||
      !std::isfinite(observation.motion_probability) ||
      !std::isfinite(observation.observation_quality) || observation.semantic_confidence < 0.0F ||
      observation.semantic_confidence > 1.0F || observation.terrain_confidence < 0.0F ||
      observation.terrain_confidence > 1.0F || observation.geometry_complexity < 0.0F ||
      observation.geometry_complexity > 1.0F || observation.motion_probability < 0.0F ||
      observation.motion_probability > 1.0F || observation.observation_quality < 0.0F ||
      observation.observation_quality > 1.0F || observation.ground > 1 ||
      observation.drivable > 2 || std::isinf(observation.ground_gradient_x) ||
      std::isinf(observation.ground_gradient_y)) {
    throw std::invalid_argument("observation evidence is out of range");
  }
  const double previous_count = static_cast<double>(count);
  if (count == 0) {
    semantic_class = observation.semantic_class;
    semantic_evidence_v = observation.semantic_confidence;
    semantic_confidence_v = observation.semantic_confidence;
    drivable_evidence_v = observation.drivable == 1   ? observation.terrain_confidence
                                     : observation.drivable == 2 ? -observation.terrain_confidence
                                                                 : 0.0F;
    ground_evidence_v = observation.ground == 1 ? observation.terrain_confidence : 0.0F;
    terrain_confidence_v = observation.terrain_confidence;
    geometry_complexity_v = observation.geometry_complexity;
    motion_evidence_v = observation.motion_probability;
    observation_quality_v = observation.observation_quality;
  } else {
    const double next_count = previous_count + 1.0;
    // Averages are computed in float and stored back quantised. The update
    // weights the old value by previous/next < 1, so re-quantising each step
    // is contractive: the error stays around one quantum instead of
    // accumulating over a cell's lifetime.
    const auto blend = [previous_count, next_count](float current, float sample) {
      return static_cast<float>((static_cast<double>(current) * previous_count +
                                 static_cast<double>(sample)) /
                                next_count);
    };
    if (observation.semantic_confidence > semantic_evidence()) {
      semantic_class = observation.semantic_class;
      semantic_evidence_v = observation.semantic_confidence;
    }
    semantic_confidence_v =
        blend(semantic_confidence(), observation.semantic_confidence);
    const float drivable = observation.drivable == 1   ? observation.terrain_confidence
                           : observation.drivable == 2 ? -observation.terrain_confidence
                                                       : 0.0F;
    const float ground = observation.ground == 1 ? observation.terrain_confidence : 0.0F;
    drivable_evidence_v = blend(drivable_evidence(), drivable);
    ground_evidence_v = blend(ground_evidence(), ground);
    terrain_confidence_v = blend(terrain_confidence(), observation.terrain_confidence);
    geometry_complexity_v = blend(geometry_complexity(), observation.geometry_complexity);
    motion_evidence_v = blend(motion_evidence(), observation.motion_probability);
    observation_quality_v = blend(observation_quality(), observation.observation_quality);
  }
  if (observation.ground == 1 && std::isfinite(observation.ground_gradient_x) &&
      std::isfinite(observation.ground_gradient_y) && observation.terrain_confidence > 0.0F) {
    if (ground_gradient_count == 0) {
      ground_gradient_x_v = observation.ground_gradient_x;
      ground_gradient_y_v = observation.ground_gradient_y;
    } else {
      const double previous = static_cast<double>(ground_gradient_count);
      const double next = previous + 1.0;
      ground_gradient_x_v = static_cast<float>(
          (static_cast<double>(ground_gradient_x_v) * previous + observation.ground_gradient_x) /
          next);
      ground_gradient_y_v = static_cast<float>(
          (static_cast<double>(ground_gradient_y_v) * previous + observation.ground_gradient_y) /
          next);
    }
    if (ground_gradient_count < std::numeric_limits<std::uint32_t>::max()) {
      ++ground_gradient_count;
    }
  }
  assign_to_layer(observation, envelope_m);
  // An accepted return is positive evidence that a surface is here. This
  // belongs on the common path, not only on the range-gated overload: whether
  // a noise model vetted the return changes how much we trust its height, not
  // whether something was detected. Putting it on the gated overload alone
  // left occupancy permanently Unknown for every caller of the plain add() --
  // the live ingestion path included, which is the same dormant-feature trap
  // the V2 wire format created for the layers.
  observe_occupied();
  sorted_envelope_m = static_cast<float>(envelope_m);
  ++count;
  last_seen = std::max(last_seen, observation.timestamp);
}

// Pooled statistics, reconstructed on demand. Chan-merging the three layers is
// the same operation a coarsening merge performs, so there is one definition
// of how elevation evidence combines rather than two kept in step by hand.
double CellStats::mean_z() const { return pooled_from_layers().mean_z; }
double CellStats::m2_z() const { return static_cast<double>(pooled_from_layers().m2_z); }
double CellStats::min_z() const { return static_cast<double>(pooled_from_layers().min_z); }
double CellStats::max_z() const { return static_cast<double>(pooled_from_layers().max_z); }

void CellStats::merge(const CellStats& other) {
  if (other.count == 0) return;
  if (count == 0) {
    *this = other;
    return;
  }
  const double left_count = static_cast<double>(count);
  const double right_count = static_cast<double>(other.count);
  count += other.count;
  last_seen = std::max(last_seen, other.last_seen);
  if (other.semantic_evidence() > semantic_evidence()) {
    semantic_class = other.semantic_class;
    semantic_evidence_v = other.semantic_evidence_v;
  }
  const double total = left_count + right_count;
  const auto weighted = [left_count, right_count, total](float mine, float theirs) {
    return static_cast<float>(
        (static_cast<double>(mine) * left_count + static_cast<double>(theirs) * right_count) /
        total);
  };
  semantic_confidence_v =
      weighted(semantic_confidence(), other.semantic_confidence());
  drivable_evidence_v = weighted(drivable_evidence(), other.drivable_evidence());
  ground_evidence_v = weighted(ground_evidence(), other.ground_evidence());
  terrain_confidence_v = weighted(terrain_confidence(), other.terrain_confidence());
  geometry_complexity_v =
      weighted(geometry_complexity(), other.geometry_complexity());
  motion_evidence_v = weighted(motion_evidence(), other.motion_evidence());
  observation_quality_v =
      weighted(observation_quality(), other.observation_quality());
  if (other.ground_gradient_count != 0) {
    if (ground_gradient_count == 0) {
      ground_gradient_x_v = other.ground_gradient_x_v;
      ground_gradient_y_v = other.ground_gradient_y_v;
      ground_gradient_count = other.ground_gradient_count;
    } else {
      const double left_gradient_count = static_cast<double>(ground_gradient_count);
      const double right_gradient_count = static_cast<double>(other.ground_gradient_count);
      const double gradient_total = left_gradient_count + right_gradient_count;
      ground_gradient_x_v = static_cast<float>(
          (ground_gradient_x_v * left_gradient_count +
           other.ground_gradient_x_v * right_gradient_count) /
          gradient_total);
      ground_gradient_y_v = static_cast<float>(
          (ground_gradient_y_v * left_gradient_count +
           other.ground_gradient_y_v * right_gradient_count) /
          gradient_total);
      const std::uint64_t combined = static_cast<std::uint64_t>(ground_gradient_count) +
                                     other.ground_gradient_count;
      ground_gradient_count = static_cast<std::uint32_t>(std::min<std::uint64_t>(
          combined, std::numeric_limits<std::uint32_t>::max()));
    }
  }

  // Layer-wise, never pooled. Merging the three layers separately is what
  // makes a coarsened cell still able to answer "how high is the ground here"
  // -- a pooled merge would fold the road back into the van roof and rebuild
  // exactly the defect the layers exist to remove.
  ground.merge(other.ground);
  obstacle.merge(other.obstacle);
  overhead.merge(other.overhead);
  unmodelled_returns += other.unmodelled_returns;
  free_observations += other.free_observations;
  rejected_outliers = static_cast<std::uint16_t>(
      std::min<std::uint32_t>(static_cast<std::uint32_t>(rejected_outliers) +
                                  static_cast<std::uint32_t>(other.rejected_outliers),
                              std::numeric_limits<std::uint16_t>::max()));
  // Occupancy merges by count-weighted average of log-odds, then re-clamps.
  //
  // Summing would be wrong: four children each saturated at the clamp would
  // give a parent four times the clamp, which is not a probability any child
  // asserted and would take four times as long to contradict. Averaging keeps
  // the parent inside the same bounded range as its children, so the "bounded
  // time to change its mind" property survives coarsening.
  const double blended =
      (static_cast<double>(occupancy_logodds) * left_count +
       static_cast<double>(other.occupancy_logodds) * right_count) / total;
  occupancy_logodds = logodds::clamp(static_cast<int>(std::lround(blended)));
  if (sorted_envelope_m == 0.0F) sorted_envelope_m = other.sorted_envelope_m;
}

HeightLayer CellStats::pooled_from_layers() const {
  HeightLayer pooled = ground;
  pooled.merge(obstacle);
  pooled.merge(overhead);
  return pooled;
}

double CellStats::variance_z() const {
  return count > 1 ? m2_z() / static_cast<double>(count - 1) : 0.0;
}

std::size_t MapSnapshot::count_at_level(int level) const {
  core::validate_level(level);
  return static_cast<std::size_t>(std::count_if(
      leaves.begin(), leaves.end(), [level](const Leaf& leaf) { return leaf.id.level == level; }));
}

bool MapSnapshot::has_no_parent_descendant_overlap() const {
  std::vector<core::CellId> ids;
  ids.reserve(leaves.size());
  for (const Leaf& leaf : leaves) ids.push_back(leaf.id);
  std::sort(ids.begin(), ids.end(), less_id);
  if (std::adjacent_find(ids.begin(), ids.end()) != ids.end()) return false;
  for (const core::CellId id : ids) {
    for (int level = id.level + 1; level <= kMaxLevel; ++level) {
      if (std::binary_search(ids.begin(), ids.end(), ancestor_at(id, level), less_id)) {
        return false;
      }
    }
  }
  return true;
}

Map::Map(ResolutionPolicy policy, MapConfig config)
    : impl_(std::make_unique<Impl>(policy, config)) {}
Map::~Map() = default;
Map::Map(Map&&) noexcept = default;
Map& Map::operator=(Map&&) noexcept = default;

core::CellId Map::cell_for(double x, double y) const {
  const int level = level_for(x, y);
  if (level < 0) throw std::out_of_range("coordinates are outside DistanceLOD range");
  return index(x, y, level);
}

int Map::level_for(double x, double y) const { return impl_->level_for(x, y); }

bool Map::accepts(double x, double y) const { return impl_->accepts(x, y); }

void Map::update(const Observation& observation) {
  impl_->validate_observation(observation);
  const int level = impl_->level_for(observation.x, observation.y);
  if (level < 0) throw std::out_of_range("observation is outside DistanceLOD range");
  update_at_level(observation, level);
}

void Map::update_at_level(const Observation& observation, int level) {
  impl_->validate_observation(observation);
  core::validate_level(level);
  const core::CellId id = index(observation.x, observation.y, level);
  impl_->refine_ancestors(id);
  (void)impl_->coarsen_to(id);
  CellStats one;
  one.add(observation, impl_->config.clearance_envelope_m);
  impl_->merge_leaf(id, one);
}

void Map::set_window_center(double x, double y) {
  if (!std::isfinite(x) || !std::isfinite(y)) {
    throw std::invalid_argument("center must be finite");
  }
  impl_->center_x = x;
  impl_->center_y = y;
  impl_->erase_entries_if(
      [&](const StoredCell& entry) { return !impl_->cell_intersects_window(entry.id); });
}

void Map::evict_stale_before(std::uint64_t minimum_timestamp) {
  impl_->erase_entries_if([minimum_timestamp](const StoredCell& entry) {
    return entry.stats.last_seen < minimum_timestamp;
  });
}

void Map::split(core::CellId id) {
  core::validate_level(id.level);
  (void)impl_->split_leaf(id);
}

void Map::merge_children(core::CellId parent) {
  core::validate_level(parent.level);
  if (parent.level == 0 || impl_->leaf(parent).has_value()) return;
  CellStats merged;
  std::array<core::CellId, 4> children{};
  std::size_t index_in_children = 0;
  for (int dy = 0; dy < 2; ++dy) {
    for (int dx = 0; dx < 2; ++dx) {
      const core::CellId child = child_at(parent, dx, dy);
      const auto stats = impl_->leaf(child);
      if (!stats.has_value()) return;
      children[index_in_children++] = child;
      merged.merge(*stats);
    }
  }
  if (const auto prior = impl_->take_prior(parent); prior.has_value()) {
    merged.merge(*prior);
  }
  for (const core::CellId child : children) (void)impl_->take_leaf(child);
  impl_->merge_leaf(parent, merged);
  ++impl_->topology_changes;
  ++impl_->merge_count;
}

ClearingStats Map::clear_free_space(const DepthImage& image, const SensorPose& pose) {
  ClearingStats stats;
  impl_->tiles.for_each_tile([&](TileKey, Tile& tile) {
    for (int level = 0; level <= kMaxLevel; ++level) {
      for (StoredCell& entry : tile.leaves[level]) {
        if (entry.stats.obstacle.empty()) continue;
        ++stats.examined;

        // Cell centre, matching the geometry cell_intersects_window uses.
        const double resolution = core::resolution_m(entry.id.level);
        const double centre_x = (static_cast<double>(entry.id.ix) + 0.5) * resolution;
        const double centre_y = (static_cast<double>(entry.id.iy) + 0.5) * resolution;

        switch (test_cell_against_scan(entry.stats, centre_x, centre_y, image, pose,
                                       impl_->config.clearing_margin_m)) {
          case ClearingOutcome::Cleared:
            // One step toward free, not a deletion. Clamped log-odds means a
            // wall needs repeated contradiction before it is released, so a
            // single bad frame cannot erase it.
            entry.stats.observe_free();
            ++stats.cleared;
            break;
          case ClearingOutcome::Occluded:
            ++stats.occluded;
            break;
          case ClearingOutcome::SparedByElevation:
            ++stats.spared_by_elevation;
            break;
          case ClearingOutcome::NoEvidence:
          case ClearingOutcome::NoObstacle:
            ++stats.no_evidence;
            break;
        }
      }
    }
  });
  return stats;
}

MapSnapshot Map::snapshot() const {
  MapSnapshot snapshot;
  impl_->tiles.for_each_tile([&](TileKey, const Tile& tile) {
    snapshot.memory.allocated_tile_bytes += sizeof(Tile);
    for (int level = 0; level <= kMaxLevel; ++level) {
      snapshot.memory.allocated_cell_array_bytes +=
          tile.leaves[level].capacity() * sizeof(StoredCell);
      snapshot.memory.allocated_cell_array_bytes +=
          tile.priors[level].capacity() * sizeof(StoredCell);
      snapshot.memory.logical_payload_bytes += tile.leaves[level].size() * sizeof(Leaf);
      snapshot.memory.retained_prior_payload_bytes += tile.priors[level].size() * sizeof(Leaf);
      for (const StoredCell& entry : tile.leaves[level]) {
        snapshot.leaves.push_back({entry.id, entry.stats});
        snapshot.point_count += entry.stats.count;
        // Accumulated during the walk the snapshot already performs, rather
        // than in a second pass over the leaves afterwards.
        const CellStats& cell = entry.stats;
        snapshot.layers.ground_points += cell.ground.count;
        snapshot.layers.obstacle_points += cell.obstacle.count;
        snapshot.layers.overhead_points += cell.overhead.count;
        snapshot.layers.unmodelled_returns += cell.unmodelled_returns;
        snapshot.layers.rejected_outliers += cell.rejected_outliers;
        if (cell.ground.count > 0) {
          ++snapshot.layers.cells_with_ground;
        } else if (cell.obstacle.count > 0 || cell.overhead.count > 0) {
          // Something was seen here and the floor was not. Unknown, not free.
          ++snapshot.layers.occluded_ground_cells;
        }
        switch (cell.occupancy()) {
          case OccupancyState::Occupied:
            ++snapshot.layers.occupied_cells;
            break;
          case OccupancyState::Free:
            ++snapshot.layers.free_cells;
            break;
          case OccupancyState::Unknown:
            break;
        }
      }
      for (const StoredCell& entry : tile.priors[level]) {
        snapshot.point_count += entry.stats.count;
        snapshot.nonspatial_prior_point_count += entry.stats.count;
      }
    }
  });
  std::sort(snapshot.leaves.begin(), snapshot.leaves.end(),
            [](const Leaf& left, const Leaf& right) { return less_id(left.id, right.id); });
  snapshot.active_leaf_count = snapshot.leaves.size();
  snapshot.tile_count = impl_->tiles.size();
  snapshot.memory.allocated_index_bytes = impl_->tiles.allocated_index_bytes();
  snapshot.memory.allocated_bytes =
      snapshot.memory.allocated_index_bytes + snapshot.memory.allocated_cell_array_bytes;
  snapshot.memory.allocated_overhead_bytes =
      snapshot.memory.allocated_bytes - snapshot.memory.allocated_cell_array_bytes;
  snapshot.logical_bytes =
      snapshot.memory.logical_payload_bytes + snapshot.memory.retained_prior_payload_bytes;
  snapshot.topology_change_count = impl_->topology_changes;
  snapshot.split_count = impl_->split_count;
  snapshot.merge_count = impl_->merge_count;
  return snapshot;
}

std::uint64_t Map::point_count() const {
  // Same leaf and prior counts as snapshot(), without leaf collection,
  // sorting, or layer aggregation: O(n) for per-frame bookkeeping.
  std::uint64_t total = 0;
  impl_->tiles.for_each_tile([&](TileKey, const Tile& tile) {
    for (int level = 0; level <= kMaxLevel; ++level) {
      for (const StoredCell& entry : tile.leaves[level]) total += entry.stats.count;
      for (const StoredCell& entry : tile.priors[level]) total += entry.stats.count;
    }
  });
  return total;
}

Uniform5Map::Uniform5Map(MapConfig config) : map_(ResolutionPolicy::Uniform5, config) {}
Uniform5Map::~Uniform5Map() = default;
Uniform5Map::Uniform5Map(Uniform5Map&&) noexcept = default;
Uniform5Map& Uniform5Map::operator=(Uniform5Map&&) noexcept = default;
core::CellId Uniform5Map::cell_for(double x, double y) const { return map_.cell_for(x, y); }
bool Uniform5Map::accepts(double x, double y) const { return map_.accepts(x, y); }
void Uniform5Map::update(const Observation& observation) { map_.update(observation); }
void Uniform5Map::set_window_center(double x, double y) { map_.set_window_center(x, y); }
void Uniform5Map::evict_stale_before(std::uint64_t timestamp) {
  map_.evict_stale_before(timestamp);
}
ClearingStats Uniform5Map::clear_free_space(const DepthImage& image, const SensorPose& pose) {
  return map_.clear_free_space(image, pose);
}

MapSnapshot Uniform5Map::snapshot() const { return map_.snapshot(); }
std::uint64_t Uniform5Map::point_count() const { return map_.point_count(); }

Uniform40Map::Uniform40Map(MapConfig config) : map_(ResolutionPolicy::Uniform40, config) {}
Uniform40Map::~Uniform40Map() = default;
Uniform40Map::Uniform40Map(Uniform40Map&&) noexcept = default;
Uniform40Map& Uniform40Map::operator=(Uniform40Map&&) noexcept = default;
core::CellId Uniform40Map::cell_for(double x, double y) const { return map_.cell_for(x, y); }
bool Uniform40Map::accepts(double x, double y) const { return map_.accepts(x, y); }
void Uniform40Map::update(const Observation& observation) { map_.update(observation); }
void Uniform40Map::set_window_center(double x, double y) { map_.set_window_center(x, y); }
void Uniform40Map::evict_stale_before(std::uint64_t timestamp) {
  map_.evict_stale_before(timestamp);
}
ClearingStats Uniform40Map::clear_free_space(const DepthImage& image, const SensorPose& pose) {
  return map_.clear_free_space(image, pose);
}

MapSnapshot Uniform40Map::snapshot() const { return map_.snapshot(); }
std::uint64_t Uniform40Map::point_count() const { return map_.point_count(); }

DistanceLodMap::DistanceLodMap(MapConfig config) : map_(ResolutionPolicy::DistanceLod, config) {}
DistanceLodMap::~DistanceLodMap() = default;
DistanceLodMap::DistanceLodMap(DistanceLodMap&&) noexcept = default;
DistanceLodMap& DistanceLodMap::operator=(DistanceLodMap&&) noexcept = default;
core::CellId DistanceLodMap::cell_for(double x, double y) const { return map_.cell_for(x, y); }
bool DistanceLodMap::accepts(double x, double y) const { return map_.accepts(x, y); }
int DistanceLodMap::level_for(double x, double y) const { return map_.level_for(x, y); }
void DistanceLodMap::update(const Observation& observation) { map_.update(observation); }
void DistanceLodMap::set_window_center(double x, double y) { map_.set_window_center(x, y); }
void DistanceLodMap::evict_stale_before(std::uint64_t timestamp) {
  map_.evict_stale_before(timestamp);
}
void DistanceLodMap::split(core::CellId id) { map_.split(id); }
void DistanceLodMap::merge_children(core::CellId parent) { map_.merge_children(parent); }
ClearingStats DistanceLodMap::clear_free_space(const DepthImage& image, const SensorPose& pose) {
  return map_.clear_free_space(image, pose);
}

MapSnapshot DistanceLodMap::snapshot() const { return map_.snapshot(); }
std::uint64_t DistanceLodMap::point_count() const { return map_.point_count(); }

}  // namespace veyra::map
