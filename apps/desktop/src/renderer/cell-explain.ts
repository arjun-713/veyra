// "Why this resolution?" — derived only from measured inputs:
// actual policy, robot-relative range, stored level/size, real evidence.
// Anything missing yields an explicit unavailable message, never a guess.

export interface DistanceBand {
  maxRangeM: number;
  level: number;
  sizeM: number;
  sizeLabel: string;
  story: string;
}

// Half-open bands: range < maxRangeM. Mirrors the DistanceLOD policy
// (0-10 m L0, 10-30 m L1, 30-60 m L2, 60-100 m L3).
export const DISTANCE_BANDS: DistanceBand[] = [
  {maxRangeM: 10, level: 0, sizeM: 0.05, sizeLabel: '5 cm', story: 'protected near-field detail'},
  {maxRangeM: 30, level: 1, sizeM: 0.10, sizeLabel: '10 cm', story: 'near-field representation'},
  {maxRangeM: 60, level: 2, sizeM: 0.20, sizeLabel: '20 cm', story: 'mid/far-field representation'},
  {maxRangeM: 100, level: 3, sizeM: 0.40, sizeLabel: '40 cm', story: 'bounded distant context'},
];

export function expectedBandForRange(rangeM: number): DistanceBand | null {
  if (!Number.isFinite(rangeM) || rangeM < 0) return null;
  for (const band of DISTANCE_BANDS) if (rangeM < band.maxRangeM) return band;
  return null;
}

export function levelFromSize(sizeM: number): number | null {
  if (!Number.isFinite(sizeM) || sizeM <= 0) return null;
  const level = Math.round(Math.log2(sizeM / 0.05));
  return level >= 0 && level <= 3 ? level : null;
}

export function cellRangeM(cellX: number, cellY: number, pose: number[] | null | undefined): number | null {
  if (!Array.isArray(pose) || pose.length !== 16) return null;
  const [x, y] = [cellX, cellY];
  const [px, py] = [pose[3], pose[7]];
  if (![x, y, px, py].every(Number.isFinite)) return null;
  return Math.hypot(x - px, y - py);
}

export interface ResolutionEvidence {
  utility: number | null;
  quality: number | null;
  geometryComplexity: number | null;
  semanticConfidence: number | null;
  semanticClass: number | null;
  motion: number | null;
  drivableEvidence: number | null;
  groundEvidence: number | null;
}

export interface ResolutionExplanationInput {
  policy: string | null;
  rangeM: number | null;
  level: number | null;
  sizeM: number | null;
  evidence: ResolutionEvidence;
  // True only when runtime promotion telemetry genuinely proves a utility
  // promotion happened. Live visualization carries no such proof, so the
  // live UI always passes false and promotion is never claimed.
  promotionProven: boolean;
}

export interface ResolutionExplanation {
  headline: string;
  detail: string;
  signals: string[];
  unavailable: string[];
  verdict: 'policy' | 'promotion' | 'mismatch' | 'unknown';
}

function fmt(n: number, digits = 1): string {
  return Number.isFinite(n) ? n.toFixed(digits) : '—';
}

function evidenceSignals(evidence: ResolutionEvidence): {signals: string[]; unavailable: string[]} {
  const signals: string[] = [];
  const unavailable: string[] = [];
  const push = (label: string, value: number | null, format: (v: number) => string) => {
    if (typeof value === 'number' && Number.isFinite(value)) signals.push(`${label} ${format(value)}`);
    else unavailable.push(label);
  };
  push('utility', evidence.utility, v => v.toFixed(2));
  push('observation quality', evidence.quality, v => v.toFixed(2));
  push('geometry complexity', evidence.geometryComplexity, v => v.toFixed(2));
  push('semantic confidence', evidence.semanticConfidence, v => v.toFixed(2));
  push('motion evidence', evidence.motion, v => v.toFixed(2));
  push('drivable evidence', evidence.drivableEvidence, v => (v > 0 ? `+${v.toFixed(2)} drivable` : v < 0 ? `${v.toFixed(2)} non-drivable` : '0 unknown'));
  push('ground evidence', evidence.groundEvidence, v => (v > 0 ? `+${v.toFixed(2)} supported` : `${v.toFixed(2)}`));
  if (typeof evidence.semanticClass === 'number' && Number.isFinite(evidence.semanticClass)) signals.push(`semantic class ${evidence.semanticClass}`);
  else unavailable.push('semantic class');
  return {signals, unavailable};
}

export function explainResolution(input: ResolutionExplanationInput): ResolutionExplanation {
  const {policy, rangeM, level, sizeM, evidence, promotionProven} = input;
  const {signals, unavailable} = evidenceSignals(evidence);
  if (level === null || sizeM === null) {
    return {headline: 'Resolution unknown', detail: 'This cell carries no usable size or level — nothing is claimed about why it looks this way.', signals, unavailable, verdict: 'unknown'};
  }
  const sizeLabel = `${Math.round(sizeM * 100)} cm`;
  if (rangeM === null) {
    return {headline: `${sizeLabel} — range unknown`, detail: 'Robot pose is unavailable for this frame, so the robot-relative range cannot be measured and no policy reason is claimed.', signals, unavailable, verdict: 'unknown'};
  }
  const band = expectedBandForRange(rangeM);
  const policyName = policy === 'utility_lod' ? 'UtilityLOD' : policy === 'distance_lod' ? 'DistanceLOD' : (policy ?? 'unknown policy');
  if (band === null) {
    return {headline: `${sizeLabel} — outside the mapped range`, detail: `${fmt(rangeM)} m from robot exceeds the 100 m mapping window; cells are not expected here.`, signals, unavailable, verdict: 'mismatch'};
  }
  if (level === band.level) {
    const nearField = rangeM < 10 ? ' Governor never coarsens the safety-protected near-field.' : '';
    return {
      headline: `${band.sizeLabel} — ${band.story}`,
      detail: `${fmt(rangeM)} m from robot · ${policyName} maps this range at ${band.sizeLabel}.${nearField}`,
      signals, unavailable, verdict: 'policy',
    };
  }
  if (level < band.level) {
    const expected = DISTANCE_BANDS[band.level];
    if (promotionProven && policy === 'utility_lod') {
      return {
        headline: `${sizeLabel} — utility-promoted detail`,
        detail: `${fmt(rangeM)} m from robot sits in the ${expected.sizeLabel} distance band, but recorded promotion telemetry proves UtilityLOD refined this cell.`,
        signals, unavailable, verdict: 'promotion',
      };
    }
    return {
      headline: `${sizeLabel} — finer than its distance band`,
      detail: `${fmt(rangeM)} m from robot sits in the ${expected.sizeLabel} band. Promotion telemetry is required to explain the refinement — not claimed from this frame alone.`,
      signals, unavailable, verdict: 'mismatch',
    };
  }
  const expected = DISTANCE_BANDS[band.level];
  return {
    headline: `${sizeLabel} — coarser than its distance band`,
    detail: `${fmt(rangeM)} m from robot sits in the ${expected.sizeLabel} band. Check live splits/merges and governor state; no reason is invented here.`,
    signals, unavailable, verdict: 'mismatch',
  };
}
