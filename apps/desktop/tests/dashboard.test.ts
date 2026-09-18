import {test} from 'node:test';import assert from 'node:assert/strict';
import {comparisonMetrics,datasetFormats,defaultSessionConfig, FIRST_CPU_SAMPLE_NOTE, formatRenderAge, inputTargetFps,isRenderStale,layerUnavailable,mapActivity,MEMORY_DOMAIN_NOTE,perceptionStages,profileConfig,recordEvent, renderAgeMs,summarizeVisual} from '../src/renderer/dashboard.ts';
test('comparison requires measured matching policy reports and never fabricates reduction',()=>{
 assert.equal(comparisonMetrics(null).memoryReduction,null);
 assert.equal(comparisonMetrics({policies:{uniform5:{aggregate:{peak_rss_bytes:100}},utility_lod:{aggregate:{peak_rss_bytes:25}}}}).memoryReduction,75);
 assert.equal(comparisonMetrics({policies:{uniform5:{aggregate:{peak_rss_bytes:0}},utility_lod:{aggregate:{peak_rss_bytes:25}}}}).memoryReduction,null);
});
test('event log is capped and records observable status transitions without repeated telemetry spam',()=>{
 let events:any[]=[];for(let i=0;i<205;i++)events=recordEvent(events,{type:'status',state:'paused',index:i},i);
 assert.equal(events.length,200);assert.equal(events[0].time,5);
 assert.equal(recordEvent(events,{type:'telemetry',fps:20},206),events);
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
