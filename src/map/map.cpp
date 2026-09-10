#include "veyra/map/map.hpp"

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

  constexpr bool operator==(const TileKey &) const = default;
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

[[nodiscard]] bool less_id(const core::CellId &left,
                           const core::CellId &right) noexcept {
  if (left.level != right.level) return left.level < right.level;
  if (left.ix != right.ix) return left.ix < right.ix;
  return left.iy < right.iy;
}

[[nodiscard]] bool less_entry(const StoredCell &left,
                              const core::CellId &right) noexcept {
  return less_id(left.id, right);
}

using CellArray = std::vector<StoredCell>;

[[nodiscard]] CellArray::iterator find_entry(CellArray &cells,
                                              core::CellId id) {
  return std::lower_bound(cells.begin(), cells.end(), id, less_entry);
}

[[nodiscard]] CellArray::const_iterator find_entry(const CellArray &cells,
                                                    core::CellId id) {
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

  [[nodiscard]] Tile *find(TileKey key) {
    const auto index = find_slot(key);
    return index.has_value() ? &slots_[*index].tile : nullptr;
  }

  [[nodiscard]] const Tile *find(TileKey key) const {
    const auto index = find_slot(key);
    return index.has_value() ? &slots_[*index].tile : nullptr;
  }

  Tile &find_or_create(TileKey key) {
    ensure_insert_capacity();
    const std::size_t mask = slots_.size() - 1U;
    std::size_t position = hash_tile(key) & mask;
    std::optional<std::size_t> first_tombstone;
    for (;;) {
      TileSlot &slot = slots_[position];
      if (slot.state == SlotState::Empty) {
        const std::size_t destination = first_tombstone.value_or(position);
        TileSlot &created = slots_[destination];
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
    TileSlot &slot = slots_[*index];
    if (!slot.tile.empty()) return;
    slot.tile = Tile{};
    slot.state = SlotState::Tombstone;
    --size_;
    ++tombstones_;
  }

  template <typename Function>
  void for_each_tile(Function &&function) {
    for (TileSlot &slot : slots_) {
      if (slot.state == SlotState::Occupied) function(slot.key, slot.tile);
    }
  }

  template <typename Function>
  void for_each_tile(Function &&function) const {
    for (const TileSlot &slot : slots_) {
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
      const TileSlot &slot = slots_[position];
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
    for (TileSlot &old : old_slots) {
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

[[nodiscard]] std::int32_t checked_floor_to_i32(double value,
                                                 const char *message) {
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
  return {level,
          checked_floor_to_i32(x / resolution, "x coordinate exceeds map lattice"),
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
  return {parent.level - 1, static_cast<std::int32_t>(child_x),
          static_cast<std::int32_t>(child_y)};
}

}  // namespace

struct Map::Impl {
  explicit Impl(ResolutionPolicy initial_policy, MapConfig initial_config)
      : policy(initial_policy), config(initial_config) {
    if (!(config.window_radius_m > 0.0) || !std::isfinite(config.window_radius_m)) {
      throw std::invalid_argument("window radius must be finite and positive");
    }
    if (!(config.tile_size_m > 0.0) || !std::isfinite(config.tile_size_m)) {
      throw std::invalid_argument("tile size must be finite and positive");
    }
    if (policy == ResolutionPolicy::DistanceLod) {
      const auto &boundaries = config.distance_boundaries_m;
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
    return {checked_floor_to_i32(static_cast<double>(id.ix) * resolution /
                                     config.tile_size_m,
                                 "x tile index exceeds map lattice"),
            checked_floor_to_i32(static_cast<double>(id.iy) * resolution /
                                     config.tile_size_m,
                                 "y tile index exceeds map lattice")};
  }

  [[nodiscard]] bool accepts(double x, double y) const {
    if (!std::isfinite(x) || !std::isfinite(y)) return false;
    const double dx = x - center_x;
    const double dy = y - center_y;
    return dx * dx + dy * dy <= config.window_radius_m * config.window_radius_m;
  }

  void validate_observation(const Observation &observation) const {
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
        const auto &boundaries = config.distance_boundaries_m;
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
    const Tile *tile = tiles.find(tile_key_for(id));
    if (tile == nullptr) return std::nullopt;
    const CellArray &entries = tile->leaves[id.level];
    const auto entry = find_entry(entries, id);
    if (entry == entries.end() || entry->id != id) return std::nullopt;
    return entry->stats;
  }

  void merge_leaf(core::CellId id, const CellStats &stats) {
    Tile &tile = tiles.find_or_create(tile_key_for(id));
    CellArray &entries = tile.leaves[id.level];
    const auto entry = find_entry(entries, id);
    if (entry != entries.end() && entry->id == id) {
      entry->stats.merge(stats);
      return;
    }
    entries.insert(entry, {id, stats});
  }

  [[nodiscard]] std::optional<CellStats> take_leaf(core::CellId id) {
    const TileKey key = tile_key_for(id);
    Tile *tile = tiles.find(key);
    if (tile == nullptr) return std::nullopt;
    CellArray &entries = tile->leaves[id.level];
    const auto entry = find_entry(entries, id);
    if (entry == entries.end() || entry->id != id) return std::nullopt;
    CellStats stats = entry->stats;
    entries.erase(entry);
    tiles.erase_if_empty(key);
    return stats;
  }

  void merge_prior(core::CellId id, const CellStats &stats) {
    if (stats.count == 0) return;
    Tile &tile = tiles.find_or_create(tile_key_for(id));
    CellArray &entries = tile.priors[id.level];
    const auto entry = find_entry(entries, id);
    if (entry != entries.end() && entry->id == id) {
      entry->stats.merge(stats);
      return;
    }
    entries.insert(entry, {id, stats});
  }

  [[nodiscard]] std::optional<CellStats> take_prior(core::CellId id) {
    const TileKey key = tile_key_for(id);
    Tile *tile = tiles.find(key);
    if (tile == nullptr) return std::nullopt;
    CellArray &entries = tile->priors[id.level];
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
    if (found_active_descendant) ++topology_changes;
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
  void erase_entries_if(Predicate &&predicate) {
    std::vector<TileKey> empty_tiles;
    tiles.for_each_tile([&](TileKey key, Tile &tile) {
      for (int level = 0; level <= kMaxLevel; ++level) {
        auto remove = [&](CellArray &entries) {
          entries.erase(std::remove_if(entries.begin(), entries.end(), predicate),
                        entries.end());
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
};

void CellStats::add(const Observation &observation) {
  if (!std::isfinite(observation.z)) {
    throw std::invalid_argument("elevation must be finite");
  }
  if (!std::isfinite(observation.semantic_confidence) ||
      !std::isfinite(observation.terrain_confidence) ||
      !std::isfinite(observation.geometry_complexity) ||
      !std::isfinite(observation.motion_probability) ||
      !std::isfinite(observation.observation_quality) ||
      observation.semantic_confidence < 0.0F || observation.semantic_confidence > 1.0F ||
      observation.terrain_confidence < 0.0F || observation.terrain_confidence > 1.0F ||
      observation.geometry_complexity < 0.0F || observation.geometry_complexity > 1.0F ||
      observation.motion_probability < 0.0F || observation.motion_probability > 1.0F ||
      observation.observation_quality < 0.0F || observation.observation_quality > 1.0F ||
      observation.ground > 1 || observation.drivable > 2) {
    throw std::invalid_argument("observation evidence is out of range");
  }
  const double previous_count = static_cast<double>(count);
  if (count == 0) {
    min_z = max_z = observation.z;
    semantic_class = observation.semantic_class;
    semantic_evidence = observation.semantic_confidence;
    semantic_confidence = observation.semantic_confidence;
    drivable_evidence = observation.drivable == 1 ? observation.terrain_confidence
                       : observation.drivable == 2 ? -observation.terrain_confidence
                                                   : 0.0F;
    ground_evidence = observation.ground == 1 ? observation.terrain_confidence : 0.0F;
    terrain_confidence = observation.terrain_confidence;
    geometry_complexity = observation.geometry_complexity;
    motion_evidence = observation.motion_probability;
    observation_quality = observation.observation_quality;
  } else {
    const double next_count = previous_count + 1.0;
    if (observation.semantic_confidence > semantic_evidence) {
      semantic_class = observation.semantic_class;
      semantic_evidence = observation.semantic_confidence;
    }
    semantic_confidence = static_cast<float>((semantic_confidence * previous_count +
                                               observation.semantic_confidence) / next_count);
    const float drivable = observation.drivable == 1 ? observation.terrain_confidence
                          : observation.drivable == 2 ? -observation.terrain_confidence : 0.0F;
    const float ground = observation.ground == 1 ? observation.terrain_confidence : 0.0F;
    drivable_evidence = static_cast<float>((drivable_evidence * previous_count + drivable) / next_count);
    ground_evidence = static_cast<float>((ground_evidence * previous_count + ground) / next_count);
    terrain_confidence = static_cast<float>((terrain_confidence * previous_count +
                                              observation.terrain_confidence) / next_count);
    geometry_complexity = static_cast<float>((geometry_complexity * previous_count +
                                               observation.geometry_complexity) / next_count);
    motion_evidence = static_cast<float>((motion_evidence * previous_count +
                                           observation.motion_probability) / next_count);
    observation_quality = static_cast<float>((observation_quality * previous_count +
                                               observation.observation_quality) / next_count);
  }
  ++count;
  const double delta = observation.z - mean_z;
  mean_z += delta / static_cast<double>(count);
  m2_z += delta * (observation.z - mean_z);
  min_z = std::min(min_z, observation.z);
  max_z = std::max(max_z, observation.z);
  last_seen = std::max(last_seen, observation.timestamp);
}

void CellStats::merge(const CellStats &other) {
  if (other.count == 0) return;
  if (count == 0) {
    *this = other;
    return;
  }
  const double left_count = static_cast<double>(count);
  const double right_count = static_cast<double>(other.count);
  const double delta = other.mean_z - mean_z;
  m2_z += other.m2_z + delta * delta * left_count * right_count /
                            (left_count + right_count);
  mean_z = (left_count * mean_z + right_count * other.mean_z) /
           (left_count + right_count);
  count += other.count;
  min_z = std::min(min_z, other.min_z);
  max_z = std::max(max_z, other.max_z);
  last_seen = std::max(last_seen, other.last_seen);
  if (other.semantic_evidence > semantic_evidence) {
    semantic_class = other.semantic_class;
    semantic_evidence = other.semantic_evidence;
  }
  const double total = left_count + right_count;
  semantic_confidence = static_cast<float>((semantic_confidence * left_count +
                                             other.semantic_confidence * right_count) / total);
  drivable_evidence = static_cast<float>((drivable_evidence * left_count +
                                           other.drivable_evidence * right_count) / total);
  ground_evidence = static_cast<float>((ground_evidence * left_count +
                                        other.ground_evidence * right_count) / total);
  terrain_confidence = static_cast<float>((terrain_confidence * left_count +
                                            other.terrain_confidence * right_count) / total);
  geometry_complexity = static_cast<float>((geometry_complexity * left_count +
                                             other.geometry_complexity * right_count) / total);
  motion_evidence = static_cast<float>((motion_evidence * left_count +
                                         other.motion_evidence * right_count) / total);
  observation_quality = static_cast<float>((observation_quality * left_count +
                                             other.observation_quality * right_count) / total);
}

double CellStats::variance_z() const {
  return count > 1 ? m2_z / static_cast<double>(count - 1) : 0.0;
}

std::size_t MapSnapshot::count_at_level(int level) const {
  core::validate_level(level);
  return static_cast<std::size_t>(std::count_if(
      leaves.begin(), leaves.end(), [level](const Leaf &leaf) {
        return leaf.id.level == level;
      }));
}

bool MapSnapshot::has_no_parent_descendant_overlap() const {
  std::vector<core::CellId> ids;
  ids.reserve(leaves.size());
  for (const Leaf &leaf : leaves) ids.push_back(leaf.id);
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
Map::Map(Map &&) noexcept = default;
Map &Map::operator=(Map &&) noexcept = default;

core::CellId Map::cell_for(double x, double y) const {
  const int level = level_for(x, y);
  if (level < 0) throw std::out_of_range("coordinates are outside DistanceLOD range");
  return index(x, y, level);
}

int Map::level_for(double x, double y) const { return impl_->level_for(x, y); }

bool Map::accepts(double x, double y) const { return impl_->accepts(x, y); }

void Map::update(const Observation &observation) {
  impl_->validate_observation(observation);
  const int level = impl_->level_for(observation.x, observation.y);
  if (level < 0) throw std::out_of_range("observation is outside DistanceLOD range");
  update_at_level(observation, level);
}

void Map::update_at_level(const Observation &observation, int level) {
  impl_->validate_observation(observation);
  core::validate_level(level);
  const core::CellId id = index(observation.x, observation.y, level);
  impl_->refine_ancestors(id);
  (void)impl_->coarsen_to(id);
  CellStats one;
  one.add(observation);
  impl_->merge_leaf(id, one);
}

void Map::set_window_center(double x, double y) {
  if (!std::isfinite(x) || !std::isfinite(y)) {
    throw std::invalid_argument("center must be finite");
  }
  impl_->center_x = x;
  impl_->center_y = y;
  impl_->erase_entries_if([&](const StoredCell &entry) {
    return !impl_->cell_intersects_window(entry.id);
  });
}

void Map::evict_stale_before(std::uint64_t minimum_timestamp) {
  impl_->erase_entries_if([minimum_timestamp](const StoredCell &entry) {
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
}

MapSnapshot Map::snapshot() const {
  MapSnapshot snapshot;
  impl_->tiles.for_each_tile([&](TileKey, const Tile &tile) {
    snapshot.memory.allocated_tile_bytes += sizeof(Tile);
    for (int level = 0; level <= kMaxLevel; ++level) {
      snapshot.memory.allocated_cell_array_bytes +=
          tile.leaves[level].capacity() * sizeof(StoredCell);
      snapshot.memory.allocated_cell_array_bytes +=
          tile.priors[level].capacity() * sizeof(StoredCell);
      snapshot.memory.logical_payload_bytes +=
          tile.leaves[level].size() * sizeof(Leaf);
      snapshot.memory.retained_prior_payload_bytes +=
          tile.priors[level].size() * sizeof(Leaf);
      for (const StoredCell &entry : tile.leaves[level]) {
        snapshot.leaves.push_back({entry.id, entry.stats});
        snapshot.point_count += entry.stats.count;
      }
      for (const StoredCell &entry : tile.priors[level]) {
        snapshot.point_count += entry.stats.count;
        snapshot.nonspatial_prior_point_count += entry.stats.count;
      }
    }
  });
  std::sort(snapshot.leaves.begin(), snapshot.leaves.end(),
            [](const Leaf &left, const Leaf &right) { return less_id(left.id, right.id); });
  snapshot.active_leaf_count = snapshot.leaves.size();
  snapshot.tile_count = impl_->tiles.size();
  snapshot.memory.allocated_index_bytes = impl_->tiles.allocated_index_bytes();
  snapshot.memory.allocated_bytes = snapshot.memory.allocated_index_bytes +
                                    snapshot.memory.allocated_cell_array_bytes;
  snapshot.memory.allocated_overhead_bytes =
      snapshot.memory.allocated_bytes - snapshot.memory.allocated_cell_array_bytes;
  snapshot.logical_bytes = snapshot.memory.logical_payload_bytes +
                           snapshot.memory.retained_prior_payload_bytes;
  snapshot.topology_change_count = impl_->topology_changes;
  return snapshot;
}

Uniform5Map::Uniform5Map(MapConfig config) : map_(ResolutionPolicy::Uniform5, config) {}
Uniform5Map::~Uniform5Map() = default;
Uniform5Map::Uniform5Map(Uniform5Map &&) noexcept = default;
Uniform5Map &Uniform5Map::operator=(Uniform5Map &&) noexcept = default;
core::CellId Uniform5Map::cell_for(double x, double y) const { return map_.cell_for(x, y); }
bool Uniform5Map::accepts(double x, double y) const { return map_.accepts(x, y); }
void Uniform5Map::update(const Observation &observation) { map_.update(observation); }
void Uniform5Map::set_window_center(double x, double y) { map_.set_window_center(x, y); }
void Uniform5Map::evict_stale_before(std::uint64_t timestamp) { map_.evict_stale_before(timestamp); }
MapSnapshot Uniform5Map::snapshot() const { return map_.snapshot(); }

Uniform40Map::Uniform40Map(MapConfig config) : map_(ResolutionPolicy::Uniform40, config) {}
Uniform40Map::~Uniform40Map() = default;
Uniform40Map::Uniform40Map(Uniform40Map &&) noexcept = default;
Uniform40Map &Uniform40Map::operator=(Uniform40Map &&) noexcept = default;
core::CellId Uniform40Map::cell_for(double x, double y) const { return map_.cell_for(x, y); }
bool Uniform40Map::accepts(double x, double y) const { return map_.accepts(x, y); }
void Uniform40Map::update(const Observation &observation) { map_.update(observation); }
void Uniform40Map::set_window_center(double x, double y) { map_.set_window_center(x, y); }
void Uniform40Map::evict_stale_before(std::uint64_t timestamp) { map_.evict_stale_before(timestamp); }
MapSnapshot Uniform40Map::snapshot() const { return map_.snapshot(); }

DistanceLodMap::DistanceLodMap(MapConfig config) : map_(ResolutionPolicy::DistanceLod, config) {}
DistanceLodMap::~DistanceLodMap() = default;
DistanceLodMap::DistanceLodMap(DistanceLodMap &&) noexcept = default;
DistanceLodMap &DistanceLodMap::operator=(DistanceLodMap &&) noexcept = default;
core::CellId DistanceLodMap::cell_for(double x, double y) const { return map_.cell_for(x, y); }
bool DistanceLodMap::accepts(double x, double y) const { return map_.accepts(x, y); }
int DistanceLodMap::level_for(double x, double y) const { return map_.level_for(x, y); }
void DistanceLodMap::update(const Observation &observation) { map_.update(observation); }
void DistanceLodMap::set_window_center(double x, double y) { map_.set_window_center(x, y); }
void DistanceLodMap::evict_stale_before(std::uint64_t timestamp) { map_.evict_stale_before(timestamp); }
void DistanceLodMap::split(core::CellId id) { map_.split(id); }
void DistanceLodMap::merge_children(core::CellId parent) { map_.merge_children(parent); }
MapSnapshot DistanceLodMap::snapshot() const { return map_.snapshot(); }

}  // namespace veyra::map
