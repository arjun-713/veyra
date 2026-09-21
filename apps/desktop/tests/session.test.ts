import {test} from 'node:test';
import assert from 'node:assert/strict';
import {canPlayback, telemetryFreshness, processRss, acceptFrame, diagnosticMessage, mergeSessionStatus} from '../src/renderer/session.ts';
import {benchmarkEvidence, validationOutcome} from '../src/renderer/session.ts';

test('completed validation displays the actual verdict, never a generic success',()=>{
 assert.equal(validationOutcome({state:'complete',result:{status:'pass'}}),'pass');
 assert.equal(validationOutcome({state:'complete',result:{status:'fail'}}),'fail');
 assert.equal(validationOutcome({state:'complete'}),'fail');
 assert.equal(validationOutcome({state:'running'}),'running');
});

test('late visualization cannot resurrect a stopped session',()=>{
 assert.equal(acceptFrame({metadata:{} as any,payload:new Uint8Array()},null,'stopped'),false);
});

test('comparison reads measured memory and quality from the real report envelope',()=>{
 const row=benchmarkEvidence({aggregate:{final_leaves_per_level:{'0':2,'1':3},quality:[{elevation_vs_fine_reference:{rmse_m:0.125}}]},runs:[{metrics:{memory:{logical_map_bytes:4096}}}]});
 assert.equal(row.logicalBytes,4096);
 assert.equal(row.leaves,5);
 assert.equal(row.rmse,0.125);
 assert.equal(benchmarkEvidence({}).leaves,null);
});

test('layer acknowledgement does not erase dataset and playback metadata',()=>{
 const status=mergeSessionStatus({state:'paused',dataset:'semanticposs',frames:488,index:4},{state:'ready',layer:'elevation'});
 assert.equal(status.frames,488);
 assert.equal(status.index,4);
 assert.equal(status.dataset,'semanticposs');
 assert.equal(status.layer,'elevation');
});

test('frame acceptance rejects an overlapping binary layout',()=>{
 const frame={metadata:{schema_version:2,generation:1,index:0,points:{offset:0,count:1,stride:68},cells:{offset:0,count:1,stride:36}},payload:new Uint8Array(104)};
 assert.throws(()=>acceptFrame(frame,null),/overlap/);
});

test('playback requires a configured healthy session and no pending operation',()=>{
 for(const state of ['unconfigured','error','stopped','loading']) assert.equal(canPlayback({state,frames:10},false),false);
 assert.equal(canPlayback({state:'paused',frames:10},false),true);
 assert.equal(canPlayback({state:'ready',frames:0},false),false);
 assert.equal(canPlayback({state:'running',frames:10},true),false);
});
test('freshness expires without a new event and missing telemetry is never fresh',()=>{
 assert.equal(telemetryFreshness({},100000),'Waiting');
 assert.equal(telemetryFreshness({timestamp:99},100000),'Fresh');
 assert.equal(telemetryFreshness({timestamp:60},100000),'Stale');
});
test('memory cannot turn absent or partially measured processes into zero or total RSS',()=>{
 assert.equal(processRss([]),null);
 assert.equal(processRss([{rss_bytes:100},{rss_bytes:null}]),null);
 assert.equal(processRss([{rss_bytes:100},{rss_bytes:200}]),300);
});
test('frame acceptance validates bytes and allows backward seek with a newer generation',()=>{
 const metadata={schema_version:2,generation:2,index:1,points:{offset:0,count:1,stride:68},cells:{offset:68,count:0,stride:36}};
 const next={metadata,payload:new Uint8Array(68)};
 assert.equal(acceptFrame(next,{metadata:{generation:1,index:99},payload:new Uint8Array()}),true);
 assert.equal(acceptFrame(next,{metadata:{generation:3,index:1},payload:new Uint8Array()}),false);
 assert.throws(()=>acceptFrame({...next,payload:new Uint8Array(4)},null),/bounds/);
});
test('rejected events provide a visible diagnostic rather than an empty viewport',()=>{
 assert.match(diagnosticMessage({type:'diagnostics',diagnostic:{code:'RUNTIME_EVENT_REJECTED',message:'bad schema'}})!,/bad schema/);
 assert.equal(diagnosticMessage({type:'status'}),null);
});
