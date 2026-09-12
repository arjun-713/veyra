import {test} from 'node:test';import assert from 'node:assert/strict';
import {pointColor,cellColor,displayPosition,fallbackScene} from '../src/renderer/colors.ts';
test('missing evidence renders neutral and unknown traversability remains distinct',()=>{
 assert.deepEqual(pointColor('ground',[0,0,0,1,2,1,1,0],{ground:'unavailable'}),[0.35,0.4,0.45]);
 assert.notDeepEqual(pointColor('terrain',[0,0,0,1,2,1,0,0],{terrain:'available'}),pointColor('terrain',[0,0,0,1,2,1,1,0],{terrain:'available'}));
});
test('ground-truth semantic status renders its measured class color',()=>{
 assert.notDeepEqual(pointColor('semantic',[0,0,0,1,9,0,0,0],{semantic:'ground_truth'}),[.35,.4,.45]);
});
test('world coordinates and 5/10/20/40cm colors remain distinguishable',()=>{
 assert.deepEqual(displayPosition(2,3,4),[3,4,-2]);
 const colors=[.05,.1,.2,.4].map(r=>cellColor('lod',[0,0,0,r,0,0,0,0]).join(','));assert.equal(new Set(colors).size,4);
});

test('canvas fallback derives bounded visible marks from the wire frame',()=>{
 const payload=new Uint8Array(32*3+36);const view=new DataView(payload.buffer);
 const pointRows=[[1,2,.1,.5,9,1,1,0],[3,4,.2,.6,1,0,2,.8],[5,6,.3,.7,15,1,1,0]];
 pointRows.forEach((row,i)=>row.forEach((value,j)=>view.setFloat32(i*32+j*4,value,true)));
 const cell=[7,8,.4,.1,1,.9,.8,.2,.7];cell.forEach((value,j)=>view.setFloat32(96+j*4,value,true));
 const frame:any={metadata:{points:{count:3,offset:0,stride:32},cells:{count:1,offset:96,stride:36},layers:{semantic:'available'}},payload};

 const semantic=fallbackScene(frame,'semantic',true,false,'top',2);
 assert.equal(semantic.marks.length,2);
 assert.deepEqual(semantic.marks.map(mark=>mark.sourceIndex),[0,2]);
 assert.notEqual(semantic.marks[0].color,semantic.marks[1].color);
 assert.ok(semantic.marks.every(mark=>Number.isFinite(mark.x)&&Number.isFinite(mark.y)));

 const adaptive=fallbackScene(frame,'lod',false,true,'top',10);
 assert.equal(adaptive.marks.length,1);
 assert.equal(adaptive.marks[0].kind,'cell');
 assert.equal(adaptive.marks[0].sourceIndex,0);
 assert.ok(adaptive.marks[0].size>0);
});
