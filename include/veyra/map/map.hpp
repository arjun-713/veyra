#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

#include "veyra/core/types.hpp"
#include "veyra/map/observation.hpp"

namespace veyra::map {

// Sufficient elevation statistics only. No observation coordinates or raw
// point history are retained by the map.
struct CellStats {
  std::uint64_t count = 0;
  double mean_z = 0.0;
  double m2_z = 0.0;
  double min_z = 0.0;
  double max_z = 0.0;
  std::uint64_t last_seen = 0;
  std::uint16_t semantic_class = 0;
  float semantic_evidence = 0.0F;
  float semantic_confidence = 0.0F;
  // Signed traversability evidence: positive is drivable, negative is
  // non-drivable, zero is unknown or insufficient confidence.
  float drivable_evidence = 0.0F;
  float ground_evidence = 0.0F;
  float terrain_confidence = 0.0F;
  // Count-weighted aggregate of the point-local height-complexity signal.
  float geometry_complexity = 0.0F;
  float motion_evidence = 0.0F;
  float observation_quality = 0.0F;

  void add(const Observation& observation);
  void merge(const CellStats& other);
  [[nodiscard]] double variance_z() const;
};

struct Leaf {
  core::CellId id;
  CellStats stats;
};

// Accounting names are deliberately non-overlapping. `allocated_bytes` is
// the exact capacity owned by the map's contiguous tile table and vectors;
// `allocated_tile_bytes` is a diagnostic subset of that table, not an input
// to the total.
struct MapMemoryAccounting {
  std::size_t logical_payload_bytes = 0;
  std::size_t retained_prior_payload_bytes = 0;
  std::size_t allocated_cell_array_bytes = 0;
  std::size_t allocated_tile_bytes = 0;
  std::size_t allocated_index_bytes = 0;
  std::size_t allocated_overhead_bytes = 0;
  std::size_t allocated_bytes = 0;
};

struct MapSnapshot {
  std::vector<Leaf> leaves;
  std::size_t active_leaf_count = 0;
  std::size_t tile_count = 0;
  // Includes active-leaf evidence and explicitly retained non-spatial priors.
  std::size_t point_count = 0;
  std::size_t nonspatial_prior_point_count = 0;
  // Retained for source compatibility; equals the two logical payload fields.
  std::size_t logical_bytes = 0;
  MapMemoryAccounting memory;
  std::uint64_t topology_change_count = 0;
  std::uint64_t split_count = 0;
  std::uint64_t merge_count = 0;

  [[nodiscard]] std::size_t count_at_level(int level) const;
  [[nodiscard]] bool has_no_parent_descendant_overlap() const;
};

struct MapConfig {
  double window_radius_m = 100.0;
  // World-aligned physical tile edge. Tiles are sparse; their cell arrays
  // grow only for observed cells and retained parent aggregates.
  double tile_size_m = 10.0;
  std::array<double, 3> distance_boundaries_m{10.0, 30.0, 60.0};
};

enum class ResolutionPolicy : std::uint8_t {
  Uniform5,
  Uniform40,
  DistanceLod,
};

// Common policy-compatible map interface. Existing named wrappers below are
// intentionally preserved for callers that use the original public API.
class Map {
 public:
  explicit Map(ResolutionPolicy policy, MapConfig config = {});
  ~Map();
  Map(Map&&) noexcept;
  Map& operator=(Map&&) noexcept;
  Map(const Map&) = delete;
  Map& operator=(const Map&) = delete;

  [[nodiscard]] core::CellId cell_for(double x, double y) const;
  [[nodiscard]] int level_for(double x, double y) const;
  // Containment query for stream ingestors. Direct update() stays fail-closed
  // and throws outside the window; ingestors pre-check with accepts() and
  // count documented rejections instead of aborting whole frames.
  [[nodiscard]] bool accepts(double x, double y) const;
  void update(const Observation& observation);
  // Applies an externally selected dyadic level after validating it. This is
  // the single seam used by a stateful policy; uniform and distance wrappers
  // continue to select their level internally.
  void update_at_level(const Observation& observation, int level);
  void set_window_center(double x, double y);
  // Drops cells whose newest evidence predates `minimum_timestamp`.
  void evict_stale_before(std::uint64_t minimum_timestamp);
  // Refinement is meaningful for a dyadic map regardless of policy. It is
  // public for deterministic topology tests and controlled refinements.
  void split(core::CellId id);
  void merge_children(core::CellId parent);
  [[nodiscard]] MapSnapshot snapshot() const;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

class Uniform5Map {
 public:
  explicit Uniform5Map(MapConfig config = {});
  ~Uniform5Map();
  Uniform5Map(Uniform5Map&&) noexcept;
  Uniform5Map& operator=(Uniform5Map&&) noexcept;
  Uniform5Map(const Uniform5Map&) = delete;
  Uniform5Map& operator=(const Uniform5Map&) = delete;
  [[nodiscard]] core::CellId cell_for(double x, double y) const;
  [[nodiscard]] bool accepts(double x, double y) const;
  void update(const Observation& observation);
  void set_window_center(double x, double y);
  void evict_stale_before(std::uint64_t minimum_timestamp);
  [[nodiscard]] MapSnapshot snapshot() const;

 private:
  Map map_;
};

class Uniform40Map {
 public:
  explicit Uniform40Map(MapConfig config = {});
  ~Uniform40Map();
  Uniform40Map(Uniform40Map&&) noexcept;
  Uniform40Map& operator=(Uniform40Map&&) noexcept;
  Uniform40Map(const Uniform40Map&) = delete;
  Uniform40Map& operator=(const Uniform40Map&) = delete;
  [[nodiscard]] core::CellId cell_for(double x, double y) const;
  [[nodiscard]] bool accepts(double x, double y) const;
  void update(const Observation& observation);
  void set_window_center(double x, double y);
  void evict_stale_before(std::uint64_t minimum_timestamp);
  [[nodiscard]] MapSnapshot snapshot() const;

 private:
  Map map_;
};

class DistanceLodMap {
 public:
  explicit DistanceLodMap(MapConfig config = {});
  ~DistanceLodMap();
  DistanceLodMap(DistanceLodMap&&) noexcept;
  DistanceLodMap& operator=(DistanceLodMap&&) noexcept;
  DistanceLodMap(const DistanceLodMap&) = delete;
  DistanceLodMap& operator=(const DistanceLodMap&) = delete;
  [[nodiscard]] core::CellId cell_for(double x, double y) const;
  [[nodiscard]] int level_for(double x, double y) const;
  [[nodiscard]] bool accepts(double x, double y) const;
  void update(const Observation& observation);
  void set_window_center(double x, double y);
  void evict_stale_before(std::uint64_t minimum_timestamp);
  void split(core::CellId id);
  void merge_children(core::CellId parent);
  [[nodiscard]] MapSnapshot snapshot() const;

 private:
  Map map_;
};

}  // namespace veyra::map
