import type {Json} from '../core.ts';
import {comparisonScope, qualityResourceRows} from './benchmark-report.ts';

export const PUBLIC_POLICY_LABELS: Record<string, string> = {
  uniform5: 'Uniform5', uniform40: 'Uniform40',
  distance_lod: 'DistanceLOD', utility_lod: 'UtilityLOD',
};
export const POLICY_COLORS: Record<string, string> = {
  uniform5: '#64748b', uniform40: '#a76b12', distance_lod: '#0069df', utility_lod: '#188252',
};

function nonNegative(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function fraction(value: unknown): number | null {
  const number = nonNegative(value);
  return number !== null && number <= 1 ? number : null;
}

export function policyQuality(value: Json) {
  const qualities = value.aggregate?.quality;
  const quality = (Array.isArray(qualities) ? qualities.at(-1) : qualities)
    ?? value.runs?.at(-1)?.quality ?? {};
  const surface = quality.high_resolution_surface_comparison ?? {};
  const input = quality.reconstruction?.status === 'available' ? quality.reconstruction : {};
  return {
    heightAccuracy: fraction(surface.height_accuracy_10cm),
    completion: fraction(surface.completion_fraction),
    surfaceChamfer: nonNegative(surface.chamfer_distance_m ?? surface.symmetric_chamfer_m),
    inputAccuracy: nonNegative(input.accuracy?.mean_m),
    inputCompletion: nonNegative(input.completion?.mean_m),
    inputChamfer: nonNegative(input.chamfer_l1_m),
  };
}

export type QualityMetric = 'heightAccuracy' | 'completion' | 'surfaceChamfer' | 'inputAccuracy' | 'inputCompletion' | 'inputChamfer';

const ROW_METRIC = {heightAccuracy: 'heightAccuracy10', completion: 'completion', surfaceChamfer: 'chamferM', inputAccuracy: 'inputAccuracyM', inputCompletion: 'inputCompletionM', inputChamfer: 'inputChamferM'} as const;
const LOWER_IS_BETTER = new Set<QualityMetric>(['surfaceChamfer', 'inputAccuracy', 'inputCompletion', 'inputChamfer']);
export const qualityMetricDirection = (metric: QualityMetric) => LOWER_IS_BETTER.has(metric) ? 'lower' : 'higher';

/**
 * Plot points from the canonical quality/resource rows. Latency uses map-update
 * p95 only when every policy has at least 20 samples (the producer's frontier
 * rule); otherwise p50. Policies missing either coordinate are omitted.
 */
export function qualityPlotPoints(report: Json | null, resource: 'memory' | 'rss' | 'latency' | 'activeCells', metric: QualityMetric) {
  const latencyMetric = comparisonScope(report).latencyMetric;
  return qualityResourceRows(report).flatMap(row => {
    const x = resource === 'memory' ? (row.logicalBytes === null ? null : row.logicalBytes / 1048576)
      : resource === 'rss' ? (row.rssBytes === null ? null : row.rssBytes / 1048576)
        : resource === 'activeCells' ? row.activeCells
          : latencyMetric === 'p95' ? row.mapP95Ms : row.mapP50Ms;
    const y = row[ROW_METRIC[metric]];
    return x === null || y === null ? [] : [{policy: row.policy, x, y}];
  });
}

/**
 * Calculate an unweighted two-axis frontier for any recorded resource. Never
 * call points Pareto-comparable unless the producer marks the run measured
 * and all four public-policy input digests agree.
 */
export function qualityParetoPolicies(report: Json | null, resource: 'memory' | 'rss' | 'latency' | 'activeCells', metric: QualityMetric): string[] {
  const scope = comparisonScope(report);
  if (scope.status !== 'measured' || scope.sameInput !== true) return [];
  const points = qualityPlotPoints(report, resource, metric);
  if (points.length !== 4) return [];
  const lowerQualityIsBetter = LOWER_IS_BETTER.has(metric);
  return points.filter(candidate => !points.some(other => {
    if (other.policy === candidate.policy) return false;
    const noMoreResource = other.x <= candidate.x;
    const noWorseQuality = lowerQualityIsBetter ? other.y <= candidate.y : other.y >= candidate.y;
    const strictlyBetter = other.x < candidate.x || (lowerQualityIsBetter ? other.y < candidate.y : other.y > candidate.y);
    return noMoreResource && noWorseQuality && strictlyBetter;
  })).map(point => point.policy);
}

export function latencyAxisLabel(report: Json | null): string {
  return comparisonScope(report).latencyMetric === 'p95' ? 'Map-update p95 (ms) ↓' : 'Map-update p50 (ms) ↓';
}

/**
 * A zero-based linear axis with round tick steps (1, 2, 2.5 or 5 × 10^k) whose
 * top tick covers `maxValue`. Never returns a fractional-looking step like
 * 405,261.9 cells or 5.47 ms.
 */
export function niceAxis(maxValue: number, intervals = 4): {max: number; ticks: number[]} {
  const target = Number.isFinite(maxValue) && maxValue > 0 ? maxValue : 1;
  const raw = target / intervals;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(factor => factor * magnitude).find(candidate => candidate >= raw * (1 - 1e-9)) ?? 10 * magnitude;
  const count = Math.max(1, Math.ceil(target / step - 1e-9));
  const ticks = Array.from({length: count + 1}, (_, index) => Number((index * step).toPrecision(12)));
  return {max: ticks.at(-1)!, ticks};
}

/** Compact, locale-independent tick text: 1.2M, 400k, 12.5, 0. */
export function formatAxisValue(value: number): string {
  const abs = Math.abs(value);
  const trim = (number: number) => Number(number.toFixed(1)).toString();
  if (abs >= 1e6) return `${trim(value / 1e6)}M`;
  if (abs >= 1e4) return `${trim(value / 1e3)}k`;
  return trim(value);
}

export interface PlacedLabel {policy: string; text: string; x: number; y: number; anchor: 'start' | 'end' | 'middle'}

/**
 * Direct policy labels beside plotted points, greedily moved (right, left,
 * above, below, then further out) so no two labels overlap and none leaves
 * the plot box. Close points (DistanceLOD vs UtilityLOD) stay identifiable
 * without hovering. Approximates 11px UI text at 6.2px per character.
 */
export function placePointLabels(
  points: {policy: string; cx: number; cy: number}[],
  box: {left: number; right: number; top: number; bottom: number},
): PlacedLabel[] {
  const charWidth = 6.2, height = 12, gap = 12;
  const placed: {x0: number; x1: number; y0: number; y1: number}[] = [];
  const markers = points.map(point => ({x0: point.cx - 6, x1: point.cx + 6, y0: point.cy - 6, y1: point.cy + 6}));
  const overlaps = (a: {x0: number; x1: number; y0: number; y1: number}, b: typeof a) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
  return [...points].sort((a, b) => a.cx - b.cx || a.cy - b.cy).map(point => {
    const text = PUBLIC_POLICY_LABELS[point.policy] ?? point.policy;
    const width = text.length * charWidth;
    const candidates: {x: number; y: number; anchor: PlacedLabel['anchor']}[] = [];
    for (const offset of [0, 12, 24, 36]) {
      candidates.push(
        {x: point.cx + gap, y: point.cy + 4 - offset, anchor: 'start'},
        {x: point.cx + gap, y: point.cy + 4 + offset, anchor: 'start'},
        {x: point.cx - gap, y: point.cy + 4 - offset, anchor: 'end'},
        {x: point.cx - gap, y: point.cy + 4 + offset, anchor: 'end'},
        {x: point.cx, y: point.cy - gap - offset, anchor: 'middle'},
        {x: point.cx, y: point.cy + gap + height - 2 + offset, anchor: 'middle'},
      );
    }
    const rect = (candidate: typeof candidates[number]) => {
      const x0 = candidate.anchor === 'start' ? candidate.x : candidate.anchor === 'end' ? candidate.x - width : candidate.x - width / 2;
      return {x0, x1: x0 + width, y0: candidate.y - height + 2, y1: candidate.y + 2};
    };
    const inside = (r: ReturnType<typeof rect>) => r.x0 >= box.left && r.x1 <= box.right && r.y0 >= box.top && r.y1 <= box.bottom;
    const free = (r: ReturnType<typeof rect>) => !placed.some(other => overlaps(r, other)) && !markers.some(marker => overlaps(r, marker));
    const choice = candidates.find(candidate => inside(rect(candidate)) && free(rect(candidate)))
      ?? candidates.find(candidate => inside(rect(candidate)))
      ?? candidates[0];
    placed.push(rect(choice));
    return {policy: point.policy, text, ...choice};
  });
}
