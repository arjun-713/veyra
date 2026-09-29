// 2.5D cell anatomy model: Ground / Obstacle / Overhead evidence plus pooled
// height statistics. Built only from measured frame data; empty or absent
// layers are explicit, never rendered as geometry.

export interface LayerAnatomy {
  name: 'ground' | 'obstacle' | 'overhead';
  state: 'present' | 'empty';
  count: number | null;
  mean: number | null;
  min: number | null;
  max: number | null;
}

export interface AnatomyPooled {
  mean: number | null;
  zmin: number | null;
  zmax: number | null;
  variance: number | null;
  count: number | null;
}

export interface CellAnatomy {
  available: boolean;
  layers: LayerAnatomy[];
  pooled: AnatomyPooled;
  resolution: string | null;
  lod: number | null;
  // Obstacle/overhead evidence with no ground support means the ground is
  // occluded: unknown, never drivable, never free.
  occluded: boolean;
  notes: string[];
}

export interface AnatomyInput {
  physicalLayers: {
    ground?: {count: number | null; mean: number | null; min: number | null; max: number | null};
    obstacle?: {count: number | null; mean: number | null; min: number | null; max: number | null};
    overhead?: {count: number | null; mean: number | null; min: number | null; max: number | null};
  } | null;
  pooled: {mean: number | null; zmin: number | null; zmax: number | null; variance: number | null; count: number | null};
  resolution: string | null;
  lod: number | null;
}

function layer(name: LayerAnatomy['name'], raw: AnatomyInput['physicalLayers']): LayerAnatomy {
  const entry = raw?.[name];
  const count = entry?.count;
  if (typeof count !== 'number' || !Number.isFinite(count) || count <= 0) {
    return {name, state: 'empty', count: null, mean: null, min: null, max: null};
  }
  const finite = (v: number | null | undefined) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  return {name, state: 'present', count, mean: finite(entry?.mean), min: finite(entry?.min), max: finite(entry?.max)};
}

export function cellAnatomy(input: AnatomyInput): CellAnatomy {
  const notes: string[] = [];
  if (!input.physicalLayers) {
    return {
      available: false,
      layers: (['ground', 'obstacle', 'overhead'] as const).map(name => ({name, state: 'empty' as const, count: null, mean: null, min: null, max: null})),
      pooled: input.pooled,
      resolution: input.resolution,
      lod: input.lod,
      occluded: false,
      notes: ['This frame carries no physical-layer section (older schema) — vertical anatomy is unavailable, not empty.'],
    };
  }
  const layers = (['ground', 'obstacle', 'overhead'] as const).map(name => layer(name, input.physicalLayers));
  const [ground, obstacle, overhead] = layers;
  const occluded = ground.state === 'empty' && (obstacle.state === 'present' || overhead.state === 'present');
  if (occluded) notes.push('Ground is occluded here: unknown, never drivable, never marked free without visibility evidence.');
  if (layers.every(l => l.state === 'empty')) notes.push('No layer holds evidence — absence of evidence clears nothing.');
  notes.push('Pooled elevation is a summary, not a surface.');
  return {available: true, layers, pooled: input.pooled, resolution: input.resolution, lod: input.lod, occluded, notes};
}

// Vertical scale for the mini cross-section: min/max over every measured
// height, pooled bounds included. Null when nothing measurable exists.
export function anatomyRange(model: CellAnatomy): {lo: number; hi: number} | null {
  const values: number[] = [];
  for (const l of model.layers) {
    if (l.state !== 'present') continue;
    for (const v of [l.min, l.max, l.mean]) if (typeof v === 'number') values.push(v);
  }
  for (const v of [model.pooled.zmin, model.pooled.zmax, model.pooled.mean]) if (typeof v === 'number') values.push(v);
  if (!values.length) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  return hi > lo ? {lo, hi} : {lo: lo - 0.5, hi: hi + 0.5};
}
