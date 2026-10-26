import {describe} from 'node:test';
import assert from 'node:assert/strict';
import live_telemetry_test from 'node:test';
import {LIVE_SAMPLE_CAP, LIVE_WINDOW_MS, LIVE_TIME_TICKS, LiveTelemetryHistory, relativeChartSeries, telemetryChartSample} from '../src/renderer/live-telemetry.ts';
import {test as telemetry_display_test} from 'node:test';
import {gateStatistic, lastMeasuredPrefix, measurementDisplay, MIN_SAMPLES, processingDisplay, semanticDisplay, telemetryConfiguredHz} from '../src/renderer/dashboard.ts';
import {formatTelemetryAge, telemetryAgeMs, telemetryFreshness} from '../src/renderer/session.ts';
import replay_telemetry_test from 'node:test';
import {replayChartSample} from '../src/renderer/live-telemetry.ts';

describe('live telemetry', () => {
  function sample(elapsedMs: number, frame: number | null = elapsedMs / 1000) {
    return {
      elapsedMs, frame, fps: 20, e2eP95Ms: 30, backendRssMb: 100,
      mapperP50Ms: 10, mapperP95Ms: 12, perceptionMs: 8, activeCells: 500,
    };
  }

  live_telemetry_test('chart x coordinates are relative seconds and never wall-clock dates', () => {
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

  live_telemetry_test('live history trims to 60 seconds and a hard sample cap', () => {
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

  live_telemetry_test('paused telemetry is ignored, resume appends, and reset clears a new session', () => {
    const history = new LiveTelemetryHistory();
    history.append(sample(1000), 'running');
    history.append(sample(2000), 'paused');
    assert.deepEqual(history.values().map(row => row.elapsedMs), [1000]);
    history.append(sample(3000), 'running');
    assert.deepEqual(history.values().map(row => row.elapsedMs), [1000, 3000]);
    history.reset();
    assert.deepEqual(history.values(), []);
  });

  live_telemetry_test('new runtime elapsed origin resets history rather than corrupting the x axis', () => {
    const history = new LiveTelemetryHistory();
    history.append(sample(20_000), 'running');
    history.append(sample(10), 'running');
    assert.deepEqual(history.values().map(row => row.elapsedMs), [10]);
  });

  live_telemetry_test('telemetry charts retain real unavailable values and use elapsed_ms, not timestamp', () => {
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

  live_telemetry_test('p95 chart values stay unavailable until the canonical 20-sample gate', () => {
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

  live_telemetry_test('backend RSS is unavailable unless every reported process has a valid measurement', () => {
    const partial = telemetryChartSample({
      elapsed_ms: 1_000, processes: [
        {name: 'runtime', rss_bytes: 50 * 1048576}, {name: 'mapper', rss_bytes: null},
      ],
    });
    assert.equal(partial?.backendRssMb, null);
  });
});

describe('telemetry display', () => {
  // TEST A: paused runtime displays PAUSED, never a dash or zero
  telemetry_display_test('paused runtime displays PAUSED with historical context',()=>{
   const shown=processingDisplay({state:'paused'},{fps:null});
   assert.equal(shown.label,'PAUSED');
   assert.match(shown.sub,/last measured/i);
  });

  // TEST B: running runtime with valid FPS displays the measured rate
  telemetry_display_test('running runtime with valid FPS displays the measured rate',()=>{
   const shown=processingDisplay({state:'running'},{fps:2.8});
   assert.match(shown.label,/2\.8/);
   const starting=processingDisplay({state:'running'},{fps:null});
   assert.equal(starting.label,'STARTING');
   const idle=processingDisplay({state:'unconfigured'},{});
   assert.equal(idle.label,'IDLE');
   const failed=processingDisplay({state:'error'},{});
   assert.equal(failed.label,'ERROR');
  });

  // TEST C: insufficient p95 samples show N/A plus the count
  telemetry_display_test('p95 below its sample gate shows N/A with counts',()=>{
   const gated=gateStatistic(302.5,7,MIN_SAMPLES.p95);
   assert.equal(gated.ok,false);
   assert.equal(gated.text,'N/A');
   assert.equal(gated.sub,'insufficient samples 7 / 20');
  });

  // TEST D: sufficient p95 samples display the percentile with n
  telemetry_display_test('p95 at its sample gate displays the value with n',()=>{
   const gated=gateStatistic(302.5,87,MIN_SAMPLES.p95);
   assert.equal(gated.ok,true);
   assert.equal(gated.sub,'n = 87');
  });

  // TEST E: p99 gate is stricter than p95
  telemetry_display_test('p99 requires 100 samples and is not presented as valid below that',()=>{
   assert.ok(MIN_SAMPLES.p99>MIN_SAMPLES.p95);
   assert.equal(gateStatistic(400,50,MIN_SAMPLES.p99).ok,false);
   assert.equal(gateStatistic(400,120,MIN_SAMPLES.p99).ok,true);
   assert.equal(MIN_SAMPLES.p50,5);
  });

  // TEST F: Ground Truth mode is explicit neural bypass
  telemetry_display_test('ground truth mode reports bypassed neural inference',()=>{
   const shown=semanticDisplay('Ground Truth',null,null,'ground_truth');
   assert.equal(shown.source,'DATASET GROUND TRUTH');
   assert.equal(shown.neural,'BYPASSED');
   assert.equal(shown.execution,'N/A');
  });

  // TEST G: neural CPU mode shows source, model and verified device
  telemetry_display_test('neural cpu mode shows source model and device',()=>{
   const shown=semanticDisplay('cenet','SENet_valid_best','cpu','model');
   assert.equal(shown.source,'cenet');
   assert.equal(shown.neural,'ACTIVE');
   assert.equal(shown.execution,'cpu');
   const unknown=semanticDisplay('salsanext',null,'unavailable','model');
   assert.equal(unknown.execution,'Unavailable');
  });

  // TEST H: telemetry freshness transitions Fresh to Stale with age
  telemetry_display_test('telemetry freshness transitions on the 30 s threshold with age text',()=>{
   assert.equal(telemetryFreshness({timestamp:99},100000),'Fresh');
   assert.equal(telemetryFreshness({timestamp:60},100000),'Stale');
   assert.equal(formatTelemetryAge({timestamp:60},100000),'40.0 s');
   assert.equal(telemetryAgeMs({},100000),null);
  });

  // TEST I: healthy runtime may legally carry stale telemetry when paused
  telemetry_display_test('freshness depends only on telemetry age, never on health state',()=>{
   const stale={timestamp:1,health:{runtime:'running',telemetry:'fresh'}};
   assert.equal(telemetryFreshness(stale,100000),'Stale');
   assert.equal(telemetryFreshness({timestamp:99.9},100000),'Fresh');
  });

  // Measurement states map explicitly, never implying completion from pause
  telemetry_display_test('benchmark capture states are explicit',()=>{
   assert.equal(measurementDisplay('running').label,'MEASURING');
   assert.equal(measurementDisplay('complete').label,'COMPLETE');
   assert.equal(measurementDisplay('failed').label,'FAILED');
   assert.equal(measurementDisplay('idle').label,'IDLE');
   assert.equal(lastMeasuredPrefix(true),'LAST MEASURED · ');
   assert.equal(lastMeasuredPrefix(false),'');
  });

  // Telemetry cadence is a configured rate, distinct from measured throughput
  telemetry_display_test('telemetry cadence reads the configured update rate',()=>{
   assert.equal(telemetryConfiguredHz({visualization:{update_hz:2}}),2);
   assert.equal(telemetryConfiguredHz({}),null);
  });
});

describe('replay telemetry', () => {
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

  replay_telemetry_test('replay samples chart RECORDED cache-build values on an elapsed axis from the first replay sample', () => {
    const sample = replayChartSample(replayEvent(1_800_000_012.5), 1_800_000_000);
    assert.deepEqual(sample, {
      elapsedMs: 12_500, frame: 7, fps: 30.8, e2eP95Ms: null,
      backendRssMb: 470_171_648 / 1048576, mapperP50Ms: 9.31,
      mapperP95Ms: 10.576292, perceptionMs: 14.59, activeCells: 562_576,
    });
  });

  replay_telemetry_test('replay presentation rate is never charted as processing fps', () => {
    const noRecordedFps = replayEvent(1_800_000_001, {
      recorded_telemetry: {map_metrics: {}}, replay_fps: 60, replay_effective_fps: 120,
    });
    assert.equal(replayChartSample(noRecordedFps, 1_800_000_000)?.fps, null);
    const withRecorded = replayChartSample(replayEvent(1_800_000_001), 1_800_000_000);
    assert.equal(withRecorded?.fps, 30.8);
    assert.notEqual(withRecorded?.fps, 120);
    assert.notEqual(withRecorded?.fps, 60);
  });

  replay_telemetry_test('recorded mapper p95 stays unavailable below the 20-sample gate', () => {
    const low = replayEvent(1_800_000_001);
    (low.recorded_telemetry as any).map_metrics.map_update_latency_ns.count = 19;
    assert.equal(replayChartSample(low, 1_800_000_000)?.mapperP95Ms, null);
  });

  replay_telemetry_test('live-only and missing replay fields stay null; non-replay or bad timestamps yield no sample', () => {
    const bare = replayChartSample({type: 'telemetry', replay: true, timestamp: 1_800_000_002, recorded_telemetry: {}}, 1_800_000_000);
    assert.deepEqual(bare, {
      elapsedMs: 2_000, frame: null, fps: null, e2eP95Ms: null, backendRssMb: null,
      mapperP50Ms: null, mapperP95Ms: null, perceptionMs: null, activeCells: null,
    });
    assert.equal(replayChartSample({type: 'telemetry', timestamp: 1_800_000_002, elapsed_ms: 5}, 1_800_000_000), null);
    assert.equal(replayChartSample({type: 'telemetry', replay: true}, 1_800_000_000), null);
    assert.equal(replayChartSample(replayEvent(1_799_999_999), 1_800_000_000), null);
  });

  replay_telemetry_test('looping replay keeps a continuous trailing window because the axis is wall-clock elapsed', () => {
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
});
