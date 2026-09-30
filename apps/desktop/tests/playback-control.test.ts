import {test} from 'node:test';
import assert from 'node:assert/strict';
import {PlaybackControl} from '../src/renderer/playback-control.ts';
import {validateCommand} from '../src/core.ts';

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
