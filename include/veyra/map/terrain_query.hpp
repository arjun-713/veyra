#pragma once
#include <cstdint>

#include "veyra/map/height_layer.hpp"
#include "veyra/map/occupancy.hpp"

namespace veyra::map {

struct CellStats;

// What the map knows about the ground in one cell.
//
// The distinction this enum exists to make is the one a pooled elevation mean
// cannot express at all: a cell holding only van-roof returns has a confident
// mean at 2.4 m and no way to say that the road underneath was never seen.
// Such a cell is Occluded, and Occluded must never be reported drivable.
enum class GroundState : std::uint8_t {
  // The cell holds no evidence of any kind. Callers reaching this through a
  // live cell should not normally see it; it is the honest answer for a cell
  // that exists but has been fully contradicted.
  Unobserved = 0,
  // Ground returns were accepted here and the surface height is measured.
  Observed = 1,
  // Something was seen in this cell -- obstacle or overhead returns -- but the
  // floor beneath it never was. Unknown, and emphatically not free.
  Occluded = 2,
};

enum class Traversability : std::uint8_t {
  // Not assessable on the evidence held. Unknown is never free: a planner must
  // treat it as it would treat an obstacle until it is observed.
  Unknown = 0,
  Drivable = 1,
  NonDrivable = 2,
};

// Why a cell was refused. Reported alongside the verdict because "unknown" and
// "non-drivable" are operationally different refusals, and because a demo that
// cannot say *why* the map refused a cell is not demonstrating anything.
enum class TerrainReason : std::uint8_t {
  Ok = 0,
  NoGroundEvidence = 1,      // ground layer empty -- occluded or never seen
  InsufficientGround = 2,    // some ground returns, below min_ground_returns
  GroundTooRough = 3,        // ground layer stddev over the platform limit
  ObstaclePresent = 4,       // obstacle layer holds uncontradicted evidence
  InsufficientClearance = 5, // overhead min_z leaves less than vehicle height
  StaleEvidence = 6,         // not re-confirmed inside the persistence horizon
  ClearedByVisibility = 7,   // obstacle evidence positively contradicted
};

// Platform limits. These belong to the vehicle, not to perception, which is
// why they are supplied at query time rather than baked into the cell.
struct VehicleProfile {
  // Returns at or above this height above ground are overhead structure the
  // vehicle passes under, not obstacles it strikes. Separating the obstacle
  // and overhead layers at this height is what lets the map distinguish a
  // branch over clear road from a bollard standing on it.
  double clearance_envelope_m = 2.0;
  // Vertical space the vehicle needs. Checked against the overhead layer.
  double vehicle_height_m = 1.8;
  // Ground roughness the platform tolerates, as a standard deviation.
  double roughness_limit_m = 0.08;
  // An obstacle layer this far above ground or less is surmountable.
  double step_limit_m = 0.12;
  // Ground returns needed before the surface height is trusted.
  std::uint32_t min_ground_returns = 3;
  // Age, in the map's own timestamp units, after which obstacle evidence is
  // no longer confirmed and the cell is reported Unknown.
  //
  // Unknown, never free. A timeout means the vehicle stopped seeing a place,
  // which is indistinguishable from that place being occluded, so it must
  // produce the conservative answer. Clearing a cell to free requires positive
  // evidence of absence -- a beam observed passing through the claimed
  // vertical extent -- which is the visibility work this field does not do.
  std::uint64_t staleness_horizon = 60;

  void validate() const;
};

struct TerrainVerdict {
  GroundState ground_state = GroundState::Unobserved;
  Traversability traversability = Traversability::Unknown;
  TerrainReason reason = TerrainReason::NoGroundEvidence;
  // Set when the querying platform is taller than the envelope the cell's
  // returns were sorted under, so obstacle and overhead cannot be told apart
  // for this vehicle. The verdict is Unknown; it is never guessed.
  bool envelope_mismatch = false;
  // Ground surface height. Only meaningful when ground_state == Observed.
  double ground_height_m = 0.0;
  // Ground roughness (layer standard deviation) at that height.
  double ground_roughness_m = 0.0;
  // Height of the lowest overhead return above the ground surface. Infinite
  // when no overhead structure was observed -- open sky, not zero clearance.
  double clearance_m = 0.0;
  // Height of the obstacle base above the ground surface. Only meaningful
  // when has_obstacle is true.
  double obstacle_height_m = 0.0;
  bool has_obstacle = false;
  bool has_overhead = false;
  OccupancyState occupancy = OccupancyState::Unknown;
  double occupancy_probability = 0.5;
};

// Classifies one cell against one platform at one frame.
//
// Pure: it reads the three layers and the profile and writes nothing. The map
// stores evidence; the vehicle's limits are applied here, at the point of use,
// so two platforms can read one map and disagree about the same cell.
//
// Validates the profile on every call. That is the right trade for a one-off
// query and the wrong one for a sweep over a snapshot, where the profile
// cannot change between cells -- use TerrainClassifier for that.
[[nodiscard]] TerrainVerdict classify(const CellStats& stats, const VehicleProfile& profile,
                                      std::uint64_t current_time);

// Classifies many cells against one platform.
//
// The profile is validated once, in the constructor, instead of once per cell.
// A snapshot sweep over a 100 k-cell map made 100 k redundant validations,
// each running four isfinite checks and five comparisons on values that cannot
// have changed. Holding the profile by value also keeps it in cache next to
// the loop rather than chasing a reference per cell.
//
// Constructing one is the only place a bad profile is rejected, so an invalid
// profile still fails loudly -- it just fails once, before the sweep, which is
// also the more useful moment to hear about it.
class TerrainClassifier {
 public:
  explicit TerrainClassifier(VehicleProfile profile);

  [[nodiscard]] TerrainVerdict classify(const CellStats& stats, std::uint64_t current_time) const;
  [[nodiscard]] const VehicleProfile& profile() const noexcept { return profile_; }

 private:
  VehicleProfile profile_;
};

}  // namespace veyra::map
