#pragma once
#include <cstdint>
#include <limits>

namespace veyra::map {

// One enriched point, already expressed in the stable world/odom frame by
// perception. This is the canonical C++ boundary shared by map fusion,
// runtime protocol ingestion, and direct map clients. The Python
// ObservationFrame contract is serialized into these fields by the runtime;
// no second, reduced Observation definition is allowed in another public
// header.
struct Observation {
  double x = 0.0;  // double to match the index arithmetic in core/types.hpp
  double y = 0.0;
  double z = 0.0;
  std::uint64_t timestamp = 0;
  std::uint16_t semantic_class = 0;
  // Preserve the source dataset/model identifier alongside the unified class.
  std::int32_t raw_semantic_class = 0;
  float semantic_confidence = 0.0F;
  // 0=unknown, 1=drivable, 2=non-drivable.
  std::uint8_t drivable = 0;
  std::uint8_t ground = 0;
  // Height of this return above the local ground surface, metres.
  //
  // Computed by the perception ground stage, which already fits a ground
  // model, and NOT by the map. Deriving it in the map would be circular: a
  // return's layer assignment needs a ground height, and the ground height is
  // the mean of the returns assigned to the ground layer. Perception owns the
  // physics; the map owns the vehicle's limits.
  //
  // Negative means below the fitted ground -- a depression, which is a hazard
  // in its own right and must not be clamped away.
  //
  // The default is NaN, not 0, and that is deliberate. The V2 wire format
  // (19 fields, src/runtime/engine.cpp) does not yet carry this value, so
  // every observation arriving from the live runtime leaves it unset. A 0
  // default would be indistinguishable from a genuine ground-level return and
  // would quietly file the whole scene into the obstacle layer while looking
  // healthy. NaN instead routes those returns to the obstacle layer -- the
  // same fail-safe destination -- and increments CellStats::unmodelled_returns,
  // so the gap shows up as a number in the snapshot instead of as a plausible
  // but wrong map. Producers must set this explicitly to get layer separation.
  float height_above_ground = std::numeric_limits<float>::quiet_NaN();
  float terrain_confidence = 0.0F;
  float geometry_complexity = 0.0F;
  float motion_probability = 0.0F;
  // 0=static, 1=possibly moving, 2=moving, 3=unknown.
  std::uint8_t motion_state = 3;
  float observation_quality = 0.0F;
  // Transient predictive-refinement input; it is not retained in CellStats.
  float velocity_x = 0.0F;
  float velocity_y = 0.0F;
  // Local world-frame ground plane derivatives dz/dx and dz/dy. NaN means
  // the perception fit was unsupported; zero is a measured flat surface.
  float ground_gradient_x = std::numeric_limits<float>::quiet_NaN();
  float ground_gradient_y = std::numeric_limits<float>::quiet_NaN();
};

}  // namespace veyra::map
