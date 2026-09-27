import type {Json} from '../core.ts';

export const PUBLIC_POLICY_LABELS: Record<string, string> = {
  uniform5: 'Uniform5', uniform40: 'Uniform40',
  distance_lod: 'DistanceLOD', utility_lod: 'UtilityLOD',
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

export function qualityPlotPoints(report: Json | null, resource: 'memory' | 'latency', metric: QualityMetric) {
  const policies = (report?.mapping ?? report)?.policies ?? {};
  return Object.keys(PUBLIC_POLICY_LABELS).flatMap(policy => {
    const value = policies[policy];
    if (!value) return [];
    const rawX = resource === 'memory'
      ? value.runs?.at(-1)?.metrics?.memory?.logical_map_bytes ?? value.aggregate?.logical_map_bytes
      : value.aggregate?.stage_latency_ns?.map_update?.p50;
    const x = nonNegative(rawX);
    const y = policyQuality(value)[metric];
    if (x === null || y === null) return [];
    return [{policy, x: x / (resource === 'memory' ? 1048576 : 1000000), y}];
  });
}
