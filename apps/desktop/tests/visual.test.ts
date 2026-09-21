import {test} from 'node:test';import assert from 'node:assert/strict';
import {pointColor,cellColor,displayPosition} from '../src/renderer/colors.ts';
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
 assert.deepEqual(displayPosition(2,3,4),[3,4,-2]);
 const colors=[.05,.1,.2,.4].map(r=>cellColor('lod',[0,0,0,r,0,0,0,0]).join(','));assert.equal(new Set(colors).size,4);
});
