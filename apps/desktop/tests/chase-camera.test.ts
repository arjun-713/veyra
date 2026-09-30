import {test} from 'node:test';import assert from 'node:assert/strict';
import {createChaseState,observePose,chaseTargets,chaseAlpha,resetChase,CHASE} from '../src/renderer/chase-camera.ts';

// Row-major 4x4 pose: translation at [3],[7],[11], sensor x-axis column [0],[4],[8].
const pose=(x:number,y:number,z=0,ax=-1,ay=0)=>[ax,0,0,x, ay,1,0,y, 0,0,1,z, 0,0,0,1];
const near=(a:number,b:number,eps=1e-9)=>assert.ok(Math.abs(a-b)<eps,`${a} !~ ${b}`);

test('first pose snaps and falls back to the flattened sensor x-axis',()=>{
 const s=createChaseState();
 assert.equal(observePose(s,1,0,pose(0,0)),true);
 near(s.hx,-1);near(s.hy,0);
 assert.equal(observePose(s,1,0,pose(0,0)),false,'re-rendering the same frame never snaps');
});
test('heading comes from displacement, not the misaligned sensor axis',()=>{
 const s=createChaseState();
 observePose(s,1,0,pose(0,0));
 assert.equal(observePose(s,1,1,pose(0,1)),false);
 near(s.hx,0);near(s.hy,1);
 observePose(s,1,2,pose(1,2));
 near(s.hx,Math.SQRT1_2);near(s.hy,Math.SQRT1_2);
});
test('tiny jitter keeps the last heading and accumulates from the anchor',()=>{
 const s=createChaseState();
 observePose(s,1,0,pose(0,0));observePose(s,1,1,pose(0,1));
 observePose(s,1,2,pose(.05,1.04));near(s.hx,0);near(s.hy,1);
 observePose(s,1,3,pose(.1,.98));near(s.hx,0);near(s.hy,1);
 // Slow creep: each step is under the threshold, but the anchor total is not.
 for(let i=0;i<4;i++)observePose(s,1,4+i,pose(0,1+(i+1)*.05));
 near(s.hx,0);near(s.hy,1);
 assert.ok(CHASE.minMove>0.1&&CHASE.minMove<0.3);
});
test('generation change or backwards index resets heading and snaps',()=>{
 const s=createChaseState();
 observePose(s,1,5,pose(0,0));observePose(s,1,6,pose(0,1));near(s.hy,1);
 assert.equal(observePose(s,2,0,pose(5,5)),true,'replay loop starts a new generation');
 near(s.hx,-1);near(s.hy,0);
 observePose(s,2,1,pose(6,5));near(s.hx,1);
 assert.equal(observePose(s,2,0,pose(0,0,0,0,1)),true,'seeking backwards snaps');
 near(s.hx,0);near(s.hy,1);
 resetChase(s);assert.equal(observePose(s,2,0,pose(0,0)),true);
});
test('degenerate sensor axis without motion keeps a usable heading',()=>{
 const s=createChaseState();
 observePose(s,1,0,pose(0,0,0,0,0));
 near(Math.hypot(s.hx,s.hy),1);
});
test('camera sits behind the vehicle relative to heading, in display coords',()=>{
 const s=createChaseState(),out=new Float64Array(6);
 observePose(s,1,0,pose(0,0,2));observePose(s,1,1,pose(0,1,2));
 chaseTargets(s,out);
 // World (x,y,z) -> display (x,z,-y). Heading +world y is display -z.
 near(out[0],0);near(out[1],2+CHASE.up);near(out[2],-(1-CHASE.back));
 near(out[3],0);near(out[4],2+CHASE.lookUp);near(out[5],-(1+CHASE.ahead));
 observePose(s,1,2,pose(1,1,2));chaseTargets(s,out);
 near(out[0],1-CHASE.back);near(out[2],-1);near(out[3],1+CHASE.ahead);
});
test('smoothing is frame-rate independent',()=>{
 const two=1-(1-chaseAlpha(1/60))**2;
 near(two,chaseAlpha(1/30),1e-12);
 assert.equal(chaseAlpha(0),0);assert.ok(chaseAlpha(10)>.99&&chaseAlpha(10)<=1);
 assert.equal(chaseAlpha(-1),0);
});
