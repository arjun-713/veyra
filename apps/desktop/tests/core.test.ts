import { test } from 'node:test';
import assert from 'node:assert/strict';
import { FrameDecoder, isSupportedDataset, validateCommand, RollingTelemetry, validateVisualization } from '../src/core.ts';
import { nativeRuntimeUnavailableMessage } from '../src/api.ts';

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

test('desktop runtime bridge failure does not direct Tauri users to Electron',()=>{
 assert.match(nativeRuntimeUnavailableMessage,/desktop runtime bridge/i);
 assert.doesNotMatch(nativeRuntimeUnavailableMessage,/electron/i);
});
