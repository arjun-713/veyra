import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {MOTION_FEATURE_ENABLED,perceptionStages,inspectorRows} from '../src/renderer/dashboard.ts';

test('motion feature is hidden until explicitly re-enabled', () => {
 assert.equal(MOTION_FEATURE_ENABLED,false);
 const frame:any={metadata:{pipeline_status:{temporal:'disabled'},perception_timings_ms:{temporal:0.1}},payload:new Uint8Array()};
 assert.deepEqual(perceptionStages(frame).map(stage=>stage.label),['Semantic','Ground','Terrain']);
 const rows=inspectorRows({point_count:3,motion:0.9} as any);
 assert.ok(!rows.some((row:any)=>row.key==='motion'));
 const app=readFileSync(new URL('../src/renderer/App.svelte',import.meta.url),'utf8');
 assert.match(app,/filter\(\(\[value\]\)=>MOTION_FEATURE_ENABLED\|\|value!=='motion'\)/);
});
