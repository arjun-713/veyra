import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as core from '../src/core.ts';
import {inspectorRows} from '../src/renderer/dashboard.ts';

test('physical inspection decodes separate surfaces rather than pooled height',()=>{
  assert.equal(typeof core.decodePhysicalLayers,'function');
  const bytes=new Uint8Array(128);
  const view=new DataView(bytes.buffer);
  [1,0,0,0,0,1,.3,.3,.3,0,1,3,3,3,0].forEach((v,i)=>view.setFloat32(68+i*4,v,true));
  const frame={metadata:{points:{count:0,offset:0,stride:68},cells:{count:1,offset:0,stride:68},physical_layers:{version:1,count:1,offset:68,stride:60}},payload:bytes};
  const layers=core.decodePhysicalLayers(frame,0);
  assert.ok(layers);
  assert.equal(layers.ground.mean,0);
  assert.equal(layers.overhead.min,3);
  assert.ok(Math.abs(layers.obstacle.mean-.3)<1e-6);
  const rows=inspectorRows({physical_layers:layers});
  assert.equal(rows.find(r=>r.key==='ground_mean')?.value,'0');
  assert.equal(rows.find(r=>r.key==='overhead_mean')?.value,'3');
});

test('missing and empty physical layers never invent measured surfaces',()=>{
  assert.equal(typeof core.decodePhysicalLayers,'function');
  assert.equal(core.decodePhysicalLayers({metadata:{},payload:new Uint8Array()},0),null);
  const bytes=new Uint8Array(128);
  const metadata={points:{count:0,offset:0,stride:68},cells:{count:1,offset:0,stride:68},physical_layers:{version:1,count:1,offset:68,stride:60}};
  const layers=core.decodePhysicalLayers({metadata,payload:bytes},0);
  assert.ok(layers);
  assert.equal(layers.ground.count,0);
  assert.equal(layers.ground.mean,null);
  assert.equal(inspectorRows({physical_layers:layers}).find(r=>r.key==='ground_mean')?.value,'Unavailable');
  assert.throws(()=>core.decodePhysicalLayers({metadata,payload:bytes},1));
  const view=new DataView(bytes.buffer);
  view.setFloat32(68,Number.POSITIVE_INFINITY,true);
  view.setFloat32(72,12,true);
  assert.equal(core.decodePhysicalLayers({metadata,payload:bytes},0)?.ground.mean,null);
});
