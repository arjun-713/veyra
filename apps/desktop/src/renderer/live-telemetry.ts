import type {Json} from '../core.ts';

export const LIVE_WINDOW_MS = 60_000;
export const LIVE_SAMPLE_CAP = 3_600;
export const LIVE_TIME_TICKS = [
  {value: -60, label: '-60s'}, {value: -45, label: '-45s'},
  {value: -30, label: '-30s'}, {value: -15, label: '-15s'},
  {value: 0, label: 'Now'},
] as const;

export interface LiveTelemetrySample {
  elapsedMs: number;
  frame: number | null;
  fps: number | null;
  e2eP95Ms: number | null;
  backendRssMb: number | null;
  mapperP50Ms: number | null;
  mapperP95Ms: number | null;
  perceptionMs: number | null;
  activeCells: number | null;
}

export type LiveMetric = Exclude<keyof LiveTelemetrySample, 'elapsedMs' | 'frame'>;

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

export function telemetryChartSample(event: Json): LiveTelemetrySample | null {
  const elapsedMs = finite(event.elapsed_ms);
  if (elapsedMs === null) return null;
  const latency = event.latency_ms ?? {};
  const processes = Array.isArray(event.processes) ? event.processes : [];
  const rssValues = processes.map((process: Json) => finite(process.rss_bytes));
  const backendRssMb = processes.length > 0 && rssValues.every((value: number | null) => value !== null)
    ? rssValues.reduce((sum: number, value: number | null) => sum + (value ?? 0), 0) / 1048576
    : null;
  return {
    elapsedMs,
    frame: finite(event.index),
    fps: finite(event.fps),
    e2eP95Ms: finite(latency.end_to_end?.count) !== null && latency.end_to_end.count >= 20 ? finite(latency.end_to_end.p95) : null,
    backendRssMb,
    mapperP50Ms: finite(latency.mapping_p50 ?? latency.mapping),
    mapperP95Ms: finite(latency.mapping_samples) !== null && latency.mapping_samples >= 20 ? finite(latency.mapping_p95) : null,
    perceptionMs: finite(latency.perception),
    activeCells: finite(event.map?.active_cells),
  };
}

export class LiveTelemetryHistory {
  private rows: LiveTelemetrySample[] = [];

  append(sample: LiveTelemetrySample, state: unknown): void {
    if (state !== 'running') return;
    const previous = this.rows.at(-1);
    if (previous && sample.elapsedMs < previous.elapsedMs) this.rows = [];
    this.rows.push(sample);
    const oldest = sample.elapsedMs - LIVE_WINDOW_MS;
    this.rows = this.rows.filter(row => row.elapsedMs >= oldest).slice(-LIVE_SAMPLE_CAP);
  }

  values(): LiveTelemetrySample[] {
    return this.rows;
  }

  reset(): void {
    this.rows = [];
  }
}

export function relativeChartSeries(rows: LiveTelemetrySample[], metric: LiveMetric) {
  const latest = rows.at(-1)?.elapsedMs ?? 0;
  return {
    x: rows.map(row => (row.elapsedMs - latest) / 1000),
    y: rows.map(row => row[metric]),
  };
}
