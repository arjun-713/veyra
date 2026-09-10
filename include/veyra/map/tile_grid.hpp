#pragma once
#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <unordered_map>

#include "veyra/core/types.hpp"
#include "veyra/map/cell.hpp"
#include "veyra/map/rolling_window.hpp"

// Hash for the tile key. All three fields participate: two tiles at the same
// (tx, ty) but different levels are different tiles, and a hash that ignored
// level would let one silently overwrite the other.
template <>
struct std::hash<veyra::core::TileId> {
  std::size_t operator()(const veyra::core::TileId& t) const noexcept {
    constexpr std::uint64_t kMix = 0x9E3779B97F4A7C15ULL;
    std::uint64_t h = static_cast<std::uint32_t>(t.tx);
    h = (h ^ static_cast<std::uint32_t>(t.ty)) * kMix;
    h = (h ^ static_cast<std::uint64_t>(static_cast<std::uint32_t>(t.level))) * kMix;
    return static_cast<std::size_t>(h ^ (h >> 32));
  }
};

namespace veyra::map {

// 32 x 32 = 1024 cells per tile.
//
// This constant lives in the storage layer, not in core/types.hpp: the other
// two domains compile against core and have no business knowing the tile
// shape. core supplies only the index arithmetic, parameterised by tile_log2.
inline constexpr int kTileLog2 = 5;
inline constexpr std::int32_t kTileSpan = std::int32_t{1} << kTileLog2;
inline constexpr std::size_t kCellsPerTile =
    static_cast<std::size_t>(kTileSpan) * static_cast<std::size_t>(kTileSpan);

struct GridStats {
  std::size_t tiles = 0;
  std::size_t occupied_cells = 0;
  std::size_t allocated_bytes = 0;
  double occupancy = 0.0;  // occupied_cells / (tiles * kCellsPerTile)
};

// Sparse tile storage for one map. Cells live in fixed-size tiles, one
// allocation per tile and never one per cell.
//
// Nothing outside this class sees the tile map, a tile, an iterator or the
// occupancy bitmap; no method returns a container. That is what keeps the
// storage layout replaceable later.
class TileGrid {
 public:
  TileGrid() = default;
  explicit TileGrid(MapWindow window) : window_(window) {}

  const MapWindow& window() const { return window_; }

  Cell* find(core::CellId id);
  const Cell* find(core::CellId id) const;
  Cell& findOrCreate(core::CellId id);
  bool erase(core::CellId id);
  GridStats statistics() const;

  // Visits every occupied cell with its CellId. Skips empty bitmap words
  // rather than scanning all 1024 slots.
  template <class Fn>
  void forEachActiveLeaf(Fn fn) const;

  // Exposed so callers can account for memory without seeing the tile type.
  static constexpr std::size_t bytesPerTile() { return sizeof(Tile); }

 private:
  struct Tile {
    std::array<Cell, kCellsPerTile> cells{};
    std::array<std::uint64_t, kCellsPerTile / 64> occupancy{};
    std::uint32_t live = 0;

    bool test(std::size_t slot) const {
      return ((occupancy[slot >> 6] >> (slot & 63)) & 1ULL) != 0ULL;
    }
    void set(std::size_t slot) { occupancy[slot >> 6] |= (1ULL << (slot & 63)); }
    void clear(std::size_t slot) { occupancy[slot >> 6] &= ~(1ULL << (slot & 63)); }
  };

  // Shift and mask, never divide and modulo: >> floors toward negative
  // infinity where / truncates toward zero, and the two disagree for every
  // cell left of the origin.
  static core::TileId tileOf(core::CellId id) { return core::tileOf(id, kTileLog2); }
  static std::size_t slotOf(core::CellId id) {
    const std::int32_t lx = core::localIndex(id.ix, kTileLog2);
    const std::int32_t ly = core::localIndex(id.iy, kTileLog2);
    return static_cast<std::size_t>(ly) * static_cast<std::size_t>(kTileSpan) +
           static_cast<std::size_t>(lx);
  }

  std::unordered_map<core::TileId, Tile> tiles_;
  MapWindow window_;
};

template <class Fn>
void TileGrid::forEachActiveLeaf(Fn fn) const {
  for (const auto& entry : tiles_) {
    const Tile& tile = entry.second;
    for (std::size_t w = 0; w < tile.occupancy.size(); ++w) {
      std::uint64_t word = tile.occupancy[w];
      while (word != 0ULL) {
        const auto bit = static_cast<std::size_t>(std::countr_zero(word));
        word &= word - 1ULL;
        const std::size_t slot = (w << 6) + bit;
        const auto lx = static_cast<std::int32_t>(slot & static_cast<std::size_t>(kTileSpan - 1));
        const auto ly = static_cast<std::int32_t>(slot >> kTileLog2);
        fn(core::cellFromTile(entry.first, lx, ly, kTileLog2), tile.cells[slot]);
      }
    }
  }
}

}  // namespace veyra::map
