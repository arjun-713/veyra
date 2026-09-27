// Canonical desktop consumer of the schema-v2 benchmark report written by
// benchmarks/run_benchmark.py (contract: docs/benchmark-contract.md).
// Every reader of benchmark evidence goes through this module so the live
// run, an opened file and an export all interpret the same fields.
// Missing measurements stay null; a measured zero stays zero.
import type {Json} from '../core.ts';

export const REPORT_SCHEMA_VERSION = 2;
export const QUALITY_RESOURCE_SCHEMA_VERSION = 1;
export const PUBLIC_POLICIES = ['uniform5', 'uniform40', 'distance_lod', 'utility_lod'] as const;
export type PublicPolicy = typeof PUBLIC_POLICIES[number];
export type ReportOrigin = 'generated' | 'loaded';

export interface AcceptedReport {
  report: Json;
  origin: ReportOrigin;
  complete: boolean;
  issues: string[];
  migratedFrom: string | null;
}

const isObject = (value: unknown): value is Json =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

export function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function nonNegative(value: unknown): number | null {
  const number = finite(value);
  return number !== null && number >= 0 ? number : null;
}

export function fraction(value: unknown): number | null {
  const number = nonNegative(value);
  return number !== null && number <= 1 ? number : null;
}

const text = (value: unknown): string | null => typeof value === 'string' && value.length > 0 ? value : null;
const bool = (value: unknown): boolean | null => typeof value === 'boolean' ? value : null;

/**
 * Validate a report before it reaches any view. Throws for input that is not
 * a schema-v2 report; records non-fatal gaps (missing provenance, summary-only
 * policies) in `issues` so views can flag incomplete evidence.
 */
export function acceptBenchmarkReport(value: unknown, origin: ReportOrigin): AcceptedReport {
  if (!isObject(value)) throw new Error('Benchmark report must be a JSON object.');
  let report = value;
  let migratedFrom: string | null = null;
  // Narrow legacy migration: early desktop exports nested the report under `mapping`.
  if (!isObject(report.policies) && isObject(report.mapping) && isObject(report.mapping.policies)) {
    report = {...report.mapping, ...Object.fromEntries(Object.entries(report).filter(([key]) => key !== 'mapping'))};
    migratedFrom = 'mapping-wrapper';
  }
  if (report.schema_version !== REPORT_SCHEMA_VERSION) {
    throw new Error(`Unsupported benchmark report schema ${JSON.stringify(report.schema_version ?? null)}; this desktop reads schema ${REPORT_SCHEMA_VERSION}.`);
  }
  if (!isObject(report.policies)) throw new Error('Benchmark report has no policies object.');
  const issues: string[] = [];
  if (migratedFrom) issues.push('Legacy desktop export: migrated from the nested "mapping" layout.');
  if (!isObject(report.provenance)) issues.push('Provenance is missing: commit, host and input identity are unavailable.');
  const summaryOnly = Object.entries(report.policies)
    .filter(([, policy]) => !isObject(policy) || !Array.isArray(policy.runs) || policy.runs.length === 0)
    .map(([name]) => name);
  if (summaryOnly.length) issues.push(`No raw repetitions for ${summaryOnly.join(', ')}: summary values only.`);
  if (!isObject(report.quality_resource)) issues.push('No quality_resource table: values are derived from per-policy aggregates.');
  else if (report.quality_resource.schema_version !== QUALITY_RESOURCE_SCHEMA_VERSION) {
    issues.push(`Unknown quality_resource schema ${JSON.stringify(report.quality_resource.schema_version)}; derived values are used.`);
  }
  const complete = isObject(report.provenance) && summaryOnly.length === 0;
  return {report, origin, complete, issues, migratedFrom};
}

export interface ReportProvenance {
  gitSha: string | null;
  workingTreeDirty: boolean | null;
  sourceStateSha256: string | null;
  timestampUtc: string | null;
  buildType: string | null;
  compiler: string | null;
  processor: string | null;
  os: string | null;
  machine: string | null;
  memoryBytes: number | null;
  perceptionExecuted: boolean | null;
  modelCheckpointSha256: string | null;
  selectionDigest: string | null;
  configDigest: string | null;
  frameStart: number | null;
  frameCount: number | null;
  repetitions: number | null;
  warmupFrames: number | null;
  latencySamples: number | null;
  p95Reliable: boolean | null;
  p99Reliable: boolean | null;
}

export function reportProvenance(report: Json | null): ReportProvenance {
  const provenance = isObject(report?.provenance) ? report!.provenance : {};
  const hardware = isObject(provenance.hardware) ? provenance.hardware : {};
  const range = isObject(provenance.frame_range) ? provenance.frame_range : {};
  const samples = isObject(provenance.sample_adequacy?.stage_latency_samples_per_policy)
    ? provenance.sample_adequacy.stage_latency_samples_per_policy : {};
  return {
    gitSha: text(provenance.git_sha),
    workingTreeDirty: bool(provenance.working_tree_dirty),
    sourceStateSha256: text(provenance.source_state_sha256),
    timestampUtc: text(provenance.timestamp_utc),
    buildType: text(provenance.build_type),
    compiler: text(provenance.compiler),
    processor: text(hardware.processor),
    os: text(hardware.os),
    machine: text(hardware.machine),
    memoryBytes: nonNegative(hardware.physical_memory_bytes),
    perceptionExecuted: bool(provenance.perception_executed),
    modelCheckpointSha256: text(provenance.model_checkpoint_sha256),
    selectionDigest: text(provenance.selection_digest),
    configDigest: text(provenance.config_digest),
    frameStart: nonNegative(range.start),
    frameCount: nonNegative(range.count ?? report?.input_frames),
    repetitions: nonNegative(provenance.repetitions),
    warmupFrames: nonNegative(provenance.warmup_frames),
    latencySamples: nonNegative(samples.samples),
    p95Reliable: bool(samples.p95_reliable),
    p99Reliable: bool(samples.p99_reliable),
  };
}

export interface SemanticBin {minM: number | null; maxM: number | null; miou: number | null; accuracy: number | null; points: number | null}
export interface SemanticQuality {
  status: 'measured' | 'unavailable';
  reason: string | null;
  miou: number | null;
  accuracy: number | null;
  points: number | null;
  reference: string | null;
  /** perception.status.semantic: `ground_truth` means labels bypassed the model. */
  source: string | null;
  groundTruth: boolean;
  bins: SemanticBin[];
}

/** mIoU and accuracy are fractions in [0, 1]; format them with `percent`. */
export function semanticQuality(report: Json | null): SemanticQuality {
  const quality = isObject(report?.semantic_quality) ? report!.semantic_quality : {};
  const source = text(report?.perception?.status?.semantic);
  const groundTruth = source === 'ground_truth';
  if (quality.status !== 'measured' || !isObject(quality.overall)) {
    return {status: 'unavailable', reason: text(quality.reason) ?? 'semantic evaluation was not recorded in this report', miou: null, accuracy: null, points: null, reference: null, source, groundTruth, bins: []};
  }
  const bins = Array.isArray(quality.range_bins) ? quality.range_bins.filter(isObject).map(bin => ({
    minM: finite(bin.min_m), maxM: finite(bin.max_m), miou: fraction(bin.miou), accuracy: fraction(bin.accuracy), points: nonNegative(bin.points),
  })) : [];
  return {
    status: 'measured', reason: null,
    miou: fraction(quality.overall.miou), accuracy: fraction(quality.overall.accuracy), points: nonNegative(quality.overall.points),
    reference: text(quality.reference), source, groundTruth, bins,
  };
}

export type EvidenceKind = 'measured' | 'analytical' | 'unavailable';
export interface ReferenceBaseline {key: string; label: string; kind: EvidenceKind; detail: string; bytes: number | null; cells: number | null}

/**
 * Reference representations beside the four policies. The dense 3D grid is an
 * analytical estimate (never allocated or timed); a measured sparse 3D leg is
 * only shown when the report actually contains one.
 */
export function referenceBaselines(report: Json | null): ReferenceBaseline[] {
  const baselines = isObject(report?.reference_baselines) ? report!.reference_baselines : {};
  const dense = isObject(baselines.uniform_5cm_3d) ? baselines.uniform_5cm_3d : null;
  const fine = isObject(baselines.uniform_5cm_2d) ? baselines.uniform_5cm_2d : null;
  const measured3d = Object.entries(isObject(report?.policies) ? report!.policies : {})
    .find(([, policy]) => isObject(policy) && policy.adapter?.suite === 'reference');
  const rows: ReferenceBaseline[] = [];
  rows.push(dense && dense.status === 'analytical_only'
    ? {key: 'uniform_5cm_3d', label: 'Dense 5 cm 3D grid', kind: 'analytical', detail: text(dense.warning) ?? 'memory estimate only; not allocated or timed', bytes: nonNegative(dense.estimated_dense_bytes), cells: nonNegative(dense.dense_voxel_count)}
    : {key: 'uniform_5cm_3d', label: 'Dense 5 cm 3D grid', kind: 'unavailable', detail: 'not recorded in this report', bytes: null, cells: null});
  if (measured3d) {
    const [key, policy] = measured3d;
    const run = Array.isArray(policy.runs) ? policy.runs.at(-1) : null;
    rows.push({key, label: 'Measured sparse 3D baseline', kind: 'measured', detail: 'executed on the same selection', bytes: nonNegative(run?.metrics?.memory?.logical_map_bytes ?? policy.aggregate?.logical_map_bytes), cells: null});
  } else {
    rows.push({key: 'measured_3d', label: 'Measured sparse 3D baseline', kind: 'unavailable', detail: 'not executed by this benchmark run', bytes: null, cells: null});
  }
  if (fine?.status === 'executed_as_fine_reference') {
    rows.push({key: 'uniform_5cm_2d', label: 'Uniform5 quality reference', kind: 'measured', detail: 'observed 5 cm support from the identical stream; not surveyed ground truth', bytes: null, cells: nonNegative(fine.reference_bins)});
  }
  return rows;
}

export interface QualityResourceRow {
  policy: PublicPolicy;
  status: string;
  source: 'quality_resource' | 'derived' | 'absent';
  logicalBytes: number | null;
  allocatedBytes: number | null;
  rssBytes: number | null;
  activeCells: number | null;
  mapP50Ms: number | null;
  mapP95Ms: number | null;
  mapP99Ms: number | null;
  mapSamples: number | null;
  p95Reliable: boolean;
  p99Reliable: boolean;
  runtimeMs: number | null;
  fpsP50: number | null;
  heightAccuracy05: number | null;
  heightAccuracy10: number | null;
  heightAccuracy20: number | null;
  completion: number | null;
  chamferM: number | null;
  rmseM: number | null;
  semanticRetention: number | null;
  vehicleRetention: number | null;
  pedestrianRetention: number | null;
  poleRetention: number | null;
  inputAccuracyM: number | null;
  inputCompletionM: number | null;
  inputChamferM: number | null;
}

const MIN_P95 = 20, MIN_P99 = 100;
const nsToMs = (value: unknown) => {const number = nonNegative(value); return number === null ? null : number / 1e6;};

function lastQuality(policy: Json): Json {
  const qualities = policy.aggregate?.quality;
  const quality = (Array.isArray(qualities) ? qualities.at(-1) : qualities) ?? policy.runs?.at(-1)?.quality;
  return isObject(quality) ? quality : {};
}

function inputReconstruction(policy: Json) {
  const reconstruction = lastQuality(policy).reconstruction;
  const input = isObject(reconstruction) && reconstruction.status === 'available' ? reconstruction : {};
  return {inputAccuracyM: nonNegative(input.accuracy?.mean_m), inputCompletionM: nonNegative(input.completion?.mean_m), inputChamferM: nonNegative(input.chamfer_l1_m)};
}

function emptyRow(policy: PublicPolicy): QualityResourceRow {
  return {policy, status: 'unavailable', source: 'absent', logicalBytes: null, allocatedBytes: null, rssBytes: null, activeCells: null, mapP50Ms: null, mapP95Ms: null, mapP99Ms: null, mapSamples: null, p95Reliable: false, p99Reliable: false, runtimeMs: null, fpsP50: null, heightAccuracy05: null, heightAccuracy10: null, heightAccuracy20: null, completion: null, chamferM: null, rmseM: null, semanticRetention: null, vehicleRetention: null, pedestrianRetention: null, poleRetention: null, inputAccuracyM: null, inputCompletionM: null, inputChamferM: null};
}

function fromQualityResource(policy: PublicPolicy, row: Json, raw: Json | null): QualityResourceRow {
  const samples = nonNegative(row.map_update_sample_count);
  return {
    ...emptyRow(policy), status: text(row.status) ?? 'unavailable', source: 'quality_resource',
    logicalBytes: nonNegative(row.logical_map_bytes), allocatedBytes: nonNegative(row.allocated_map_bytes), rssBytes: nonNegative(row.rss_bytes),
    activeCells: nonNegative(row.active_cells), mapP50Ms: nonNegative(row.map_update_p50_ms), mapP95Ms: nonNegative(row.map_update_p95_ms), mapP99Ms: nonNegative(row.map_update_p99_ms),
    mapSamples: samples, p95Reliable: row.map_update_p95_reliable === true && (samples ?? 0) >= MIN_P95, p99Reliable: row.map_update_p99_reliable === true && (samples ?? 0) >= MIN_P99,
    runtimeMs: nonNegative(row.runtime_per_frame_ms ?? row.runtime_ms), fpsP50: nonNegative(row.processing_fps_p50),
    heightAccuracy05: fraction(row.height_accuracy_05cm), heightAccuracy10: fraction(row.height_accuracy_10cm), heightAccuracy20: fraction(row.height_accuracy_20cm),
    completion: fraction(row.completion_fraction), chamferM: nonNegative(row.chamfer_distance_m ?? row.symmetric_chamfer_m), rmseM: nonNegative(row.elevation_rmse_m),
    semanticRetention: fraction(row.semantic_retention_fraction), vehicleRetention: fraction(row.vehicle_retention_fraction),
    pedestrianRetention: fraction(row.pedestrian_retention_fraction), poleRetention: fraction(row.pole_retention_fraction),
    ...(raw ? inputReconstruction(raw) : {}),
  };
}

// Mirrors benchmarks/quality_resource.py::comparison_rows for reports that
// predate the embedded quality_resource table.
function derived(policy: PublicPolicy, raw: Json): QualityResourceRow {
  const quality = lastQuality(raw);
  const surface = isObject(quality.high_resolution_surface_comparison) ? quality.high_resolution_surface_comparison : {};
  const latency = raw.aggregate?.stage_latency_ns?.map_update ?? {};
  const samples = nonNegative(latency.count);
  const levels = isObject(raw.aggregate?.final_leaves_per_level) ? raw.aggregate.final_leaves_per_level : null;
  const retention = isObject(quality.field_retention) ? quality.field_retention : {};
  const members = retention.task_classes?.members ?? {};
  const memory = raw.runs?.at(-1)?.metrics?.memory ?? raw.aggregate?.memory ?? {};
  return {
    ...emptyRow(policy), status: text(surface.status) ?? (Object.keys(surface).length ? 'measured' : 'unavailable'), source: 'derived',
    logicalBytes: nonNegative(memory.logical_map_bytes ?? raw.aggregate?.logical_map_bytes), allocatedBytes: nonNegative(memory.allocated_map_bytes),
    rssBytes: nonNegative(raw.aggregate?.peak_rss_bytes),
    activeCells: levels ? Object.values(levels).reduce((sum: number, count) => sum + (nonNegative(count) ?? 0), 0) : null,
    mapP50Ms: nsToMs(latency.p50), mapP95Ms: nsToMs(latency.p95), mapP99Ms: nsToMs(latency.p99), mapSamples: samples,
    p95Reliable: (samples ?? 0) >= MIN_P95, p99Reliable: (samples ?? 0) >= MIN_P99,
    runtimeMs: nsToMs(raw.aggregate?.stage_latency_ns?.frame_pipeline?.p50), fpsP50: nonNegative(raw.aggregate?.fps?.p50),
    heightAccuracy05: fraction(surface.height_accuracy_05cm), heightAccuracy10: fraction(surface.height_accuracy_10cm), heightAccuracy20: fraction(surface.height_accuracy_20cm),
    completion: fraction(surface.completion_fraction), chamferM: nonNegative(surface.chamfer_distance_m ?? surface.symmetric_chamfer_m),
    rmseM: nonNegative(surface.elevation_rmse_m ?? quality.elevation_vs_fine_reference?.rmse_m),
    semanticRetention: fraction(retention.semantic?.retention_fraction), vehicleRetention: fraction(members.vehicle?.retention_fraction),
    pedestrianRetention: fraction(members.pedestrian?.retention_fraction), poleRetention: fraction(members.pole?.retention_fraction),
    ...inputReconstruction(raw),
  };
}

/** One row per public policy, preferring the producer's quality_resource table. */
export function qualityResourceRows(report: Json | null): QualityResourceRow[] {
  const policies = isObject(report?.policies) ? report!.policies : {};
  const table = isObject(report?.quality_resource) && report!.quality_resource.schema_version === QUALITY_RESOURCE_SCHEMA_VERSION && Array.isArray(report!.quality_resource.policies)
    ? report!.quality_resource.policies.filter(isObject) : null;
  return PUBLIC_POLICIES.map(policy => {
    const raw = isObject(policies[policy]) ? policies[policy] : null;
    const row = table?.find(item => item.policy === policy);
    if (row && row.status !== 'unavailable') return fromQualityResource(policy, row, raw);
    return raw ? derived(policy, raw) : emptyRow(policy);
  });
}

export interface ComparisonScope {
  status: 'measured' | 'partial' | 'unavailable';
  sameInput: boolean | null;
  inputDigests: Record<string, string>;
  dataset: string | null;
  sequence: string | null;
  frameStart: number | null;
  frameCount: number | null;
  latencyMetric: 'p95' | 'p50';
  referenceIsGroundTruth: boolean | null;
}

export function comparisonScope(report: Json | null): ComparisonScope {
  const table = isObject(report?.quality_resource) ? report!.quality_resource : {};
  const provenance = reportProvenance(report);
  const digests = isObject(table.input_stream_digests)
    ? Object.fromEntries(Object.entries(table.input_stream_digests).filter(([, digest]) => typeof digest === 'string')) as Record<string, string>
    : {};
  const rows = qualityResourceRows(report);
  const allP95 = rows.every(row => row.p95Reliable);
  return {
    status: table.status === 'measured' || table.status === 'partial' ? table.status : 'unavailable',
    sameInput: bool(table.same_input_for_all_policies),
    inputDigests: digests,
    dataset: text(report?.dataset), sequence: text(report?.sequence),
    frameStart: provenance.frameStart ?? nonNegative(report?.start), frameCount: provenance.frameCount,
    latencyMetric: table.latency_plot_metric === 'map_update_p95_ms' || (!table.latency_plot_metric && allP95) ? 'p95' : 'p50',
    referenceIsGroundTruth: bool(table.reference?.is_ground_truth),
  };
}

export function percent(value: number | null, decimals = 1): string {
  return value === null ? '—' : `${(value * 100).toLocaleString(undefined, {maximumFractionDigits: decimals})}%`;
}

export function mebibytes(bytes: number | null, decimals = 1): string {
  return bytes === null ? '—' : `${(bytes / 1048576).toLocaleString(undefined, {maximumFractionDigits: decimals})} MB`;
}

export function millis(value: number | null, decimals = 2): string {
  return value === null ? '—' : `${value.toLocaleString(undefined, {maximumFractionDigits: decimals})} ms`;
}

export function millimetres(metres: number | null, decimals = 1): string {
  return metres === null ? '—' : `${(metres * 1000).toLocaleString(undefined, {maximumFractionDigits: decimals})} mm`;
}

/** Normalize benchmark lifecycle states; the runtime reports failures as `error`. */
export function benchmarkLifecycle(state: unknown): 'idle' | 'running' | 'loading' | 'complete' | 'failed' {
  if (state === 'running' || state === 'loading' || state === 'complete') return state;
  if (state === 'error' || state === 'failed') return 'failed';
  return 'idle';
}
