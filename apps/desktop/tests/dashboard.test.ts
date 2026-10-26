import {describe} from 'node:test';
import {test as dashboard_test} from 'node:test';
import assert from 'node:assert/strict';
import {MOTION_FEATURE_ENABLED, comparisonMetrics, datasetFormats, defaultSessionConfig, clampRenderCounts, formatRenderAge, inputTargetFps, isRenderStale, layerUnavailable, mapActivity, perceptionStages, profileConfig, recordEvent, renderAgeMs, summarizeVisual, RENDER_CAPACITY, inspectorRows, lodLabel, resolutionLabel, datasetCapabilities, sessionPhase, GLOSSARY} from '../src/renderer/dashboard.ts';
import {test as judge_clarity_test} from 'node:test';
import {enterJudgeView, exitJudgeView, initialJudgeView, judgeViewPreset} from '../src/renderer/judge-view.ts';
import {bandLabels, cellRangeM, explainResolution, expectedBandForRange, levelFromSize, parsePolicyDescriptor, resolutionLabelForLevel} from '../src/renderer/cell-explain.ts';
import {anatomyRange, cellAnatomy} from '../src/renderer/cell-anatomy.ts';
import {findCellInPayload, inspectorFromRow, readCellRow} from '../src/renderer/cell-lookup.ts';
import {compactRecorded, formatRecorded, replayPolicyName} from '../src/renderer/replay-metrics.ts';
import {samplingStatus} from '../src/renderer/dashboard.ts';
import setup_test from 'node:test';
import {errorRecovery, previewReadiness, runtimeLabel, sessionActive} from '../src/renderer/setup.ts';
import locale_test from 'node:test';
import {safeLocale} from '../src/locale.ts';

describe('dashboard', () => {
  dashboard_test('comparison requires measured matching policy reports and never fabricates reduction',()=>{
   const reduction=(report:any,policy:string)=>comparisonMetrics(report).rows.find(row=>row.policy===policy)!.memoryReduction;
   assert.ok(comparisonMetrics(null).rows.every(row=>row.memory===null&&row.memoryReduction===null));
   const memory=(bytes:number)=>({runs:[{metrics:{memory:{logical_map_bytes:bytes}}}],aggregate:{peak_rss_bytes:bytes*100}});
   assert.equal(reduction({schema_version:2,policies:{uniform5:memory(100),utility_lod:memory(25)}},'utility_lod'),75);
   assert.equal(reduction({schema_version:2,policies:{uniform5:memory(0),utility_lod:memory(25)}},'utility_lod'),null);
   assert.equal(reduction({schema_version:2,policies:{uniform5:memory(100)}},'uniform5'),null,'no reduction against itself');
  });
  dashboard_test('overview comparison uses p95 only when every policy has enough samples',()=>{
   const policy=(count:number)=>({aggregate:{stage_latency_ns:{map_update:{p50:1e6,p95:9e6,count}}}});
   const all=(count:number)=>({schema_version:2,policies:{uniform5:policy(count),uniform40:policy(count),distance_lod:policy(count),utility_lod:policy(count)}});
   assert.equal(comparisonMetrics(all(4)).latencyMetric,'p50');
   assert.equal(comparisonMetrics(all(4)).rows[0].latency,1);
   assert.equal(comparisonMetrics(all(20)).latencyMetric,'p95');
   assert.equal(comparisonMetrics(all(20)).rows[0].latency,9);
  });
  dashboard_test('event log is capped and records observable status transitions without repeated telemetry spam',()=>{
   let events:any[]=[];for(let i=0;i<205;i++)events=recordEvent(events,{type:'status',state:'paused',index:i},i);
   assert.equal(events.length,200);assert.equal(events[0].time,5);
   assert.equal(recordEvent(events,{type:'telemetry',fps:20},206),events);
   assert.equal(recordEvent([], {type:'validation',state:'complete'}, 207)[0].message, 'Validation complete');
  });
  dashboard_test('summary reports displayed semantic points only when semantic evidence exists',()=>{
   const bytes=new Uint8Array(64);const data=new DataView(bytes.buffer);data.setFloat32(16,2,true);data.setFloat32(48,2,true);
   assert.deepEqual(summarizeVisual({metadata:{points:{count:2,offset:0,stride:32},layers:{semantic:'unavailable'}},payload:bytes}),[]);
   const result=summarizeVisual({metadata:{points:{count:2,offset:0,stride:32},layers:{semantic:'available'}},payload:bytes});
   assert.equal(result[0].count,2);assert.equal(result[0].percent,100);
  });
  dashboard_test('product presets coordinate display and runtime governor budgets',()=>{
   const current:any={map:{policy:'utility_lod'},visualization:{point_budget:1}};
   const performance=profileConfig(current,'Performance');
   assert.deepEqual(performance.map,{policy:'utility_lod',resource_profile:'performance',governor_override:'automatic'});
   assert.deepEqual(performance.visualization,{point_budget:20000,cell_budget:10000,update_hz:10});
   assert.equal(profileConfig(current,'Quality').map.resource_profile,'quality');
  });
  dashboard_test('new desktop sessions request ground and terrain evidence by default',()=>{
   const config=defaultSessionConfig();
   assert.deepEqual(config.pipeline,{semantic:{mode:'ground_truth'},ground:{enabled:true,parameter_overrides:{min_range:0,max_range:100}},terrain:{enabled:true},temporal:{enabled:false}});
  });
  dashboard_test('supported runtime datasets and snapshot layer availability stay aligned',()=>{
   assert.deepEqual(datasetFormats.map(item=>item[0]),['generic','semanticposs','semantickitti','rellis3d']);
   const frame:any={metadata:{layers:{utility:'available'}},payload:new Uint8Array()};
   assert.equal(layerUnavailable(frame,'utility'),false);assert.equal(layerUnavailable(frame,'motion'),true);
   const labeled:any={metadata:{layers:{semantic:'ground_truth'}},payload:new Uint8Array()};assert.equal(layerUnavailable(labeled,'semantic'),false);
  });
  dashboard_test('semantic layer flags its n/a badge when semantic evidence is missing',()=>{
   const missing:any={metadata:{layers:{}},payload:new Uint8Array()};
   assert.equal(layerUnavailable(missing,'semantic'),true);
   const unavailable:any={metadata:{layers:{semantic:'unavailable'}},payload:new Uint8Array()};
   assert.equal(layerUnavailable(unavailable,'semantic'),true);
   const available:any={metadata:{layers:{semantic:'available'}},payload:new Uint8Array()};
   assert.equal(layerUnavailable(available,'semantic'),false);
   assert.equal(layerUnavailable(null,'elevation'),false);
   assert.equal(layerUnavailable(null,'lod'),false);
  });
  dashboard_test('perception stage summary keeps backend state distinct from timing',()=>{
   const rows=perceptionStages({metadata:{pipeline_status:{semantic:'model',ground:'available',terrain:'unavailable',temporal:'skipped'},perception_timings_ms:{semantic:12.5,ground:3.2}},payload:new Uint8Array()});
   assert.deepEqual(rows,[{label:'Semantic',status:'model',latency:12.5},{label:'Ground',status:'available',latency:3.2},{label:'Terrain',status:'unavailable',latency:null},...(MOTION_FEATURE_ENABLED?[{label:'Temporal',status:'skipped',latency:null}]:[])]);
  });
  dashboard_test('performance activity exposes measured split and merge rates',()=>{
   const activity=mapActivity({map:{splits_per_second:12.5,merges_per_second:3.25}} as any);
   assert.deepEqual(activity.slice(-2),[['Splits / second',12.5],['Merges / second',3.25]]);
  });
  dashboard_test('input target rate derives from session playback fps and speed without fabrication',()=>{
   assert.equal(inputTargetFps({playback:{fps:10}},{speed:2}),20);
   assert.equal(inputTargetFps({playback:{fps:10}},{}),10);
   assert.equal(inputTargetFps({},{speed:1}),null);
   assert.equal(inputTargetFps({playback:{fps:10}},{speed:0}),null);
   assert.equal(inputTargetFps({playback:{fps:NaN}},{speed:1}),null);
   assert.equal(inputTargetFps({playback:{fps:10}},{speed:NaN}),null);
  });


  dashboard_test('render stats persist with timestamp and mark stale off-Map (G-4)',()=>{
   assert.equal(renderAgeMs({} as any,1000),null);
   assert.equal(renderAgeMs({updated_at:900} as any,1000),100);
   assert.equal(renderAgeMs({updated_at:1100} as any,1000),null);
   assert.equal(isRenderStale({} as any,1000),false);
   assert.equal(isRenderStale({fps:60} as any,1000),true);
   assert.equal(isRenderStale({fps:60,updated_at:900} as any,1000),false);
   assert.equal(isRenderStale({fps:60,updated_at:0} as any,10000),true);
   assert.equal(formatRenderAge({} as any,1000),'—');
   assert.equal(formatRenderAge({updated_at:900} as any,1000),'100 ms ago');
   assert.equal(formatRenderAge({updated_at:0} as any,2500),'2.5 s ago');
  });
  dashboard_test('renderer clamps packed counts to GPU buffer capacity instead of overflowing',()=>{
   assert.deepEqual(clampRenderCounts(10,20),{points:{count:10,truncated:false},cells:{count:20,truncated:false},truncated:false});
   const over=clampRenderCounts(RENDER_CAPACITY+5000,RENDER_CAPACITY+1);
   assert.equal(over.points.count,RENDER_CAPACITY);
   assert.equal(over.cells.count,RENDER_CAPACITY);
   assert.equal(over.truncated,true);
   assert.deepEqual(clampRenderCounts(Number.NaN,undefined),{points:{count:0,truncated:true},cells:{count:0,truncated:true},truncated:true});
   assert.deepEqual(clampRenderCounts(-3,-7),{points:{count:0,truncated:false},cells:{count:0,truncated:false},truncated:false});
   assert.equal(RENDER_CAPACITY,100000);
  });

  dashboard_test('bridge rejections surface as visible error diagnostics instead of vanishing',()=>{
   const rejection={type:'diagnostics',diagnostic:{code:'RUNTIME_EVENT_REJECTED',message:'visualization event must declare schema_version 2'}};
   const events=recordEvent([],rejection,100);
   assert.equal(events.length,1);
   assert.equal(events[0].kind,'error');
   assert.match(events[0].message,/RUNTIME_EVENT_REJECTED/);
   assert.match(events[0].message,/schema_version 2/);
   assert.equal(recordEvent(events,rejection,101).length,1);
   assert.equal(recordEvent([],{type:'telemetry'} as any,102).length,0);
  });
  dashboard_test('v2 production strides decode with real point and cell sections',()=>{
   const points=33329,stride=68,cells=18625;
   const bytes=new Uint8Array(points*stride+cells*36);
   const data=new DataView(bytes.buffer);
   data.setFloat32(16,3,true);
   const frame:any={metadata:{points:{count:points,offset:0,stride},cells:{count:cells,offset:points*stride,stride:36},layers:{semantic:'ground_truth'}},payload:bytes};
   const summary=summarizeVisual(frame);
   assert.equal(summary.find((row:any)=>row.id===3)?.count,1);
   const clamped=clampRenderCounts(points,cells);
   assert.equal(clamped.truncated,false);
   assert.equal(clamped.points.count,points);
   assert.equal(clamped.cells.count,cells);
   const over=clampRenderCounts(250000,180000);
   assert.equal(over.truncated,true);
   assert.equal(over.points.count,RENDER_CAPACITY);
  });
  dashboard_test('new desktop sessions expose the full sequence with bounded display budgets',()=>{
   const value=defaultSessionConfig();
   assert.equal(value.playback.frame_limit,30);
   assert.equal(value.playback.full_sequence,true);
   assert.equal(value.playback.fps,30);
   assert.equal(value.visualization.point_budget,15000);
   assert.equal(value.visualization.cell_budget,10000);
  });
  dashboard_test('cell inspector labels every stored field and never fabricates missing evidence',()=>{
    const full:any={x:1.234,y:-2.5,elevation:4.5,resolution:0.05,lod_level:0,semantic_class:9,motion:0.7,quality:0.8,drivable_evidence:-0.4,utility:0.6,semantic_confidence:0.9,ground_evidence:0.6,terrain_confidence:0.5,geometry_complexity:0.3,point_count:42,height_min:4.1,height_max:4.9,height_variance:0.04};
    const rows=inspectorRows(full);
    const byKey=Object.fromEntries(rows.map(r=>[r.key,r.value]));
    assert.equal(byKey.resolution,'5 cm');assert.equal(byKey.lod,'L0');assert.equal(byKey.count,'42');
    assert.equal(byKey.class,'Road');assert.equal(byKey.trav,'Non-drivable');assert.equal(byKey.motion,MOTION_FEATURE_ENABLED?'MOVING':undefined);
    const empty=Object.fromEntries(inspectorRows({}).map(r=>[r.key,r.value]));
    assert.ok(Object.values(empty).every(v=>v==='Unavailable'||v==='Unknown'));
    assert.equal(empty.trav,'Unavailable');
  });
  dashboard_test('inspector derives LOD from resolution and reports dataset capabilities honestly',()=>{
    assert.equal(lodLabel(null,0.4),'L3');assert.equal(lodLabel(null,NaN),'Unavailable');
    assert.equal(resolutionLabel(0.1),'10 cm');assert.equal(resolutionLabel(NaN),'Unavailable');
    const caps=datasetCapabilities({sequences:[{id:'00',frames:488,labels:488,poses:true,timestamps:false}]},'00');
    assert.equal(caps.semantic,'available');assert.match(caps.motion,/no dataset timestamps/);
    assert.equal(sessionPhase(null,{state:'unconfigured',frames:0},false),'EMPTY');
    assert.equal(sessionPhase({sequences:[]},{state:'unconfigured',frames:0},true),'VALIDATING');
    assert.equal(sessionPhase({sequences:[]},{state:'ready',frames:10},false),'READY');
    assert.ok(Object.keys(GLOSSARY).length>=6);
  });

  dashboard_test('cell selection footer states recent-scan and folded selection honestly',async()=>{
   const {cellSelectionLabel}=await import('../src/renderer/dashboard.ts');
   const f=(v:unknown,d=1)=>typeof v==='number'?v.toLocaleString('en-US',{maximumFractionDigits:d}):'—';
   assert.equal(cellSelectionLabel('all',900,900,0,f),'all 900 map leaves');
   assert.equal(cellSelectionLabel('recent',36046,634091,0,f,1),'36,046 of 634,091 map leaves seen in the last scan');
   assert.equal(cellSelectionLabel('recent',48000,634091,0,f,3),'48,000 of 634,091 map leaves seen in the last 3 scans');
   assert.equal(cellSelectionLabel('folded',10000,107526,12.34,f),'newest scan folded into 10,000 display tiles of 107,526 map leaves · native detail within 12.3 m');
   assert.equal(cellSelectionLabel('folded_nearest',40,3600,0,f),'nearest 40 3.2 m tiles of 3,600 leaves — map exceeds display budget');
   assert.equal(cellSelectionLabel(undefined,10000,107526,undefined,f),'nearest 10,000 of 107,526 to vehicle');
  });
});

describe('judge clarity', () => {
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

  judge_clarity_test('judge view enables the correct viewer state',()=>{
   const current = {viewMode: 'both', view: 'driver', follow: false, mode: 'terrain', boundaries: false, showRings: false};
   const state = judgeViewPreset(current);
   assert.deepEqual(state, {...current, mode: 'semantic', showRings: true});
  });

  judge_clarity_test('entering judge view saves prior state; exiting restores it uncorrupted',()=>{
   const prior = {viewMode: 'both', view: 'orbit', follow: false, mode: 'semantic', boundaries: false, showRings: false};
   const entered = enterJudgeView(prior, initialJudgeView());
   assert.equal(entered.session.active, true);
   assert.deepEqual(entered.state, {...prior, showRings: true});
   const exited = exitJudgeView(entered.session, entered.state);
   assert.deepEqual(exited.state, prior);
   assert.equal(exited.session.active, false);
   assert.equal(exited.session.saved, null);
  });

  judge_clarity_test('re-entering judge view keeps the original saved state',()=>{
   const prior = {viewMode: 'raw', view: 'driver', follow: true, mode: 'terrain', boundaries: true, showRings: false};
   const once = enterJudgeView(prior, initialJudgeView());
   const tweaked = {...once.state, follow: false};
   const twice = enterJudgeView(tweaked, once.session);
   assert.deepEqual(exitJudgeView(twice.session, twice.state).state, prior);
  });

  // --- Policy descriptor parsing ---

  judge_clarity_test('descriptor parses the mapper report; garbage is unavailable, never defaulted',()=>{
   assert.equal(DISTANCE.available, true);
   assert.equal(DISTANCE.name, 'distance_lod');
   assert.deepEqual(bandLabels(DISTANCE), ['0–10 m', '10–30 m', '30–60 m', '60–100 m']);
   for (const raw of [null, undefined, {}, {name: 'distance_lod'}, {name: 'nope'}, {name: 'distance_lod', distance_boundaries_m: [10, 30]}, {name: 'distance_lod', distance_boundaries_m: [30, 10, 60], window_radius_m: 100}, 'x', 42]) {
    const parsed = parsePolicyDescriptor(raw);
    assert.equal(parsed.available, false, JSON.stringify(raw));
    assert.equal(bandLabels(parsed), null);
   }
  });

  judge_clarity_test('custom/non-default distance thresholds flow through, not frontend constants',()=>{
   const custom = descriptor('distance_lod', {distance_boundaries_m: [5, 15, 45], window_radius_m: 80});
   assert.equal(custom.available, true);
   assert.deepEqual(bandLabels(custom), ['0–5 m', '5–15 m', '15–45 m', '45–80 m']);
   assert.equal(expectedBandForRange(custom, 7)?.level, 1);
   assert.equal(expectedBandForRange(custom, 50)?.level, 3);
   assert.equal(resolutionLabelForLevel(custom, 2), '20 cm');
  });

  judge_clarity_test('distance bands map the documented ranges',()=>{
   assert.equal(expectedBandForRange(DISTANCE, 7.8)?.level, 0);
   assert.equal(expectedBandForRange(DISTANCE, 10)?.level, 1);
   assert.equal(expectedBandForRange(DISTANCE, 42.1)?.level, 2);
   assert.equal(expectedBandForRange(DISTANCE, 73.4)?.level, 3);
   assert.equal(expectedBandForRange(DISTANCE, 150), null);
   assert.equal(expectedBandForRange(DISTANCE, NaN), null);
  });

  judge_clarity_test('level derives from stored size',()=>{
   assert.equal(levelFromSize(0.05), 0);
   assert.equal(levelFromSize(0.4), 3);
   assert.equal(levelFromSize(NaN), null);
   assert.equal(levelFromSize(-1), null);
  });

  judge_clarity_test('range needs a full 16-float world pose',()=>{
   assert.equal(cellRangeM(3, 4, [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]), 5);
   assert.equal(cellRangeM(0, 0, null), null);
   assert.equal(cellRangeM(0, 0, [1,2,3]), null);
  });

  // --- Uniform policies: no bands, ever ---

  judge_clarity_test('resolution explanations distinguish policy, missing evidence and actual attribution',()=>{
   const cases: [string, Parameters<typeof explainResolution>[0], [string,string,string|RegExp][]][] = [
    ["uniform5 explains without any distance band", {descriptor: descriptor('uniform5'), policyName: 'uniform5', rangeM: 73.4, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION}, [['verdict', 'equal', 'policy'], ['headline', 'match', /5 cm/], ['detail', 'match', /Distance from robot does not determine/], ['headline + detail', 'doesNotMatch', /10 m|30 m|60 m|band/]]],
    ["uniform40 explains without any distance band", {descriptor: descriptor('uniform40'), policyName: 'uniform40', rangeM: 3.1, level: 3, sizeM: 0.4, evidence: EVIDENCE, attribution: NO_ATTRIBUTION}, [['verdict', 'equal', 'policy'], ['headline', 'match', /40 cm/], ['headline + detail', 'doesNotMatch', /10 m|30 m|60 m|band/]]],
    ["uniform mismatch reports disagreement honestly", {descriptor: descriptor('uniform5'), policyName: 'uniform5', rangeM: 3.1, level: 3, sizeM: 0.4, evidence: EVIDENCE, attribution: NO_ATTRIBUTION}, [['verdict', 'equal', 'mismatch'], ['detail', 'match', /disagreement/]]],
    ["matching band explains the real policy", {descriptor: DISTANCE, policyName: 'distance_lod', rangeM: 7.8, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION}, [['verdict', 'equal', 'policy'], ['headline', 'match', /5 cm/], ['detail', 'match', /7\.8 m from robot/], ['detail', 'match', /DistanceLOD/], ['detail', 'doesNotMatch', /protects this range/]]],
    ["mid-field match carries no protection note", {descriptor: DISTANCE, policyName: 'distance_lod', rangeM: 42.1, level: 2, sizeM: 0.2, evidence: EVIDENCE, attribution: NO_ATTRIBUTION}, [['verdict', 'equal', 'policy'], ['headline', 'match', /20 cm/]]],
    ["finer-than-band without attribution claims nothing", {descriptor: descriptor('utility_lod'), policyName: 'utility_lod', rangeM: 42.1, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION}, [['verdict', 'equal', 'mismatch'], ['detail', 'match', /Utility decision attribution unavailable/], ['detail', 'match', /distance reference is 20 cm/], ['headline + detail', 'doesNotMatch', /better|superior|outperform/]]],
    ["proven attribution explains the refinement", {descriptor: descriptor('utility_lod'), policyName: 'utility_lod', rangeM: 42.1, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: {available: true}}, [['verdict', 'equal', 'promotion'], ['detail', 'match', /decision attribution proves/]]]
   ];
   for(const [name,input,expectations] of cases){
    const out=explainResolution(input);
    for(const [field,operation,expected] of expectations){
     const actual=field==='headline + detail'?out.headline+out.detail:out[field as 'verdict'|'headline'|'detail'];
     if(operation==='equal')assert.equal(actual,expected,name);
     else if(operation==='match')assert.match(actual,expected as RegExp,name);
     else assert.doesNotMatch(actual,expected as RegExp,name);
    }
   }
  });





  // --- DistanceLOD from the active descriptor ---





  judge_clarity_test('custom thresholds change the expected level',()=>{
   const custom = descriptor('distance_lod', {distance_boundaries_m: [5, 15, 45], window_radius_m: 80});
   const out = explainResolution({descriptor: custom, policyName: 'distance_lod', rangeM: 7.8, level: 1, sizeM: 0.1, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
   assert.equal(out.verdict, 'policy');
   assert.match(out.headline, /10 cm/);
  });

  judge_clarity_test('missing descriptor never assumes bands',()=>{
   const out = explainResolution({descriptor: parsePolicyDescriptor(null), policyName: 'distance_lod', rangeM: 7.8, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
   assert.equal(out.verdict, 'unknown');
   assert.match(out.headline + ' ' + out.detail, /policy configuration unavailable/i);
  });

  judge_clarity_test('missing range or level never fabricates',()=>{
   const noRange = explainResolution({descriptor: DISTANCE, policyName: 'distance_lod', rangeM: null, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
   assert.equal(noRange.verdict, 'unknown');
   assert.match(noRange.detail, /pose is unavailable/);
   const noLevel = explainResolution({descriptor: DISTANCE, policyName: 'distance_lod', rangeM: 5, level: null, sizeM: null, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
   assert.equal(noLevel.verdict, 'unknown');
  });

  judge_clarity_test('range past the reported window is outside the map',()=>{
   const out = explainResolution({descriptor: DISTANCE, policyName: 'distance_lod', rangeM: 120, level: 3, sizeM: 0.4, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
   assert.equal(out.verdict, 'mismatch');
   assert.match(out.headline + ' ' + out.detail, /outside the mapped range/);
  });

  // --- UtilityLOD: attribution or explicit unavailability ---





  judge_clarity_test('utility at reference level shows signals without claiming promotion',()=>{
   const out = explainResolution({descriptor: descriptor('utility_lod'), policyName: 'utility_lod', rangeM: 42.1, level: 2, sizeM: 0.2, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
   assert.equal(out.verdict, 'policy');
   assert.ok(out.signals.some(s => s.startsWith('utility')));
   assert.match(out.detail, /no promotion is proven/);
  });

  judge_clarity_test('protection note appears only with a reported radius',()=>{
   const near = explainResolution({descriptor: descriptor('utility_lod'), policyName: 'utility_lod', rangeM: 7.8, level: 0, sizeM: 0.05, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
   assert.match(near.detail, /near-field radius protects/);
   const far = explainResolution({descriptor: descriptor('utility_lod'), policyName: 'utility_lod', rangeM: 42.1, level: 2, sizeM: 0.2, evidence: EVIDENCE, attribution: NO_ATTRIBUTION});
   assert.doesNotMatch(far.detail, /protects/);
  });

  // --- Semantic names, not bare IDs ---

  judge_clarity_test('semantic class renders human-readable',()=>{
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

  judge_clarity_test('anatomy separates ground, obstacle, overhead evidence',()=>{
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

  judge_clarity_test('ground absent without proof is unobserved, not occluded',()=>{
   const model = cellAnatomy({
     physicalLayers: {ground: {count: 0, mean: null, min: null, max: null}, obstacle: {count: 5, mean: 1.2, min: 0.4, max: 2.0}, overhead: {count: 0, mean: null, min: null, max: null}},
     pooled: {mean: 1.2, zmin: 0.4, zmax: 2.0, variance: 0.2, count: 5}, resolution: '10 cm', lod: 1});
   assert.equal(model.groundUnobserved, true);
   assert.ok(model.notes.some(n => n.includes('Ground unobserved')));
   assert.ok(!model.notes.some(n => n.toLowerCase().includes('occluded')));
   assert.ok(model.notes.some(n => n.includes('never drivable')));
  });

  judge_clarity_test('missing section is unavailable, all-empty clears nothing',()=>{
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





  function payloadWithCells(rows: number[][], stride = 17): {payload: Uint8Array; section: {count: number; offset: number; stride: number}} {
   const floats = rows.length * stride;
   const buffer = new Float32Array(floats).fill(Number.NaN);
   rows.forEach((row, i) => row.forEach((v, j) => { buffer[i * stride + j] = v; }));
   const bytes = new Uint8Array(buffer.buffer);
   return {payload: bytes, section: {count: rows.length, offset: 0, stride: stride * 4}};
  }

  const ROW_A = [3.025, -9.85, 0.09, 0.05, 9, 0, 0.9, 1.5, 0.2, 0.8, 2.1, 0.7, 0.1, 40, 0.05, 0.14, 0.001];
  const ROW_B = [10.05, 4.05, 0.5, 0.2, 3, 0, 0.8, 0, 0.1, 0.6, 0, 0.5, 0.3, 120, 0.3, 0.7, 0.01];

  judge_clarity_test('selection re-resolves the same world cell in a new frame',()=>{
   const {payload, section} = payloadWithCells([ROW_A, ROW_B]);
   assert.equal(findCellInPayload(payload, section, 3.025, -9.85, 0.05), 0);
   assert.equal(findCellInPayload(payload, section, 10.05, 4.05, 0.2), 1);
  });

  judge_clarity_test('merged-away cell falls back to the smallest containing owner',()=>{
   const big = [3.1, -9.9, 0.09, 0.2, 9, 0, 0.9, 1.5, 0.2, 0.8, 2.1, 0.7, 0.1, 200, 0.0, 0.2, 0.004];
   const {payload, section} = payloadWithCells([big]);
   assert.equal(findCellInPayload(payload, section, 3.025, -9.85, 0.05), 0);
  });

  judge_clarity_test('evicted cell returns null so selection clears with a message',()=>{
   const {payload, section} = payloadWithCells([ROW_B]);
   assert.equal(findCellInPayload(payload, section, 3.025, -9.85, 0.05), null);
   assert.equal(findCellInPayload(payload, section, NaN, 0, 0.05), null);
   const bad = {...section, stride: 40};
   assert.equal(findCellInPayload(payload, bad, 3.025, -9.85, 0.05), null);
  });

  judge_clarity_test('inspector builder matches click and refresh paths exactly',()=>{
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

  judge_clarity_test('recorded values label RECORDED; missing values are N/A, never live',()=>{
   assert.equal(formatRecorded(385000, v => v.toLocaleString('en-US')), '385,000 · RECORDED');
   assert.equal(formatRecorded(null, v => String(v)), 'N/A DURING REPLAY');
   assert.equal(formatRecorded(undefined, v => String(v)), 'N/A DURING REPLAY');
   assert.equal(formatRecorded(NaN, v => String(v)), 'N/A DURING REPLAY');
  });

  judge_clarity_test('compact recorded chips keep the full honesty label in the tooltip',()=>{
   assert.deepEqual(compactRecorded(492206, v => v.toLocaleString('en-US')), {text: '492,206', title: '492,206 · RECORDED'});
   assert.deepEqual(compactRecorded(null, v => String(v)), {text: 'N/A', title: 'N/A DURING REPLAY'});
  });

  judge_clarity_test('policy chip prefers the replay header while replaying',()=>{
   assert.equal(replayPolicyName({replay: {active: true, policy: 'utility_lod'}, policy: 'distance_lod'}), 'utility_lod');
   assert.equal(replayPolicyName({replay: {active: false, policy: 'utility_lod'}, policy: 'distance_lod'}), 'distance_lod');
   assert.equal(replayPolicyName({policy: 'distance_lod'}), 'distance_lod');
   assert.equal(replayPolicyName(null), null);
   assert.equal(replayPolicyName({}), null);
  });

  // --- Sampling transparency ---

  judge_clarity_test('engine disc sampling and renderer clamp report separately',()=>{
   assert.deepEqual(samplingStatus(385000, 50000, 50000), {total: 385000, wire: 50000, rendered: 50000, engineSampled: true, rendererClamped: false});
   assert.deepEqual(samplingStatus(80000, 80000, 50000), {total: 80000, wire: 80000, rendered: 50000, engineSampled: false, rendererClamped: true});
   assert.deepEqual(samplingStatus(9000, 9000, 9000), {total: 9000, wire: 9000, rendered: 9000, engineSampled: false, rendererClamped: false});
   const missing = samplingStatus(null, undefined, NaN);
   assert.equal(missing.engineSampled, false);
   assert.equal(missing.rendererClamped, false);
  });

  // --- Anatomy context passthrough ---

  judge_clarity_test('anatomy carries perception and state context',()=>{
   const model = cellAnatomy({physicalLayers: {ground: {count: 2, mean: 0.09, min: 0.05, max: 0.14}, obstacle: {count: 0, mean: null, min: null, max: null}, overhead: {count: 0, mean: null, min: null, max: null}}, pooled: {mean: 0.09, zmin: 0.05, zmax: 0.14, variance: 0.001, count: 2}, resolution: '5 cm', lod: 0, context: {semantic: 'Road', semanticConfidence: 0.8, motion: 'STATIC', traversability: 'Drivable', quality: 0.9, observations: 2}});
   assert.equal(model.context.semantic, 'Road');
   assert.equal(model.context.traversability, 'Drivable');
   assert.equal(model.context.observations, 2);
   const bare = cellAnatomy({physicalLayers: null, pooled: {mean: null, zmin: null, zmax: null, variance: null, count: null}, resolution: null, lod: null});
   assert.equal(bare.context.semantic, null);
  });
});

describe('setup', () => {
  const catalog = {root: '/datasets/poss', sequences: [{id: '00', frames: 488}, {id: '01', frames: 0}]};

  setup_test('preview requires a discovered, non-empty selected sequence', () => {
    assert.equal(previewReadiness(null, '', false).ready, false);
    assert.equal(previewReadiness(catalog, 'missing', false).ready, false);
    assert.equal(previewReadiness(catalog, '01', false).ready, false);
    assert.equal(previewReadiness(catalog, '00', false).ready, true);
    assert.equal(previewReadiness(catalog, '00', true).ready, false);
    assert.equal(previewReadiness({...catalog, root: ''}, '00', false).ready, false);
  });

  setup_test('session actions follow runtime truth even if a stopped status retains dataset metadata', () => {
    assert.equal(sessionActive({state: 'stopped', dataset: 'semanticposs', frames: 488}), false);
    assert.equal(sessionActive({state: 'error', dataset: 'semanticposs'}), false);
    assert.equal(sessionActive({state: 'running', dataset: 'semanticposs'}), true);
    assert.equal(sessionActive({state: 'paused', dataset: 'semanticposs'}), true);
  });

  setup_test('runtime states have plain user labels and preserve unknown backend states', () => {
    assert.equal(runtimeLabel('unconfigured'), 'No session');
    assert.equal(runtimeLabel('running'), 'Playing');
    assert.equal(runtimeLabel('paused'), 'Paused');
    assert.equal(runtimeLabel('stopped'), 'Stopped');
    assert.equal(runtimeLabel('recovering'), 'recovering');
  });

  setup_test('changing the display profile preserves the selected resolution policy', () => {
    for (const name of ['LowResource', 'Performance', 'Balanced', 'Quality']) {
      assert.equal(profileConfig({map: {policy: 'utility_lod'}}, name).map.policy, 'utility_lod');
    }
  });

  setup_test('invalid configuration and missing dependencies do not suggest blind restart', () => {
    assert.equal(errorRecovery('SyntaxError: Unexpected token in JSON').restart, false);
    const missing = errorRecovery("runtime exited: exit status: 1: ModuleNotFoundError: No module named numpy");
    assert.equal(missing.restart, false);
    assert.match(missing.action, /Python|backend/);
    assert.equal(errorRecovery('MODEL_NOT_FOUND: checkpoint missing').restart, false);
    assert.equal(errorRecovery('PROTOCOL_VERSION_MISMATCH').restart, false);
  });

  setup_test('unexpected process exit keeps a real recovery path without claiming success', () => {
    const advice = errorRecovery('CONTROLLER_ERROR: runtime process error: runtime exited: exit status: 1');
    assert.equal(advice.restart, true);
    assert.match(advice.action, /Diagnostics/);
    assert.match(advice.title, /stopped/);
  });

  setup_test('unknown errors remain errors and recommend evidence, not a fabricated diagnosis', () => {
    const advice = errorRecovery('Something unexpected happened');
    assert.equal(advice.restart, false);
    assert.match(advice.action, /Diagnostics/);
    assert.match(errorRecovery('WEBGL_UNAVAILABLE').action, /WebGL/);
  });
});

describe('locale', () => {
  locale_test('locale inputs normalize to valid browser tags',()=>{
   for(const [input,expected] of [['C','en-US'],['en-IN','en-IN'],['not a locale','en-US']] as const){
    assert.equal(safeLocale(input),expected,String(input));
   }
  });




});
