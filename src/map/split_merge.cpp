#include "veyra/map/split_merge.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>

#include "veyra/map/cell.hpp"

namespace veyra::map {

bool split(TileGrid& grid, core::CellId parent) {
  // Level 0 is the floor. Without this an unguarded level - 1 would create
  // cells at level -1: a key that hashes and compares perfectly well but names
  // a resolution that does not exist.
  if (parent.level <= 0 || parent.level > kMaxLevel) {
    return false;
  }
  const Cell* found = grid.find(parent);
  if (found == nullptr) {
    return false;
  }
  const Cell src = *found;  // copied before the parent is erased

  // A parent holds one mean for its whole square, so which child had which
  // height is not recoverable -- that information was destroyed at fusion
  // time, not here. Copying the parent's estimate into each child invents
  // nothing that contradicts evidence, but the evidence itself must be
  // divided rather than multiplied: four children must not each claim the
  // parent's full observation weight.
  const std::uint32_t base_n = src.count / 4U;
  const std::uint32_t rem_n = src.count % 4U;
  const auto conf = static_cast<std::uint32_t>(src.confidence);
  const std::uint32_t base_c = conf / 4U;
  const std::uint32_t rem_c = conf % 4U;
  const auto total_n = static_cast<double>(src.count);

  grid.erase(parent);
  const std::array<core::CellId, 4> kids = core::childrenOf(parent);
  for (std::uint32_t i = 0; i < 4U; ++i) {
    Cell& c = grid.findOrCreate(kids[i]);
    c = src;  // mean_z, min_z, max_z, last_seen, cls, traversability, motion
    // The remainder is distributed, not dropped: n / 4 loses up to three
    // counts, which breaks conservation at n = 101 while passing at n = 100.
    c.count = base_n + (i < rem_n ? 1U : 0U);
    // Provenance: a split child holds an estimate, so it carries a reduced
    // share of the parent's semantic confidence. Distributed with the same
    // remainder rule so a merge recovers the original exactly.
    c.confidence = static_cast<std::uint8_t>(base_c + (i < rem_c ? 1U : 0U));
    // m2 scales with count, which keeps each child's variance equal to the
    // parent's and leaves a zero-count child with no spread. A uniform
    // quarter would give zero-count children an m2 that the merge then drops,
    // losing it from the total.
    c.m2 = total_n > 0.0 ? static_cast<float>(static_cast<double>(src.m2) *
                                              (static_cast<double>(c.count) / total_n))
                         : 0.0F;
  }
  return true;
}

bool merge(TileGrid& grid, core::CellId parent) {
  if (parent.level <= 0 || parent.level > kMaxLevel) {
    return false;
  }

  const std::array<core::CellId, 4> kids = core::childrenOf(parent);
  std::array<Cell, 4> src{};
  for (std::uint32_t i = 0; i < 4U; ++i) {
    const Cell* c = grid.find(kids[i]);
    if (c == nullptr) {
      return false;
    }
    src[i] = *c;
  }

  // Combined pairwise rather than left to right. All four children share a
  // mean, so Chan's delta is zero and m2 is a plain sum -- but summing four
  // equal floats in a balanced tree is exact where a running total need not
  // be.
  Cell out = mergeCells(mergeCells(src[0], src[1]), mergeCells(src[2], src[3]));

  // mergeCells carries the non-statistical fields from its first operand, so
  // confidence is recombined here. Saturating, never wrapping.
  std::uint32_t conf = 0;
  std::uint32_t last_seen = 0;
  for (const Cell& c : src) {
    conf += static_cast<std::uint32_t>(c.confidence);
    last_seen = std::max(last_seen, c.last_seen);
  }
  out.confidence = static_cast<std::uint8_t>(conf > 255U ? 255U : conf);
  out.last_seen = last_seen;

  for (const core::CellId k : kids) {
    grid.erase(k);
  }
  grid.findOrCreate(parent) = out;
  return true;
}

}  // namespace veyra::map
