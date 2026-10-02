import {test} from 'node:test';
import assert from 'node:assert/strict';
import {overviewSession,replayCards,replayControl,sessionLabel} from '../src/renderer/overview-replay.ts';

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
