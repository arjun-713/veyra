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

export type QualityMetric = 'heightAccuracy' | 'completion' | 'surfaceChamfer';

const ROW_METRIC = {heightAccuracy: 'heightAccuracy10', completion: 'completion', surfaceChamfer: 'chamferM'} as const;

/**
 * Plot points from the canonical quality/resource rows. Latency uses map-update
 * p95 only when every policy has at least 20 samples (the producer's frontier
 * rule); otherwise p50. Policies missing either coordinate are omitted.
 */
export function qualityPlotPoints(report: Json | null, resource: 'memory' | 'latency', metric: QualityMetric) {
  const latencyMetric = comparisonScope(report).latencyMetric;
  return qualityResourceRows(report).flatMap(row => {
    const x = resource === 'memory'
      ? (row.logicalBytes === null ? null : row.logicalBytes / 1048576)
      : latencyMetric === 'p95' ? row.mapP95Ms : row.mapP50Ms;
    const y = row[ROW_METRIC[metric]];
    return x === null || y === null ? [] : [{policy: row.policy, x, y}];
  });
}

export function latencyAxisLabel(report: Json | null): string {
  return comparisonScope(report).latencyMetric === 'p95' ? 'Map-update p95 (ms) ↓' : 'Map-update p50 (ms) ↓';
}
