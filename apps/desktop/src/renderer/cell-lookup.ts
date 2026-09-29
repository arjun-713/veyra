// Stable cell identity across frames: re-resolve a selected world cell in
// a NEW frame payload by (x, y, size). Leaf order and instance IDs are
// frame-local (splits/merges/eviction reorder them), so instanceId must
// never be carried across frames. Only measured payload data is read.

export interface InspectorCell {
  x: number | null;
  y: number | null;
  elevation: number | null;
  resolution: number | null;
  lod_level: number | null;
  semantic_class: number | null;
  motion: number | null;
  quality: number | null;
  drivable_evidence: number | null;
  utility: number | null;
  semantic_confidence: number | null;
  ground_evidence: number | null;
  terrain_confidence: number | null;
  geometry_complexity: number | null;
  point_count: number | null;
  height_min: number | null;
  height_max: number | null;
  height_variance: number | null;
  [key: string]: number | null | undefined;
}

export interface CellSection {
  count: number;
  offset: number;
  stride: number;
}

function finiteOrNull(value: number): number | null {
  return Number.isFinite(value) ? value : null;
}

// Build the inspector object from one normalized 17-float v3 row — the same
// mapping MapCanvas.pick uses, shared so refresh and click agree exactly.
export function inspectorFromRow(row: ArrayLike<number>): InspectorCell {
  const num = (i: number) => finiteOrNull(row[i]);
  const size = num(3);
  const level = size !== null ? Math.max(0, Math.min(3, Math.round(Math.log2(size / 0.05)))) : null;
  return {
    x: num(0), y: num(1), elevation: num(2), resolution: size, lod_level: level,
    semantic_class: num(4), motion: num(5), quality: num(6), drivable_evidence: num(7),
    utility: num(8), semantic_confidence: num(9), ground_evidence: num(10),
    terrain_confidence: num(11), geometry_complexity: num(12), point_count: num(13),
    height_min: num(14), height_max: num(15), height_variance: num(16),
  };
}

// Locate the cell containing world point (x, y) at the requested size.
// Exact center+size match first; otherwise the smallest containing cell
// (covers LOD ownership changes after splits/merges). Stride 9 (v2) rows
// expose indices 0..8; fields beyond are treated as missing, never zero.
export function findCellInPayload(
  payload: Uint8Array, section: CellSection, x: number, y: number, sizeM: number,
): number | null {
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(sizeM) || sizeM <= 0) return null;
  if (!Number.isInteger(section.count) || section.count < 0) return null;
  const floats = Math.round(section.stride / 4);
  if (floats !== 9 && floats !== 17) return null;
  if (section.offset < 0 || section.offset % 4 !== 0) return null;
  if (section.offset + section.count * section.stride > payload.byteLength) return null;
  const view = new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
  let exact: number | null = null;
  let container: number | null = null;
  let containerSize = Infinity;
  const half = (s: number) => s / 2 + 1e-6;
  for (let i = 0; i < section.count; i++) {
    const base = section.offset + i * section.stride;
    const cx = view.getFloat32(base, true);
    const cy = view.getFloat32(base + 4, true);
    const size = view.getFloat32(base + 12, true);
    if (!Number.isFinite(cx) || !Number.isFinite(cy) || !Number.isFinite(size) || size <= 0) continue;
    if (Math.abs(cx - x) <= half(size) && Math.abs(cy - y) <= half(size)) {
      if (size === sizeM || Math.abs(size - sizeM) <= 1e-9) {
        if (exact === null) exact = i;
      } else if (size < containerSize) {
        container = i;
        containerSize = size;
      }
    }
  }
  return exact ?? container;
}

// Read one row (normalized to 17 floats, NaN-padded like the renderer)
// for the inspector builder.
export function readCellRow(payload: Uint8Array, section: CellSection, index: number): Float32Array | null {
  const floats = Math.round(section.stride / 4);
  if (floats !== 9 && floats !== 17) return null;
  if (!Number.isInteger(index) || index < 0 || index >= section.count) return null;
  const view = new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
  const row = new Float32Array(17).fill(Number.NaN);
  const base = section.offset + index * section.stride;
  for (let j = 0; j < floats; j++) row[j] = view.getFloat32(base + j * 4, true);
  return row;
}
