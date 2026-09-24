#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

#include "veyra/core/types.hpp"
#include "veyra/map/depth_image.hpp"
#include "veyra/map/height_layer.hpp"
#include "veyra/map/occupancy.hpp"
#include "veyra/map/sensor_model.hpp"
#include "veyra/map/observation.hpp"

namespace veyra::map {

// Sufficient elevation statistics only. No observation coordinates or raw
// point history are retained by the map.
struct CellStats {
 public:
  std::uint64_t count = 0;
  std::uint64_t last_seen = 0;
  std::uint16_t semantic_class = 0;
  // Evidence fields. These stay 32-bit floats, and that is a decision, not an
  // oversight: quantising them to one byte was implemented, measured and
  // reverted.
  //
  // These are running averages, x <- (x*n + v)/(n+1). Once n is large the
  // per-update change is (v - x)/n, and at 1/255 resolution that falls below
  // one quantum at a few hundred returns -- after which every update rounds
  // straight back and the field stops moving. Measured: 20,000 observations of
  // 0.20 against a stored 0.73 moved it by exactly zero, where the true mean
  // is 0.465. It is the failure veyra::map::Cell's own comment warns about for
  // float means, in a coarser form: a plausible-looking wrong value that no
  // assertion catches.
  //
  // float puts that cliff at ~10^7 updates, far outside a cell's life in a
  // rolling window. The 24 bytes it costs buy evidence that can still change
  // its mind. test_quantised_evidence_does_not_drift guards this.
  float semantic_evidence_v = 0.0F;
  float semantic_confidence_v = 0.0F;
  // Signed traversability evidence: positive is drivable, negative is
  // non-drivable, zero is unknown or insufficient confidence.
  float drivable_evidence_v = 0.0F;
  float ground_evidence_v = 0.0F;
  float terrain_confidence_v = 0.0F;
  // Count-weighted aggregate of the point-local height-complexity signal.
  float geometry_complexity_v = 0.0F;
  float motion_evidence_v = 0.0F;
  float observation_quality_v = 0.0F;
  // Count-weighted local plane derivatives from trusted ground returns.
  // A separate count is required because some ground observations have no
  // supported terrain fit and must not dilute valid directional evidence.
  float ground_gradient_x_v = 0.0F;
  float ground_gradient_y_v = 0.0F;
  std::uint32_t ground_gradient_count = 0;

  [[nodiscard]] float semantic_evidence() const { return semantic_evidence_v; }
  [[nodiscard]] float semantic_confidence() const { return semantic_confidence_v; }
  [[nodiscard]] float drivable_evidence() const { return drivable_evidence_v; }
  [[nodiscard]] float ground_evidence() const { return ground_evidence_v; }
  [[nodiscard]] float terrain_confidence() const { return terrain_confidence_v; }
  [[nodiscard]] float geometry_complexity() const { return geometry_complexity_v; }
  [[nodiscard]] float motion_evidence() const { return motion_evidence_v; }
  [[nodiscard]] float observation_quality() const { return observation_quality_v; }
  [[nodiscard]] float ground_gradient_x() const { return ground_gradient_x_v; }
  [[nodiscard]] float ground_gradient_y() const { return ground_gradient_y_v; }

  // Physically separated elevation evidence. The pooled fields above remain
  // the map's accounting record -- point conservation and the existing
  // invariant-4 tolerances are stated over them -- while these three carry the
  // surfaces a planner actually needs to tell apart.
  //
  // `ground` holds returns perception accepted as ground; its mean is the
  // surface height and its variance is the roughness.
  // `obstacle` holds non-ground returns inside the vehicle envelope; its
  // min_z is the base of a kerb or step.
  // `overhead` holds returns above the envelope; its min_z is the clearance.
  //
  // The three are exhaustive and disjoint over accepted returns, so
  // ground.count + obstacle.count + overhead.count == count, and Chan-merging
  // them reproduces the pooled statistics. Both are asserted by tests rather
  // than assumed -- see pooled_from_layers().
  HeightLayer ground{};
  HeightLayer obstacle{};
  HeightLayer overhead{};
  // Returns whose ground model was unavailable (non-finite height above
  // ground). They are routed to the obstacle layer, the fail-safe direction,
  // and counted here so a degraded ground stage is visible rather than silent.
  std::uint32_t unmodelled_returns = 0;
  // Returns refused by the Mahalanobis gate because they disagreed with the
  // layer by more than their own modelled uncertainty could explain. Counted,
  // never silent: a cell quietly discarding half its returns is a sensor or
  // calibration fault, and it should be visible as a number.
  std::uint16_t rejected_outliers = 0;
  // Bayesian occupancy in fixed-point log-odds. See veyra/map/occupancy.hpp.
  // Bounded by clamps, so the map can change its mind in bounded time.
  std::int16_t occupancy_logodds = 0;
  // Times a beam was observed passing through this cell's obstacle extent.
  // This is positive evidence of absence, and it is the only thing that may
  // drive a cell toward Free -- ageing never does.
  std::uint32_t free_observations = 0;

  void add(const Observation& observation);
  // Folds a return in, sorting it into the ground, obstacle or overhead layer
  // at `envelope_m` metres above the fitted ground. The one-argument overload
  // uses the MapConfig default and exists so existing callers keep compiling.
  void add(const Observation& observation, double envelope_m);
  // Folds a return in with range-dependent uncertainty and Mahalanobis outlier
  // rejection. Returns false when the gate refused the return, in which case
  // only `rejected_outliers` changed. This is the overload a production
  // ingestor should use; the others assume every return is equally reliable.
  bool add(const Observation& observation, double envelope_m, const SensorNoiseModel& noise,
           const SensorPose& pose);
  void merge(const CellStats& other);

  // Pooled elevation statistics, reconstructed from the three layers.
  //
  // These were stored fields. They are now derived, because storing a value
  // the layers already determine is duplication that can drift, and it cost
  // 32 bytes in a cell that had more than doubled. Chan-merging three
  // accumulators is a handful of arithmetic on data already in cache.
  //
  // The consequence is stated plainly: `m2_z`, `min_z` and `max_z` now carry
  // the layers' float precision rather than double. `count` is unaffected and
  // remains exact, so point conservation is unchanged. See
  // docs/map-correctness.md invariant 8.
  [[nodiscard]] double mean_z() const;
  [[nodiscard]] double m2_z() const;
  [[nodiscard]] double min_z() const;
  [[nodiscard]] double max_z() const;

  // Positive evidence that a surface is present here.
  void observe_occupied();
  // Positive evidence of absence: a beam was observed passing through this
  // cell's claimed vertical extent. Never called by a timer -- absence of
  // evidence is not evidence of absence, so ageing produces Unknown, not Free.
  void observe_free();
  [[nodiscard]] OccupancyState occupancy() const;
  [[nodiscard]] double variance_z() const;

  // Chan-merges the three layers back into one accumulator.
  //
  // This is the claim the layered design rests on: splitting the elevation
  // evidence by physical surface costs no accounting fidelity, because the
  // pooled statistics remain exactly recoverable. It is a function rather than
  // a comment so the test suite can hold it to the invariant-4 tolerances in
  // docs/map-correctness.md.
  [[nodiscard]] HeightLayer pooled_from_layers() const;

  // Boundary between the obstacle and overhead layers, in metres above the
  // fitted ground, that was used when these returns were folded in.
  //
  // Stored per cell rather than assumed globally: a cell whose returns were
  // sorted under one envelope cannot be reinterpreted under another without
  // the raw points, and the map does not keep raw points. A caller querying
  // with a taller vehicle than the one that built the map gets a refusal, not
  // a silently wrong answer.
  float sorted_envelope_m = 0.0F;

 private:
  // Routes one return to exactly one layer. Private because the routing rule
  // and the pooled accumulator must stay in lockstep: every path that touches
  // one touches the other, in add(), or the reconstruction claim breaks.
  void assign_to_layer(const Observation& observation, double envelope_m);
  [[nodiscard]] const HeightLayer& layer_for(const Observation& observation,
                                             double envelope_m) const;
  // The one copy of the routing rule. nullptr means "no ground model for this
  // return", which routes to the obstacle layer and is counted separately.
  [[nodiscard]] static HeightLayer CellStats::*route(const Observation& observation,
                                                     double envelope_m) noexcept;
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

// Aggregate layer evidence across the snapshot's active leaves.
//
// Exists so the layered representation is observable from outside the process.
// Without it the layers are real but invisible: a producer that stops
// supplying height_above_ground would degrade the map silently, and an
// end-to-end test would have nothing to assert against. `unmodelled_returns`
// is the number that makes that failure loud.
struct LayerTotals {
  std::uint64_t ground_points = 0;
  std::uint64_t obstacle_points = 0;
  std::uint64_t overhead_points = 0;
  // Returns whose ground model was unavailable. Non-zero in a run that should
  // have a ground stage means the stage or the protocol is not delivering.
  std::uint64_t unmodelled_returns = 0;
  std::uint64_t rejected_outliers = 0;
  // Cells holding obstacle or overhead evidence but no ground evidence: the
  // floor was never observed. These must never be reported drivable.
  std::uint64_t occluded_ground_cells = 0;
  std::uint64_t cells_with_ground = 0;
  std::uint64_t occupied_cells = 0;
  std::uint64_t free_cells = 0;
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
  LayerTotals layers;
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
  // Height of the sensor above the pose origin the protocol reports, metres.
  //
  // A calibration constant, so it lives in config rather than on the wire.
  // Visibility clearing needs the sensor's own position: the pose gives x and
  // y, and getting z wrong tilts every beam elevation and would clear the
  // wrong cells.
  double sensor_height_m = 1.8;
  // Range slack before a measured return counts as lying beyond a cell.
  // Without it, range noise on a surface lets that surface clear itself.
  double clearing_margin_m = 0.10;
  // Height above the fitted ground at which a return stops being an obstacle
  // the vehicle strikes and becomes overhead structure it passes under. This
  // is a property of the platform the map is built for; classify() refuses
  // queries from a vehicle taller than the map was sorted for.
  double clearance_envelope_m = 2.0;
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
  // Contradicts obstacle evidence the current scan saw through.
  //
  // Walks the active leaves once and applies the depth-image test to each.
  // Only cells the scan positively contradicts move toward free; occlusion,
  // absent returns, and beams that passed over or under an obstacle all leave
  // the cell alone, which is what keeps a timeout from ever producing free
  // space. Returns what happened, because a clearing pass that cannot report
  // how many cells it spared is not auditable.
  ClearingStats clear_free_space(const DepthImage& image, const SensorPose& pose);

  // Refinement is meaningful for a dyadic map regardless of policy. It is
  // public for deterministic topology tests and controlled refinements.
  void split(core::CellId id);
  void merge_children(core::CellId parent);
  [[nodiscard]] MapSnapshot snapshot() const;
  [[nodiscard]] std::uint64_t point_count() const;

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
  ClearingStats clear_free_space(const DepthImage& image, const SensorPose& pose);
  [[nodiscard]] MapSnapshot snapshot() const;
  [[nodiscard]] std::uint64_t point_count() const;

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
  ClearingStats clear_free_space(const DepthImage& image, const SensorPose& pose);
  [[nodiscard]] MapSnapshot snapshot() const;
  [[nodiscard]] std::uint64_t point_count() const;

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
  ClearingStats clear_free_space(const DepthImage& image, const SensorPose& pose);
  void split(core::CellId id);
  void merge_children(core::CellId parent);
  [[nodiscard]] MapSnapshot snapshot() const;
  [[nodiscard]] std::uint64_t point_count() const;

 private:
  Map map_;
};

}  // namespace veyra::map
