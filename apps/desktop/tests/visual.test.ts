import {test} from 'node:test';import assert from 'node:assert/strict';
import {pointColor,cellColor,displayPosition} from '../src/renderer/colors.ts';
import {traversabilityLabel} from '../src/renderer/dashboard.ts';
test('missing evidence renders neutral and unknown traversability remains distinct',()=>{
 assert.deepEqual(pointColor('ground',[0,0,0,1,2,1,1,0],{ground:'unavailable'}),[0.35,0.4,0.45]);
 assert.notDeepEqual(pointColor('terrain',[0,0,0,1,2,42,0,0],{terrain:'available'}),pointColor('terrain',[0,0,0,1,2,42,0,1],{terrain:'available'}));
});
test('ground-truth semantic status renders its measured class color',()=>{
 assert.notDeepEqual(pointColor('semantic',[0,0,0,1,9,0,0,0],{semantic:'ground_truth'}),[.35,.4,.45]);
});
test('Patchwork++ ground is colored and unavailable map ground evidence is neutral',()=>{
 assert.deepEqual(pointColor('ground',[0,0,0,1,2,42,1],{ground:'pypatchworkpp.patchworkpp'}),[.3,.8,.5]);
 assert.deepEqual(cellColor('ground',[0,0,0,.05,0,0,0,0]),[.35,.4,.45]);
});
test('world coordinates and 5/10/20/40cm colors remain distinguishable',()=>{
 assert.deepEqual(displayPosition(2,3,4),[2,4,-3]);
 const colors=[.05,.1,.2,.4].map(r=>cellColor('lod',[0,0,0,r,0,0,0,0]).join(','));assert.equal(new Set(colors).size,4);
});
test('extended v3 cell rows keep legacy color indices stable',()=>{
  const v2=[0,0,1.5,.05,9,.2,.8,-.4,0.7];
  const v3=[...v2,0.7,0.9,0.6,0.5,0.3,42,1.2,1.8,0.01];
  for(const mode of ['lod','semantic','motion','terrain','utility'])assert.deepEqual(cellColor(mode,v2 as any),cellColor(mode,v3 as any));
});
test('cell terrain uses finite sign test with exact palette',()=>{
  const green:[number,number,number]=[.2,.85,.5],red:[number,number,number]=[.95,.3,.35],neutral:[number,number,number]=[.35,.4,.45];
  const row=(e:any)=>[0,0,1.5,.05,9,.2,.8,e,0.7] as any;
  assert.deepEqual(cellColor('terrain',row(1)),green);
  assert.deepEqual(cellColor('terrain',row(0.3)),green);
  assert.deepEqual(cellColor('terrain',row(1e-6)),green);
  assert.deepEqual(cellColor('terrain',row(0)),neutral);
  assert.deepEqual(cellColor('terrain',row(-0)),neutral);
  assert.deepEqual(cellColor('terrain',row(-0.2)),red);
  assert.deepEqual(cellColor('terrain',row(-1e-6)),red);
  assert.deepEqual(cellColor('terrain',row(-1)),red);
  assert.deepEqual(cellColor('terrain',row(NaN)),neutral);
  assert.deepEqual(cellColor('terrain',row(undefined)),neutral);
  assert.deepEqual(cellColor('terrain',row(null)),neutral);
  assert.deepEqual(cellColor('terrain',row(Infinity)),neutral);
  assert.deepEqual(cellColor('terrain',row(-Infinity)),neutral);
  assert.deepEqual(cellColor('terrain',[0,0,1.5,.05,9,.2,.8] as any),neutral);
  assert.deepEqual(cellColor('terrain',[] as any),neutral);
});
test('cell terrain agrees with traversabilityLabel',()=>{
  const green:[number,number,number]=[.2,.85,.5],red:[number,number,number]=[.95,.3,.35],neutral:[number,number,number]=[.35,.4,.45];
  const cases:[unknown,string,[number,number,number]][]=[[1,'Drivable',green],[0.3,'Drivable',green],[1e-6,'Drivable',green],[0,'Unknown',neutral],[-0,'Unknown',neutral],[-0.2,'Non-drivable',red],[-1e-6,'Non-drivable',red],[-1,'Non-drivable',red],[NaN,'Unavailable',neutral],[undefined,'Unavailable',neutral],[null,'Unavailable',neutral]];
  for(const [e,label,color] of cases){
    assert.equal(traversabilityLabel(e),label);
    assert.deepEqual(cellColor('terrain',[0,0,1.5,.05,9,.2,.8,e,0.7] as any),color);
  }
});
