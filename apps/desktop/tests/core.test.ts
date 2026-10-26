import {describe} from 'node:test';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {FrameDecoder, isSupportedDataset, validateCommand, RollingTelemetry, validateVisualization} from '../src/core.ts';
import {normalizeOpenDatasetResponse, supportsDirectOpen} from '../src/api.ts';
import {LOW_RESOURCE_PRESET, defaultRuntimeConfig, fullSequenceConfig} from '../src/renderer/runtime-config.ts';
import {canPlayback, telemetryFreshness, processRss, acceptFrame, diagnosticMessage, mergeSessionStatus} from '../src/renderer/session.ts';
import {validationOutcome} from '../src/renderer/session.ts';
import {qualityResourceRows} from '../src/renderer/benchmark-report.ts';

describe('core', () => {
  test('rejects arbitrary commands, traversal capabilities, and invalid numeric controls', () => {
    for (const [command,args] of [['exec',{shell:'touch x'}],['seek',{index:-1}],['speed',{speed:Infinity}],['policy',{policy:'unsafe'}],['start',{executable:'/tmp/evil'}]]) {
      assert.throws(() => validateCommand(command, args));
    }
    assert.deepEqual(validateCommand('seek',{index:12}),{command:'seek',args:{index:12}});
    assert.deepEqual(validateCommand('governor',{mode:'conserve'}),{command:'governor',args:{mode:'conserve'}});
    assert.deepEqual(validateCommand('layer',{layer:'lod'}),{command:'layer',args:{layer:'lod'}});
    assert.deepEqual(validateCommand('validation',{}),{command:'validation',args:{}});
    assert.throws(()=>validateCommand('layer',{layer:'../../etc'}));
    assert.throws(()=>validateCommand('governor',{mode:'shell'}));
  });

  test('benchmark requests carry frames, warm-up and repetitions; cancel takes no fields', () => {
    const args={dataset:'semanticposs',sequence:'00',count:110,warmup_frames:10,repetitions:3};
    assert.deepEqual(validateCommand('benchmark',args),{command:'benchmark',args});
    assert.deepEqual(validateCommand('benchmark_cancel',{}),{command:'benchmark_cancel',args:{}});
    assert.throws(()=>validateCommand('benchmark_cancel',{force:true}));
    assert.throws(()=>validateCommand('benchmark',{count:1.5}));
    assert.throws(()=>validateCommand('benchmark',{repetitions:-1}));
  });

  test('decodes split and concatenated frames without trusting unbounded lengths', () => {
    const meta = Buffer.from('{"type":"status","state":"ready"}');
    const wire = Buffer.alloc(16 + meta.length); wire.write('VYRA'); wire.writeUInt16LE(1,4); wire.writeUInt16LE(1,6); wire.writeUInt32LE(meta.length,8); meta.copy(wire,16);
    const decoder = new FrameDecoder();
    assert.equal(decoder.push(wire.subarray(0,13)).length,0);
    assert.equal(decoder.push(Buffer.concat([wire.subarray(13),wire])).length,2);
    const bad = Buffer.from(wire.subarray(0,16)); bad.writeUInt32LE(0xffffffff,12);
    assert.throws(() => new FrameDecoder().push(bad), /limit/);
  });

  test('rolling history evicts old samples and preserves unavailable measurements', () => {
    const ring = new RollingTelemetry(2);
    ring.push({timestamp:1,fps:4}); ring.push({timestamp:2,fps:null}); ring.push({timestamp:3,fps:6});
    assert.deepEqual(ring.values().map(x=>x.timestamp),[2,3]);
    assert.deepEqual(ring.series('fps'),[null,6]);
  });

  test('visualization rejects out-of-bounds sections and invalid strides', () => {
    validateVisualization({points:{count:1,offset:0,stride:68},cells:{count:1,offset:68,stride:36}},new Uint8Array(104));
    assert.throws(()=>validateVisualization({points:{count:2,offset:0,stride:68},cells:{count:0,offset:136,stride:36}},new Uint8Array(68)), /bounds/);
    assert.throws(()=>validateVisualization({points:{count:1,offset:0,stride:32},cells:{count:0,offset:68,stride:36}},new Uint8Array(68)), /stride/);
  });

  test('desktop accepts every dataset adapter exposed by the runtime',()=>{
   for(const dataset of ['generic','semanticposs','semantickitti','rellis3d'])assert.equal(isSupportedDataset(dataset),true);
   assert.equal(isSupportedDataset('../dataset'),false);
  });



  test('visualization accepts v3 evidence cell rows while keeping v2 decodable', () => {
    validateVisualization({points:{count:1,offset:0,stride:68},cells:{count:1,offset:68,stride:68}},new Uint8Array(136));
    validateVisualization({points:{count:1,offset:0,stride:68},cells:{count:1,offset:68,stride:36}},new Uint8Array(104));
    assert.throws(()=>validateVisualization({points:{count:1,offset:0,stride:68},cells:{count:1,offset:68,stride:40}},new Uint8Array(108)), /stride/);
  });

  test('optional physical layer sections must match cells and stay inside the payload', () => {
    const base={points:{count:0,offset:0,stride:68},cells:{count:1,offset:0,stride:68}};
    const section={version:1,count:1,offset:68,stride:60};
    validateVisualization({...base,physical_layers:section},new Uint8Array(128));
    for(const invalid of [{...section,count:2},{...section,offset:0},{...section,stride:64},{...section,version:2}]){
      assert.throws(()=>validateVisualization({...base,physical_layers:invalid},new Uint8Array(128)));
    }
    assert.throws(()=>validateVisualization({...base,physical_layers:section},new Uint8Array(127)));
  });
});

describe('desktop api', () => {
  test('direct open is advertised only by shells that implement openDataset',()=>{
   assert.equal(supportsDirectOpen({} as any),false);
   assert.equal(supportsDirectOpen({openDataset:async()=>({})} as any),true);
  });

  test('open_dataset responses normalize across daemon envelope shapes',()=>{
   const catalog={status:'ok',root:'/data',sequences:[{id:'00',frames:10}]};
   const nested=normalizeOpenDatasetResponse({catalog:{result:catalog},selected_sequence:'00',configured:{status:{state:'ready'}}});
   assert.equal(nested.catalog, catalog);
   assert.equal(nested.sequence,'00');
   assert.deepEqual(nested.status,{state:'ready'});
   const flat=normalizeOpenDatasetResponse({catalog,configured:{status:{state:'paused'}},selected_sequence:''});
   assert.equal(flat.sequence,'00');
   assert.deepEqual(flat.status,{state:'paused'});
   const missing=normalizeOpenDatasetResponse({result:catalog});
   assert.equal(missing.sequence,'00');
   assert.equal(missing.status,null);
  });
});

describe('runtime config', () => {
  test('low-resource runtime config is the persisted desktop default',()=>{
   const config=defaultRuntimeConfig();
   assert.equal(LOW_RESOURCE_PRESET,'LowResource');
   assert.equal(config.preset,LOW_RESOURCE_PRESET);
   assert.deepEqual(config.map,{policy:'distance_lod',resource_profile:'performance',governor_override:'automatic'});
   assert.deepEqual(config.playback,{fps:30,speed:1,frame_limit:30,full_sequence:true});
   assert.deepEqual(config.visualization,{point_budget:15000,cell_budget:10000,update_hz:2,max_in_flight:1});
  });

  test('full-sequence mode is explicit and keeps low-resource display limits',()=>{
   const config=fullSequenceConfig(defaultRuntimeConfig());
   assert.equal(config.playback.full_sequence,true);
   assert.equal(config.playback.frame_limit,30);
   assert.equal(config.visualization.point_budget,15000);
  });
});

describe('session', () => {
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
   const uniform5={aggregate:{final_leaves_per_level:{'0':2,'1':3},quality:[{elevation_vs_fine_reference:{rmse_m:0.125}}]},runs:[{metrics:{memory:{logical_map_bytes:4096}}}]};
   const [row]=qualityResourceRows({schema_version:2,policies:{uniform5}});
   assert.equal(row.logicalBytes,4096);
   assert.equal(row.activeCells,5);
   assert.equal(row.rmseM,0.125);
   assert.equal(qualityResourceRows({schema_version:2,policies:{uniform5:{}}})[0].activeCells,null);
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

  test('visualization accepts schema v3 evidence frames and still rejects unknown versions',()=>{
    const v3={metadata:{schema_version:3,generation:2,index:1,points:{offset:0,count:1,stride:68},cells:{offset:68,count:0,stride:68}},payload:new Uint8Array(68)};
    assert.equal(acceptFrame(v3 as any,null),true);
    const bad={metadata:{schema_version:9,generation:1,index:0,points:{offset:0,count:0,stride:68},cells:{offset:0,count:0,stride:68}},payload:new Uint8Array(0)};
    assert.throws(()=>acceptFrame(bad as any,null),/Unsupported visualization schema/);
  });
});
