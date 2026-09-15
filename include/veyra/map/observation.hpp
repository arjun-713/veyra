#pragma once
#include <cstdint>

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
  float terrain_confidence = 0.0F;
  float geometry_complexity = 0.0F;
  float motion_probability = 0.0F;
  // 0=static, 1=possibly moving, 2=moving, 3=unknown.
  std::uint8_t motion_state = 3;
  float observation_quality = 0.0F;
  // Transient predictive-refinement input; it is not retained in CellStats.
  float velocity_x = 0.0F;
  float velocity_y = 0.0F;
};

}  // namespace veyra::map
