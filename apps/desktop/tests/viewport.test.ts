import {test} from 'node:test';import assert from 'node:assert/strict';
import {drawableSize,worldRowBounds,topFitDistance,sphereFitDistance,presetPose,boundsCenter,MIN_FIT_DISTANCE,MAX_FIT_DISTANCE,type Bounds} from '../src/renderer/viewport.ts';

const tanHalf=(fov:number)=>Math.tan(fov*Math.PI/360);
const square=(half:number,height=0):Bounds=>({min:[-half,0,-half],max:[half,height,half]});

test('an unlaid or hidden host is never applied as the drawable size',()=>{
 assert.equal(drawableSize(0,0),null);
 assert.equal(drawableSize(1174,0),null);
 assert.equal(drawableSize(0,635),null);
 assert.equal(drawableSize(Number.NaN,635),null);
 assert.equal(drawableSize(.4,.4),null);
 assert.deepEqual(drawableSize(1174.6,635.2),{width:1174,height:635});
 // Whatever is applied yields a finite, positive aspect: no NaN projection.
 const size=drawableSize(1,1)!;assert.ok(Number.isFinite(size.width/size.height)&&size.width/size.height>0);
});

test('world rows are bounded in display coordinates and non-finite rows skipped',()=>{
 // stride 17 like cell/point wire rows: world x,y,z first.
 const rows=new Float32Array(3*17);
 rows.set([2,5,1],0);rows.set([-4,-1,3],17);rows.set([Number.NaN,99,99],34);
 const bounds=worldRowBounds(rows,3,17)!;
 // display = (x, z, -y)
 assert.deepEqual(bounds.min,[-4,1,-5]);
 assert.deepEqual(bounds.max,[2,3,1]);
 assert.equal(worldRowBounds(rows,0,17),null);
 assert.equal(worldRowBounds(new Float32Array([Number.NaN,0,0]),1,3),null);
});

test('top fit sees the whole footprint along both screen axes',()=>{
 const fov=55,aspect=1174/635,b=square(10);
 const d=topFitDistance(b,fov,aspect);
 const t=tanHalf(fov);
 assert.ok(d*t>=10,'vertical half-extent visible');
 assert.ok(d*t*aspect>=10,'horizontal half-extent visible');
 // A wide-but-short footprint on a portrait viewport is bound by width.
 const wide:Bounds={min:[-40,0,-5],max:[40,0,5]};
 assert.ok(topFitDistance(wide,fov,.5)*t*.5>=40);
 // Much closer than the old fixed 100 m for a ~20 m near-field map.
 assert.ok(d<40,`distance ${d}`);
});

test('fit distances are clamped and survive degenerate input',()=>{
 assert.equal(topFitDistance(square(0),55,1.8),MIN_FIT_DISTANCE);
 assert.equal(sphereFitDistance(square(0),55,1.8),MIN_FIT_DISTANCE);
 assert.equal(topFitDistance(square(5000),55,1.8),MAX_FIT_DISTANCE);
 for(const aspect of [0,Number.NaN,-1]){
  const d=topFitDistance(square(10),55,aspect);assert.ok(Number.isFinite(d)&&d>=MIN_FIT_DISTANCE);
  const s=sphereFitDistance(square(10),55,aspect);assert.ok(Number.isFinite(s)&&s>=MIN_FIT_DISTANCE);
 }
 const bad:Bounds={min:[Number.NaN,0,0],max:[1,1,1]};
 assert.ok(Number.isFinite(topFitDistance(bad,55,1)));
});

test('orbit fit grows with the map and keeps the historical viewing direction',()=>{
 const small=presetPose('orbit',square(10),55,1.8,[0,0,0]);
 const large=presetPose('orbit',square(40),55,1.8,[0,0,0]);
 const dist=(p:{position:number[];target:number[]})=>Math.hypot(p.position[0]-p.target[0],p.position[1]-p.target[1],p.position[2]-p.target[2]);
 assert.ok(dist(large)>dist(small));
 const dir=[-32,25,36],len=Math.hypot(...dir);
 const d=dist(small);
 small.position.forEach((v,i)=>assert.ok(Math.abs((v-small.target[i])/d-dir[i]/len)<1e-9));
});

test('presets target the map centre; driver chases the vehicle',()=>{
 const b:Bounds={min:[100,-1,-60],max:[120,3,-40]};
 const center=boundsCenter(b);assert.deepEqual(center,[110,1,-50]);
 const top=presetPose('top',b,55,1.8,[0,0,0]);
 assert.deepEqual(top.target,center);
 assert.equal(top.position[0],center[0]);
 assert.ok(top.position[1]>center[1]);
 assert.ok(Math.abs(top.position[2]-center[2])<.1,'looks straight down');
 const driver=presetPose('driver',b,55,1.8,[0,0,0],[112,0,-45]);
 assert.deepEqual(driver.target,[112,0,-45]);
 assert.deepEqual(driver.position,[112,3,-37]);
});

test('without bounds the presets fall back to the historical fixed offsets',()=>{
 const t:[number,number,number]=[1,2,3];
 assert.deepEqual(presetPose('top',null,55,1.8,t).position,[1,102,3.01]);
 assert.deepEqual(presetPose('driver',null,55,1.8,t).position,[1,5,11]);
 const orbit=presetPose('orbit',null,55,1.8,t);
 orbit.position.forEach((v,i)=>assert.ok(Math.abs(v-[t[0]-32,t[1]+25,t[2]+36][i])<1e-9));
});
