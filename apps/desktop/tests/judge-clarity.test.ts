import {test} from 'node:test';
import assert from 'node:assert/strict';
import {enterJudgeView, exitJudgeView, initialJudgeView, judgeViewPreset} from '../src/renderer/judge-view.ts';
import {cellRangeM, DISTANCE_BANDS, expectedBandForRange, explainResolution, levelFromSize} from '../src/renderer/cell-explain.ts';
import {anatomyRange, cellAnatomy} from '../src/renderer/cell-anatomy.ts';

const EVIDENCE = {utility: 0.2, quality: 0.9, geometryComplexity: 0.4, semanticConfidence: 0.8, semanticClass: 9, motion: 0, drivableEvidence: 1.5, groundEvidence: 2.1};

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

// --- Resolution bands ---

test('distance bands map the documented ranges',()=>{
 assert.equal(DISTANCE_BANDS.length, 4);
 assert.equal(expectedBandForRange(7.8)?.level, 0);
 assert.equal(expectedBandForRange(10)?.level, 1);
 assert.equal(expectedBandForRange(42.1)?.level, 2);
 assert.equal(expectedBandForRange(73.4)?.level, 3);
 assert.equal(expectedBandForRange(150), null);
 assert.equal(expectedBandForRange(NaN), null);
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

// --- Why this resolution? ---

test('matching band explains the real policy',()=>{
 const out = explainResolution({policy: 'distance_lod', rangeM: 7.8, level: 0, sizeM: 0.05, evidence: EVIDENCE, promotionProven: false});
 assert.equal(out.verdict, 'policy');
 assert.match(out.headline, /5 cm/);
 assert.match(out.detail, /7\.8 m from robot/);
 assert.match(out.detail, /DistanceLOD/);
 assert.match(out.detail, /never coarsens the safety-protected near-field/);
});

test('mid-field match carries no near-field note',()=>{
 const out = explainResolution({policy: 'distance_lod', rangeM: 42.1, level: 2, sizeM: 0.2, evidence: EVIDENCE, promotionProven: false});
 assert.equal(out.verdict, 'policy');
 assert.match(out.headline, /20 cm/);
 assert.doesNotMatch(out.detail, /near-field/);
});

test('missing range or level never fabricates',()=>{
 const noRange = explainResolution({policy: 'distance_lod', rangeM: null, level: 0, sizeM: 0.05, evidence: EVIDENCE, promotionProven: false});
 assert.equal(noRange.verdict, 'unknown');
 assert.match(noRange.detail, /pose is unavailable/);
 const noLevel = explainResolution({policy: 'distance_lod', rangeM: 5, level: null, sizeM: null, evidence: EVIDENCE, promotionProven: false});
 assert.equal(noLevel.verdict, 'unknown');
});

test('finer-than-band without proof claims nothing',()=>{
 const out = explainResolution({policy: 'distance_lod', rangeM: 42.1, level: 0, sizeM: 0.05, evidence: EVIDENCE, promotionProven: false});
 assert.equal(out.verdict, 'mismatch');
 assert.match(out.detail, /Promotion telemetry is required/);
 assert.doesNotMatch(out.headline + out.detail, /UtilityLOD.*better|better.*UtilityLOD/);
});

test('proven promotion explains with genuine signals only',()=>{
 const out = explainResolution({policy: 'utility_lod', rangeM: 42.1, level: 0, sizeM: 0.05, evidence: EVIDENCE, promotionProven: true});
 assert.equal(out.verdict, 'promotion');
 assert.match(out.detail, /promotion telemetry proves/);
});

test('utility policy without proof still shows measured signals honestly',()=>{
 const out = explainResolution({policy: 'utility_lod', rangeM: 42.1, level: 2, sizeM: 0.2, evidence: EVIDENCE, promotionProven: false});
 assert.equal(out.verdict, 'policy');
 assert.ok(out.signals.some(s => s.startsWith('utility')));
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
 assert.equal(model.occluded, false);
 const range = anatomyRange(model)!;
 assert.ok(range.lo <= 0.05 && range.hi >= 0.14);
});

test('occluded ground is unknown, never drivable',()=>{
 const model = cellAnatomy({
   physicalLayers: {ground: {count: 0, mean: null, min: null, max: null}, obstacle: {count: 5, mean: 1.2, min: 0.4, max: 2.0}, overhead: {count: 0, mean: null, min: null, max: null}},
   pooled: {mean: 1.2, zmin: 0.4, zmax: 2.0, variance: 0.2, count: 5}, resolution: '10 cm', lod: 1});
 assert.equal(model.occluded, true);
 assert.ok(model.notes.some(n => n.includes('occluded')));
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
