import {test} from 'node:test';import assert from 'node:assert/strict';
import {ScanHistory,colorInput,HISTORY_STRIDE,isDynamicClass} from '../src/renderer/accumulation.ts';

const wire=(count:number,x:number)=>{const rows=new Float32Array(count*17);for(let i=0;i<count;i++){rows[i*17]=x;rows[i*17+1]=i;rows[i*17+2]=1;rows[i*17+4]=9;rows[i*17+6]=1;rows[i*17+7]=2;rows[i*17+12]=.5;}return rows;};
const meta=(index:number,extra:Record<string,unknown>={})=>({generation:1,index,dataset:'pandaset',sequence:'011',pose_available:true,...extra});

test('world-frame scans accumulate up to the window, oldest first',()=>{
 const history=new ScanHistory(3);
 for(let i=0;i<5;i++)assert.equal(history.push(meta(i),wire(2,i),2),true);
 assert.deepEqual(history.list().map(frame=>frame.index),[2,3,4]);
 assert.equal(history.pointCount,6);
});
test('sensor-frame scans never accumulate because they cannot be aligned',()=>{
 const history=new ScanHistory(20);
 for(let i=0;i<4;i++)history.push(meta(i,{pose_available:false}),wire(2,i),2);
 assert.equal(history.frameCount,1);
});
test('re-rendering the same frame does not duplicate it',()=>{
 const history=new ScanHistory(20);
 history.push(meta(4),wire(2,4),2);
 assert.equal(history.push(meta(4),wire(2,4),2),false);
 assert.equal(history.frameCount,1);
});
test('seeking backwards, a new generation or a new sequence resets history',()=>{
 const history=new ScanHistory(20);
 history.push(meta(5),wire(1,5),1);history.push(meta(6),wire(1,6),1);
 history.push(meta(2),wire(1,2),1);assert.deepEqual(history.list().map(frame=>frame.index),[2]);
 history.push(meta(3,{generation:2}),wire(1,3),1);assert.equal(history.frameCount,1);
 history.push(meta(4,{generation:2,sequence:'021'}),wire(1,4),1);assert.equal(history.frameCount,1);
});
test('point capacity evicts oldest scans but always keeps the live scan',()=>{
 const history=new ScanHistory(50,5);
 for(let i=0;i<4;i++)history.push(meta(i),wire(2,i),2);
 assert.deepEqual(history.list().map(frame=>frame.index),[2,3]);
 history.push(meta(9),wire(8,9),8);
 assert.deepEqual(history.list().map(frame=>frame.index),[9]);
});
test('shrinking the window trims history immediately',()=>{
 const history=new ScanHistory(10);
 for(let i=0;i<6;i++)history.push(meta(i),wire(1,i),1);
 history.setWindow(1);assert.deepEqual(history.list().map(frame=>frame.index),[5]);
});
test('compact rows keep position and every field pointColor reads',()=>{
 const history=new ScanHistory(2);history.push(meta(0),wire(1,7),1);
 const rows=history.list()[0].rows;assert.equal(rows.length,HISTORY_STRIDE);
 assert.deepEqual(Array.from(rows.subarray(0,3)),[7,0,1]);
 const p=colorInput(rows,0,new Float32Array(17));
 assert.deepEqual([p[2],p[4],p[6],p[7],p[12]],[1,9,1,2,.5]);
});
test('moving classes are kept only in the live scan so traffic leaves no trails',()=>{
 const scan=(index:number)=>{const rows=wire(3,index);rows[4]=1;rows[17+4]=6;rows[34+4]=13;return rows;};// car, person, building
 const history=new ScanHistory(5);
 history.push(meta(0),scan(0),3);history.push(meta(1),scan(1),3);history.push(meta(2),scan(2),3);
 const classes=history.list().map(frame=>Array.from({length:frame.count},(_,i)=>frame.rows[i*HISTORY_STRIDE+3]));
 assert.deepEqual(classes,[[13],[13],[1,6,13]]);
 assert.equal(history.pointCount,5);
 assert.equal(isDynamicClass(9),false);
});
