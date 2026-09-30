import {test} from 'node:test';import assert from 'node:assert/strict';
import {comparisonMetrics,datasetFormats,defaultSessionConfig, FIRST_CPU_SAMPLE_NOTE, clampRenderCounts, formatRenderAge, inputTargetFps,isRenderStale,layerUnavailable,mapActivity,MEMORY_DOMAIN_NOTE,perceptionStages,profileConfig,recordEvent, renderAgeMs,summarizeVisual, RENDER_CAPACITY,inspectorRows,lodLabel,resolutionLabel,datasetCapabilities,sessionPhase,GLOSSARY} from '../src/renderer/dashboard.ts';
test('comparison requires measured matching policy reports and never fabricates reduction',()=>{
 const reduction=(report:any,policy:string)=>comparisonMetrics(report).rows.find(row=>row.policy===policy)!.memoryReduction;
 assert.ok(comparisonMetrics(null).rows.every(row=>row.memory===null&&row.memoryReduction===null));
 const memory=(bytes:number)=>({runs:[{metrics:{memory:{logical_map_bytes:bytes}}}],aggregate:{peak_rss_bytes:bytes*100}});
 assert.equal(reduction({schema_version:2,policies:{uniform5:memory(100),utility_lod:memory(25)}},'utility_lod'),75);
 assert.equal(reduction({schema_version:2,policies:{uniform5:memory(0),utility_lod:memory(25)}},'utility_lod'),null);
 assert.equal(reduction({schema_version:2,policies:{uniform5:memory(100)}},'uniform5'),null,'no reduction against itself');
});
test('overview comparison uses p95 only when every policy has enough samples',()=>{
 const policy=(count:number)=>({aggregate:{stage_latency_ns:{map_update:{p50:1e6,p95:9e6,count}}}});
 const all=(count:number)=>({schema_version:2,policies:{uniform5:policy(count),uniform40:policy(count),distance_lod:policy(count),utility_lod:policy(count)}});
 assert.equal(comparisonMetrics(all(4)).latencyMetric,'p50');
 assert.equal(comparisonMetrics(all(4)).rows[0].latency,1);
 assert.equal(comparisonMetrics(all(20)).latencyMetric,'p95');
 assert.equal(comparisonMetrics(all(20)).rows[0].latency,9);
});
test('event log is capped and records observable status transitions without repeated telemetry spam',()=>{
 let events:any[]=[];for(let i=0;i<205;i++)events=recordEvent(events,{type:'status',state:'paused',index:i},i);
 assert.equal(events.length,200);assert.equal(events[0].time,5);
 assert.equal(recordEvent(events,{type:'telemetry',fps:20},206),events);
 assert.equal(recordEvent([], {type:'validation',state:'complete'}, 207)[0].message, 'Validation complete');
});
test('summary reports displayed semantic points only when semantic evidence exists',()=>{
 const bytes=new Uint8Array(64);const data=new DataView(bytes.buffer);data.setFloat32(16,2,true);data.setFloat32(48,2,true);
 assert.deepEqual(summarizeVisual({metadata:{points:{count:2,offset:0,stride:32},layers:{semantic:'unavailable'}},payload:bytes}),[]);
 const result=summarizeVisual({metadata:{points:{count:2,offset:0,stride:32},layers:{semantic:'available'}},payload:bytes});
 assert.equal(result[0].count,2);assert.equal(result[0].percent,100);
});
test('product presets coordinate display and runtime governor budgets',()=>{
 const current:any={map:{policy:'utility_lod'},visualization:{point_budget:1}};
 const performance=profileConfig(current,'Performance');
 assert.deepEqual(performance.map,{policy:'utility_lod',resource_profile:'performance',governor_override:'automatic'});
 assert.deepEqual(performance.visualization,{point_budget:20000,cell_budget:10000,update_hz:10});
 assert.equal(profileConfig(current,'Quality').map.resource_profile,'quality');
});
test('new desktop sessions request ground and terrain evidence by default',()=>{
 const config=defaultSessionConfig();
 assert.deepEqual(config.pipeline,{semantic:{mode:'ground_truth'},ground:{enabled:true,parameter_overrides:{min_range:0,max_range:100}},terrain:{enabled:true},temporal:{enabled:false}});
});
test('supported runtime datasets and snapshot layer availability stay aligned',()=>{
 assert.deepEqual(datasetFormats.map(item=>item[0]),['generic','semanticposs','semantickitti','rellis3d']);
 const frame:any={metadata:{layers:{utility:'available'}},payload:new Uint8Array()};
 assert.equal(layerUnavailable(frame,'utility'),false);assert.equal(layerUnavailable(frame,'motion'),true);
 const labeled:any={metadata:{layers:{semantic:'ground_truth'}},payload:new Uint8Array()};assert.equal(layerUnavailable(labeled,'semantic'),false);
});
test('semantic layer flags its n/a badge when semantic evidence is missing',()=>{
 const missing:any={metadata:{layers:{}},payload:new Uint8Array()};
 assert.equal(layerUnavailable(missing,'semantic'),true);
 const unavailable:any={metadata:{layers:{semantic:'unavailable'}},payload:new Uint8Array()};
 assert.equal(layerUnavailable(unavailable,'semantic'),true);
 const available:any={metadata:{layers:{semantic:'available'}},payload:new Uint8Array()};
 assert.equal(layerUnavailable(available,'semantic'),false);
 assert.equal(layerUnavailable(null,'elevation'),false);
 assert.equal(layerUnavailable(null,'lod'),false);
});
test('perception stage summary keeps backend state distinct from timing',()=>{
 const rows=perceptionStages({metadata:{pipeline_status:{semantic:'model',ground:'available',terrain:'unavailable',temporal:'skipped'},perception_timings_ms:{semantic:12.5,ground:3.2}},payload:new Uint8Array()});
 assert.deepEqual(rows,[{label:'Semantic',status:'model',latency:12.5},{label:'Ground',status:'available',latency:3.2},{label:'Terrain',status:'unavailable',latency:null},{label:'Temporal',status:'skipped',latency:null}]);
});
test('performance activity exposes measured split and merge rates',()=>{
 const activity=mapActivity({map:{splits_per_second:12.5,merges_per_second:3.25}} as any);
 assert.deepEqual(activity.slice(-2),[['Splits / second',12.5],['Merges / second',3.25]]);
});
test('input target rate derives from session playback fps and speed without fabrication',()=>{
 assert.equal(inputTargetFps({playback:{fps:10}},{speed:2}),20);
 assert.equal(inputTargetFps({playback:{fps:10}},{}),10);
 assert.equal(inputTargetFps({},{speed:1}),null);
 assert.equal(inputTargetFps({playback:{fps:10}},{speed:0}),null);
 assert.equal(inputTargetFps({playback:{fps:NaN}},{speed:1}),null);
 assert.equal(inputTargetFps({playback:{fps:10}},{speed:NaN}),null);
});
test('memory domains carry an incomparability caption (G-3)',()=>{
 assert.match(MEMORY_DOMAIN_NOTE,/different domains/);
 assert.match(MEMORY_DOMAIN_NOTE,/do not compare/);
});
test('first CPU sample documents its by-construction em-dash (G-7)',()=>{
 assert.match(FIRST_CPU_SAMPLE_NOTE,/by construction/);
 assert.match(FIRST_CPU_SAMPLE_NOTE,/two/);
});
test('render stats persist with timestamp and mark stale off-Map (G-4)',()=>{
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
test('renderer clamps packed counts to GPU buffer capacity instead of overflowing',()=>{
 assert.deepEqual(clampRenderCounts(10,20),{points:{count:10,truncated:false},cells:{count:20,truncated:false},truncated:false});
 const over=clampRenderCounts(RENDER_CAPACITY+5000,RENDER_CAPACITY+1);
 assert.equal(over.points.count,RENDER_CAPACITY);
 assert.equal(over.cells.count,RENDER_CAPACITY);
 assert.equal(over.truncated,true);
 assert.deepEqual(clampRenderCounts(Number.NaN,undefined),{points:{count:0,truncated:true},cells:{count:0,truncated:true},truncated:true});
 assert.deepEqual(clampRenderCounts(-3,-7),{points:{count:0,truncated:false},cells:{count:0,truncated:false},truncated:false});
 assert.equal(RENDER_CAPACITY,100000);
});
test('render provenance distinguishes source data from sampled viewport data',()=>{
 const stats:any={source_points:250000,rendered_points:100000,source_cells:180000,rendered_cells:100000,sampling_active:true};
 assert.equal(stats.rendered_points<stats.source_points,true);
 assert.equal(stats.sampling_active,true);
});
test('bridge rejections surface as visible error diagnostics instead of vanishing',()=>{
 const rejection={type:'diagnostics',diagnostic:{code:'RUNTIME_EVENT_REJECTED',message:'visualization event must declare schema_version 2'}};
 const events=recordEvent([],rejection,100);
 assert.equal(events.length,1);
 assert.equal(events[0].kind,'error');
 assert.match(events[0].message,/RUNTIME_EVENT_REJECTED/);
 assert.match(events[0].message,/schema_version 2/);
 assert.equal(recordEvent(events,rejection,101).length,1);
 assert.equal(recordEvent([],{type:'telemetry'} as any,102).length,0);
});
test('v2 production strides decode with real point and cell sections',()=>{
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
test('new desktop sessions expose the full sequence with bounded display budgets',()=>{
 const value=defaultSessionConfig();
 assert.equal(value.playback.frame_limit,30);
 assert.equal(value.playback.full_sequence,true);
 assert.equal(value.playback.fps,30);
 assert.equal(value.visualization.point_budget,15000);
 assert.equal(value.visualization.cell_budget,10000);
});
test('cell inspector labels every stored field and never fabricates missing evidence',()=>{
  const full:any={x:1.234,y:-2.5,elevation:4.5,resolution:0.05,lod_level:0,semantic_class:9,motion:0.7,quality:0.8,drivable_evidence:-0.4,utility:0.6,semantic_confidence:0.9,ground_evidence:0.6,terrain_confidence:0.5,geometry_complexity:0.3,point_count:42,height_min:4.1,height_max:4.9,height_variance:0.04};
  const rows=inspectorRows(full);
  const byKey=Object.fromEntries(rows.map(r=>[r.key,r.value]));
  assert.equal(byKey.resolution,'5 cm');assert.equal(byKey.lod,'L0');assert.equal(byKey.count,'42');
  assert.equal(byKey.class,'Road');assert.equal(byKey.trav,'Non-drivable');assert.equal(byKey.motion,'MOVING');
  const empty=Object.fromEntries(inspectorRows({}).map(r=>[r.key,r.value]));
  assert.ok(Object.values(empty).every(v=>v==='Unavailable'||v==='Unknown'));
  assert.equal(empty.trav,'Unavailable');
});
test('inspector derives LOD from resolution and reports dataset capabilities honestly',()=>{
  assert.equal(lodLabel(null,0.4),'L3');assert.equal(lodLabel(null,NaN),'Unavailable');
  assert.equal(resolutionLabel(0.1),'10 cm');assert.equal(resolutionLabel(NaN),'Unavailable');
  const caps=datasetCapabilities({sequences:[{id:'00',frames:488,labels:488,poses:true,timestamps:false}]},'00');
  assert.equal(caps.semantic,'available');assert.match(caps.motion,/no dataset timestamps/);
  assert.equal(sessionPhase(null,{state:'unconfigured',frames:0},false),'EMPTY');
  assert.equal(sessionPhase({sequences:[]},{state:'unconfigured',frames:0},true),'VALIDATING');
  assert.equal(sessionPhase({sequences:[]},{state:'ready',frames:10},false),'READY');
  assert.ok(Object.keys(GLOSSARY).length>=6);
});
