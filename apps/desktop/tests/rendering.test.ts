import {describe} from 'node:test';
import {test as canvas_colors_test} from 'node:test';
import assert from 'node:assert/strict';
import {pointColor, cellColor} from '../src/renderer/colors.ts';
import {test as chase_camera_test} from 'node:test';
import {createChaseState, observePose, chaseTargets, chaseAlpha, resetChase, CHASE} from '../src/renderer/chase-camera.ts';
import {test as physical_layers_test} from 'node:test';
import * as core from '../src/core.ts';
import {inspectorRows} from '../src/renderer/dashboard.ts';
import motion_hidden_test from 'node:test';
import {readFileSync} from 'node:fs';
import {MOTION_FEATURE_ENABLED, perceptionStages} from '../src/renderer/dashboard.ts';
import {test as viewport_test} from 'node:test';
import {drawableSize, worldRowBounds, topFitDistance, sphereFitDistance, presetPose, boundsCenter, MIN_FIT_DISTANCE, MAX_FIT_DISTANCE, type Bounds} from '../src/renderer/viewport.ts';
import {test as visual_test} from 'node:test';
import {displayPosition} from '../src/renderer/colors.ts';
import {traversabilityLabel} from '../src/renderer/dashboard.ts';

describe('canvas colors', () => {
  // The fixed semantic palette must not create garbage for every point in
  // an accumulated scan. Reintroducing per-call palette construction breaks
  // this allocation contract while preserving the RGB values.
  canvas_colors_test('semantic canvas coloring reuses RGB storage for repeated classes',()=>{
   const row=new Float32Array(17);row[4]=9;
   const layers={semantic:'ground_truth'};
   const results=new Set();
   for(let i=0;i<10000;i++){
    results.add(pointColor('semantic',row,layers));
    results.add(cellColor('semantic',row));
   }
   assert.equal(results.size,1,'one class needs one shared RGB value, not one allocation per entity');
   assert.deepEqual([...results][0],[.22,.55,.98]);
  });
});

describe('chase camera', () => {
  // Row-major 4x4 pose: translation at [3],[7],[11], sensor x-axis column [0],[4],[8].
  const pose=(x:number,y:number,z=0,ax=-1,ay=0)=>[ax,0,0,x, ay,1,0,y, 0,0,1,z, 0,0,0,1];
  const near=(a:number,b:number,eps=1e-9)=>assert.ok(Math.abs(a-b)<eps,`${a} !~ ${b}`);

  chase_camera_test('first pose snaps and falls back to the flattened sensor x-axis',()=>{
   const s=createChaseState();
   assert.equal(observePose(s,1,0,pose(0,0)),true);
   near(s.hx,-1);near(s.hy,0);
   assert.equal(observePose(s,1,0,pose(0,0)),false,'re-rendering the same frame never snaps');
  });
  chase_camera_test('heading comes from displacement, not the misaligned sensor axis',()=>{
   const s=createChaseState();
   observePose(s,1,0,pose(0,0));
   assert.equal(observePose(s,1,1,pose(0,1)),false);
   near(s.hx,0);near(s.hy,1);
   observePose(s,1,2,pose(1,2));
   near(s.hx,Math.SQRT1_2);near(s.hy,Math.SQRT1_2);
  });
  chase_camera_test('tiny jitter keeps the last heading and accumulates from the anchor',()=>{
   const s=createChaseState();
   observePose(s,1,0,pose(0,0));observePose(s,1,1,pose(0,1));
   observePose(s,1,2,pose(.05,1.04));near(s.hx,0);near(s.hy,1);
   observePose(s,1,3,pose(.1,.98));near(s.hx,0);near(s.hy,1);
   // Slow creep: each step is under the threshold, but the anchor total is not.
   for(let i=0;i<4;i++)observePose(s,1,4+i,pose(0,1+(i+1)*.05));
   near(s.hx,0);near(s.hy,1);
   assert.ok(CHASE.minMove>0.1&&CHASE.minMove<0.3);
  });
  chase_camera_test('generation change or backwards index resets heading and snaps',()=>{
   const s=createChaseState();
   observePose(s,1,5,pose(0,0));observePose(s,1,6,pose(0,1));near(s.hy,1);
   assert.equal(observePose(s,2,0,pose(5,5)),true,'replay loop starts a new generation');
   near(s.hx,-1);near(s.hy,0);
   observePose(s,2,1,pose(6,5));near(s.hx,1);
   assert.equal(observePose(s,2,0,pose(0,0,0,0,1)),true,'seeking backwards snaps');
   near(s.hx,0);near(s.hy,1);
   resetChase(s);assert.equal(observePose(s,2,0,pose(0,0)),true);
  });
  chase_camera_test('degenerate sensor axis without motion keeps a usable heading',()=>{
   const s=createChaseState();
   observePose(s,1,0,pose(0,0,0,0,0));
   near(Math.hypot(s.hx,s.hy),1);
  });
  chase_camera_test('camera sits behind the vehicle relative to heading, in display coords',()=>{
   const s=createChaseState(),out=new Float64Array(6);
   observePose(s,1,0,pose(0,0,2));observePose(s,1,1,pose(0,1,2));
   chaseTargets(s,out);
   // World (x,y,z) -> display (x,z,-y). Heading +world y is display -z.
   near(out[0],0);near(out[1],2+CHASE.up);near(out[2],-(1-CHASE.back));
   near(out[3],0);near(out[4],2+CHASE.lookUp);near(out[5],-(1+CHASE.ahead));
   observePose(s,1,2,pose(1,1,2));chaseTargets(s,out);
   near(out[0],1-CHASE.back);near(out[2],-1);near(out[3],1+CHASE.ahead);
  });
  chase_camera_test('smoothing is frame-rate independent',()=>{
   const two=1-(1-chaseAlpha(1/60))**2;
   near(two,chaseAlpha(1/30),1e-12);
   assert.equal(chaseAlpha(0),0);assert.ok(chaseAlpha(10)>.99&&chaseAlpha(10)<=1);
   assert.equal(chaseAlpha(-1),0);
  });
});

describe('physical layers', () => {
  physical_layers_test('physical inspection decodes separate surfaces rather than pooled height',()=>{
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

  physical_layers_test('reused render instance index resolves its matching physical-layer row',()=>{
    const bytes=new Uint8Array(17*4*2+60*2);
    const view=new DataView(bytes.buffer);
    const first=[1,0,0,0,0,1,.3,.3,.3,0,1,3,3,3,0];
    const second=[1,0,0,0,0,1,.7,.7,.7,0,1,8,8,8,0];
    [...first,...second].forEach((v,i)=>view.setFloat32(136+i*4,v,true));
    const frame={metadata:{points:{count:0,offset:0,stride:68},cells:{count:2,offset:0,stride:68},physical_layers:{version:1,count:2,offset:136,stride:60}},payload:bytes};

    // MapCanvas reuses its instance buffers; instance 1 must continue to map to
    // cell row 1 and therefore physical-layer row 1 after an update.
    const layers=core.decodePhysicalLayers(frame,1);
    assert.ok(layers);
    assert.equal(layers.ground.mean,0);
    assert.ok(Math.abs(Number(layers.obstacle.mean)-0.7)<1e-6);
    assert.equal(layers.overhead.mean,8);
  });

  physical_layers_test('missing and empty physical layers never invent measured surfaces',()=>{
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
});

describe('motion hidden', () => {
  motion_hidden_test('motion feature is hidden until explicitly re-enabled', () => {
   assert.equal(MOTION_FEATURE_ENABLED,false);
   const frame:any={metadata:{pipeline_status:{temporal:'disabled'},perception_timings_ms:{temporal:0.1}},payload:new Uint8Array()};
   assert.deepEqual(perceptionStages(frame).map(stage=>stage.label),['Semantic','Ground','Terrain']);
   const rows=inspectorRows({point_count:3,motion:0.9} as any);
   assert.ok(!rows.some((row:any)=>row.key==='motion'));
   const app=readFileSync(new URL('../src/renderer/App.svelte',import.meta.url),'utf8');
   assert.match(app,/filter\(\(\[value\]\)=>MOTION_FEATURE_ENABLED\|\|value!=='motion'\)/);
  });
});

describe('viewport', () => {
  const tanHalf=(fov:number)=>Math.tan(fov*Math.PI/360);
  const square=(half:number,height=0):Bounds=>({min:[-half,0,-half],max:[half,height,half]});

  viewport_test('an unlaid or hidden host is never applied as the drawable size',()=>{
   assert.equal(drawableSize(0,0),null);
   assert.equal(drawableSize(1174,0),null);
   assert.equal(drawableSize(0,635),null);
   assert.equal(drawableSize(Number.NaN,635),null);
   assert.equal(drawableSize(.4,.4),null);
   assert.deepEqual(drawableSize(1174.6,635.2),{width:1174,height:635});
   // Whatever is applied yields a finite, positive aspect: no NaN projection.
   const size=drawableSize(1,1)!;assert.ok(Number.isFinite(size.width/size.height)&&size.width/size.height>0);
  });

  viewport_test('world rows are bounded in display coordinates and non-finite rows skipped',()=>{
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

  viewport_test('top fit sees the whole footprint along both screen axes',()=>{
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

  viewport_test('fit distances are clamped and survive degenerate input',()=>{
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

  viewport_test('orbit fit grows with the map and keeps the historical viewing direction',()=>{
   const small=presetPose('orbit',square(10),55,1.8,[0,0,0]);
   const large=presetPose('orbit',square(40),55,1.8,[0,0,0]);
   const dist=(p:{position:number[];target:number[]})=>Math.hypot(p.position[0]-p.target[0],p.position[1]-p.target[1],p.position[2]-p.target[2]);
   assert.ok(dist(large)>dist(small));
   const dir=[-32,25,36],len=Math.hypot(...dir);
   const d=dist(small);
   small.position.forEach((v,i)=>assert.ok(Math.abs((v-small.target[i])/d-dir[i]/len)<1e-9));
  });

  viewport_test('presets target the map centre; driver chases the vehicle',()=>{
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

  viewport_test('without bounds the presets fall back to the historical fixed offsets',()=>{
   const t:[number,number,number]=[1,2,3];
   assert.deepEqual(presetPose('top',null,55,1.8,t).position,[1,102,3.01]);
   assert.deepEqual(presetPose('driver',null,55,1.8,t).position,[1,5,11]);
   const orbit=presetPose('orbit',null,55,1.8,t);
   orbit.position.forEach((v,i)=>assert.ok(Math.abs(v-[t[0]-32,t[1]+25,t[2]+36][i])<1e-9));
  });
});

describe('visual', () => {
  visual_test('missing evidence renders neutral and unknown traversability remains distinct',()=>{
   assert.deepEqual(pointColor('ground',[0,0,0,1,2,1,1,0],{ground:'unavailable'}),[0.35,0.4,0.45]);
   assert.notDeepEqual(pointColor('terrain',[0,0,0,1,2,42,0,0],{terrain:'available'}),pointColor('terrain',[0,0,0,1,2,42,0,1],{terrain:'available'}));
  });
  visual_test('ground-truth semantic status renders its measured class color',()=>{
   assert.notDeepEqual(pointColor('semantic',[0,0,0,1,9,0,0,0],{semantic:'ground_truth'}),[.35,.4,.45]);
  });
  visual_test('Patchwork++ ground is colored and unavailable map ground evidence is neutral',()=>{
   assert.deepEqual(pointColor('ground',[0,0,0,1,2,42,1],{ground:'pypatchworkpp.patchworkpp'}),[.3,.8,.5]);
   assert.deepEqual(cellColor('ground',[0,0,0,.05,0,0,0,0]),[.35,.4,.45]);
  });
  visual_test('world coordinates and 5/10/20/40cm colors remain distinguishable',()=>{
   assert.deepEqual(displayPosition(2,3,4),[2,4,-3]);
   const colors=[.05,.1,.2,.4].map(r=>cellColor('lod',[0,0,0,r,0,0,0,0]).join(','));assert.equal(new Set(colors).size,4);
  });
  visual_test('extended v3 cell rows keep legacy color indices stable',()=>{
    const v2=[0,0,1.5,.05,9,.2,.8,-.4,0.7];
    const v3=[...v2,0.7,0.9,0.6,0.5,0.3,42,1.2,1.8,0.01];
    for(const mode of ['lod','semantic','motion','terrain','utility'])assert.deepEqual(cellColor(mode,v2 as any),cellColor(mode,v3 as any));
  });
  visual_test('cell terrain uses finite sign test with exact palette',()=>{
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
  visual_test('cell terrain agrees with traversabilityLabel',()=>{
    const green:[number,number,number]=[.2,.85,.5],red:[number,number,number]=[.95,.3,.35],neutral:[number,number,number]=[.35,.4,.45];
    const cases:[unknown,string,[number,number,number]][]=[[1,'Drivable',green],[0.3,'Drivable',green],[1e-6,'Drivable',green],[0,'Unknown',neutral],[-0,'Unknown',neutral],[-0.2,'Non-drivable',red],[-1e-6,'Non-drivable',red],[-1,'Non-drivable',red],[NaN,'Unavailable',neutral],[undefined,'Unavailable',neutral],[null,'Unavailable',neutral]];
    for(const [e,label,color] of cases){
      assert.equal(traversabilityLabel(e),label);
      assert.deepEqual(cellColor('terrain',[0,0,1.5,.05,9,.2,.8,e,0.7] as any),color);
    }
  });
});
