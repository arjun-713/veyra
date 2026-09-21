#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace veyra::map {

// Three-state occupancy, held explicitly.
//
// Veyra previously had no representation of free space at all: a cell either
// held evidence or did not exist, and "does not exist" conflated never-looked
// with looked-and-found-nothing. That conflation is the thing UFOMap was
// written to fix, and it is why a planner cannot safely treat an absent cell
// as traversable.
enum class OccupancyState : std::uint8_t {
  Unknown = 0,   // no decisive evidence either way
  Free = 1,      // positively observed empty -- a beam passed through
  Occupied = 2,  // positively observed as containing a surface
};

// Log-odds occupancy, stored as fixed-point millilog-odds in an int16.
//
// Log-odds is the standard Bayesian occupancy accumulator (OctoMap, UFOMap,
// ROG-Map): each observation adds a constant, so the update is one integer
// add, and probability never saturates to exactly 0 or 1.
//
// The clamps are the part that matters for dynamic scenes, and they are not an
// optimisation -- they are what makes the map able to change its mind. Without
// them, a wall observed 10,000 times accumulates 10,000 units of evidence and
// then needs on the order of 10,000 contradicting observations before it will
// clear. A parked car that leaves would persist for minutes. Clamping bounds
// the evidence in both directions, so the number of observations needed to
// flip a cell is bounded too, regardless of how long it was observed.
//
// This is exactly the mechanism the layered design's "decrement, never delete"
// rule needed and did not have: the K contradictions required to release an
// obstacle fall out of the clamp arithmetic instead of being a tuned constant.
namespace logodds {

// Fixed-point scale: 1 unit = 0.001 log-odds. int16 therefore spans +/-32.7
// log-odds, far beyond the clamps below, so the accumulator cannot overflow.
inline constexpr double kScale = 1000.0;

// p_hit = 0.7  ->  +0.847 log-odds
inline constexpr std::int16_t kHit = 847;
// p_miss = 0.4 ->  -0.405 log-odds
inline constexpr std::int16_t kMiss = -405;
// Clamps: p in [0.12, 0.97].
inline constexpr std::int16_t kClampMin = -1992;
inline constexpr std::int16_t kClampMax = 3476;
// Decision thresholds: occupied above p=0.7, free below p=0.4. The band
// between them is Unknown and is deliberately wide -- a cell with mixed or
// marginal evidence must not be reported as either.
inline constexpr std::int16_t kOccupiedThreshold = 847;
inline constexpr std::int16_t kFreeThreshold = -405;

[[nodiscard]] inline std::int16_t clamp(int value) noexcept {
  return static_cast<std::int16_t>(std::clamp(value, static_cast<int>(kClampMin),
                                              static_cast<int>(kClampMax)));
}

[[nodiscard]] inline std::int16_t hit(std::int16_t current) noexcept {
  return clamp(static_cast<int>(current) + static_cast<int>(kHit));
}

[[nodiscard]] inline std::int16_t miss(std::int16_t current) noexcept {
  return clamp(static_cast<int>(current) + static_cast<int>(kMiss));
}

[[nodiscard]] inline OccupancyState state_of(std::int16_t value) noexcept {
  if (value >= kOccupiedThreshold) return OccupancyState::Occupied;
  if (value <= kFreeThreshold) return OccupancyState::Free;
  return OccupancyState::Unknown;
}

[[nodiscard]] inline double probability_of(std::int16_t value) noexcept {
  const double l = static_cast<double>(value) / kScale;
  return 1.0 - 1.0 / (1.0 + std::exp(l));
}

// Observations needed to drive a fully-saturated cell to the opposite state.
// Exposed because it is the honest answer to "how fast can this map forget?",
// and because a bound that exists only in a comment is a bound nobody checks.
[[nodiscard]] inline int misses_to_clear_from_saturated() noexcept {
  const int span = static_cast<int>(kClampMax) - static_cast<int>(kFreeThreshold);
  return (span + (-kMiss) - 1) / (-kMiss);
}

[[nodiscard]] inline int hits_to_occupy_from_saturated_free() noexcept {
  const int span = static_cast<int>(kOccupiedThreshold) - static_cast<int>(kClampMin);
  return (span + kHit - 1) / kHit;
}

}  // namespace logodds
}  // namespace veyra::map
