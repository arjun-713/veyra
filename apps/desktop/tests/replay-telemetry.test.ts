import assert from 'node:assert/strict';
import test from 'node:test';
import {LiveTelemetryHistory, replayChartSample} from '../src/renderer/live-telemetry.ts';

function replayEvent(timestamp: number, overrides: Record<string, unknown> = {}) {
  return {
    type: 'telemetry', schema_version: 1, timestamp, state: 'running', index: 7, frames: 200,
    replay: true, fps: null, replay_serve_ms: 0.4, replay_fps: 60, replay_effective_fps: 120,
    recorded_telemetry: {
      recorded_during_cache_build: true,
      perception_timings_ms: {sensor_transform: 0.59, semantic: 0.12, ground: 6.05, terrain: 6.2, temporal: 0.0001, total: 14.59},
      active_cells: 562_576, cells_by_level: [175_706, 272_071, 101_129, 13_670],
      map_update_ms: 9.31, logical_bytes: 122_744_256,
      map_metrics: {
        fps: 30.8, map_update_latency_ns: {count: 201, p50: 9_310_959, p95: 10_576_292, p99: 11_471_542},
        measured_rss_bytes: 470_171_648,
      },
    },
    ...overrides,
  };
}

test('replay samples chart RECORDED cache-build values on an elapsed axis from the first replay sample', () => {
  const sample = replayChartSample(replayEvent(1_800_000_012.5), 1_800_000_000);
  assert.deepEqual(sample, {
    elapsedMs: 12_500, frame: 7, fps: 30.8, e2eP95Ms: null,
    backendRssMb: 470_171_648 / 1048576, mapperP50Ms: 9.31,
    mapperP95Ms: 10.576292, perceptionMs: 14.59, activeCells: 562_576,
  });
});

test('replay presentation rate is never charted as processing fps', () => {
  const noRecordedFps = replayEvent(1_800_000_001, {
    recorded_telemetry: {map_metrics: {}}, replay_fps: 60, replay_effective_fps: 120,
  });
  assert.equal(replayChartSample(noRecordedFps, 1_800_000_000)?.fps, null);
  const withRecorded = replayChartSample(replayEvent(1_800_000_001), 1_800_000_000);
  assert.equal(withRecorded?.fps, 30.8);
  assert.notEqual(withRecorded?.fps, 120);
  assert.notEqual(withRecorded?.fps, 60);
});

test('recorded mapper p95 stays unavailable below the 20-sample gate', () => {
  const low = replayEvent(1_800_000_001);
  (low.recorded_telemetry as any).map_metrics.map_update_latency_ns.count = 19;
  assert.equal(replayChartSample(low, 1_800_000_000)?.mapperP95Ms, null);
});

test('live-only and missing replay fields stay null; non-replay or bad timestamps yield no sample', () => {
  const bare = replayChartSample({type: 'telemetry', replay: true, timestamp: 1_800_000_002, recorded_telemetry: {}}, 1_800_000_000);
  assert.deepEqual(bare, {
    elapsedMs: 2_000, frame: null, fps: null, e2eP95Ms: null, backendRssMb: null,
    mapperP50Ms: null, mapperP95Ms: null, perceptionMs: null, activeCells: null,
  });
  assert.equal(replayChartSample({type: 'telemetry', timestamp: 1_800_000_002, elapsed_ms: 5}, 1_800_000_000), null);
  assert.equal(replayChartSample({type: 'telemetry', replay: true}, 1_800_000_000), null);
  assert.equal(replayChartSample(replayEvent(1_799_999_999), 1_800_000_000), null);
});

test('looping replay keeps a continuous trailing window because the axis is wall-clock elapsed', () => {
  const history = new LiveTelemetryHistory();
  const origin = 1_800_000_000;
  for (let second = 0; second <= 70; second++) {
    const sample = replayChartSample(replayEvent(origin + second, {index: second % 20}), origin);
    if (sample) history.append(sample, 'running');
  }
  const rows = history.values();
  assert.equal(rows.at(-1)?.elapsedMs, 70_000);
  assert.ok(rows.every(row => row.elapsedMs >= 10_000));
  assert.equal(rows.length, 61);
});
