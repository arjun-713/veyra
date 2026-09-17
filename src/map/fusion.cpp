#include "veyra/map/fusion.hpp"

#include <cmath>
#include <limits>

#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"
#include "veyra/map/split_merge.hpp"

namespace veyra::map {
namespace {

// Streaming majority (Boyer-Moore) over the class label, with Cell::confidence
// serving as the agreement counter.
//
// The counter reads naturally as confidence in Cell::cls -- many agreeing
// observations mean a well-supported label -- which is consistent with the
// 0-255 maps to [0,1] meaning cell.hpp documents for the field.
//
// Saturating, never wrapping: 255 is a ceiling, 0 a floor. A wrapping counter
// would make 256 agreeing observations report no confidence at all.
//
// ORDER-DEPENDENT, and honestly so: when no class holds a strict majority of
// the observations in a cell, the surviving label depends on arrival order.
// A class with a true majority survives any order; a plurality may not.
//
// Only cls and confidence are touched here. traversability and motion are
// terrain and temporal concerns, and AGENTS.md separates semantic_class from
// motion_state, so fusion does not write them.
void accumulateClass(Cell& cell, std::uint8_t cls, float confidence) {
  if (!(confidence > 0.0F)) {
    return;  // no semantic evidence; the point still contributes geometry
  }
  if (cell.confidence == 0) {
    cell.cls = cls;
    cell.confidence = 1;
    return;
  }
  if (cell.cls == cls) {
    if (cell.confidence < 255) {
      ++cell.confidence;
    }
    return;
  }
  --cell.confidence;
}

}  // namespace

FusionStats integrate(TileGrid& grid, std::span<const Observation> points,
                      std::uint32_t frame_index) {
  FusionStats stats;
  for (const Observation& o : points) {
    // Finite first, always. Every comparison against NaN is false, so a NaN
    // would slip through the range test below and reach the double-to-int32
    // conversion in worldToKey, which is undefined behaviour.
    if (!std::isfinite(o.x) || !std::isfinite(o.y) || !std::isfinite(o.z)) {
      ++stats.rejected_non_finite;
      continue;
    }
    // Representability guard, not policy: worldToKey converts a double to
    // int32_t and a finite but absurd coordinate would make that conversion
    // undefined. Must precede worldToKey; the window test follows it.
    if (std::fabs(o.x) >= kMaxIndexableM || std::fabs(o.y) >= kMaxIndexableM) {
      ++stats.rejected_out_of_range;
      continue;
    }
    const core::CellId id = core::worldToKey(o.x, o.y, 0);
    // The shared predicate. Acceptance here and eviction in recenter() cannot
    // disagree, because they are the same function on the same argument.
    if (!inWindow(grid.window(), id)) {
      ++stats.rejected_out_of_range;
      continue;
    }
    // Never place a cell beneath an active one. Indexing is done at level 0,
    // but once the resolution pass has coarsened a region the observation
    // belongs to the active leaf already covering it -- creating an L0 cell
    // underneath would violate invariant 2 (parent/child exclusivity) through
    // two functions that are each correct alone.
    core::CellId target = id;
    core::CellId ancestor = id;
    while (ancestor.level < kMaxLevel) {
      ancestor = core::parentOf(ancestor);
      if (grid.find(ancestor) != nullptr) {
        target = ancestor;
        break;
      }
    }

    const bool created = grid.find(target) == nullptr;
    Cell& cell = grid.findOrCreate(target);
    // Read last_seen before stamping it: cells_touched counts cells first
    // seen in this frame, so a second point landing in the same cell in the
    // same frame must not count again.
    const bool first_this_frame = created || cell.last_seen != frame_index;

    updateCell(cell, static_cast<double>(o.z));
    cell.last_seen = frame_index;
    if (o.semantic_class <= std::numeric_limits<std::uint8_t>::max()) {
      accumulateClass(cell, static_cast<std::uint8_t>(o.semantic_class),
                      o.semantic_confidence);
    } else if (o.semantic_confidence > 0.0F) {
      ++stats.semantic_labels_unrepresentable;
    }

    ++stats.accepted;
    stats.cells_created += static_cast<std::size_t>(created);
    stats.cells_touched += static_cast<std::size_t>(first_this_frame);
  }
  return stats;
}

}  // namespace veyra::map
