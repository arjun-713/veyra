import {test} from 'node:test';import assert from 'node:assert/strict';
import {comparisonMetrics,datasetFormats,governorEvent,layerUnavailable,mapActivity,metricTrend,profileConfig,recordEvent,summarizeVisual} from '../src/renderer/dashboard.ts';
test('comparison requires measured matching policy reports and never fabricates reduction',()=>{
 assert.equal(comparisonMetrics(null).memoryReduction,null);
 assert.equal(comparisonMetrics({policies:{uniform5:{aggregate:{peak_rss_bytes:100}},utility_lod:{aggregate:{peak_rss_bytes:25}}}}).memoryReduction,75);
 assert.equal(comparisonMetrics({policies:{uniform5:{aggregate:{peak_rss_bytes:0}},utility_lod:{aggregate:{peak_rss_bytes:25}}}}).memoryReduction,null);
});
test('event log is capped and records observable status transitions without repeated telemetry spam',()=>{
 let events:any[]=[];for(let i=0;i<205;i++)events=recordEvent(events,{type:'status',state:`state-${i}`,index:i},i);
 assert.equal(events.length,200);assert.equal(events[0].time,5);
 const stable=recordEvent(events,{type:'status',state:'state-204',index:999},206);assert.equal(stable,events);
 assert.equal(recordEvent(events,{type:'telemetry',fps:20},206),events);
});
test('one-minute trends require sufficient measured coverage and preserve direction',()=>{
 assert.equal(metricTrend([{timestamp:1,fps:10},{timestamp:11,fps:12}],'fps'),null);
 assert.deepEqual(metricTrend([{timestamp:1,fps:10},{timestamp:46,fps:13}],'fps'),{delta:3,baseline:10,current:13,coveredMs:45000});
 assert.equal(metricTrend([{timestamp:1,fps:null},{timestamp:61,fps:13}],'fps'),null);
});
test('governor events are emitted only for state changes or measured interventions',()=>{
 const previous:any={state:'nominal',interventions:2,actions_applied:1};
 assert.equal(governorEvent(previous,{...previous}),null);
 assert.deepEqual(governorEvent(previous,{state:'limited',interventions:3,actions_applied:5,allow_optional_splits:false}),{type:'governor',state:'limited',interventions:1,actions:4,allow_optional_splits:false});
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
test('supported runtime datasets and snapshot layer availability stay aligned',()=>{
 assert.deepEqual(datasetFormats.map(item=>item[0]),['generic','semanticposs','semantickitti','rellis3d']);
 const frame:any={metadata:{layers:{utility:'available'}},payload:new Uint8Array()};
 assert.equal(layerUnavailable(frame,'utility'),false);assert.equal(layerUnavailable(frame,'motion'),true);
 const labeled:any={metadata:{layers:{semantic:'ground_truth'}},payload:new Uint8Array()};assert.equal(layerUnavailable(labeled,'semantic'),false);
});
test('performance activity exposes measured split and merge rates',()=>{
 const activity=mapActivity({map:{splits_per_second:12.5,merges_per_second:3.25}} as any);
 assert.deepEqual(activity.slice(-2),[['Splits / second',12.5],['Merges / second',3.25]]);
});
