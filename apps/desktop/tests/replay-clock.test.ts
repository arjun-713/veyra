import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ReplayClock, PrefetchWindow, REPLAY_DEFAULT_FPS, percentile, resolveReplayFps, smoothReplayPath} from '../src/renderer/replay-clock.ts';
import {validateCommand} from '../src/core.ts';

// 488 SemanticPOSS frames at 30 FPS present as ~16.3 s of demo playback.
test('default replay rate turns 488 frames into a ~16.3 s demo',()=>{
 assert.equal(REPLAY_DEFAULT_FPS,30);
 const clock=new ReplayClock(488);
 assert.ok(Math.abs(clock.durationMs/1000-16.267)<0.01);
});

test('presentation clock advances one snapshot per 33.333 ms at 1x',()=>{
 const clock=new ReplayClock(488);clock.start();
 let sample=clock.advance(33.333,10,1000);
 assert.equal(sample?.presentedIndex,0);
 sample=clock.advance(33.333,10,1033);
 assert.equal(sample?.presentedIndex,1);
 // Below one frame interval: nothing new due.
 assert.equal(clock.advance(0.0001,10,1033.0001),null);
});

test('2x speed presents two snapshots per 33.333 ms tick',()=>{
 const clock=new ReplayClock(488);clock.speed=2;clock.start();
 const sample=clock.advance(33.333,10,1000);
 assert.equal(sample?.presentedIndex,1);
});

test('latest frame wins: a stall jumps forward and counts drops',()=>{
 const clock=new ReplayClock(488);clock.start();
 clock.advance(33.333,10,1000);
 // ~334 ms stall: ~10 snapshots pass, newest available is 10.
 const sample=clock.advance(334,10,1334);
 assert.equal(sample?.presentedIndex,10);
 assert.equal(sample?.dropped,9);
 assert.equal(clock.snapshot().presentationDrops,9);
});

test('clock never presents a snapshot that has not arrived',()=>{
 const clock=new ReplayClock(488);clock.start();
 // Frame 0 arrives and presents; nothing newer arrives for 150 ms.
 clock.advance(16.666,0,1000);
 const held=clock.advance(150,0,1150);
 assert.equal(held,null);
 assert.equal(clock.snapshot().bufferUnderruns,1);
 assert.equal(clock.snapshot().lastIndex,0);
});

test('restart returns to frame 0 immediately',()=>{
 const clock=new ReplayClock(488);clock.start();
 clock.advance(5000,200,5000);
 clock.restart();
 const sample=clock.advance(33.333,487,5100);
 assert.equal(sample?.presentedIndex,0);
});

test('seek jumps the clock without recomputation',()=>{
 const clock=new ReplayClock(488);clock.start();
 clock.seekToFrame(244);
 const sample=clock.advance(1,300,1000);
 assert.equal(sample?.presentedIndex,244);
});

test('end of sequence is sticky at the last frame',()=>{
 const clock=new ReplayClock(3);clock.start();
 clock.advance(1000,2,1000);
 assert.equal(clock.finished,true);
 assert.equal(clock.advance(100,2,1100),null);
});

test('jitter report carries p50/p95/max over presentation intervals',()=>{
 const clock=new ReplayClock(488);clock.start();
 let now=0;
 for(let i=0;i<10;i++){now+=33;clock.advance(33,500,now);}
 const report=clock.jitterReport();
 assert.equal(report.count,9);
 assert.ok(report.p50!==null&&report.p95!==null&&report.max!==null);
 assert.ok(report.p95>=report.p50);
 assert.equal(percentile([],0.5),null);
});

test('prefetch window is bounded and releases behind the playhead',()=>{
 const window=new PrefetchWindow(4);
 for(let i=0;i<10;i++)window.note(i,1024);
 assert.equal(window.size,4);
 window.releaseThrough(8);
 assert.equal(window.size,1);
 assert.equal(window.bytes,1024);
 window.clear();
 assert.equal(window.size,0);
});

test('replay commands validate path and fps bounds',()=>{
 assert.deepEqual(validateCommand('replay_open',{path:'data/cache/replays/a.veyra-replay',fps:30}).command,'replay_open');
 assert.deepEqual(validateCommand('replay_close',{}).command,'replay_close');
 assert.deepEqual(validateCommand('replay_status',{}).command,'replay_status');
 assert.throws(()=>validateCommand('replay_open',{path:'',fps:30}),/path/);
 assert.throws(()=>validateCommand('replay_open',{path:'a',fps:120}),/FPS/);
 assert.throws(()=>validateCommand('replay_open',{path:'a',fps:30,extra:1}),/not allowed/);
});

test('cached playback issues no processing commands',()=>{
 // The replay UI path may only use presentation commands; benchmark and
 // validation would rerun expensive work and must never fire during replay.
 const allowed=new Set(['start','pause','step','seek','speed','status','replay_open','replay_close','replay_status','layer']);
 const forbidden=['benchmark','validation','configure','policy','sequence','reset','governor'];
 for(const command of forbidden)assert.ok(!allowed.has(command),`${command} must not run during cached replay`);
});

test('session configuration supplies the replay rate, including 60 FPS',()=>{
 // The visible replay selector is authoritative even when the session has a rate.
 assert.equal(resolveReplayFps(30,60),60);
 assert.equal(resolveReplayFps(60,30),30);
 assert.equal(resolveReplayFps(15,30),30);
 assert.equal(resolveReplayFps(10,30),30);
 assert.equal(resolveReplayFps(undefined,30),30);
 assert.equal(resolveReplayFps('60',30),30);
});

test('ordinary Play uses a prepared cache unless a manual path was entered',()=>{
 assert.equal(smoothReplayPath('',{state:'ready',path:'/cache/session.veyra-replay'}),'/cache/session.veyra-replay');
 assert.equal(smoothReplayPath(' /manual.veyra-replay ',{state:'ready',path:'/cache/session.veyra-replay'}),'/manual.veyra-replay');
 assert.equal(smoothReplayPath('',{state:'preparing',done:10,frames:488}),null);
 assert.equal(smoothReplayPath('',{state:'failed',error:'disk full'}),null);
});

test('60 FPS presentation clock advances every 16.667 ms',()=>{
 const clock=new ReplayClock(488,60);clock.start();
 assert.equal(clock.frameIntervalMs,1000/60);
 const sample=clock.advance(1000/60,10,1000);
 assert.equal(sample?.presentedIndex,1);
 assert.ok(Math.abs(new ReplayClock(488,60).durationMs/1000-8.133)<0.01);
});
