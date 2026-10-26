import {describe} from 'node:test';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ReplayClock, PrefetchWindow, REPLAY_DEFAULT_FPS, percentile, policyReplayPath, resolveReplayFps, smoothReplayPath} from '../src/renderer/replay-clock.ts';
import {validateCommand} from '../src/core.ts';
import {PlaybackControl} from '../src/renderer/playback-control.ts';
import {overviewSession, replayCards, replayControl, sessionLabel} from '../src/renderer/overview-replay.ts';
import {ScanHistory, colorInput, HISTORY_STRIDE, isDynamicClass} from '../src/renderer/accumulation.ts';

describe('replay clock', () => {
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

  test('policy switch resumes only the requested policy cache, never a stale or manual one',()=>{
   const ready={state:'ready',path:'/cache/utility.veyra-replay'};
   assert.equal(policyReplayPath('utility_lod',{policy:'utility_lod',replay:{active:false},auto_replay:ready}),'/cache/utility.veyra-replay');
   // A late status event still describing the previous policy's open replay.
   assert.equal(policyReplayPath('utility_lod',{policy:'distance_lod',replay:{active:false},auto_replay:{state:'ready',path:'/cache/distance.veyra-replay'}}),null);
   assert.equal(policyReplayPath('utility_lod',{policy:'utility_lod',replay:{active:true},auto_replay:ready}),null);
   assert.equal(policyReplayPath('utility_lod',{policy:'utility_lod',auto_replay:{state:'preparing'}}),null);
   assert.equal(policyReplayPath(null,{policy:'utility_lod',auto_replay:ready}),null);
  });

  test('60 FPS presentation clock advances every 16.667 ms',()=>{
   const clock=new ReplayClock(488,60);clock.start();
   assert.equal(clock.frameIntervalMs,1000/60);
   const sample=clock.advance(1000/60,10,1000);
   assert.equal(sample?.presentedIndex,1);
   assert.ok(Math.abs(new ReplayClock(488,60).durationMs/1000-8.133)<0.01);
  });
});

describe('playback control', () => {
  test('Pause can interrupt a pending Play and a late Play response cannot resume the UI',async()=>{
   const calls:Array<{name:string;resolve:(value:any)=>void}>=[],statuses:any[]=[],pending:Array<string|null>=[];
   const control=new PlaybackControl({
    command:name=>new Promise(resolve=>calls.push({name,resolve})),
    onPending:value=>pending.push(value),onStatus:value=>statuses.push(value),onError:error=>{throw error;},
   });
   const start=control.setRunning(true);
   const pause=control.setRunning(false);
   assert.deepEqual(calls.map(call=>call.name),['start','pause']);
   assert.deepEqual(pending,['running','paused']);
   calls[1].resolve({status:{state:'paused',frames:488,index:1}});await pause;
   calls[0].resolve({status:{state:'running',frames:488,index:1}});await start;
   assert.deepEqual(statuses,[{state:'paused',frames:488,index:1}]);
   assert.equal(pending.at(-1),null);
  });

  test('failed playback requests release the pending intent and report the failure',async()=>{
   const pending:Array<string|null>=[],errors:unknown[]=[];
   const control=new PlaybackControl({command:async()=>{throw new Error('cache unavailable');},onPending:value=>pending.push(value),onStatus:()=>assert.fail(),onError:error=>errors.push(error)});
   await control.setRunning(true);
   assert.equal(pending.at(-1),null);assert.match(String(errors[0]),/cache unavailable/);
  });

  test('a replaced session ignores a late response from its old playback request',async()=>{
   let resolve:(value:any)=>void=()=>{};const statuses:any[]=[],pending:Array<string|null>=[];
   const control=new PlaybackControl({command:()=>new Promise(done=>{resolve=done;}),onPending:value=>pending.push(value),onStatus:value=>statuses.push(value),onError:error=>{throw error;}});
   const request=control.setRunning(true);control.invalidate();
   resolve({status:{state:'running',dataset:'old-session'}});await request;
   assert.deepEqual(statuses,[]);assert.equal(pending.at(-1),null);
  });

  test('replay rate changes accept only the supported presentation rates',()=>{
   for(const fps of [15,30,60])assert.deepEqual(validateCommand('replay_rate',{fps}),{command:'replay_rate',args:{fps}});
   for(const fps of [0,10,120,'60',NaN])assert.throws(()=>validateCommand('replay_rate',{fps}),/FPS/);
  });
});

describe('overview replay', () => {
  const replayStatus={state:'running',dataset:null,sequence:null,policy:'distance_lod',frames:0,index:12,
   replay:{active:true,dataset:'semanticposs',sequence:'00',policy:'utility_lod',frames:488,position:12,fps:30}};

  test('Overview identity comes from the replay header while replaying, never "No dataset selected"',()=>{
   assert.equal(sessionLabel(replayStatus,true),'semanticposs · 00');
   assert.equal(sessionLabel({state:'unconfigured'},false),'No dataset selected');
   const session=overviewSession(replayStatus,true);
   assert.equal(session.title,'semanticposs');
   assert.equal(session.policy,'utility_lod');
   assert.match(session.line,/Smooth Replay · cached presentation · Sequence 00 · frame 12 \/ 488 · utility lod/);
  });

  test('live Overview keeps the live session identity',()=>{
   const session=overviewSession({dataset:'semanticposs',sequence:'00',frames:488,policy:'distance_lod'},false);
   assert.equal(session.title,'semanticposs');
   assert.match(session.line,/Sequence 00 · 488 frames · distance lod/);
  });

  test('replay cards are RECORDED values or explicit N/A, never live telemetry',()=>{
   const cards=replayCards({map_metrics:{fps:9.5},map_update_ms:4.25,active_cells:37000},replayStatus);
   assert.equal(cards.length,4);
   assert.ok(cards.every(card=>card.label.includes('RECORDED')));
   assert.equal(cards[0].value,'9.5 FPS · RECORDED');
   assert.match(cards[0].detail,/presenting 30 cached FPS/);
   assert.equal(cards[2].value,'N/A DURING REPLAY');
   assert.equal(replayCards(null,replayStatus)[3].value,'N/A DURING REPLAY');
  });

  test('Overview replay control plays an open replay or opens a prepared cache',()=>{
   const base={replayActive:false,running:false,canOpen:false,busy:false,canPlay:true};
   assert.deepEqual(replayControl({...base,replayActive:true,running:true}).playing,true);
   assert.equal(replayControl({...base,replayActive:true,running:true}).label,'Pause replay');
   const ready=replayControl({...base,canOpen:true,autoReplay:{state:'ready',frames:488}});
   assert.equal(ready.enabled,true);assert.match(ready.hint,/488 cached frames ready/);
   const preparing=replayControl({...base,autoReplay:{state:'preparing',done:24,frames:488}});
   assert.equal(preparing.enabled,false);assert.match(preparing.hint,/24 \/ 488/);
   assert.equal(replayControl({...base,busy:true,canOpen:true}).enabled,false);
   assert.equal(replayControl({...base,canPlay:false,replayActive:true}).enabled,false);
  });
});

describe('accumulation', () => {
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
});
