import {test} from 'node:test';
import assert from 'node:assert/strict';
import {enterJudgeView, exitJudgeView, initialJudgeView, judgeViewPreset} from '../src/renderer/judge-view.ts';
import {bandLabels, cellRangeM, explainResolution, expectedBandForRange, levelFromSize, parsePolicyDescriptor, resolutionLabelForLevel} from '../src/renderer/cell-explain.ts';
import {anatomyRange, cellAnatomy} from '../src/renderer/cell-anatomy.ts';

const EVIDENCE = {utility: 0.2, quality: 0.9, geometryComplexity: 0.4, semanticConfidence: 0.8, semanticClass: 9, semanticLabel: 'Road', motion: 0, drivableEvidence: 1.5, groundEvidence: 2.1};

// Mapper-reported descriptor, as emitted by the engine frame report.
function descriptor(policy: string, overrides: Record<string, unknown> = {}) {
  return parsePolicyDescriptor({
    name: policy,
    levels: [{level: 0, resolution_m: 0.05}, {level: 1, resolution_m: 0.1}, {level: 2, resolution_m: 0.2}, {level: 3, resolution_m: 0.4}],
    distance_boundaries_m: [10, 30, 60],
    window_radius_m: 100,
    near_field_radius_m: policy === 'utility_lod' ? 10 : null,
    ...overrides,
  });
}

const DISTANCE = descriptor('distance_lod');
const NO_ATTRIBUTION = {available: false};

// --- Judge view state ---

test('judge view enables the correct viewer state',()=>{
 const state = judgeViewPreset();
 assert.deepEqual(state, {viewMode: 'map', view: 'top', follow: true, mode: 'lod', boundaries: true, showRings: true});
});

test('entering judge view saves prior state; exiting restores it uncorrupted',()=>{
 const prior = {viewMode: 'both', view: 'orbit', follow: false, mode: 'semantic', boundaries: false, showRings: false};
 const entered = enterJudgeView(prior, initialJudgeView());
 assert.equal(entered.session.active, true);
 assert.deepEqual(entered.state, judgeViewPreset());
 const exited = exitJudgeView(entered.session, judgeViewPreset());
 assert.deepEqual(exited.state, prior);
 assert.equal(exited.session.active, false);
 assert.equal(exited.session.saved, null);
});

test('re-entering judge view keeps the original saved state',()=>{
 const prior = {viewMode: 'raw', view: 'driver', follow: true, mode: 'terrain', boundaries: true, showRings: false};
 const once = enterJudgeView(prior, initialJudgeView());
 const tweaked = {...judgeViewPreset(), follow: false};
 const twice = enterJudgeView(tweaked, once.session);
 assert.deepEqual(exitJudgeView(twice.session, judgeViewPreset()).state, prior);
});

// --- Policy descriptor parsing ---

test('descriptor parses the mapper report; garbage is unavailable, never defaulted',()=>{
 assert.equal(DISTANCE.available, true);
 assert.equal(DISTANCE.name, 'distance_lod');
 assert.deepEqual(bandLabels(DISTANCE), ['0–10 m', '10–30 m', '30–60 m', '60–100 m']);
 for (const raw of [null, undefined, {}, {name: 'distance_lod'}, {name: 'nope'}, {name: 'distance_lod', distance_boundaries_m: [10, 30]}, {name: 'distance_lod', distance_boundaries_m: [30, 10, 60], window_radius_m: 100}, 'x', 42]) {
  const parsed = parsePolicyDescriptor(raw);
  assert.equal(parsed.available, false, JSON.stringify(raw));
  assert.equal(bandLabels(parsed), null);
 }
});

test('custom/non-default distance thresholds flow through, not frontend constants',()=>{
 const custom = descriptor('distance_lod', {distance_boundaries_m: [5, 15, 45], window_radius_m: 80});
 assert.equal(custom.available, true);
 assert.deepEqual(bandLabels(custom), ['0–5 m', '5–15 m', '15–45 m', '45–80 m']);
 assert.equal(expectedBandForRange(custom, 7)?.level, 1);
 assert.equal(expectedBandForRange(custom, 50)?.level, 3);
 assert.equal(resolutionLabelForLevel(custom, 2), '20 cm');
});

test('distance bands map the documented ranges',()=>{
 assert.equal(expectedBandForRange(DISTANCE, 7.8)?.level, 0);
 assert.equal(expectedBandForRange(DISTANCE, 10)?.level, 1);
 assert.equal(expectedBandForRange(DISTANCE, 42.1)?.level, 2);
 assert.equal(expectedBandForRange(DISTANCE, 73.4)?.level, 3);
 assert.equal(expectedBandForRange(DISTANCE, 150), null);
 assert.equal(expectedBandForRange(DISTANCE, NaN), null);
});

test('level derives from stored size',()=>{
 assert.equal(levelFromSize(0.05), 0);
 assert.equal(levelFromSize(0.4), 3);
 assert.equal(levelFromSize(NaN), null);
 assert.equal(levelFromSize(-1), null);
});

test('range needs a full 16-float world pose',()=>{
 assert.equal(cellRangeM(3, 4, [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]), 5);
 assert.equal(cellRangeM(0, 0, null), null);
 assert.equal(cellRangeM(0, 0, [1,2,3]), null);
});

// --- Uniform policies: no bands, ever ---

test('uniform5 explains without any distance band',()=>{
 const out = explainResolution({descriptor: descriptor('uniform5'), policyName: 'uniform5', rangeM: 73.4, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.equal(out.verdict, 'policy');
 assert.match(out.headline, /5 cm/);
 assert.match(out.detail, /Distance from robot does not determine/);
 assert.doesNotMatch(out.headline + out.detail, /10 m|30 m|60 m|band/);
});

test('uniform40 explains without any distance band',()=>{
 const out = explainResolution({descriptor: descriptor('uniform40'), policyName: 'uniform40', rangeM: 3.1, level: 3, sizeM: 0.4, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.equal(out.verdict, 'policy');
 assert.match(out.headline, /40 cm/);
 assert.doesNotMatch(out.headline + out.detail, /10 m|30 m|60 m|band/);
});

test('uniform mismatch reports disagreement honestly',()=>{
 const out = explainResolution({descriptor: descriptor('uniform5'), policyName: 'uniform5', rangeM: 3.1, level: 3, sizeM: 0.4, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.equal(out.verdict, 'mismatch');
 assert.match(out.detail, /disagreement/);
});

// --- DistanceLOD from the active descriptor ---

test('matching band explains the real policy',()=>{
 const out = explainResolution({descriptor: DISTANCE, policyName: 'distance_lod', rangeM: 7.8, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.equal(out.verdict, 'policy');
 assert.match(out.headline, /5 cm/);
 assert.match(out.detail, /7\.8 m from robot/);
 assert.match(out.detail, /DistanceLOD/);
 assert.doesNotMatch(out.detail, /protects this range/);
});

test('mid-field match carries no protection note',()=>{
 const out = explainResolution({descriptor: DISTANCE, policyName: 'distance_lod', rangeM: 42.1, level: 2, sizeM: 0.2, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.equal(out.verdict, 'policy');
 assert.match(out.headline, /20 cm/);
});

test('custom thresholds change the expected level',()=>{
 const custom = descriptor('distance_lod', {distance_boundaries_m: [5, 15, 45], window_radius_m: 80});
 const out = explainResolution({descriptor: custom, policyName: 'distance_lod', rangeM: 7.8, level: 1, sizeM: 0.1, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.equal(out.verdict, 'policy');
 assert.match(out.headline, /10 cm/);
});

test('missing descriptor never assumes bands',()=>{
 const out = explainResolution({descriptor: parsePolicyDescriptor(null), policyName: 'distance_lod', rangeM: 7.8, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.equal(out.verdict, 'unknown');
 assert.match(out.headline + ' ' + out.detail, /policy configuration unavailable/i);
});

test('missing range or level never fabricates',()=>{
 const noRange = explainResolution({descriptor: DISTANCE, policyName: 'distance_lod', rangeM: null, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.equal(noRange.verdict, 'unknown');
 assert.match(noRange.detail, /pose is unavailable/);
 const noLevel = explainResolution({descriptor: DISTANCE, policyName: 'distance_lod', rangeM: 5, level: null, sizeM: null, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.equal(noLevel.verdict, 'unknown');
});

test('range past the reported window is outside the map',()=>{
 const out = explainResolution({descriptor: DISTANCE, policyName: 'distance_lod', rangeM: 120, level: 3, sizeM: 0.4, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.equal(out.verdict, 'mismatch');
 assert.match(out.headline + ' ' + out.detail, /outside the mapped range/);
});

// --- UtilityLOD: attribution or explicit unavailability ---

test('finer-than-band without attribution claims nothing',()=>{
 const out = explainResolution({descriptor: descriptor('utility_lod'), policyName: 'utility_lod', rangeM: 42.1, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.equal(out.verdict, 'mismatch');
 assert.match(out.detail, /Utility decision attribution unavailable/);
 assert.match(out.detail, /distance reference is 20 cm/);
 assert.doesNotMatch(out.headline + out.detail, /better|superior|outperform/);
});

test('proven attribution explains the refinement',()=>{
 const out = explainResolution({descriptor: descriptor('utility_lod'), policyName: 'utility_lod', rangeM: 42.1, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: {available: true}});
 assert.equal(out.verdict, 'promotion');
 assert.match(out.detail, /decision attribution proves/);
});

test('utility at reference level shows signals without claiming promotion',()=>{
 const out = explainResolution({descriptor: descriptor('utility_lod'), policyName: 'utility_lod', rangeM: 42.1, level: 2, sizeM: 0.2, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.equal(out.verdict, 'policy');
 assert.ok(out.signals.some(s => s.startsWith('utility')));
 assert.match(out.detail, /no promotion is proven/);
});

test('protection note appears only with a reported radius',()=>{
 const near = explainResolution({descriptor: descriptor('utility_lod'), policyName: 'utility_lod', rangeM: 7.8, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.match(near.detail, /near-field radius protects/);
 const far = explainResolution({descriptor: descriptor('utility_lod'), policyName: 'utility_lod', rangeM: 42.1, level: 2, sizeM: 0.2, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.doesNotMatch(far.detail, /protects/);
});

// --- Semantic names, not bare IDs ---

test('semantic class renders human-readable',()=>{
 const out = explainResolution({descriptor: DISTANCE, policyName: 'distance_lod', rangeM: 7.8, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
 assert.ok(out.signals.some(s => s === 'Road · ID 9'));
 const noName = explainResolution({descriptor: DISTANCE, policyName: 'distance_lod', rangeM: 7.8, level: 0, sizeM: 0.05, evidence: {...EVIDENCE, semanticLabel: null}, attribution: NO_ATTRIBUTION});
 assert.ok(!noName.signals.some(s => s.includes(' 9')));
 assert.ok(noName.unavailable.includes('semantic class'));
});

// --- 2.5D anatomy ---

const PHYSICAL = {
  ground: {count: 2, mean: 0.094, min: 0.05, max: 0.14},
  obstacle: {count: 0, mean: null, min: null, max: null},
  overhead: {count: null, mean: null, min: null, max: null},
};

test('anatomy separates ground, obstacle, overhead evidence',()=>{
 const model = cellAnatomy({physicalLayers: PHYSICAL, pooled: {mean: 0.1, zmin: 0.05, zmax: 0.14, variance: 0.001, count: 2}, resolution: '5 cm', lod: 0});
 assert.equal(model.available, true);
 assert.equal(model.layers[0].state, 'present');
 assert.equal(model.layers[0].mean, 0.094);
 assert.equal(model.layers[1].state, 'empty');
 assert.equal(model.layers[2].state, 'empty');
 assert.equal(model.groundUnobserved, false);
 const range = anatomyRange(model)!;
 assert.ok(range.lo <= 0.05 && range.hi >= 0.14);
});

test('ground absent without proof is unobserved, not occluded',()=>{
 const model = cellAnatomy({
   physicalLayers: {ground: {count: 0, mean: null, min: null, max: null}, obstacle: {count: 5, mean: 1.2, min: 0.4, max: 2.0}, overhead: {count: 0, mean: null, min: null, max: null}},
   pooled: {mean: 1.2, zmin: 0.4, zmax: 2.0, variance: 0.2, count: 5}, resolution: '10 cm', lod: 1});
 assert.equal(model.groundUnobserved, true);
 assert.ok(model.notes.some(n => n.includes('Ground unobserved')));
 assert.ok(!model.notes.some(n => n.toLowerCase().includes('occluded')));
 assert.ok(model.notes.some(n => n.includes('never drivable')));
});

test('missing section is unavailable, all-empty clears nothing',()=>{
 const legacy = cellAnatomy({physicalLayers: null, pooled: {mean: null, zmin: null, zmax: null, variance: null, count: null}, resolution: null, lod: null});
 assert.equal(legacy.available, false);
 assert.equal(anatomyRange(legacy), null);
 const empty = cellAnatomy({
   physicalLayers: {ground: {count: 0, mean: null, min: null, max: null}, obstacle: {count: 0, mean: null, min: null, max: null}, overhead: {count: 0, mean: null, min: null, max: null}},
   pooled: {mean: null, zmin: null, zmax: null, variance: null, count: 0}, resolution: '40 cm', lod: 3});
 assert.ok(empty.notes.some(n => n.includes('clears nothing')));
 assert.equal(anatomyRange(empty), null);
});

// --- Cell lookup across frames (selection sync) ---

import {findCellInPayload, inspectorFromRow, readCellRow} from '../src/renderer/cell-lookup.ts';
import {formatRecorded, replayPolicyName} from '../src/renderer/replay-metrics.ts';
import {samplingStatus} from '../src/renderer/dashboard.ts';

function payloadWithCells(rows: number[][], stride = 17): {payload: Uint8Array; section: {count: number; offset: number; stride: number}} {
 const floats = rows.length * stride;
 const buffer = new Float32Array(floats).fill(Number.NaN);
 rows.forEach((row, i) => row.forEach((v, j) => { buffer[i * stride + j] = v; }));
 const bytes = new Uint8Array(buffer.buffer);
 return {payload: bytes, section: {count: rows.length, offset: 0, stride: stride * 4}};
}

const ROW_A = [3.025, -9.85, 0.09, 0.05, 9, 0, 0.9, 1.5, 0.2, 0.8, 2.1, 0.7, 0.1, 40, 0.05, 0.14, 0.001];
const ROW_B = [10.05, 4.05, 0.5, 0.2, 3, 0, 0.8, 0, 0.1, 0.6, 0, 0.5, 0.3, 120, 0.3, 0.7, 0.01];

test('selection re-resolves the same world cell in a new frame',()=>{
 const {payload, section} = payloadWithCells([ROW_A, ROW_B]);
 assert.equal(findCellInPayload(payload, section, 3.025, -9.85, 0.05), 0);
 assert.equal(findCellInPayload(payload, section, 10.05, 4.05, 0.2), 1);
});

test('merged-away cell falls back to the smallest containing owner',()=>{
 const big = [3.1, -9.9, 0.09, 0.2, 9, 0, 0.9, 1.5, 0.2, 0.8, 2.1, 0.7, 0.1, 200, 0.0, 0.2, 0.004];
 const {payload, section} = payloadWithCells([big]);
 assert.equal(findCellInPayload(payload, section, 3.025, -9.85, 0.05), 0);
});

test('evicted cell returns null so selection clears with a message',()=>{
 const {payload, section} = payloadWithCells([ROW_B]);
 assert.equal(findCellInPayload(payload, section, 3.025, -9.85, 0.05), null);
 assert.equal(findCellInPayload(payload, section, NaN, 0, 0.05), null);
 const bad = {...section, stride: 40};
 assert.equal(findCellInPayload(payload, bad, 3.025, -9.85, 0.05), null);
});

test('inspector builder matches click and refresh paths exactly',()=>{
 const {payload, section} = payloadWithCells([ROW_A]);
 const row = readCellRow(payload, section, 0)!;
 const cell = inspectorFromRow(row);
 assert.ok(Math.abs((cell.x ?? 0) - 3.025) < 1e-6);
 assert.ok(Math.abs((cell.resolution ?? 0) - 0.05) < 1e-9);
 assert.equal(cell.lod_level, 0);
 assert.equal(cell.semantic_class, 9);
 assert.equal(cell.point_count, 40);
 const v2 = payloadWithCells([[3.025, -9.85, 0.09, 0.05, 9, 0, 0.9, 1.5, 0.2]], 9);
 const v2row = readCellRow(v2.payload, v2.section, 0)!;
 const v2cell = inspectorFromRow(v2row);
 assert.ok(Math.abs((v2cell.x ?? 0) - 3.025) < 1e-6);
 assert.equal(v2cell.point_count, null);
 assert.equal(readCellRow(v2.payload, v2.section, 5), null);
});

// --- Replay metric honesty ---

test('recorded values label RECORDED; missing values are N/A, never live',()=>{
 assert.equal(formatRecorded(385000, v => v.toLocaleString('en-US')), '385,000 · RECORDED');
 assert.equal(formatRecorded(null, v => String(v)), 'N/A DURING REPLAY');
 assert.equal(formatRecorded(undefined, v => String(v)), 'N/A DURING REPLAY');
 assert.equal(formatRecorded(NaN, v => String(v)), 'N/A DURING REPLAY');
});

test('policy chip prefers the replay header while replaying',()=>{
 assert.equal(replayPolicyName({replay: {active: true, policy: 'utility_lod'}, policy: 'distance_lod'}), 'utility_lod');
 assert.equal(replayPolicyName({replay: {active: false, policy: 'utility_lod'}, policy: 'distance_lod'}), 'distance_lod');
 assert.equal(replayPolicyName({policy: 'distance_lod'}), 'distance_lod');
 assert.equal(replayPolicyName(null), null);
 assert.equal(replayPolicyName({}), null);
});

// --- Sampling transparency ---

test('engine disc sampling and renderer clamp report separately',()=>{
 assert.deepEqual(samplingStatus(385000, 50000, 50000), {total: 385000, wire: 50000, rendered: 50000, engineSampled: true, rendererClamped: false});
 assert.deepEqual(samplingStatus(80000, 80000, 50000), {total: 80000, wire: 80000, rendered: 50000, engineSampled: false, rendererClamped: true});
 assert.deepEqual(samplingStatus(9000, 9000, 9000), {total: 9000, wire: 9000, rendered: 9000, engineSampled: false, rendererClamped: false});
 const missing = samplingStatus(null, undefined, NaN);
 assert.equal(missing.engineSampled, false);
 assert.equal(missing.rendererClamped, false);
});

// --- Anatomy context passthrough ---

test('anatomy carries perception and state context',()=>{
 const model = cellAnatomy({physicalLayers: {ground: {count: 2, mean: 0.09, min: 0.05, max: 0.14}, obstacle: {count: 0, mean: null, min: null, max: null}, overhead: {count: 0, mean: null, min: null, max: null}}, pooled: {mean: 0.09, zmin: 0.05, zmax: 0.14, variance: 0.001, count: 2}, resolution: '5 cm', lod: 0, context: {semantic: 'Road', semanticConfidence: 0.8, motion: 'STATIC', traversability: 'Drivable', quality: 0.9, observations: 2}});
 assert.equal(model.context.semantic, 'Road');
 assert.equal(model.context.traversability, 'Drivable');
 assert.equal(model.context.observations, 2);
 const bare = cellAnatomy({physicalLayers: null, pooled: {mean: null, zmin: null, zmax: null, variance: null, count: null}, resolution: null, lod: null});
 assert.equal(bare.context.semantic, null);
});
