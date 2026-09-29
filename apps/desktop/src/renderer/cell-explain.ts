// "Why this resolution?" — derived only from measured inputs: the mapper's
// own policy descriptor for this frame, robot-relative range, stored
// level/size, and real evidence. Anything missing yields an explicit
// unavailable message, never a guess and never silent defaults.

export interface PolicyLevel {
  level: number;
  resolution_m: number;
}

export interface PolicyBand {
  max_range_m: number;
  level: number;
}

export interface PolicyDescriptor {
  available: boolean;
  name: string | null;
  levels: PolicyLevel[];
  bands: PolicyBand[];
  // Null when the mapper reports no governor config (e.g. DistanceLOD):
  // protection claims require a reported radius, never an assumed one.
  protected_radius_m: number | null;
  map_radius_m: number | null;
}

export interface ResolutionEvidence {
  utility: number | null;
  quality: number | null;
  geometryComplexity: number | null;
  semanticConfidence: number | null;
  semanticClass: number | null;
  // Human-readable taxonomy name resolved by the caller (single taxonomy
  // source in dashboard.ts); null renders as unavailable, never a bare ID.
  semanticLabel: string | null;
  motion: number | null;
  drivableEvidence: number | null;
  groundEvidence: number | null;
}

export interface DecisionAttribution {
  // True only when mapper/policy execution genuinely proves what refined or
  // coarsened this cell (base/requested/actual + reason flags on the wire).
  // Live visualization carries no such proof, so callers pass
  // {available:false} and promotion is never claimed.
  available: boolean;
}

export interface ResolutionExplanationInput {
  descriptor: PolicyDescriptor;
  // Backend-reported policy name (status/header) used only to label uniform
  // policies, which need no bands. Distance/utility reasoning always uses
  // the descriptor; without it the answer is "unavailable".
  policyName: string | null;
  rangeM: number | null;
  level: number | null;
  sizeM: number | null;
  evidence: ResolutionEvidence;
  attribution: DecisionAttribution;
}

export interface ResolutionExplanation {
  headline: string;
  detail: string;
  signals: string[];
  unavailable: string[];
  verdict: 'policy' | 'promotion' | 'mismatch' | 'unknown';
}

const KNOWN_POLICIES = ['uniform5', 'uniform40', 'distance_lod', 'utility_lod'] as const;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

// Parse the mapper-reported descriptor. Anything malformed or absent yields
// available:false — the UI then says "Policy configuration unavailable".
export function parsePolicyDescriptor(raw: unknown): PolicyDescriptor {
  const empty: PolicyDescriptor = {available: false, name: null, levels: [], bands: [], protected_radius_m: null, map_radius_m: null};
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return empty;
  const record = raw as Record<string, unknown>;
  const name = typeof record.name === 'string' && (KNOWN_POLICIES as readonly string[]).includes(record.name) ? record.name : null;
  if (name === null) return empty;
  const levels: PolicyLevel[] = [];
  if (Array.isArray(record.levels)) {
    for (const entry of record.levels) {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue;
      const {level, resolution_m} = entry as Record<string, unknown>;
      if (Number.isInteger(level) && isFiniteNumber(resolution_m) && (resolution_m as number) > 0) {
        levels.push({level: level as number, resolution_m: resolution_m as number});
      }
    }
  }
  const boundaries = Array.isArray(record.distance_boundaries_m)
    ? (record.distance_boundaries_m as unknown[]).filter(isFiniteNumber)
    : [];
  const mapRadius = isFiniteNumber(record.window_radius_m) ? (record.window_radius_m as number) : null;
  const bands: PolicyBand[] = [];
  if (boundaries.length === 3 && mapRadius !== null && boundaries[0] < boundaries[1] && boundaries[1] < boundaries[2] && boundaries[2] < mapRadius) {
    bands.push({max_range_m: boundaries[0], level: 0}, {max_range_m: boundaries[1], level: 1}, {max_range_m: boundaries[2], level: 2}, {max_range_m: mapRadius, level: 3});
  }
  const protectedRadius = isFiniteNumber(record.near_field_radius_m) ? (record.near_field_radius_m as number) : null;
  if (!bands.length) return {...empty, name};
  return {available: true, name, levels, bands, protected_radius_m: protectedRadius, map_radius_m: mapRadius};
}

// Human band labels ("0–10 m") derived from a parsed descriptor, or null
// when no descriptor is available — never hardcoded fallbacks.
export function bandLabels(descriptor: PolicyDescriptor): string[] | null {
  if (!descriptor.available || !descriptor.bands.length) return null;
  const labels: string[] = [];
  let lo = 0;
  for (const band of descriptor.bands) {
    labels.push(`${trimNum(lo)}–${trimNum(band.max_range_m)} m`);
    lo = band.max_range_m;
  }
  return labels;
}

function trimNum(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 10) / 10);
}

export function expectedBandForRange(descriptor: PolicyDescriptor, rangeM: number): PolicyBand | null {
  if (!descriptor.available || !isFiniteNumber(rangeM) || rangeM < 0) return null;
  for (const band of descriptor.bands) if (rangeM < band.max_range_m) return band;
  return null;
}

export function levelFromSize(sizeM: number): number | null {
  if (!isFiniteNumber(sizeM) || (sizeM as number) <= 0) return null;
  const level = Math.round(Math.log2((sizeM as number) / 0.05));
  return level >= 0 && level <= 3 ? level : null;
}

export function resolutionLabelForLevel(descriptor: PolicyDescriptor, level: number): string {
  const entry = descriptor.levels.find(l => l.level === level);
  const meters = entry ? entry.resolution_m : 0.05 * 2 ** level;
  return meters < 1 ? `${Math.round(meters * 100)} cm` : `${meters} m`;
}

export function cellRangeM(cellX: number, cellY: number, pose: number[] | null | undefined): number | null {
  if (!Array.isArray(pose) || pose.length !== 16) return null;
  const [x, y] = [cellX, cellY];
  const [px, py] = [pose[3], pose[7]];
  if (![x, y, px, py].every(isFiniteNumber)) return null;
  return Math.hypot((x as number) - (px as number), (y as number) - (py as number));
}

function fmt(n: number, digits = 1): string {
  return Number.isFinite(n) ? n.toFixed(digits) : '—';
}

function evidenceSignals(evidence: ResolutionEvidence): {signals: string[]; unavailable: string[]} {
  const signals: string[] = [];
  const unavailable: string[] = [];
  const push = (label: string, value: number | null, format: (v: number) => string) => {
    if (isFiniteNumber(value)) signals.push(`${label} ${format(value as number)}`);
    else unavailable.push(label);
  };
  push('utility', evidence.utility, v => v.toFixed(2));
  push('observation quality', evidence.quality, v => v.toFixed(2));
  push('geometry complexity', evidence.geometryComplexity, v => v.toFixed(2));
  push('semantic confidence', evidence.semanticConfidence, v => v.toFixed(2));
  push('motion evidence', evidence.motion, v => v.toFixed(2));
  push('drivable evidence', evidence.drivableEvidence, v => (v > 0 ? `+${v.toFixed(2)} drivable` : v < 0 ? `${v.toFixed(2)} non-drivable` : '0 unknown'));
  push('ground evidence', evidence.groundEvidence, v => (v > 0 ? `+${v.toFixed(2)} supported` : `${v.toFixed(2)}`));
  if (typeof evidence.semanticLabel === 'string' && evidence.semanticLabel) {
    signals.push(typeof evidence.semanticClass === 'number' ? `${evidence.semanticLabel} · ID ${evidence.semanticClass}` : evidence.semanticLabel);
  } else unavailable.push('semantic class');
  return {signals, unavailable};
}

const BAND_STORIES = ['protected near-field detail', 'near-field representation', 'mid/far-field representation', 'bounded distant context'] as const;

function uniformExplanation(policyName: string, expectedLevel: number, sizeLabel: string, level: number | null): ResolutionExplanation {
  const coarse = expectedLevel === 3;
  if (level === expectedLevel) {
    return {
      headline: `${sizeLabel} — uniform ${coarse ? 'coarse' : 'high-resolution'} policy`,
      detail: `${policyName === 'uniform5' ? 'Uniform5' : 'Uniform40'} maps every active region at ${sizeLabel}. Distance from robot does not determine this cell's level.`,
      signals: [], unavailable: [], verdict: 'policy',
    };
  }
  return {
    headline: `${sizeLabel} — unexpected under a uniform policy`,
    detail: `${policyName === 'uniform5' ? 'Uniform5' : 'Uniform40'} holds every active region at ${expectedLevel === 0 ? '5 cm' : '40 cm'}, but this cell stores level ${level}. Map/config disagreement — check the active policy and rebuild state; no reason is invented.`,
    signals: [], unavailable: [], verdict: 'mismatch',
  };
}

export function explainResolution(input: ResolutionExplanationInput): ResolutionExplanation {
  const {descriptor, policyName, rangeM, level, sizeM, evidence, attribution} = input;
  const {signals, unavailable} = evidenceSignals(evidence);
  const withEvidence = (explanation: Omit<ResolutionExplanation, 'signals' | 'unavailable'>): ResolutionExplanation => ({...explanation, signals, unavailable});
  if (level === null || sizeM === null) {
    return withEvidence({headline: 'Resolution unknown', detail: 'This cell carries no usable size or level — nothing is claimed about why it looks this way.', verdict: 'unknown'});
  }
  const sizeLabel = `${Math.round((sizeM as number) * 100)} cm`;
  // Uniform policies need only the backend-reported name: distance plays no
  // role, so no bands are mentioned at all.
  if (policyName === 'uniform5' || (descriptor.available && descriptor.name === 'uniform5')) {
    return withEvidence(uniformExplanation('uniform5', 0, sizeLabel, level));
  }
  if (policyName === 'uniform40' || (descriptor.available && descriptor.name === 'uniform40')) {
    return withEvidence(uniformExplanation('uniform40', 3, sizeLabel, level));
  }
  if (rangeM === null) {
    return withEvidence({headline: `${sizeLabel} — range unknown`, detail: 'Robot pose is unavailable for this frame, so the robot-relative range cannot be measured and no policy reason is claimed.', verdict: 'unknown'});
  }
  if (!descriptor.available) {
    return withEvidence({headline: `${sizeLabel} — policy configuration unavailable`, detail: 'This frame carries no mapper policy descriptor (older schema), so distance bands are unknown and nothing is assumed. Measured evidence below still holds.', verdict: 'unknown'});
  }
  const policyLabel = descriptor.name === 'utility_lod' ? 'UtilityLOD' : descriptor.name === 'distance_lod' ? 'DistanceLOD' : (descriptor.name ?? 'unknown policy');
  if (descriptor.map_radius_m !== null && (rangeM as number) >= (descriptor.map_radius_m as number)) {
    return withEvidence({headline: `${sizeLabel} — outside the mapped range`, detail: `${fmt(rangeM as number)} m from robot reaches the ${fmt(descriptor.map_radius_m)} m mapping window edge; cells are not expected beyond it.`, verdict: 'mismatch'});
  }
  const band = expectedBandForRange(descriptor, rangeM as number);
  if (band === null) {
    return withEvidence({headline: `${sizeLabel} — range outside configured bands`, detail: `${fmt(rangeM as number)} m from robot matches no configured distance band.`, verdict: 'mismatch'});
  }
  const expectedLabel = resolutionLabelForLevel(descriptor, band.level);
  if (level === band.level) {
    const protection = descriptor.protected_radius_m !== null && (rangeM as number) < (descriptor.protected_radius_m as number)
      ? ' The reported near-field radius protects this range from coarsening.'
      : '';
    const utilityNote = descriptor.name === 'utility_lod'
      ? ' UtilityLOD is active; no promotion is proven for this cell — it sits at the distance reference level.'
      : '';
    return withEvidence({
      headline: `${expectedLabel} — ${BAND_STORIES[band.level] ?? 'configured band'}`,
      detail: `${fmt(rangeM as number)} m from robot · ${policyLabel} maps this range at ${expectedLabel}.${protection}${utilityNote}`,
      verdict: 'policy',
    });
  }
  if ((level as number) < band.level) {
    if (attribution.available && descriptor.name === 'utility_lod') {
      return withEvidence({
        headline: `${sizeLabel} — utility-refined detail`,
        detail: `${fmt(rangeM as number)} m from robot sits in the ${expectedLabel} distance band; recorded decision attribution proves UtilityLOD refined this cell to ${sizeLabel}.`,
        verdict: 'promotion',
      });
    }
    const base = descriptor.name === 'utility_lod' ? ` Its distance reference is ${expectedLabel} (base level ${band.level}).` : '';
    return withEvidence({
      headline: `${sizeLabel} — finer than its distance band`,
      detail: `${fmt(rangeM as number)} m from robot sits in the ${expectedLabel} band.${base} Utility decision attribution unavailable for this frame — the refinement is not claimed from the utility score alone.`,
      verdict: 'mismatch',
    });
  }
  return withEvidence({
    headline: `${sizeLabel} — coarser than its distance band`,
    detail: `${fmt(rangeM as number)} m from robot sits in the ${expectedLabel} band. Check live splits/merges and governor state; no reason is invented here.`,
    verdict: 'mismatch',
  });
}
