import {test} from 'node:test';
import assert from 'node:assert/strict';
import {gateStatistic, lastMeasuredPrefix, measurementDisplay, MIN_SAMPLES, processingDisplay, semanticDisplay, telemetryConfiguredHz} from '../src/renderer/dashboard.ts';
import {formatTelemetryAge, telemetryAgeMs, telemetryFreshness} from '../src/renderer/session.ts';

// TEST A: paused runtime displays PAUSED, never a dash or zero
test('paused runtime displays PAUSED with historical context',()=>{
 const shown=processingDisplay({state:'paused'},{fps:null});
 assert.equal(shown.label,'PAUSED');
 assert.match(shown.sub,/last measured/i);
});

// TEST B: running runtime with valid FPS displays the measured rate
test('running runtime with valid FPS displays the measured rate',()=>{
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
test('p95 below its sample gate shows N/A with counts',()=>{
 const gated=gateStatistic(302.5,7,MIN_SAMPLES.p95);
 assert.equal(gated.ok,false);
 assert.equal(gated.text,'N/A');
 assert.equal(gated.sub,'insufficient samples 7 / 20');
});

// TEST D: sufficient p95 samples display the percentile with n
test('p95 at its sample gate displays the value with n',()=>{
 const gated=gateStatistic(302.5,87,MIN_SAMPLES.p95);
 assert.equal(gated.ok,true);
 assert.equal(gated.sub,'n = 87');
});

// TEST E: p99 gate is stricter than p95
test('p99 requires 100 samples and is not presented as valid below that',()=>{
 assert.ok(MIN_SAMPLES.p99>MIN_SAMPLES.p95);
 assert.equal(gateStatistic(400,50,MIN_SAMPLES.p99).ok,false);
 assert.equal(gateStatistic(400,120,MIN_SAMPLES.p99).ok,true);
 assert.equal(MIN_SAMPLES.p50,5);
});

// TEST F: Ground Truth mode is explicit neural bypass
test('ground truth mode reports bypassed neural inference',()=>{
 const shown=semanticDisplay('Ground Truth',null,null,'ground_truth');
 assert.equal(shown.source,'DATASET GROUND TRUTH');
 assert.equal(shown.neural,'BYPASSED');
 assert.equal(shown.execution,'N/A');
});

// TEST G: neural CPU mode shows source, model and verified device
test('neural cpu mode shows source model and device',()=>{
 const shown=semanticDisplay('cenet','SENet_valid_best','cpu','model');
 assert.equal(shown.source,'cenet');
 assert.equal(shown.neural,'ACTIVE');
 assert.equal(shown.execution,'cpu');
 const unknown=semanticDisplay('salsanext',null,'unavailable','model');
 assert.equal(unknown.execution,'Unavailable');
});

// TEST H: telemetry freshness transitions Fresh to Stale with age
test('telemetry freshness transitions on the 30 s threshold with age text',()=>{
 assert.equal(telemetryFreshness({timestamp:99},100000),'Fresh');
 assert.equal(telemetryFreshness({timestamp:60},100000),'Stale');
 assert.equal(formatTelemetryAge({timestamp:60},100000),'40.0 s');
 assert.equal(telemetryAgeMs({},100000),null);
});

// TEST I: healthy runtime may legally carry stale telemetry when paused
test('freshness depends only on telemetry age, never on health state',()=>{
 const stale={timestamp:1,health:{runtime:'running',telemetry:'fresh'}};
 assert.equal(telemetryFreshness(stale,100000),'Stale');
 assert.equal(telemetryFreshness({timestamp:99.9},100000),'Fresh');
});

// Measurement states map explicitly, never implying completion from pause
test('benchmark capture states are explicit',()=>{
 assert.equal(measurementDisplay('running').label,'MEASURING');
 assert.equal(measurementDisplay('complete').label,'COMPLETE');
 assert.equal(measurementDisplay('failed').label,'FAILED');
 assert.equal(measurementDisplay('idle').label,'IDLE');
 assert.equal(lastMeasuredPrefix(true),'LAST MEASURED · ');
 assert.equal(lastMeasuredPrefix(false),'');
});

// Telemetry cadence is a configured rate, distinct from measured throughput
test('telemetry cadence reads the configured update rate',()=>{
 assert.equal(telemetryConfiguredHz({visualization:{update_hz:2}}),2);
 assert.equal(telemetryConfiguredHz({}),null);
});
