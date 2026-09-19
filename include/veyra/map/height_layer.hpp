#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace veyra::map {

// One elevation accumulator. A cell instantiates three of these -- ground,
// obstacle, overhead -- instead of the single pooled accumulator that averages
// a road surface together with the van roof standing on it.
//
// 32 bytes, zero padding, two layers per 64-byte cache line. The field order
// and types mirror the reasoning already documented on veyra::map::Cell and
// must not be "simplified":
//
// `mean_z` is double because the Welford update adds `delta / count` to it; in
// float that increment is silently swallowed at high counts and the failure
// mode is a plausible-looking wrong mean with no error raised.
//
// `m2_z` stays float: ordinary summation drift, no self-feedback.
//
// `min_z` / `max_z` are comparisons only. They carry the two numbers this
// whole design exists to preserve: the obstacle layer's `min_z` is the base of
// a curb or step, and the overhead layer's `min_z` is the clearance height.
// A pooled mean destroys both.
//
// `count` is uint32_t, not uint16_t: merging 64 leaves into an L3 cell sums
// their counts and 16 bits overflows at a level the system reaches.
//
// `last_seen` is per layer, not per cell. Dynamic updates need to know when
// the obstacle evidence was last confirmed independently of when the ground
// under it was last confirmed -- that separation is what lets a departed
// pedestrian clear without eroding the curb behind them.
//
// It is uint64_t to match CellStats::last_seen exactly. A uint32 frame index
// would be narrower and would leave the same 32-byte footprint, but it would
// force a silent truncation at the one seam where the map's timestamps cross
// into a layer, and a truncated timestamp compares wrong rather than failing.
// Placing it last also consumes what would otherwise be tail padding, so the
// wider type is free: the struct is 32 bytes either way.
struct HeightLayer {
  double mean_z = 0.0;         // 8  Welford running mean
  float m2_z = 0.0F;           // 4  Welford sum of squared deviations
  float min_z = 0.0F;          // 4
  float max_z = 0.0F;          // 4
  std::uint32_t count = 0;     // 4
  std::uint64_t last_seen = 0; // 8  newest evidence in THIS layer, map timestamp

  [[nodiscard]] bool empty() const noexcept { return count == 0; }

  // Fold one elevation into the layer (Welford's incremental algorithm).
  //
  // The second use of `mean_z` below is the UPDATED mean, after the increment
  // on the line above it. Using the pre-update value is the classic Welford
  // bug and yields a subtly wrong m2 that no other assertion catches.
  void add(double z, std::uint64_t observed_at) noexcept {
    if (count == 0) {
      // Seed directly. min_z / max_z must not be left at 0, or a layer whose
      // points all sit above or all below zero would report bounds that
      // include a height it never observed.
      count = 1;
      mean_z = z;
      m2_z = 0.0F;
      min_z = static_cast<float>(z);
      max_z = static_cast<float>(z);
      last_seen = observed_at;
      return;
    }
    count += 1;
    const double delta = z - mean_z;
    mean_z += delta / static_cast<double>(count);
    m2_z = static_cast<float>(static_cast<double>(m2_z) + delta * (z - mean_z));
    min_z = std::min(min_z, static_cast<float>(z));
    max_z = std::max(max_z, static_cast<float>(z));
    last_seen = std::max(last_seen, observed_at);
  }

  // Chan's parallel merge. Computed in double throughout even though m2_z is
  // stored as float -- cast on the way in, truncate on the way out. There are
  // no points to re-accumulate, by design: layers hold sufficient statistics
  // only, exactly as AGENTS.md requires of cells.
  //
  // Merging with an empty layer returns the other operand unchanged and two
  // empties give an empty, so neither path divides by zero. This is also the
  // operation that reconstructs the pooled statistics from the three layers,
  // which is what keeps map invariant 4 intact.
  void merge(const HeightLayer& other) noexcept {
    if (other.count == 0) return;
    if (count == 0) {
      *this = other;
      return;
    }
    const auto na = static_cast<double>(count);
    const auto nb = static_cast<double>(other.count);
    const double n = na + nb;
    const double delta = other.mean_z - mean_z;

    m2_z = static_cast<float>(static_cast<double>(m2_z) + static_cast<double>(other.m2_z) +
                              delta * delta * na * nb / n);
    mean_z += delta * nb / n;
    count += other.count;
    min_z = std::min(min_z, other.min_z);
    max_z = std::max(max_z, other.max_z);
    last_seen = std::max(last_seen, other.last_seen);
  }

  // Population variance (m2 / count): a layer's returns are the whole
  // population observed in that layer, not a sample drawn from a larger one.
  // Returns 0 for count < 2 rather than dividing by zero or returning NaN.
  [[nodiscard]] double variance_z() const noexcept {
    if (count < 2) return 0.0;
    return static_cast<double>(m2_z) / static_cast<double>(count);
  }

  // Standard deviation of the layer. On the ground layer this is the surface
  // roughness signal that traversability is scored against; on the obstacle
  // layer it separates a flat kerb face from a scattered bush.
  [[nodiscard]] double stddev_z() const noexcept { return std::sqrt(variance_z()); }
};

static_assert(sizeof(HeightLayer) == 32);
static_assert(alignof(HeightLayer) == 8);

}  // namespace veyra::map
