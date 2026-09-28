import assert from 'node:assert/strict';
import test from 'node:test';
import {
  LIVE_SAMPLE_CAP, LIVE_WINDOW_MS, LIVE_TIME_TICKS, LiveTelemetryHistory,
  relativeChartSeries, telemetryChartSample,
} from '../src/renderer/live-telemetry.ts';

function sample(elapsedMs: number, frame: number | null = elapsedMs / 1000) {
  return {
    elapsedMs, frame, fps: 20, e2eP95Ms: 30, backendRssMb: 100,
    mapperP50Ms: 10, mapperP95Ms: 12, perceptionMs: 8, activeCells: 500,
  };
}

test('chart x coordinates are relative seconds and never wall-clock dates', () => {
  const history = new LiveTelemetryHistory();
  history.append(sample(1_800_000_000_000 - 30_000), 'running');
  history.append(sample(1_800_000_000_000), 'running');
  const series = relativeChartSeries(history.values(), 'fps');
  assert.deepEqual(series.x, [-30, 0]);
  assert.deepEqual(series.y, [20, 20]);
  assert.deepEqual(LIVE_TIME_TICKS, [
    {value: -60, label: '-60s'}, {value: -45, label: '-45s'},
    {value: -30, label: '-30s'}, {value: -15, label: '-15s'},
    {value: 0, label: 'Now'},
  ]);
});

test('live history trims to 60 seconds and a hard sample cap', () => {
  const history = new LiveTelemetryHistory();
  assert.equal(LIVE_WINDOW_MS, 60_000);
  for (let second = 0; second <= 61; second++) history.append(sample(second * 1000), 'running');
  assert.ok(history.values().every(row => row.elapsedMs >= 1000));
  assert.ok(history.values().every(row => row.elapsedMs <= 61_000));
  for (let second = 62; second < 62 + LIVE_SAMPLE_CAP + 10; second++) {
    history.append(sample(second * 1000), 'running');
  }
  assert.ok(history.values().length <= LIVE_SAMPLE_CAP);
});

test('paused telemetry is ignored, resume appends, and reset clears a new session', () => {
  const history = new LiveTelemetryHistory();
  history.append(sample(1000), 'running');
  history.append(sample(2000), 'paused');
  assert.deepEqual(history.values().map(row => row.elapsedMs), [1000]);
  history.append(sample(3000), 'running');
  assert.deepEqual(history.values().map(row => row.elapsedMs), [1000, 3000]);
  history.reset();
  assert.deepEqual(history.values(), []);
});

test('new runtime elapsed origin resets history rather than corrupting the x axis', () => {
  const history = new LiveTelemetryHistory();
  history.append(sample(20_000), 'running');
  history.append(sample(10), 'running');
  assert.deepEqual(history.values().map(row => row.elapsedMs), [10]);
});

test('telemetry charts retain real unavailable values and use elapsed_ms, not timestamp', () => {
  const result = telemetryChartSample({
    type: 'telemetry', schema_version: 1,
    timestamp: 1_800_000_000, elapsed_ms: 12_500, state: 'running', index: 42,
    fps: 12.5, latency_ms: {end_to_end: {p95: 41, count: 24}, mapping: 18,
      mapping_p95: 26, mapping_samples: 22, perception: 9},
    processes: [{name: 'runtime', rss_bytes: 50 * 1048576}, {name: 'mapper', rss_bytes: 20 * 1048576}],
    map: {active_cells: 900},
  });
  assert.deepEqual(result, {
    elapsedMs: 12_500, frame: 42, fps: 12.5, e2eP95Ms: 41,
    backendRssMb: 70, mapperP50Ms: 18, mapperP95Ms: 26,
    perceptionMs: 9, activeCells: 900,
  });
  const missing = telemetryChartSample({type: 'telemetry', timestamp: 1_800_000_000});
  assert.equal(missing, null);
});

test('p95 chart values stay unavailable until the canonical 20-sample gate', () => {
  const low = telemetryChartSample({
    elapsed_ms: 1_000, state: 'running', latency_ms: {
      end_to_end: {p95: 40, count: 19}, mapping_p95: 30, mapping_samples: 19,
    },
  });
  assert.equal(low?.e2eP95Ms, null);
  assert.equal(low?.mapperP95Ms, null);
  const adequate = telemetryChartSample({
    elapsed_ms: 2_000, state: 'running', latency_ms: {
      end_to_end: {p95: 40, count: 20}, mapping_p95: 30, mapping_samples: 20,
    },
  });
  assert.equal(adequate?.e2eP95Ms, 40);
  assert.equal(adequate?.mapperP95Ms, 30);
});

test('backend RSS is unavailable unless every reported process has a valid measurement', () => {
  const partial = telemetryChartSample({
    elapsed_ms: 1_000, processes: [
      {name: 'runtime', rss_bytes: 50 * 1048576}, {name: 'mapper', rss_bytes: null},
    ],
  });
  assert.equal(partial?.backendRssMb, null);
});
