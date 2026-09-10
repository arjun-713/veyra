#pragma once
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

}  // namespace veyra::map
