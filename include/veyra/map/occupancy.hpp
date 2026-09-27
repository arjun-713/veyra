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
  return static_cast<std::int16_t>(
      std::clamp(value, static_cast<int>(kClampMin), static_cast<int>(kClampMax)));
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
//
// These count APPLIED log-odds steps (observe_free/observe_occupied calls).
// The visibility-clearing path arms first: the first kStrikesToDecrement
// contradictory frames per streak only raise consecutive_misses and leave
// log-odds untouched, so end-to-end contradictory frames through
// Map::clear_free_space are kStrikesToDecrement + misses_to_clear_from_
// saturated() (see frames_to_clear_from_saturated below). Direct observe_*
// callers arm nothing.
[[nodiscard]] inline int misses_to_clear_from_saturated() noexcept {
  const int span = static_cast<int>(kClampMax) - static_cast<int>(kFreeThreshold);
  return (span + (-kMiss) - 1) / (-kMiss);
}

[[nodiscard]] inline int hits_to_occupy_from_saturated_free() noexcept {
  const int span = static_cast<int>(kOccupiedThreshold) - static_cast<int>(kClampMin);
  return (span + kHit - 1) / kHit;
}

// Contradictory visibility frames required before Map::clear_free_space
// applies the first log-odds decrement to a cell.
//
// A single flicker frame (occlusion edge, one bad association) must not erode
// an Occupied cell it cannot re-confirm: the first kStrikesToDecrement frames
// only arm the streak. Past that, exactly one kMiss applies per frame, so a
// genuinely departed object still clears in bounded time and a reacquired cell
// (streak reset by obstacle evidence) recovers immediately. This is a small
// constant, not a TTL: no timestamps, no ageing, no semantics are consulted.
inline constexpr std::uint8_t kStrikesToDecrement = 2;

// End-to-end contradictory frames to drive a saturated cell to Free through
// Map::clear_free_space: arming frames plus applied decrements.
[[nodiscard]] inline int frames_to_clear_from_saturated() noexcept {
  return static_cast<int>(kStrikesToDecrement) + misses_to_clear_from_saturated();
}

// Hits (+kHit each, clamped) needed to return to Occupied from the state left
// by `applied_misses` post-arm observe_free steps starting at the clamp max.
// Used to state the reacquire arithmetic exactly: a cell contradicted `m`
// times needs this many re-hits before it reads Occupied again.
[[nodiscard]] inline int hits_to_recover_from_misses(int applied_misses) noexcept {
  const int after = static_cast<int>(kClampMax) + applied_misses * static_cast<int>(kMiss);
  const int need = static_cast<int>(kOccupiedThreshold) - after;
  if (need <= 0) return 0;
  return (need + static_cast<int>(kHit) - 1) / static_cast<int>(kHit);
}

}  // namespace logodds
}  // namespace veyra::map
