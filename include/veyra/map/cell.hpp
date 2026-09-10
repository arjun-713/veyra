#pragma once
#include <algorithm>
#include <cstdint>

namespace veyra::map {

// Per-cell sufficient statistics: 32 bytes, zero padding, two cells per
// 64-byte cache line. AGENTS.md forbids raw point history in cells, so this
// struct holds summaries only — never a point list or sample buffer.
//
// The field types and their order are deliberate. Do not reorder them and do
// not "simplify" them:
//
// `mean_z` is a double because the Welford update adds `delta / count` to it.
// As `count` grows that increment shrinks toward the ulp of `mean_z`; in float
// at 30 m the ulp is ~1.9e-6, so updates start being silently swallowed at
// high counts. The failure mode is a plausible-looking wrong mean with no
// error raised. double moves that cliff out of reach.
//
// `m2` stays float: its error is ordinary summation drift, and it does not
// feed back into itself the way the mean does.
//
// `min_z` / `max_z` are comparisons only, so float costs nothing.
//
// `count` is uint32_t, not uint16_t: merging 64 leaves into an L3 cell sums
// their counts, and 16 bits would overflow at a level the system reaches.
//
// Putting the double first makes the struct 8-aligned and leaves the
// remaining fields summing to exactly 24.
struct Cell {
  double mean_z;           // 8   Welford running mean
  float m2;                // 4   Welford sum of squared deviations
  float min_z;             // 4
  float max_z;             // 4
  uint32_t count;          // 4
  uint32_t last_seen;      // 4   frame index, not a wall-clock timestamp
  uint8_t cls;             // 1
  uint8_t confidence;      // 1   0-255 maps to [0,1]
  uint8_t traversability;  // 1
  uint8_t motion;          // 1
};

static_assert(sizeof(Cell) == 32);
static_assert(alignof(Cell) == 8);

// Fold one point into a cell (Welford's incremental algorithm).
//
// The second use of `mean_z` below is the UPDATED mean, after the increment on
// the line above it. Using the pre-update value is the classic Welford bug and
// yields a subtly wrong m2 that no other assertion catches.
//
// Computed in double throughout; m2 is stored back as float.
inline void updateCell(Cell& c, double z) {
  if (c.count == 0) {
    // First point: seed directly. min_z / max_z must not be left at 0, or a
    // cell whose points all sit above or all below zero would report bounds
    // that include a height it never saw.
    c.count = 1;
    c.mean_z = z;
    c.m2 = 0.0F;
    c.min_z = static_cast<float>(z);
    c.max_z = static_cast<float>(z);
    return;
  }
  c.count += 1;
  const double delta = z - c.mean_z;
  c.mean_z += delta / static_cast<double>(c.count);
  c.m2 = static_cast<float>(static_cast<double>(c.m2) + delta * (z - c.mean_z));
  c.min_z = std::min(c.min_z, static_cast<float>(z));
  c.max_z = std::max(c.max_z, static_cast<float>(z));
}

}  // namespace veyra::map
